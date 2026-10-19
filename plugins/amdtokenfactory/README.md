# AMD Token Factory

Author: Letian Kang · Contact: Letian.Kang@amd.com

## Overview

[AMD Token Factory](https://developer.amd.com.cn/login?source=sta8ZpC3e) provides **open-model APIs on AMD GPUs with a daily free quota**—no GPU setup required.

The service supports OpenAI- and Anthropic-compatible APIs. This plugin uses the OpenAI-compatible endpoint:
`https://developer.amd.com.cn/radeon/api/v1`

## 🎁 Daily Free Quota

| Item | Example Account Limits |
|---|---|
| **Daily free quota** | **1 USD/day**, reset daily |
| Request rate | **20 requests/minute** |

**Points (pts) track your free quota usage—you are not billed for them.** Actual limits vary by account. Check **Model Usage** in your AMD account for your free quota, request limits, and reset time.

## Models

| Model | Context | Image Input |
|---|---|---|
| DeepSeek-V4.1-Flash | 1M | ✓ |
| DeepSeek-V4-Flash | 1M | |
| GLM-5.3-Flash | 256K | |
| MiMo-V2.6-Flash | 1M | ✓ |
| Qwen3.8-Flash-Next | 256K | ✓ |
| Qwen3.8-27B | 256K | ✓ |
| Gemma-4-31B-IT | 256K | ✓ |

All models support **streaming, tool calling, and reasoning content**, with text, JSON Object, or JSON Schema responses. New models arrive through plugin updates.

## Configure

1. Get your free API key from **[AMD Token Factory Model APIs](https://developer.amd.com.cn/login?source=sta8ZpC3e)**. Keys start with `rc-`.
2. In Dify, open **Settings → Model Provider → AMD Token Factory**, enter your key, and save.

Saving the key sends a one-token validation request to `Qwen3.8-27B`. The plugin requires outbound HTTPS access to `developer.amd.com.cn`; each request can run for up to **300 seconds**.

## Usage

Select an AMD Token Factory model in your chatbot, agent, workflow LLM node, or other app. Use your **daily free quota** to test ideas and build AI application prototypes.

Open **Model Usage** in your AMD account to track used and remaining points, daily token usage, request limits, reset time, and per-model usage. Click **Refresh** for updated records.

## Privacy

Prompts, conversation history, images, and tool data are sent to `developer.amd.com.cn`. The plugin itself stores no data. See [PRIVACY.md](https://github.com/JoursBleu/dify/blob/feature/amdtokenfactory-marketplace-preview/plugins/amdtokenfactory/PRIVACY.md).

## Support

Plugin: [Letian.Kang@amd.com](mailto:Letian.Kang@amd.com)<br>
Token Factory service: [member-service@mail.developer.amd.com.cn](mailto:member-service@mail.developer.amd.com.cn)<br>
Source: [dify/plugins/amdtokenfactory at feature/amdtokenfactory-marketplace-preview · JoursBleu/dify](https://github.com/JoursBleu/dify/tree/feature/amdtokenfactory-marketplace-preview/plugins/amdtokenfactory)
