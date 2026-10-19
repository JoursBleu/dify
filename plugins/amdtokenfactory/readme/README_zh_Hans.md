# AMD Token Factory

作者：Letian Kang · 联系邮箱：Letian.Kang@amd.com

## 简介

[AMD Token Factory](https://developer.amd.com.cn/login?source=sta8ZpC3e) 提供**基于 AMD GPU 的开源模型 API，每日赠送免费额度**，无需配置 GPU。

服务兼容 OpenAI 和 Anthropic 接口。本插件使用 OpenAI 兼容接口：
`https://developer.amd.com.cn/radeon/api/v1`

## 🎁 每日免费额度

| 项目 | 账号限额示例 |
|---|---|
| **每日免费额度** | **1 USD/天**，每日重置 |
| 请求频率 | **20 次/分钟** |

**点数（pts）用于统计免费额度的使用情况，不会向你计费**。实际限额因账号而异，请在 AMD 账号的 **Model Usage** 页面查看你的免费额度、请求限制和重置时间。

## 模型

| 模型 | 上下文 | 图片输入 |
|---|---|---|
| DeepSeek-V4.1-Flash | 1M | ✓ |
| DeepSeek-V4-Flash | 1M | |
| GLM-5.3-Flash | 256K | |
| MiMo-V2.6-Flash | 1M | ✓ |
| Qwen3.8-Flash-Next | 256K | ✓ |
| Qwen3.8-27B | 256K | ✓ |
| Gemma-4-31B-IT | 256K | ✓ |

所有模型都支持**流式输出、工具调用和推理内容**，回复格式可选文本、JSON Object 或 JSON Schema。新模型随插件更新提供。

## 配置

1. 在 **[AMD Token Factory Model APIs](https://developer.amd.com.cn/login?source=sta8ZpC3e)** 免费获取 API Key（以 `rc-` 开头）。
2. 在 Dify 中打开 **设置 → 模型供应商 → AMD Token Factory**，填入 Key 并保存。

保存时插件会向 `Qwen3.8-27B` 发一个 1 token 的请求来校验 Key。插件需要能通过 HTTPS 访问 `developer.amd.com.cn`；单次请求最长 **300 秒**。

## 使用

在聊天助手、Agent、工作流 LLM 节点或其他应用中选择 AMD Token Factory 模型。用**每日免费额度**验证想法、搭建 AI 应用原型。

在 AMD 账号的 **Model Usage** 页面可以查看已用和剩余点数、每日 token 用量、请求限制、重置时间和各模型用量；点击 **Refresh** 刷新记录。

## 隐私

Prompt、对话历史、图片和工具数据会发送到 `developer.amd.com.cn`，插件本身不存储任何数据。详见 [PRIVACY.md](https://github.com/JoursBleu/dify/blob/feature/amdtokenfactory-marketplace-preview/plugins/amdtokenfactory/PRIVACY.md)。

## 支持

插件：[Letian.Kang@amd.com](mailto:Letian.Kang@amd.com)<br>
Token Factory 服务：[member-service@mail.developer.amd.com.cn](mailto:member-service@mail.developer.amd.com.cn)<br>
源码：[dify/plugins/amdtokenfactory at feature/amdtokenfactory-marketplace-preview · JoursBleu/dify](https://github.com/JoursBleu/dify/tree/feature/amdtokenfactory-marketplace-preview/plugins/amdtokenfactory)
