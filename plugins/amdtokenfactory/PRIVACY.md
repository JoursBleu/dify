# Privacy

**Author: AMDTokenFactory**  
**Human author: Letian Kang**  
**Contact: Letian.Kang@amd.com**

This policy describes experimental `0.0.12` native-catalog integration source,
not a built/published or Marketplace-ready release. Automatic listing requires
UNRELEASED paired SDK / plugin-daemon / Dify / Graphon changes. No host source or
API overlays are included in the plugin.
On stock Dify 1.17.1 / SDK 0.10.2, `predefined-model` enables the key form but the
predefined list is empty: no models are selectable in the standard selector.
Saving a key is not proof that Chat, Agent or Workflow calls are available.

Dify and its plugin host handle configured credentials and requests. The plugin
sends the configured AMDTokenFactory API key and model requests to the fixed
base `https://developer.amd.com.cn/radeon/api/v1`; arbitrary/custom URLs are not
accepted and redirects are refused. Requests may include model IDs, prompts,
conversation messages, images, tool definitions, tool results, and generation
parameters. Responses may include generated content, reasoning content, tool
calls, usage data, request IDs, and errors.

Saving credentials can fetch the fixed `/models` catalog and sends a short
`max_tokens=1` validation completion. This can consume billable quota even when
the selector remains empty; `/models` alone does not prove key validity or model
access. No automatic authorization is performed. Obtain keys manually at
<https://developer.amd.com.cn/radeon/modelapis>.

The plugin adds the fixed request header `X-Source: dify` for aggregate channel
attribution. The header does not identify a Dify user, workspace, application,
conversation, or request. The plugin does not add persistent storage or its own
analytics service; this is not a claim that Dify, its host or AMD retain no data.

Native `fetch_models` listing calls only the same fixed AMD `/models` endpoint
with the configured key, not chat completions. Metadata has a 30-second cache
reuse TTL under a SHA-256 credential digest; it contains no raw keys or prompts
and starts no background polling. Cache entries and current-writer metadata are
each bounded to 64; expiry is cleaned on lookup and writer state at completion.
Failed refreshes do not use a stale fallback; superseded writers cannot repopulate
the cache after a newer refresh, failure or clear. The cache is credential-scoped;
tenant/provider isolation is the host's responsibility. The native RPC host
integration and end-to-end acceptance remain pending.

AMDTokenFactory and the selected model service may process and log request data,
IP addresses, request IDs, and usage metadata to provide, secure, operate, and
bill the service. Review AMD's privacy policy and the AMDTokenFactory terms before
using the plugin with sensitive data.

AMD Privacy Policy: <https://www.amd.com/en/corporate/privacy.html>

Privacy questions for this integration can be sent to **Letian Kang** at
`Letian.Kang@amd.com`. Keep keys out of prompts, GitHub reports, screenshots and
logs; revoke compromised or retired keys at AMDTokenFactory. Renaming the plugin
does not revoke cloud keys or migrate credentials from a different plugin ID.

The API-key help page opens in the user's browser and does not automatically
authorize the plugin. The packaged logo is a local PNG; displaying it does not
make a request to the logo's source website or add browser tracking.

Source: <https://github.com/JoursBleu/dify>. Discovery discussion:
[Dify issue #44157](https://github.com/langgenius/dify/issues/44157); earlier
[PR #44142](https://github.com/langgenius/dify/pull/44142) is closed and unmerged.
The [source license](https://github.com/JoursBleu/dify/blob/696759f84024eb01e53dd19f546139b5e4b2cc28/LICENSE)
and third-party notices remain applicable. This Draft makes no claim of approved
publisher status, brand permission or legal clearance.
