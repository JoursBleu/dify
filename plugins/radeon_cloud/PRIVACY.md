# Privacy

This plugin sends the configured Radeon Cloud API key and model requests to
`https://developer.amd.com.cn`. Requests may include model IDs, prompts,
conversation messages, images, tool definitions, tool results, and generation
parameters. Responses may include generated content, reasoning content, tool
calls, usage data, request IDs, and errors.

The plugin adds the fixed request header `X-Source: dify` for aggregate channel
attribution. The header does not identify a Dify user, workspace, application,
conversation, or request. The plugin does not add persistent storage or its own
analytics service.

Radeon Cloud and the selected model service may process and log request data,
IP addresses, request IDs, and usage metadata to provide, secure, operate, and
bill the service. Review AMD's privacy policy and the Token Factory terms before
using the plugin with sensitive data.

AMD Privacy Policy: <https://www.amd.com/en/corporate/privacy.html>

Privacy questions for this integration can be sent to
`kangletian@hotmail.com` during development.
