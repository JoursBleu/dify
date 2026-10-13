# AMDGPUCloud

**作者：Letian Kang**  
**联系邮箱：Letian.Kang@amd.com**

这是 AMD GPU Cloud / Token Factory 的 Dify 原生模型供应商插件，显示名为 **AMDGPUCloud**，当前为集成预览版。
使用固定的 OpenAI-compatible API 和随插件版本发布的模型目录；用户只需填写 `rc-*` API Key。

参照 Cherry Studio 的集成：使用标准供应商入口、复用已有 OpenAI-compatible 接口、
手动获取 Key；使用 AMD GPU Cloud 页面 Logo。本插件在 Dify 与其他模型供应商统一管理，
不通过安装器中的独立“Radeon 插件”按钮。

**请使用0.0.8：个人发布者版。** 发布者为 `letian-kang`，插件名和Provider名为 `amdgpucloud`。
原生安装框标识 `letian-kang/amdgpucloud`，显示名称仍为 **AMDGPUCloud**。
规范Provider为 `letian-kang/amdgpucloud/amdgpucloud`；带点的 `letian.kang` 不符合原生标识规则。

## 配置

1. 打开 [AMD GPU Cloud Model APIs](https://developer.amd.com.cn/radeon/modelapis)，登录并取得自己的 `rc-*` Key。
2. 在 Dify 原生“集成 → 安装 → 从本地文件”安装 `AMDGPUCloud-0.0.8.difypkg`。
3. 打开 Integrations → Model Provider → AMDGPUCloud（部分版本在 Settings 下），填写 Key 并保存。
4. 在 Chat、Agent 或 Workflow 中选择模型。

本版不仅改标签，也更换了完整机器身份。旧版不能当作同ID升级；安装后应在新Provider配置Key，
再迁移默认模型和App／Workflow引用，确认无依赖后再通过Dify原生页面卸载旧版。
安装器不会自动迁移Key、改写应用或删除旧插件；已有Dify无需重装。
Windows操作详见同目录 `INSTALL_windows_zh_Hans.txt`。

固定入口：`https://developer.amd.com.cn/radeon/api/v1`。插件不接受自定义 URL。
保存凭据会发送一个最多生成 1 Token 的短请求，因此验证也会消耗少量额度。
`/models` 只检查模型是否存在，不能用它证明 Key 有效。

## 首版模型与限制

- `DeepSeek-V4-Flash`
- `DeepSeek-V4.1-Flash`
- `Qwen3.8-Flash-Next`

预览版支持文本、流式输出、单工具调用和 JSON Object；图片能力取决于模型。
不声明并行工具、JSON Schema、Embedding 或 OCR 能力。
模型 YAML 的最大输出值是**待验证的预览限制**，不是生产 API 的承诺上限。
在真实 Token Factory Key、Dify UI、工具续轮和图片测试完成前，不宣称已正式接入。

## 价格与请求归因

Dify 展示的是普通输入／输出 Token 的估算价格，不包含 KV Cache 折扣。
**实际扣费与每日额度以 Token Factory 账单为准**；限额取决于账号，不保证所有用户每日额度相同。

插件固定发送 `X-Source: dify`，用于汇总渠道用量，不包含用户、工作区、应用或会话 ID。
获取 Key 的链接不使用 `source=cherry-studio`，也不虚构尚未实现的 `source=dify` 登录归因；不自动回填 Key。
请求正文可能包含 Prompt、对话、图片、工具参数与结果。
插件不额外持久化这些数据；但 Token Factory 和上游服务可能记录请求数据，
不能将“不新增插件存储”理解成平台零留存。敏感数据使用前请阅读 `PRIVACY.md`。

## 开发与发布边界

默认测试不请求线上 API；只有显式开启 Live Test 并提供专用测试 Key 才会发送真实调用。
预览包通过本地校验不等于已上架 Marketplace。
正式发布前仍需核验输出上限、模型价格、AMD 品牌图标、Publisher、支持联系信息和隐私／服务条款。
本地图标来自 AMD GPU Cloud 网页 Logo，与 Cherry Studio 的白底居中方式一致；不表示 Marketplace 品牌审核已完成。

反馈时只附脱敏错误和版本，不提交 API Key、完整 Prompt 或内部服务地址。

开发包发布者为 `letian-kang`，人类作者署名 **Letian Kang**，联系 **Letian.Kang@amd.com**。
源码在JoursBleu/dify的feature/radeon-cloud-provider分支plugins/amdgpucloud；仓库owner与插件slug分开。
合法slug不证明已取得Marketplace账号归属或AMD／Dify批准，当前未上架Marketplace。