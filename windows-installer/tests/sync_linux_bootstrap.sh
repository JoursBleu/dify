#!/usr/bin/env bash
# Refresh only installer-owned public plugin artifacts, never daemon storage or configuration.
set -euo pipefail
umask 077
SOURCE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../payload/plugins" && pwd)
ROOT="$HOME/.local/share/dify-windows"
SHA=66f7bd9c8e15136a57228088daa647953d0a373a430d85ee11abff9c5bc5e845
[[ -d "$ROOT/plugins" && ! -L "$ROOT/plugins" && -f "$ROOT/instance.meta" ]] || exit 2
grep -qx 'DIFY_VERSION=1.17.1' "$ROOT/instance.meta"
[[ -f "$SOURCE/amdgpucloud.difypkg" && ! -L "$SOURCE/amdgpucloud.difypkg" ]] || exit 2
printf '%s  %s\n' "$SHA" "$SOURCE/amdgpucloud.difypkg" | sha256sum -c -
for name in amdgpucloud.difypkg INSTALL_windows_zh_Hans.txt README_zh_Hans.md PRIVACY.md; do
    [[ -f "$SOURCE/$name" && ! -L "$SOURCE/$name" && ! -L "$ROOT/plugins/$name" ]] || exit 2
done
notices="$(dirname -- "$SOURCE")/THIRD_PARTY_NOTICES.txt"
[[ -f "$notices" && ! -L "$notices" && ! -L "$ROOT/THIRD_PARTY_NOTICES.txt" ]] || exit 2
configuration_before=$(sha256sum "$ROOT/app/docker/.env" "$ROOT/instance.meta")
backup=$(mktemp -d "$ROOT/bootstrap-before-publisher-0.0.8.XXXXXX")
if [[ -e "$ROOT/plugins/radeon_cloud.difypkg" ]]; then
    [[ -f "$ROOT/plugins/radeon_cloud.difypkg" && ! -L "$ROOT/plugins/radeon_cloud.difypkg" ]] || exit 2
    mv "$ROOT/plugins/radeon_cloud.difypkg" "$backup/previous-plugin-0.0.6.difypkg"
fi
if [[ -e "$ROOT/plugins/amdgpucloud.difypkg" ]]; then
    [[ -f "$ROOT/plugins/amdgpucloud.difypkg" && ! -L "$ROOT/plugins/amdgpucloud.difypkg" ]] || exit 2
    cp "$ROOT/plugins/amdgpucloud.difypkg" "$backup/previous-amdgpucloud.difypkg"
fi
for name in amdgpucloud.difypkg INSTALL_windows_zh_Hans.txt README_zh_Hans.md PRIVACY.md; do
    [[ -f "$SOURCE/$name" && ! -L "$SOURCE/$name" && ! -L "$ROOT/plugins/$name" ]] || exit 2
    cp -- "$SOURCE/$name" "$ROOT/plugins/$name"
    chmod 644 "$ROOT/plugins/$name"
    cmp --silent "$SOURCE/$name" "$ROOT/plugins/$name"
done
cp -- "$notices" "$ROOT/THIRD_PARTY_NOTICES.txt"
chmod 644 "$ROOT/THIRD_PARTY_NOTICES.txt"
cmp --silent "$notices" "$ROOT/THIRD_PARTY_NOTICES.txt"
[[ "$configuration_before" == "$(sha256sum "$ROOT/app/docker/.env" "$ROOT/instance.meta")" ]] || exit 3
printf 'PASS: Linux bootstrap plugin and public guides synchronized; private configuration unchanged.\n'
printf 'Previous public plugin archived outside active plugins directory: %s\n' "$backup"
printf 'No daemon storage, model credentials or running services modified.\n'