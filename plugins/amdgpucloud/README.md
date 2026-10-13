# AMDGPUCloud

**Author: Letian Kang**  
**Contact: Letian.Kang@amd.com**

AMDGPUCloud is a native Dify model provider for AMD GPU Cloud / Token Factory.
Like the Cherry Studio integration, it uses the standard OpenAI-compatible
provider interface, the AMD GPU Cloud page logo, a fixed API endpoint and manual
API-key setup. It is managed alongside other providers inside Dify, not through
a separate Windows plugin window.

## Configure

1. Open [AMD GPU Cloud Model APIs](https://developer.amd.com.cn/radeon/modelapis).
2. Sign in and create an API key beginning with `rc-`.
3. Install `AMDGPUCloud-0.0.8.difypkg` using Dify's standard plugin package installer.
4. Open **Integrations -> Model Provider -> AMDGPUCloud** (or Model Provider under Settings).
5. Enter the API key and save.

The plugin fixes the API endpoint to
`https://developer.amd.com.cn/radeon/api/v1`. It does not accept custom
endpoints or arbitrary model names.

## Initial models

- `DeepSeek-V4-Flash`
- `DeepSeek-V4.1-Flash`
- `Qwen3.8-Flash-Next`

This is an integration preview. Model availability, output limits, features,
and pricing must be verified against the public Token Factory endpoint before a
Marketplace release.

## Complete plugin identity

Version 0.0.8 uses the personal publisher slug **`letian-kang`**, with plugin
name and provider name **`amdgpucloud`**. The native installation card uses
**`letian-kang/amdgpucloud`**; the canonical model-provider namespace is
`letian-kang/amdgpucloud/amdgpucloud`. Both display labels remain `AMDGPUCloud`.
The human author is **Letian Kang**, contact **Letian.Kang@amd.com**.

Dify requires lowercase identifier syntax, not a specific personal publisher
name. The requested dotted slug `letian.kang` is invalid; `letian-kang` uses
allowed characters. This unsigned development package does not establish
verified publisher account ownership or official AMD/Dify Marketplace status.

Versions before 0.0.8 used different machine identities. Dify cannot perform a
same-ID upgrade across this change: install this package normally, configure
its credentials and update any workspace defaults or App/Workflow references.
Remove the earlier plugin only after those references have been migrated.
The installer does not copy keys, rewrite stored app data or uninstall plugins.
An unused earlier integration can be removed through native Dify management;
do not remove a configured provider without an explicit migration plan.

## Request attribution

Credential validation and model requests send `X-Source: dify` so AMD GPU Cloud
can measure aggregate usage from the Dify integration. The value is fixed and
does not contain a user, workspace, application, conversation, or request ID.
The API-key help link has no Cherry Studio source query. Dify does not claim
Cherry-specific login attribution, automatic OAuth or a Dify login conversion
funnel that the service has not implemented.

## Pricing

Dify model schemas can display standard input and output prices. Token Factory
also supports cached-input pricing, which Dify's current `PriceConfig` cannot
represent. Token Factory usage and billing records are authoritative.

## Development

```bash
uv sync --group dev
uv run pytest
uv run ruff check .
```

Run the opt-in public API tests with a dedicated test key:

```bash
uv run python scripts/run_live_tests.py --key-file /path/to/private/rc-test-key
```

The file must be a regular, non-symlink file owned by you and readable only by
you (mode `0600` or stricter). It contains only the dedicated `rc-*` key. The
launcher passes it to the test process without placing it in command arguments,
and disables traceback/local-variable and captured-output reporting. Do not
reuse an internal AMD subscription key or place a key in CI or a shell command.

For Dify remote debugging, copy `.env.example` to `.env`, insert the debug
server and key shown by Dify, then run:

```bash
uv run python -m main
```

The provider requires complete JSON/SSE responses with usage. Streams are not
replayed automatically; malformed frames, missing `[DONE]`, redirects and
upstream errors produce sanitized failures. Closing an active generator releases
the HTTP response. The HTTP read timeout is 600 seconds; the Dify daemon and
plugin execution deadline must also be configured for long requests. Socket
cleanup is covered offline, not yet verified as GPU-side cancellation.

Before distributing a build, run the official Marketplace validator and the
local package audit. Local tests exercise the real SDK/Requests request builder
with an intercepted network boundary; they are not public API or Dify UI tests.

Chinese installation guide: [README_zh_Hans](readme/README_zh_Hans.md).
Windows package installation guide: [INSTALL_windows_zh_Hans](readme/INSTALL_windows_zh_Hans.txt).

The bundled PNG uses the AMD GPU Cloud page logo with a white square canvas,
matching the Cherry Studio integration's visual approach. It is stored locally
and loads no remote image in Dify. Source and SHA-256 are recorded in
`_assets/BRAND_ASSET_NOTICE.txt`; this does not imply official publisher or
brand approval for a Marketplace release.

## Source and support

Source repository: <https://github.com/JoursBleu/dify>

Source is under `plugins/amdgpucloud` on branch `feature/radeon-cloud-provider`.
The complete Windows bootstrapper source is in the sibling `windows-installer`
directory. The repository owner is distinct from the plugin's publisher slug.
Publisher account ownership and Marketplace approval remain separate checks.

During integration development, report issues in the source repository and do
not include API keys or prompt content. Author: **Letian Kang**.
Contact: `Letian.Kang@amd.com`.
