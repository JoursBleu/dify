# Radeon Cloud

Radeon Cloud is a Dify model provider for AMD Radeon Cloud Token Factory. It
uses a fixed OpenAI-compatible endpoint and a curated model catalog.

## Configure

1. Open [Radeon Cloud Token Factory](https://developer.amd.com.cn/radeon/tokenfactory).
2. Sign in and create an API key beginning with `rc-`.
3. In Dify, open **Settings -> Model Provider -> Radeon Cloud**.
4. Enter the API key and save.

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

## Request attribution

Credential validation and model requests send `X-Source: dify` so Radeon Cloud
can measure aggregate usage from the Dify integration. The value is fixed and
does not contain a user, workspace, application, conversation, or request ID.

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
RUN_RADEON_LIVE=1 RADEON_API_KEY='rc-...' uv run pytest -q tests/test_live.py
```

For Dify remote debugging, copy `.env.example` to `.env`, insert the debug
server and key shown by Dify, then run:

```bash
uv run python -m main
```

The bundled icon is a development placeholder. Replace it with an approved AMD
or Radeon Cloud brand asset before publishing.

## Source and support

Source repository: <https://github.com/JoursBleu/dify>

During integration development, report issues in the source repository and do
not include API keys or prompt content. Contact: `kangletian@hotmail.com`.
