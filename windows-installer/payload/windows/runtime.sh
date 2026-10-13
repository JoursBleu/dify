#!/usr/bin/env bash
# Install and manage only the new, private local Dify instance owned by this user.
set -euo pipefail
umask 077

ACTION=${1:-check}
PORT=${2:-18080}
ALLOW_UNSIGNED=${3:-false}
PAYLOAD=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
ROOT=${DIFY_INSTALL_ROOT:-"$HOME/.local/share/dify-windows"}
VERSION=1.17.1
PROJECT=${DIFY_INSTALL_PROJECT:-"dify-windows-${UID}"}
COMPOSE_SHA=40343e21ca777173e69cff5dbafeb37c6f81f3b0d57d9e597f036e95eb63e76a
PLUGIN_SHA=66f7bd9c8e15136a57228088daa647953d0a373a430d85ee11abff9c5bc5e845

fail() { printf 'ERROR: %s\n' "$1" >&2; exit 1; }
[[ "$PORT" =~ ^[0-9]+$ ]] && ((PORT >= 1024 && PORT <= 65535)) || fail 'Invalid local port.'
[[ "$ALLOW_UNSIGNED" == true || "$ALLOW_UNSIGNED" == false ]] || fail 'Invalid signature option.'
[[ "$PROJECT" =~ ^dify-windows-[a-z0-9-]+$ ]] || fail 'Invalid installer project name.'
case "$ROOT" in
    /mnt/*|/|"$HOME"|*..*|*$'\n'*|*$'\r'*) fail 'Dify data must be in a dedicated Linux directory.' ;;
esac
[[ "$ROOT" == /* ]] || fail 'Installation path must be absolute.'
[[ ! -L "$ROOT" ]] || fail 'Refusing a symlink installation root.'

check_prerequisites() {
    [[ "$(uname -m)" == x86_64 ]] || fail 'This installer supports x64 WSL Linux only.'
    [[ "$(uname -r)" =~ [Ww][Ss][Ll]2 ]] || fail 'A WSL2 Linux distribution is required.'
    for tool in docker openssl curl tar sha256sum flock realpath stat ss; do
        command -v "$tool" >/dev/null || fail "Missing Linux prerequisite: $tool."
    done
    docker --host unix:///var/run/docker.sock info >/dev/null 2>&1 ||
        fail 'Start Docker Desktop with WSL integration, or your existing WSL Docker Engine.'
    [[ "$(docker --host unix:///var/run/docker.sock info --format '{{.OSType}}')" == linux ]] ||
        fail 'Linux containers are required.'
    local cpus memory free
    cpus=$(docker --host unix:///var/run/docker.sock info --format '{{.NCPU}}')
    memory=$(docker --host unix:///var/run/docker.sock info --format '{{.MemTotal}}')
    free=$(df -Pk "$HOME" | awk 'NR==2 {print $4}')
    ((cpus >= 4 && memory >= 8 * 1024 * 1024 * 1024)) ||
        fail 'Allocate at least 4 CPU cores and 8 GiB to WSL/Docker for this full local stack.'
    ((free >= 20 * 1024 * 1024)) || fail 'At least 20 GiB of Linux filesystem free space is required.'
    printf 'WSL Linux and local Docker ready; CPU=%s, memory=%s bytes.\n' "$cpus" "$memory"
}

compose() {
    # Ignore inherited overrides of instance-local settings (including signature and passwords).
    local variable
    local -a clean_environment=()
    while IFS='=' read -r variable _; do
        [[ "$variable" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] && clean_environment+=(-u "$variable")
    done < "$ROOT/app/docker/.env"
    env -u DOCKER_CONTEXT -u DOCKER_TLS_VERIFY -u DOCKER_CERT_PATH \
        -u COMPOSE_FILE -u COMPOSE_PROFILES \
        "${clean_environment[@]}" \
        DOCKER_HOST=unix:///var/run/docker.sock \
        COMPOSE_PROFILES=postgresql,weaviate,collaboration \
        "$ROOT/tools/docker-compose-linux-x86_64" --ansi never --progress quiet --parallel 4 \
        --project-name "$PROJECT" --project-directory "$ROOT/app/docker" \
        --env-file "$ROOT/app/docker/.env" \
        -f "$ROOT/app/docker/docker-compose.yaml" -f "$ROOT/app/docker/local.override.yaml" "$@"
}

set_value() {
    local name=$1 value=$2 temporary="$ROOT/app/docker/.env.tmp"
    awk -v name="$name" -v value="$value" '
        BEGIN {found=0}
        index($0,name "=")==1 {print name "=" value; found=1; next}
        {print}
        END {if(!found) print name "=" value}
    ' "$ROOT/app/docker/.env" > "$temporary"
    mv "$temporary" "$ROOT/app/docker/.env"
}

create_configuration() {
    cp "$ROOT/app/docker/.env.example" "$ROOT/app/docker/.env"
    local origin="http://localhost:$PORT" secret redis_secret weaviate_secret sandbox_secret
    set_value SECRET_KEY "$(openssl rand -hex 32)"
    set_value DB_PASSWORD "$(openssl rand -hex 24)"
    redis_secret=$(openssl rand -hex 24)
    set_value REDIS_PASSWORD "$redis_secret"
    set_value CELERY_BROKER_URL "redis://:$redis_secret@redis:6379/1"
    weaviate_secret=$(openssl rand -hex 24)
    set_value WEAVIATE_API_KEY "$weaviate_secret"
    set_value WEAVIATE_AUTHENTICATION_APIKEY_ALLOWED_KEYS "$weaviate_secret"
    set_value WEAVIATE_AUTHENTICATION_ANONYMOUS_ACCESS_ENABLED false
    set_value WEAVIATE_DISABLE_TELEMETRY true
    sandbox_secret=$(openssl rand -hex 24)
    set_value CODE_EXECUTION_API_KEY "$sandbox_secret"
    set_value SANDBOX_API_KEY "$sandbox_secret"
    set_value PLUGIN_DAEMON_KEY "$(openssl rand -hex 32)"
    set_value PLUGIN_DIFY_INNER_API_KEY "$(openssl rand -hex 32)"
    set_value DIFY_AGENT_API_TOKEN "$(openssl rand -hex 32)"
    # Agent Stub requires strict unpadded base64url encoding of exactly 32 random bytes.
    set_value DIFY_AGENT_SERVER_SECRET_KEY "$(openssl rand -base64 32 | tr '+/' '-_' | tr -d '=\r\n')"
    set_value DIFY_AGENT_LOCAL_SANDBOX_AUTH_TOKEN "$(openssl rand -hex 32)"
    set_value EXPOSE_NGINX_PORT "$PORT"
    set_value EXPOSE_PLUGIN_DEBUGGING_PORT 15003
    set_value COMPOSE_PROFILES postgresql,weaviate,collaboration
    set_value VECTOR_STORE weaviate
    set_value DB_TYPE postgresql
    # Keep browser API calls same-origin, including Windows/remote localhost port forwarding.
    set_value CONSOLE_API_URL ''
    set_value CONSOLE_WEB_URL "$origin"
    set_value SERVICE_API_URL "$origin"
    set_value TRIGGER_URL "$origin"
    set_value APP_API_URL ''
    set_value APP_WEB_URL "$origin"
    set_value FILES_URL "$origin"
    set_value ENDPOINT_URL_TEMPLATE "$origin/e/{hook_id}"
    set_value NEXT_PUBLIC_SOCKET_URL "ws://localhost:$PORT"
    set_value WEB_API_CORS_ALLOW_ORIGINS "$origin,http://127.0.0.1:$PORT"
    set_value CONSOLE_CORS_ALLOW_ORIGINS "$origin,http://127.0.0.1:$PORT"
    set_value TEXT_GENERATION_TIMEOUT_MS 600000
    set_value PLUGIN_PYTHON_ENV_INIT_TIMEOUT 600
    set_value NEXT_TELEMETRY_DISABLED 1
    set_value FORCE_VERIFYING_SIGNATURE "$([[ "$ALLOW_UNSIGNED" == true ]] && echo false || echo true)"
    # Keep YAML and environment sandbox credentials consistent across image precedence rules.
    cat > "$ROOT/app/docker/volumes/sandbox/conf/config.yaml" <<EOF
app:
  port: 8194
  debug: false
  key: $sandbox_secret
max_workers: 4
max_requests: 50
worker_timeout: 15
enable_network: true
allowed_syscalls:
proxy:
  socks5: ''
  http: 'http://ssrf_proxy:3128'
  https: 'http://ssrf_proxy:3128'
EOF
    # Preserve the external localhost port when nginx passes host information upstream.
    sed -i '1i# Local installer modification: preserve the external localhost Host and port.' \
        "$ROOT/app/docker/nginx/proxy.conf.template"
    sed -i 's/Host \$host;/Host \$http_host;/; s/X-Forwarded-Port \$server_port;/X-Forwarded-Port '"$PORT"';/' \
        "$ROOT/app/docker/nginx/proxy.conf.template"
    sed -i '1i# Local installer modification: preserve the external localhost port in webhook URLs.' \
        "$ROOT/app/docker/nginx/conf.d/default.conf.template"
    sed -i 's|\$scheme://\$host\$request_uri|$scheme://$http_host$request_uri|' \
        "$ROOT/app/docker/nginx/conf.d/default.conf.template"
    chmod 600 "$ROOT/app/docker/.env" "$ROOT/app/docker/volumes/sandbox/conf/config.yaml"
}

verify_existing() {
    [[ -f "$ROOT/instance.meta" && ! -L "$ROOT/instance.meta" ]] ||
        fail 'Existing directory is not an installer-owned Dify instance; refusing to overwrite.'
    grep -qx "DIFY_VERSION=$VERSION" "$ROOT/instance.meta" || fail 'Existing Dify version differs; no automatic migration.'
    grep -qx "PORT=$PORT" "$ROOT/instance.meta" || fail 'Existing instance uses another port; use its saved configuration.'
    grep -qx "ALLOW_UNSIGNED=$ALLOW_UNSIGNED" "$ROOT/instance.meta" || fail 'Existing signature policy differs; refusing to replace it.'
    grep -qx "PROJECT=$PROJECT" "$ROOT/instance.meta" || fail 'Existing instance belongs to another Docker project.'
    [[ -f "$ROOT/app/docker/.env" && ! -L "$ROOT/app/docker/.env" ]] || fail 'Existing private configuration is missing.'
}

prepare() {
    if [[ -e "$ROOT" ]]; then
        verify_existing
        printf '%s  %s\n' "$COMPOSE_SHA" "$ROOT/tools/docker-compose-linux-x86_64" | sha256sum -c -
        printf 'Preserving the existing Dify data and private configuration.\n'
        return
    fi
    [[ -z "$(docker --host unix:///var/run/docker.sock ps -aq --filter "label=com.docker.compose.project=$PROJECT")" ]] ||
        fail 'An existing Docker project has this name; it will not be taken over.'
    for port in "$PORT" 15003; do
        [[ -z "$(ss -H -ltn "sport = :$port")" ]] || fail "Local port $port is already occupied."
    done
    mkdir -p "$ROOT/app" "$ROOT/tools" "$ROOT/plugins"
    chmod 700 "$ROOT"
    cp -R "$PAYLOAD/docker" "$ROOT/app/docker"
    cp "$PAYLOAD/LICENSE" "$ROOT/LICENSE"
    cp "$PAYLOAD/tools/COMPOSE-LICENSE.txt" "$ROOT/tools/"
    cp "$PAYLOAD/tools/docker-compose-linux-x86_64" "$ROOT/tools/"
    cp "$PAYLOAD/plugins/amdgpucloud.difypkg" "$ROOT/plugins/"
    cp "$PAYLOAD/windows/local.override.yaml" "$ROOT/app/docker/local.override.yaml"
    chmod 755 "$ROOT/tools/docker-compose-linux-x86_64"
    printf '%s  %s\n' "$COMPOSE_SHA" "$ROOT/tools/docker-compose-linux-x86_64" | sha256sum -c -
    printf '%s  %s\n' "$PLUGIN_SHA" "$ROOT/plugins/amdgpucloud.difypkg" | sha256sum -c -
    create_configuration
    printf 'DIFY_VERSION=%s\nPORT=%s\nALLOW_UNSIGNED=%s\nPROJECT=%s\n' \
        "$VERSION" "$PORT" "$ALLOW_UNSIGNED" "$PROJECT" > "$ROOT/instance.meta"
    printf 'Created isolated Dify configuration under %s (secrets not printed).\n' "$ROOT"
}

wait_for_ui() {
    curl --fail --silent --show-error --retry 60 --retry-all-errors --retry-connrefused \
        --retry-delay 3 --connect-timeout 5 --max-time 10 \
        "http://127.0.0.1:$PORT/console/api/setup" -o "$ROOT/setup-state.json"
    grep -q '"' "$ROOT/setup-state.json" || fail 'Dify API did not return setup metadata.'
    curl --fail --silent --show-error --connect-timeout 5 --max-time 15 \
        "http://127.0.0.1:$PORT/install" -o /dev/null
    local service state
    for service in api api_websocket worker worker_beat web plugin_daemon agent_backend local_sandbox \
        db_postgres redis weaviate sandbox ssrf_proxy agent_ssrf_proxy nginx; do
        state=$(docker --host unix:///var/run/docker.sock ps \
            --filter "label=com.docker.compose.project=$PROJECT" \
            --filter "label=com.docker.compose.service=$service" --format '{{.Status}}')
        [[ "$state" == Up* && "$state" != *unhealthy* ]] || fail "Dify service is not running: $service."
    done
    printf 'Dify application and setup API are ready: http://localhost:%s/install\n' "$PORT"
    compose ps --format table
}

case "$ACTION" in
    check) check_prerequisites; exit 0 ;;
    install|prepare|start|stop|status|probe)
        check_prerequisites
        ;;
    *) fail 'Unknown installer action.' ;;
esac

# Acquire the lock before creating configuration so concurrent first installs cannot race.
mkdir -p "$HOME/.cache/dify-windows"
chmod 700 "$HOME/.cache/dify-windows"
exec 9> "$HOME/.cache/dify-windows/$PROJECT.lock"
flock -n 9 || fail 'Another installer operation is running for this instance.'
case "$ACTION" in
    install|prepare) prepare ;;
    *) verify_existing ;;
esac
compose config --quiet
case "$ACTION" in
    install)
        printf 'Downloading official Dify runtime images; first installation needs Internet access.\n'
        compose pull --policy missing
        compose up -d
        wait_for_ui
        ;;
    start) compose up -d; wait_for_ui ;;
    stop)
        # A long graceful stop avoids killing Weaviate while its index is being persisted.
        compose stop --timeout 180
        printf 'Dify stopped; databases, uploads, plugins and Docker volumes are retained.\n'
        ;;
    status) compose ps --format table ;;
    probe) wait_for_ui ;;
    prepare) printf 'Deployment configuration validated; containers were not started.\n' ;;
esac