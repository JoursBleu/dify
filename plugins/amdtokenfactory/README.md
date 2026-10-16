# AMDTokenFactory

**Author: AMDTokenFactory**  
**Human author: Letian Kang**  
**Contact: Letian.Kang@amd.com**

**Version 0.0.12 — experimental native catalog Draft, not ready for Marketplace.**
An OpenAI-compatible model-provider plugin implementing automatic chat-model
discovery through a proposed native catalog RPC. It contains no Dify API, SDK,
daemon or Graphon source, API overlays or Windows application installers.
The package is for review; it is not a standalone stock-Dify solution.

## Installation

Automatic listing requires **UNRELEASED paired SDK / plugin-daemon / Dify /
Graphon changes**, not stock Dify 1.17.1 or released SDK 0.10.2. The native
contract declares `remote_model_catalog: true`, dispatches the
`get_ai_model_list` action to `fetch_models(model_type, credentials)`, and returns
AIModelEntity schemas in `models`. All four components must agree on that contract.
The manifest's `minimum_dify_version: 1.17.1` is an install floor, not a catalog
compatibility guarantee. The package retains the published SDK 0.10.2 dependency
for reproducible Draft review and explicitly refuses credential validation on it.
It does not fetch or bundle a forked SDK. A native-enabled SDK release and matched
host components must be approved and selected before a non-Draft release.

On the stock versions, the empty predefined list still provides **no selectable
models in the standard model selector**. The installed base class can load the
provider override, but does not dispatch this RPC or recognize the new declaration
field. This revision rejects provider credential validation before any network call
when the SDK has no native catalog hook, instead of showing a successful Key with
zero usable models. This check cannot certify the daemon or host installation;
the complete paired stack is still required. There is no manual model-ID workaround.

For a test workspace after paired-stack integration and a reviewed build only:
1. If a reviewed `AMDTokenFactory-0.0.12.difypkg` is provided, import it through
  **Integrations -> Install -> From Local File**.
