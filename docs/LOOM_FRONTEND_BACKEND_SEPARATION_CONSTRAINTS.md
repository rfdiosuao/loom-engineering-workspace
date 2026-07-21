# LOOM 前后端分离开发约束

更新时间：2026-07-02

## 目标

把 LOOM / 麓鸣改造成“前端可换壳、后端可复用、Agent 可调用”的本地自动化控制台：

- 前端只负责用户体验、页面状态、白标主题和交互编排。
- 后端统一承载账号、订阅、模型配置、组件安装、手机矩阵、任务队列、日志、MCP/CLI 能力。
- Codex、ClaudeCode、OpenCode、UI、CLI、MCP 都通过同一套后端能力面访问 LOOM，不各写一套业务逻辑。

## 主线边界

主线只认：

- `D:\Axiangmu\AUSTART\openclaw_new_launcher`
- `D:\Axiangmu\AUSTART\docs`
- `D:\Axiangmu\AUSTART\scripts`
- 与本次拆分直接相关的 tests、mocks、fixtures

不要扩大到旧 UI 大重构。旧 UI 只允许做隔离、兼容说明或最小转接。

## 分层规则

### 前端可以做

- 路由、布局、状态展示、动效、空状态、错误提示、白标主题。
- 调用统一 `LoomClient` 或等价 API facade。
- 做轻量表单校验，例如邮箱格式、必填项、按钮 disabled 状态。
- 展示任务进度、设备状态、账号状态、订阅页、模型列表、日志摘要。
- 使用 mock 数据支撑 UI 开发和 contract 测试。

### 前端禁止做

- 直接拼接账号、模型、wire、phone、matrix、MCP 协议字段。
- 直接读写 token、私钥、真实账号配置、本地发布包配置。
- 直接操控 ADB、APKClaw、Hermes、Codex、ClaudeCode、OpenClaw 安装细节。
- 在组件里写业务决策，例如“选择哪个模型可用”“注册还是登录”“任务如何重试”“是否允许批量外发”。
- 在多个页面复制同一段 fetch、错误解析、状态映射或本地缓存逻辑。

### 后端必须承载

- 账号注册、验证码登录、登录态保持、订阅信息、模型同步。
- Codex / ClaudeCode / OpenCode / Hermes / OpenClaw 的安装状态和模型配置。
- 手机单机控制、手机矩阵、ADB 兜底、APKClaw HTTP 快速通道。
- Task Ledger、Action Trace、Template Optimizer。
- 定时任务、任务模板、任务日志、失败重试、人工确认边界。
- secret redaction、release 排除规则、审计日志和安全策略。

## API 契约边界

所有 UI、CLI、MCP 都应收敛到同一组能力域：

| 域 | 建议路径 | 职责 |
|---|---|---|
| 系统状态 | `/api/status`, `/api/diagnostics/*` | 本地服务、依赖、端口、诊断、修复建议 |
| 账号订阅 | `/api/account/*` | 验证码、登录态、订阅、余额、模型额度 |
| 模型配置 | `/api/models/*`, `/api/wire/*` | 可用模型、默认模型、Agent 配置落盘 |
| 组件安装 | `/api/components/*` | Codex、ClaudeCode、OpenCode、Hermes、APKClaw 安装和修复 |
| 手机控制 | `/api/phone/*` | 单手机状态、截图、读屏、任务提交、ADB doctor |
| 手机矩阵 | `/api/matrix/*` | 设备注册、任务分发、watch、cancel、retry、线索记录 |
| 媒体能力 | `/api/media/*` | 生图、生视频、素材导入、模板化提示词 |
| 任务系统 | `/api/jobs/*`, `/api/logs/*` | 定时任务、运行日志、ledger、action trace |
| 设置主题 | `/api/config/*`, `/api/theme/*` | 本机设置、白标主题、UI 配置 |
| Agent 接入 | `/api/cli/*`, MCP tools | 给 Codex/ClaudeCode/OpenCode 的能力发现与调用 |

禁止新增“万能大接口”，例如 `/api/do-everything`。每个接口要能被 contract test 验证。

## 数据契约

- 后端返回结构化 JSON，前端不得从日志字符串里解析业务状态。
- 每个可复用 DTO 必须有稳定字段名，新增字段只能向后兼容。
- 不允许随意改动 `account`、`wire`、`phone`、`matrix`、`MCP` 已暴露字段。
- 错误返回必须包含：
  - `ok` 或等价状态
  - `code`
  - `message`
  - 可选 `detail`
  - 可选 `action`
- 高风险动作必须返回 `requiresConfirmation: true` 或后端直接拒绝。

## 安全约束

- 前端永远不持久化真实 API key、私钥、手机 token、短信验证码、用户密码。
- 只允许通过后端安全存储读取敏感配置。
- UI 日志只展示脱敏摘要，不展示完整 token、手机号、邮箱敏感段、cookie、私钥。
- 发布包不得包含 audit log、运行缓存、真实账号、真实用户数据、`.gradle`、`.kotlin`、`build` 等缓存。
- 本地 API 需要 localhost 绑定、来源校验或本机 token，避免被网页跨站调用。

## 合规约束

手机矩阵只能做合规自动化：

- 允许设备管理、任务模板、线索记录、定时执行、执行日志、失败重试。
- 外发消息、评论、私信、报价、承诺、批量触达必须有人确认或有明确模板授权。
- 不做批量骚扰、平台规则绕过、隐藏来源、绕验证码、绕风控、无确认外发高风险内容。

## 前端白标约束

前端必须可换壳：

- 品牌名、logo、色板、文案语气、联系方式、订阅页入口必须集中配置。
- 页面业务流程不能硬编码某个代理商或某个中转站。
- 白标换壳不得影响后端 API、MCP、CLI 和任务记录格式。
- UI 主题要统一，不允许“安装页一套配色、创作页一套配色、账号页一套配色”。

## 迁移策略

采用 strangler pattern 渐进剥离：

1. 先加统一 `LoomClient`，不立刻大改页面。
2. 每次迁移一个页面或一个能力域。
3. 迁移后新增 contract test，禁止回退到组件内直接拼业务逻辑。
4. CLI/MCP 与 UI 对齐同一后端能力，不复制实现。
5. 每轮改动都能独立构建、回滚和解释。

## 不可破坏清单

- Lumi / APKClaw 签名链路。
- 现有 phone HTTP 快速通道与 ADB 兜底能力。
- Codex / ClaudeCode / OpenCode 已有安装路径和配置兼容。
- 新老账号登录态兼容。
- `loom_cli.py` 与 `loom_mcp.py` 的核心命令发现能力。
- 现有 route contract tests 覆盖的 API 字段。

## 完成定义

前后端分离第一阶段完成时，应满足：

- 已迁移页面不再直接散落 fetch / invoke / 本地业务判断。
- 前端通过统一 client 调用后端，并有 mock/contract 测试。
- 后端拥有稳定 API 契约和错误格式。
- CLI/MCP 调用和 UI 调用走同一后端核心。
- 白标主题、订阅页、模型账号页不再和业务逻辑耦合。
- 构建、Python 编译、相关测试通过或明确说明缺失前置条件。
