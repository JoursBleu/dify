# AMDTokenFactory

**作者：AMDTokenFactory**  
**自然人作者：Letian Kang**  
**联系邮箱：Letian.Kang@amd.com**

**版本 0.0.12：实验性原生目录集成源码，尚未达到 Marketplace 发布条件。**
本次实现聊天模型自动目录接口，仅供 Draft 审查，不是可独立用于原版 Dify 的正式包。
目录内不包含 Dify API、SDK、daemon、Graphon 源码、API overlay 或 Windows 完整应用安装器。
非 Draft 发布前必须选择已获批准的配套版本并完成验收。

## 安装与配置

自动列出模型需要 **UNRELEASED（尚未发布）的配套 SDK／plugin-daemon／Dify／Graphon 修改**，
不是原版 Dify 1.17.1 或已发布 SDK 0.10.2 的能力。协议由 `remote_model_catalog: true` 声明启用，
`get_ai_model_list` 动作调用 `fetch_models(model_type, credentials)`，响应 `models` 为 AIModelEntity 列表。
四个组件须使用一致协议；`minimum_dify_version: 1.17.1` 只是安装下限，不保证原生目录兼容。
项目及锁文件保留公开 SDK 0.10.2 用于可复现 Draft 审查，不下载或内置修改版 SDK；
本次在旧 SDK 上配置凭据会明确拒绝，不能把依赖版本当作原生目录已支持。

原版环境的预定义列表仍为空，**标准模型选择器中没有本供应商可选模型**。
现有基类可以加载 provider 覆盖方法，但不会分派新 RPC，也不识别新声明字段。
旧 SDK 下保存 Key 会在任何网络请求前报兼容性错误，避免再次显示“Key 绿色、0 Models”；
这不能认证 daemon 或宿主版本，完整配套链路仍是必要条件。
凭据验证成功不代表 Chat／Agent／Workflow 已通过验收；不提供手动模型 ID 或逐模型凭据的替代方案。

