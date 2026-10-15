#!/usr/bin/env bash
# Materialize public build inputs only; never load an installed configuration.
set -euo pipefail
umask 022
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
DIFY_COMMIT=8387590ace4a094de812b7847fc6a4c3a27cd52b
DIFY_SOURCE=git@github.com:langgenius/dify.git
PLUGIN_SHA=a52e0e67f0c152d2d458ac77e4ac4fc189bd69e2d29d81f07b3f2d3555ebb528
COMPOSE_SHA=40343e21ca777173e69cff5dbafeb37c6f81f3b0d57d9e597f036e95eb63e76a
COMPOSE_SOURCE=https://github.com/docker/compose/releases/download/v5.6.0/docker-compose-linux-x86_64

fail() { printf 'ERROR: %s\n' "$1" >&2; exit 2; }
(( $# > 0 )) || fail 'Usage: prepare_payload.sh PACKAGE [--offline] [--source-repository PATH] [--compose PATH]'
PACKAGE=$1
shift
SOURCE_REPOSITORY="$ROOT/.."
COMPOSE_INPUT="$ROOT/payload/tools/docker-compose-linux-x86_64"
OFFLINE=false
while (( $# > 0 )); do
    case "$1" in
        --offline) OFFLINE=true; shift ;;
        --source-repository|--compose)
            (( $# >= 2 )) || fail 'An option path is missing.'
            if [[ "$1" == --source-repository ]]; then SOURCE_REPOSITORY=$2; else COMPOSE_INPUT=$2; fi
            shift 2 ;;
        *) fail 'Unknown preparation option.' ;;
    esac
done
for tool in git sha256sum cmp cp mv chmod mkdir mktemp find sort xargs flock dirname rm; do
    command -v "$tool" >/dev/null || fail "Missing build prerequisite: $tool."
done
check_hash() {
    local expected=$1 file=$2 actual
    [[ -f "$file" && ! -L "$file" ]] || fail 'A reviewed input must be a regular non-symlink file.'
    actual=$(sha256sum -- "$file")
    [[ "${actual%% *}" == "$expected" ]] || fail 'A generated input does not match its pinned SHA-256.'
}
check_hash "$PLUGIN_SHA" "$PACKAGE"
if [[ -e "$COMPOSE_INPUT" || -L "$COMPOSE_INPUT" ]]; then
    check_hash "$COMPOSE_SHA" "$COMPOSE_INPUT"
elif [[ "$OFFLINE" == true ]]; then
    fail 'Offline preparation requires the reviewed Compose binary; pass --compose PATH.'
fi
[[ -d "$ROOT/payload" && ! -L "$ROOT/payload" ]] || fail 'Expected a source payload directory.'
for directory in docker api-compat plugins tools; do
    target="$ROOT/payload/$directory"
    [[ ! -L "$target" && ( ! -e "$target" || -d "$target" ) ]] || fail 'Unsafe generated payload directory.'
done
for relative in .upstream-commit .prepared.sha256 plugins/AMDTokenFactory-0.0.10.difypkg \
    plugins/INSTALL_windows_zh_Hans.txt plugins/README_zh_Hans.md plugins/PRIVACY.md \
    tools/docker-compose-linux-x86_64 LICENSE tools/COMPOSE-LICENSE.txt; do
    target="$ROOT/payload/$relative"
    [[ ! -L "$target" && ( ! -e "$target" || -f "$target" ) ]] || fail 'Unsafe generated payload file.'
done
[[ -f "$ROOT/payload/LICENSE" && -f "$ROOT/payload/tools/COMPOSE-LICENSE.txt" ]] ||
    fail 'Tracked source licenses must be present.'
[[ ! -L "$ROOT/.prepare-payload.lock" && ( ! -e "$ROOT/.prepare-payload.lock" || -f "$ROOT/.prepare-payload.lock" ) ]] ||
    fail 'Unsafe preparation lock file.'
exec 9>> "$ROOT/.prepare-payload.lock"
flock -n 9 || fail 'Another payload preparation is running.'
staging=$(mktemp -d "$ROOT/.prepare-payload.XXXXXX")
trap 'rm -rf -- "$staging"' EXIT

# Never resolve HEAD/a moving tag, honor replacement objects, or invoke a key helper.
unset GIT_DIR GIT_WORK_TREE GIT_COMMON_DIR GIT_INDEX_FILE GIT_OBJECT_DIRECTORY GIT_ALTERNATE_OBJECT_DIRECTORIES \
    GIT_CONFIG GIT_CONFIG_COUNT GIT_CONFIG_PARAMETERS GIT_TEMPLATE_DIR
git_public() {
    GIT_NO_LAZY_FETCH=1 GIT_TERMINAL_PROMPT=0 GIT_ASKPASS=/bin/false GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 \
        GIT_SSH_COMMAND='ssh -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=15' GIT_SSH_VARIANT=ssh \
        git --no-replace-objects -c credential.helper= -c core.askpass= -c core.hooksPath=/dev/null \
        -c init.templateDir= -c protocol.allow=never -c protocol.https.allow=never \
        -c protocol.http.allow=never -c protocol.ssh.allow=never -c protocol.git.allow=never \
        -c protocol.file.allow=never -c protocol.ext.allow=never "$@"
}
if ! git_public -C "$SOURCE_REPOSITORY" cat-file -e "$DIFY_COMMIT^{commit}" 2>/dev/null; then
    [[ "$OFFLINE" == false ]] || fail 'Pinned Dify release object is missing; branch main is not a substitute.'
    SOURCE_REPOSITORY="$staging/upstream.git"
    git_public init --bare --quiet "$SOURCE_REPOSITORY"
    git_public -c protocol.ssh.allow=always -C "$SOURCE_REPOSITORY" \
        fetch --quiet --no-tags --depth=1 "$DIFY_SOURCE" "$DIFY_COMMIT"
fi
[[ "$(git_public -C "$SOURCE_REPOSITORY" rev-parse --verify "$DIFY_COMMIT^{commit}")" == "$DIFY_COMMIT" ]] ||
    fail 'Upstream release commit verification failed.'

# Reconstruct verified Git blobs instead of extracting an externally supplied tar.
# This also ignores worktree .env files, export-subst filters and archive links.
mkdir -p "$staging/payload"
git_public -C "$SOURCE_REPOSITORY" ls-tree -r -z --full-tree "$DIFY_COMMIT" -- docker LICENSE > "$staging/tree"
while IFS= read -r -d '' entry; do
    metadata=${entry%%$'\t'*}
    path=${entry#*$'\t'}
    [[ "$metadata" =~ ^(100644|100755)\ blob\ ([0-9a-f]{40})$ ]] || fail 'Upstream links/submodules are not allowed.'
    mode=${BASH_REMATCH[1]}
    blob=${BASH_REMATCH[2]}
    [[ "$path" == LICENSE || "$path" == docker/* ]] || fail 'Unexpected upstream payload path.'
    case "$path" in
        *\\*|*:*|*\?*|*\**|*\"*|*\<*|*\>*|*\|*|*$'\n'*|*$'\r'*|*$'\t'*) fail 'Unsafe upstream filename.' ;;
    esac
    case "/$path/" in *//*|*/../*|*/./*|*/.env/*) fail 'Unsafe or private upstream path.' ;; esac
    destination="$staging/payload/$path"
    mkdir -p -- "$(dirname -- "$destination")"
    git_public -C "$SOURCE_REPOSITORY" cat-file blob "$blob" > "$destination"
    [[ "$(git_public -C "$SOURCE_REPOSITORY" hash-object --no-filters -- "$destination")" == "$blob" ]] ||
        fail 'Upstream blob integrity verification failed.'
    chmod "${mode#100}" "$destination"
done < "$staging/tree"
for relative in docker/docker-compose.yaml docker/.env.example LICENSE; do
    [[ -f "$staging/payload/$relative" ]] || fail 'Pinned upstream deployment is incomplete.'
done
cmp --silent "$staging/payload/LICENSE" "$ROOT/payload/LICENSE" || fail 'Tracked Dify license differs from the pinned release.'

SOURCE_ROOT=$(cd -- "$ROOT/.." && pwd -P)
for directory in "$SOURCE_ROOT/api-compat" "$SOURCE_ROOT/plugins" "$SOURCE_ROOT/plugins/amdtokenfactory" "$SOURCE_ROOT/plugins/amdtokenfactory/readme"; do
    [[ -d "$directory" && ! -L "$directory" ]] || fail 'Canonical API/plugin source is missing or unsafe.'
done
mkdir -p "$staging/payload/api-compat" "$staging/payload/plugins" "$staging/payload/tools"
copy_public() {
    [[ -f "$1" && ! -L "$1" ]] || fail 'Canonical public source must be a regular non-symlink file.'
    cp -- "$1" "$staging/payload/$2"
    chmod 644 "$staging/payload/$2"
}
for name in prepare_overlay.py amdtokenfactory_remote.py; do
    copy_public "$SOURCE_ROOT/api-compat/$name" "api-compat/$name"
done
copy_public "$SOURCE_ROOT/plugins/amdtokenfactory/model_catalog.py" api-compat/model_catalog.py
for name in INSTALL_windows_zh_Hans.txt README_zh_Hans.md; do
    copy_public "$SOURCE_ROOT/plugins/amdtokenfactory/readme/$name" "plugins/$name"
done
copy_public "$SOURCE_ROOT/plugins/amdtokenfactory/PRIVACY.md" plugins/PRIVACY.md
copy_public "$PACKAGE" plugins/AMDTokenFactory-0.0.10.difypkg
if [[ -f "$COMPOSE_INPUT" ]]; then
    copy_public "$COMPOSE_INPUT" tools/docker-compose-linux-x86_64
else
    [[ "$OFFLINE" == false ]] || fail 'Reviewed Compose input disappeared during offline preparation.'
    command -v curl >/dev/null || fail 'curl is required to download the pinned Compose binary.'
    curl --disable --fail --location --silent --show-error --connect-timeout 15 --max-time 180 \
        --proto '=https' --proto-redir '=https' --tlsv1.2 \
        "$COMPOSE_SOURCE" -o "$staging/payload/tools/docker-compose-linux-x86_64"
fi
check_hash "$COMPOSE_SHA" "$staging/payload/tools/docker-compose-linux-x86_64"
check_hash "$PLUGIN_SHA" "$staging/payload/plugins/AMDTokenFactory-0.0.10.difypkg"
chmod 755 "$staging/payload/tools/docker-compose-linux-x86_64"
printf '%s\n' "$DIFY_COMMIT" > "$staging/payload/.upstream-commit"
(
    cd -- "$staging/payload"
    find LICENSE docker api-compat plugins tools -type f -print0 | LC_ALL=C sort -z | xargs -0 sha256sum > .prepared.sha256
)

# Replace generated build directories, never an installed instance. No stale .env,
# old overlay or cache can be carried forward from an earlier preparation.
rm -f -- "$ROOT/payload/.upstream-commit" "$ROOT/payload/.prepared.sha256"
for directory in docker api-compat; do
    if [[ -e "$ROOT/payload/$directory" ]]; then mv -T -- "$ROOT/payload/$directory" "$staging/previous-$directory"; fi
    mv -T -- "$staging/payload/$directory" "$ROOT/payload/$directory"
done
mkdir -p "$ROOT/payload/plugins" "$ROOT/payload/tools"
for relative in plugins/AMDTokenFactory-0.0.10.difypkg plugins/INSTALL_windows_zh_Hans.txt \
    plugins/README_zh_Hans.md plugins/PRIVACY.md tools/docker-compose-linux-x86_64 \
    .prepared.sha256 .upstream-commit; do
    mv -fT -- "$staging/payload/$relative" "$ROOT/payload/$relative"
done
printf 'Payload ready from Dify release %s. No services, credentials or signature policies changed.\n' "$DIFY_COMMIT"