2. Obtain your own `rc-*` key manually at
  [AMDTokenFactory Model APIs](https://developer.amd.com.cn/radeon/modelapis).
3. Configure the single provider API Key in **Model Provider -> AMDTokenFactory**.
  The paired native stack obtains all eligible chat IDs and metadata automatically;
  do not enter model IDs or create per-model credentials. The Python host/SDK/plugin
  chain is covered by offline integration tests with synthetic transport and data;
  live installation and browser acceptance remain pending.

The endpoint is fixed to `https://developer.amd.com.cn/radeon/api/v1`; custom
URLs are not accepted. Saving credentials sends a short `max_tokens=1`
validation request and can consume billable quota even when the selector is empty;
`/models` alone cannot validate a key. If local or unsigned packages are blocked,
contact the administrator rather than disabling production security checks.

### Native integration status

SDK declaration/dispatch and daemon / Dify / Graphon consumption are separate,
unreleased changes. This plugin does not patch host APIs, offer overlay deployment
instructions, install Dify / WSL / Docker, or prescribe service restarts.

The paired source proposals are pinned for review, not merged releases:

| Component | Source commit |
|---|---|
| Plugin SDK | [f9ba731](https://github.com/JoursBleu/dify-plugin-sdks/commit/f9ba731f38d271f3d408bb036d02227445f6ce77) |
| Plugin daemon | [2820380](https://github.com/JoursBleu/dify-plugin-daemon/commit/2820380c51b1f1407f175ff9cc4bf25489504371) |
| Graphon runtime | [9b2ae3b](https://github.com/JoursBleu/graphon/commit/9b2ae3bb06d6e400880c2f8eefa4db0b505b6f1f) |
| Dify API | [9c39d70](https://github.com/JoursBleu/dify/commit/9c39d7035308d6b602dee7823fd57ccc81fca997) |

These add an opt-in `remote_model_catalog` declaration and a credentials-aware
`/dispatch/model/list` RPC. Hosts retain credential policy, model enablement and
request-local results; existing static-provider behavior remains independent.

Remote discovery is discussed in the created [Dify issue #44157](https://github.com/langgenius/dify/issues/44157).
The earlier [Dify PR #44142](https://github.com/langgenius/dify/pull/44142) is closed
and unmerged; it does not establish upstream support for this Draft.

## Dynamic discovery and compatibility

`AMDTokenFactoryModelProvider.fetch_models` returns every eligible remote chat
LLM as an AIModelEntity through shared `fetch_catalog` and its existing sanitized
error mapping. Non-LLM requests return an empty list without network access.
Listing itself calls only the fixed `/models` endpoint, never chat completions;
credential saving retains the separate, potentially billable validation request.
`predefined: []` and the unified Key form remain; there are no model YAMLs,
hardcoded IDs, manual model entries or fallback lists. IDs, capabilities, context,
parameters and prices come from metadata. Additions within the supported schema
need no plugin rebuild; automatic UI availability still needs the paired stack.

The plugin's in-memory catalog cache has a 30-second reuse TTL and uses a SHA-256
credential digest, not raw keys or prompts. Cache entries and current-writer
metadata are each capped at 64; expired entries are removed on lookup and writer
metadata is cleaned at completion. Tenant/provider isolation is the host's
responsibility, not inferred from the plugin's credential-only cache.
Failed refreshes report sanitized errors without stale fallback. Older in-flight
requests may return to their own caller but cannot overwrite or repopulate the
cache after a newer refresh, failure, eviction or clear. Malformed status types
fail safely. Generation checks membership. Input is bounded to 2 MiB / 2,048 entries.

Unpublished output maxima remain unspecified; default output budgets are client
settings, not service limits. Single tools and JSON Object depend on model
metadata. Vision-capable chat LLMs are retained when image input is declared;
OCR/non-chat models are filtered, not all vision LLMs. Parallel tools, JSON Schema,
embeddings, OCR and video are not declared. None of these code capabilities is a
claim of completed stock-Dify end-to-end acceptance.

## Identity and saved credentials

The technical plugin ID is **`amdtokenfactory/amdtokenfactory`** and the canonical
provider is `amdtokenfactory/amdtokenfactory/amdtokenfactory`. The publication
author label above does not certify publisher ownership or alter that identifier.
The prior ID `amdgpucloud/amdgpucloud` is different, not an upgrade under the old
identifier: saved credentials cannot migrate automatically.
Do not uninstall the old provider or copy saved keys. Configure AMDTokenFactory only
through its secure credential form, and review default models and application references
separately. Catalog refreshes do not migrate credentials or rewrite applications.

## Pricing, privacy and attribution

Dify displays ordinary input/output estimates, not cached-input discounts.
AMDTokenFactory account limits, usage and billing records are authoritative.
Requests use fixed `X-Source: dify` for aggregate attribution, without user,
workspace, application, conversation or request identifiers. Keys are obtained manually.
Prompt, image and tool data are sent to AMD; the plugin adds no persistent storage,
but the service may log requests. Read [PRIVACY.md](PRIVACY.md) before sending sensitive data.

## Development and acceptance

- Source development uses Python 3.12. Development scripts, including
  `scripts/run_live_tests.py`, `scripts/check_package.py` and `.env.example`, are
  source-only references, not packaged tools or installation steps.
- Default tests do not call the public API. Opt-in live tests can be billable:
  use only a dedicated `rc-*` key in an owned regular non-symlink file, mode `0600`
  or stricter. Do not use internal subscription keys or put keys in CI, logs,
  prompts or shell arguments. The source launcher keeps keys out of argv and
  suppresses sensitive diagnostics.
- JSON/SSE responses require complete usage; streams are not automatically replayed.
  Redirects, malformed frames and missing `[DONE]` are rejected. The HTTP read
  timeout is 600 seconds; host deadlines may constrain long requests separately.

Offline provider-override tests can run on SDK 0.10.2; they cover all remote IDs,
metadata, sanitized errors, absence of chat calls, and deterministic cache races
with bounded cleanup. They are not native SDK dispatch or UI acceptance tests.
Native SDK tests are a separate integration task. Package safety and the official
Marketplace validator must be rerun on the eventual exact build, including the
new declaration field. Native provider-listing support, public-key Chat/Agent/Workflow,
vision/JSON/tool-round-trip acceptance and GPU-side cancellation remain pending.
Current limits/prices, publisher ownership, licensing and brand permission need
review before any non-Draft release; none is represented as approved.

## Source, support and licensing

Source: <https://github.com/JoursBleu/dify>. Report only sanitized errors and versions;
never include API keys or prompt content. Contact the author listed above.
[Simplified Chinese guide](readme/README_zh_Hans.md) · [Windows browser guide](readme/INSTALL_windows_zh_Hans.txt).

The [Dify Open Source License](https://github.com/JoursBleu/dify/blob/696759f84024eb01e53dd19f546139b5e4b2cc28/LICENSE)
and third-party notices remain applicable.
The local icon retains the AMD GPU Cloud page's source logo and loads no remote image;
source/checksum and trademark
boundaries are in [_assets/BRAND_ASSET_NOTICE.txt](_assets/BRAND_ASSET_NOTICE.txt).
`scripts/prepare_brand_icon.ps1` is a source-only reproduction helper.
This experimental Draft does not establish AMD/Dify approval, legal clearance or
Marketplace publisher status.