仅在配套栈集成并提供已审查构建后，供测试 Workspace 验证：
1. 若提供了已审查的 `AMDTokenFactory-0.0.12.difypkg`，可从“集成 → 安装 → 从本地文件”导入。
2. 从 [AMDTokenFactory Model APIs](https://developer.amd.com.cn/radeon/modelapis) 手动取得自己的 `rc-*` Key。
3. 在“模型提供方 → AMDTokenFactory”安全表单配置统一 API Key。
  配套原生目录链路应自动获取所有符合条件的聊天 ID 和元数据，不手动录入模型 ID，不配置逐模型凭据。
  Python 宿主／SDK／插件链路已由模拟传输和数据的离线集成测试覆盖；真实部署与浏览器验收尚未完成。

固定入口为 `https://developer.amd.com.cn/radeon/api/v1`，不接受自定义 URL。
保存凭据会发送 `max_tokens=1` 的短验证请求，即使选择器为空也可能产生计费、消耗额度；
`/models` 不能单独证明 Key 有效。本地包或未签名包被拒绝时联系管理员，不擅自关闭生产安全校验。
Windows 操作见 [INSTALL_windows_zh_Hans.txt](INSTALL_windows_zh_Hans.txt)。
这是浏览器插件操作说明，不是 EXE／MSI；插件不安装 Dify／WSL／Docker。

### 原生集成状态

SDK 声明／分派与 daemon／Dify／Graphon 消费链路分别由配套修改实现，尚未发布。
本插件不修改宿主 API，不提供 overlay 部署步骤，也不指导 API／Compose 修改或服务重启。
配套审查源码：SDK `f9ba731`、daemon `2820380`、Graphon `9b2ae3b`、Dify API `9c39d70`；
完整固定提交链接见英文 README 的 Native integration status，不代表已合并或发布。
远端发现需求见已创建的 [Dify Issue #44157](https://github.com/langgenius/dify/issues/44157)；
此前 [PR #44142](https://github.com/langgenius/dify/pull/44142) 已关闭、未合并，不代表原型已获上游支持。

## 动态目录与兼容边界

`AMDTokenFactoryModelProvider.fetch_models` 经共享 `fetch_catalog` 和既有脱敏异常映射，
返回所有符合条件的远端聊天 LLM 的 AIModelEntity；非 LLM 类型不联网，返回空列表。
列目录只调用固定 `/models`，不发送聊天请求；保存凭据仍保留单独且可能计费的验证请求。
保留 `predefined: []` 和统一 Key 表单，没有模型 YAML、硬编码 ID、手动模型录入或兜底清单。
模型、上下文、能力、参数及价格来自元数据；支持结构内新增模型无需重打包，自动 UI 列表仍依赖配套栈。

插件内存缓存复用 TTL 为 30 秒，以凭据 SHA-256 摘要为键，不存原始 Key 或 Prompt。
缓存与当前写入者元数据分别最多 64 项；查找时清理过期项，完成请求后清理写入者。
租户／Provider 隔离由宿主负责，不由插件的仅凭据缓存推断。
刷新失败脱敏报错，不以旧目录兜底；旧在途请求可返回其自身调用者，但不能在新刷新、失败、淘汰或清空后
覆盖或重新填充缓存。畸形 status 类型安全失败；调用检查目录成员资格。输入最多 2 MiB、2,048 条。
未知最大输出值不虚构上限，默认输出预算只是客户端设置，不是服务最大值。
单工具、JSON Object 取决于元数据；保留声明图片输入的 vision LLM，按元数据过滤 OCR／非聊天模型，
不是排除所有视觉 LLM。不声明并行工具、JSON Schema、Embedding、OCR 或视频能力；代码能力不等于端到端验收通过。

## 身份与已保存凭据

技术插件 ID 为 **`amdtokenfactory/amdtokenfactory`**，完整 Provider 为
`amdtokenfactory/amdtokenfactory/amdtokenfactory`。文首投稿作者名称不修改技术标识，也不证明 publisher 归属。
原 ID `amdgpucloud/amdgpucloud` 与此不同，不是原标识下的升级，已保存凭据不能自动迁移。
不要卸载旧供应商或复制已保存 Key；仅通过安全凭据表单配置 AMDTokenFactory，
默认模型和应用引用须另行检查。目录刷新不迁移凭据，也不改写应用。

## 价格、隐私与归因

Dify 展示普通输入／输出估算价格，不包含缓存折扣；实际扣费、额度与限额以 AMDTokenFactory 账号和账单为准。
请求固定带 `X-Source: dify` 汇总渠道用量，不附加用户、工作区、应用、会话或请求标识，不自动授权或回填 Key。
Prompt、历史、图片和工具数据会发送到 AMD API；插件不新增持久化存储，但服务可能保留日志。
敏感数据使用前请阅读 [PRIVACY.md](../PRIVACY.md)，不要将“不新增存储”理解成平台零留存。

## 开发与验收

- 源码开发使用 Python 3.12；`scripts/run_live_tests.py`、`scripts/check_package.py`、`.env.example`
  仅是源码开发引用，不是包内工具或安装步骤。
- 默认测试不调用公网；显式 Live Test 可能计费。仅使用专用 `rc-*` 测试 Key，文件须本人拥有、
  非符号链接的普通文件且权限不宽于 `0600`；不使用内部订阅 Key，不将 Key 写入 CI、日志、Prompt 或命令参数。
  源码启动器避免 Key 进入 argv 并屏蔽敏感诊断。
- JSON／SSE 须完整且包含用量，不自动重放流；重定向、异常帧和缺少 `[DONE]` 均安全失败。
  HTTP 读取超时为 600 秒，宿主执行期限可能另行限制长请求。

离线 provider 覆盖方法测试可在 SDK 0.10.2 上运行，覆盖全量新 ID、元数据、脱敏错误、无聊天调用，
以及确定性缓存竞态与有界清理；不等同于原生 SDK 分派或 UI 验收。原生 SDK 测试属于独立集成任务。
未来实际构建须重跑包安全与官方 Marketplace 校验，包括新声明字段兼容性。
原生列表支持、公网 Key 的 Chat／Agent／Workflow、视觉／JSON／工具续轮验收及 GPU 侧取消仍待完成。
非 Draft 发布前还需核验当前输出上限、价格、publisher 归属、许可和品牌授权，不能视为已经批准。

## 源码、支持与许可

源码：<https://github.com/JoursBleu/dify>。反馈仅附脱敏错误和版本，不提交 API Key 或完整 Prompt；联系作者见文首。
[Dify 开源许可证](https://github.com/JoursBleu/dify/blob/696759f84024eb01e53dd19f546139b5e4b2cc28/LICENSE)及第三方声明继续适用。
本地 Logo 保留 AMD GPU Cloud 页面的来源资产，不加载远端图片；来源、校验和及商标边界见
[BRAND_ASSET_NOTICE.txt](../_assets/BRAND_ASSET_NOTICE.txt)，
`scripts/prepare_brand_icon.ps1` 仅为源码复现辅助工具。
实验性 Draft 不代表 AMD／Dify 批准、法律许可结论或 Marketplace publisher 身份。