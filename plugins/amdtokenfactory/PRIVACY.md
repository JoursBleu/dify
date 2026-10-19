# Privacy

Author: Letian Kang · Contact: Letian.Kang@amd.com

## What the plugin sends

The plugin sends requests only to `https://developer.amd.com.cn/radeon/api/v1`.
Custom URLs are not accepted and redirects are refused.

- **Model calls** go to `/chat/completions` with your API key. They include the model ID,
  prompts, conversation history, images, tool definitions, tool results and generation
  parameters.
- **Saving the API key** sends one `max_tokens=1` request to Qwen3.8-27B to check the key.
  Validating a single model also reads `/models` with your key.
- Every request carries the header `X-Source: dify` for channel usage statistics.
  It does not identify a Dify user, workspace, app, conversation or request.

## What the plugin stores

Nothing. The plugin has no database, cache or analytics of its own.
Dify stores the API key in its own credential store.

## What AMD Token Factory may keep

AMD Token Factory may process and log request data, IP addresses, request IDs and usage
to operate and secure the service. See the
[AMD Privacy Policy](https://www.amd.com/en/legal/privacy.html) before sending
sensitive data.

## Contact

Privacy questions about the plugin: Letian.Kang@amd.com. Questions about how AMD Token Factory
handles your data: member-service@mail.developer.amd.com.cn. If a key is exposed, revoke it at
[AMD Token Factory Model APIs](https://developer.amd.com.cn/login?source=sta8ZpC3e).

Source: <https://github.com/JoursBleu/dify/tree/feature/amdtokenfactory-marketplace-preview/plugins/amdtokenfactory>
