#!/usr/bin/env bash
# Generate a read-only compatibility overlay from the pinned public API image.
# Never load an installed .env or credential record; never restart services.
set -euo pipefail
umask 022
ROOT=${1:?Dedicated installer-owned Linux root is required}
PAYLOAD=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
[[ "$ROOT" == /* && "$ROOT" != / && "$ROOT" != "$HOME" && "$ROOT" != /mnt/* ]] || exit 2
[[ -f "$ROOT/instance.meta" && ! -L "$ROOT/instance.meta" ]] || exit 2
grep -qx 'DIFY_VERSION=1.17.1' "$ROOT/instance.meta"
for name in prepare_overlay.py model_catalog.py amdtokenfactory_remote.py; do
    [[ -f "$PAYLOAD/api-compat/$name" && ! -L "$PAYLOAD/api-compat/$name" ]] || exit 2
done
output="$ROOT/app/docker/compat"
[[ ! -L "$output" ]] || exit 2
mkdir -p "$output"
docker --host unix:///var/run/docker.sock run --rm --network none --read-only \
    --cap-drop ALL --security-opt no-new-privileges \
    --user "$(id -u):$(id -g)" --entrypoint /app/api/.venv/bin/python \
    --mount "type=bind,source=$PAYLOAD/api-compat,target=/payload,readonly" \
    --mount "type=bind,source=$output,target=/output" \
    langgenius/dify-api:1.17.1 /payload/prepare_overlay.py --payload /payload --output /output
for name in provider_configuration.py model_runtime.py model_catalog.py amdtokenfactory_remote.py; do
    [[ -f "$output/$name" && ! -L "$output/$name" ]] || exit 2
done
cp "$PAYLOAD/windows/remote-models.override.yaml" "$ROOT/app/docker/remote-models.override.yaml"
printf 'Remote model-list compatibility ready. No services restarted and private configuration unchanged.\n'