#!/usr/bin/env bash
# Materialize pinned, generated inputs; never install or modify a Dify instance.
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
PACKAGE=${1:?Pass the reviewed AMDGPUCloud-0.0.8.difypkg path}
PLUGIN_SHA=66f7bd9c8e15136a57228088daa647953d0a373a430d85ee11abff9c5bc5e845
COMPOSE_SHA=40343e21ca777173e69cff5dbafeb37c6f81f3b0d57d9e597f036e95eb63e76a
[[ -f "$PACKAGE" && ! -L "$PACKAGE" ]] || exit 2
printf '%s  %s\n' "$PLUGIN_SHA" "$PACKAGE" | sha256sum -c -
mkdir -p "$ROOT/payload/plugins" "$ROOT/payload/tools"
COMPOSE="$ROOT/payload/tools/docker-compose-linux-x86_64"
if [[ ! -e "$COMPOSE" ]]; then
    temporary=$(mktemp "$ROOT/payload/tools/compose-download.XXXXXX")
    trap 'rm -f -- "$temporary"' EXIT
    curl --fail --location --silent --show-error --connect-timeout 15 --max-time 180 \
        https://github.com/docker/compose/releases/download/v5.6.0/docker-compose-linux-x86_64 \
        -o "$temporary"
    printf '%s  %s\n' "$COMPOSE_SHA" "$temporary" | sha256sum -c -
    mv -- "$temporary" "$COMPOSE"
    trap - EXIT
fi
[[ -f "$COMPOSE" && ! -L "$COMPOSE" ]] || exit 2
printf '%s  %s\n' "$COMPOSE_SHA" "$COMPOSE" | sha256sum -c -
chmod 755 "$COMPOSE"
cp -- "$PACKAGE" "$ROOT/payload/plugins/amdgpucloud.difypkg"
printf 'Payload ready. No services, accounts, credentials or signature policies changed.\n'