# LOOM Core Business Stability Implementation Plan

> **受控副本元数据**
> - 纳管日期：2026-07-28
> - 冻结基线：`4f2a01e40c2e0b777ec4f279e06969f962b4bc08`
> - 来源 SHA256：`AA150D20ED24745BE58F1410CCC94C087EABB7D27EF480459F428DF12DCA54ED`
> - 本副本只补充基线元数据；原路线内容保持不变。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 LOOM 从“功能很多但首次成功率不稳定”的综合工具，收敛为以中转站账号、主流智能体安装和模型接入为第一主线，并以手机矩阵和媒体创作为差异化增值能力的稳定商业产品。

**Architecture:** 保留现有 Tauri + React 桌面端、FastAPI Bridge、Python 核心服务、CLI/MCP 和 Android AgentPhone 架构。所有安装、模型发现、配置写入、健康检查和故障分类统一由 Bridge 提供，UI、CLI、MCP 和原生 Agent 只消费同一能力面；手机矩阵进入稳定维护期，不再建立第二套执行协议。

**Tech Stack:** Tauri 2、React 18、TypeScript、FastAPI、Python 3、Rust、NSIS、Node.js、LOOM CLI/MCP、NewAPI/兼容中转站接口、Android AgentPhone。

## Global Constraints

- 默认使用简体中文呈现安装、模型、网络、账号和上游错误；原始错误码保留在可展开详情中。
- 不把 API Key 当作 LOOM 授权码，不在日志、命令行、URL、进程列表或 API 响应中暴露明文密钥。
- 中转站账号身份、模型余额、LOOM 产品权益和手机设备席位必须分别建模。
- 支持 LOOM 托管中转站、自定义中转站和用户自带 Key；托管服务故障不得阻止本地只读能力启动。
- 写配置必须先备份、原子写入、回读校验；失败时恢复原配置，不能显示假成功。
- 重新配置或覆盖升级不得删除 Codex、Claude Code、OpenCode 的历史会话和用户自定义配置。
- Codex、Claude Code 和 OpenCode 是 `2.4.0` 首批正式支持对象；OpenClaw、Hermes 保持兼容维护，不扩大主路径。
- 手机矩阵在 `2.4.x` 期间只修复 P0/P1 缺陷，不新增控制协议、视觉模型或平台发布流程。
- 生图、生视频和全案九步在 `2.4.x` 期间只修复阻断性问题，不增加新的供应商和工作流。
- 每项任务必须先补失败测试，再实现，再运行定向测试与全量发行门禁。
- 未单独注明工作目录的 Python、Node、Rust 和前端命令，均从 `apps/loom-platform/openclaw_new_launcher` 执行；工作区门禁从仓库根目录执行。

---

## 1. 产品决策

### 1.1 主产品定义

LOOM 在下一阶段统一对外定义为：

> 快速安装主流 AI 智能体、自动接入可用模型、持续检测并修复运行环境的本地 AI 工作台。

### 1.2 优先级

| 优先级 | 能力 | 商业作用 | 下一阶段策略 |
| --- | --- | --- | --- |
| P0 | 中转站账号与模型服务 | 直接收入与留存 | 主开发线 |
| P0 | Codex / Claude Code / OpenCode 安装配置 | 新用户首次价值 | 主开发线 |
| P0 | 模型发现、验证、选择和故障分类 | 决定产品是否可用 | 主开发线 |
| P1 | 自动更新、诊断、日志、数据保护 | 降低售后成本 | 持续建设 |
| P1 | 原生中枢智能体 | 统一使用入口 | 只优化可靠性 |
| P2 | 手机连接与矩阵 | 差异化高级能力 | 稳定维护期 |
| P2 | 生图、生视频、全案九步 | 增值能力 | 阻断缺陷维护 |
| P3 | YOLO、游戏控制、新平台自动发布 | 未来能力 | 暂停 |

### 1.3 暂停项

在 `2.4.0` 达到发行门槛前，不开始以下工作：

- 新增手机控制动作或新的手机通信协议。
- 新增媒体供应商、全案步骤或创作页面。
- 新增不产生安装、配置、付费或留存价值的 UI 页面。
- 同时支持更多 Agent，导致首批三个 Agent 的兼容测试被稀释。
- 只为隐藏错误而增加重试，不先建立错误分类和上游健康证据。

---

## 2. 成功指标

### 2.1 首次使用

| 指标 | `2.4.0` 门槛 |
| --- | --- |
| 干净 Windows 10/11 x64 安装 LOOM 成功率 | >= 98% |
| Codex / Claude Code / OpenCode 单项安装成功率 | >= 95% |
| 安装后真实启动检测成功率 | >= 95% |
| 从打开 LOOM 到首轮有效对话 | P50 <= 5 分钟 |
| 配置成功但实际不可调用的假阳性 | 0 |
| 失败场景具有中文原因、错误码和建议动作 | 100% |

### 2.2 模型接入

| 指标 | `2.4.0` 门槛 |
| --- | --- |
| 写入的模型必须存在于账号可用目录 | 100% |
| 写入前真实轻量探测通过 | 100% |
| 配置失败恢复原文件 | 100% |
| 上游故障与本地配置故障准确区分 | 100% 已知错误 |
| 托管模型不可用时允许用户切换备用或 BYOK | 100% |

### 2.3 发行与售后

| 指标 | 门槛 |
| --- | --- |
| 覆盖升级保留账号、配置和历史会话 | 100% |
| 自动更新失败可回退或手动继续 | 100% |
| P0 回归 | 0 |
| P1 已知缺陷 | 必须有明确规避方案和负责人 |
| 客服可导出的诊断摘要 | 不含密钥，可直接定位所属故障域 |

---

## 3. 版本路线

### `2.4.0`：安装与模型稳定版

- Codex、Claude Code、OpenCode 安装前预检、安装、启动验证、修复和卸载闭环。
- 统一模型目录、能力标签、真实探测、配置事务和中文错误。
- 首次使用向导只保留账号、Agent、模型和首轮验证四步。
- 上游故障与本地故障明确分离。

### `2.4.1`：账号与权益中心

- 中转站账号统一登录。
- 模型余额、LOOM 权益、设备席位分离。
- 原授权码降级为一次性兑换码或渠道码。
- 换机、解绑和离线宽限期。

### `2.4.2`：健康与故障切换

- 模型健康快照、备用模型、熔断和恢复。
- 供应商状态历史和客服诊断摘要。
- 原生 Agent 使用同一健康结果，停止重复探测刷屏。

### `2.5.0`：手机矩阵可靠性版

- 只有在 `2.4.x` 主链路达标后恢复矩阵开发。
- 完成 10 台实体手机 2 小时 soak、截图并发、急停和长任务状态一致性。
- 不以增加功能代替稳定性验收。

---

## 4. 文件边界

### 安装链路

- `apps/loom-platform/openclaw_new_launcher/python/core/component_installer.py`：组件预检、安装、检测、修复和卸载核心。
- `apps/loom-platform/openclaw_new_launcher/python/api/routes_components.py`：安装 API、错误分类和安全响应。
- `apps/loom-platform/openclaw_new_launcher/src/components/agents/AgentInstallerPage.tsx`：安装状态、操作入口和中文反馈。
- `apps/loom-platform/release-manifest.json`：受信组件、架构、版本、大小和哈希。
- `apps/loom-platform/openclaw_new_launcher/python/tests/test_component_installer.py`：安装核心回归。
- `apps/loom-platform/openclaw_new_launcher/python/tests/test_routes_components.py`：安装 API 回归。
- `apps/loom-platform/openclaw_new_launcher/python/tests/test_agent_installer_page_contract.py`：安装 UI 合同。

### 模型与配置链路

- `apps/loom-platform/openclaw_new_launcher/python/core/wire_config.py`：模型发现、探测、Agent 配置事务和回滚。
- `apps/loom-platform/openclaw_new_launcher/python/core/newapi_account_manager.py`：托管账号、模型目录和账户同步。
- `apps/loom-platform/openclaw_new_launcher/python/core/loom_model_client.py`：LOOM 原生 Agent 模型请求。
- `apps/loom-platform/openclaw_new_launcher/python/api/routes_wire.py`：模型接线和验证 API。
- `apps/loom-platform/openclaw_new_launcher/python/api/routes_account.py`：账号和模型目录 API。
- `apps/loom-platform/openclaw_new_launcher/src/components/models/ModelsPage.tsx`：模型选择、能力和健康状态。
- `apps/loom-platform/openclaw_new_launcher/python/tests/test_wire_config.py`：模型配置与回滚测试。
- `apps/loom-platform/openclaw_new_launcher/python/tests/test_newapi_account_manager.py`：账号和模型目录测试。
- `apps/loom-platform/openclaw_new_launcher/python/tests/test_loom_model_client.py`：原生 Agent 模型兼容测试。

### 账号与权益链路

- `apps/loom-platform/openclaw_new_launcher/python/core/member_manager.py`：本地账号状态。
- `apps/loom-platform/openclaw_new_launcher/python/core/feature_access.py`：LOOM 功能权益判定。
- `apps/loom-platform/openclaw_new_launcher/python/api/routes_member.py`：登录与本地会话 API。
- `apps/loom-platform/openclaw_new_launcher/python/api/routes_license.py`：旧授权兼容与兑换迁移。
- `apps/loom-platform/license_server/luming_license/domains/accounts.py`：服务端账号域模型。

### 稳定维护链路

- `apps/loom-platform/openclaw_new_launcher/python/api/routes_diagnostics.py`：可导出的结构化诊断。
- `apps/loom-platform/openclaw_new_launcher/src/components/diagnostics/DiagnosticsPage.tsx`：中文诊断和修复入口。
- `apps/loom-platform/openclaw_new_launcher/python/core/phone_matrix.py`：矩阵 P0/P1 修复，不增加协议。
- `apps/loom-platform/openclaw_new_launcher/python/api/routes_matrix.py`：矩阵状态和任务 API。
- `apps/loom-platform/openclaw_new_launcher/src/components/matrix/MatrixWorkbenchPage.tsx`：矩阵状态一致性。

---

## Task 1: 冻结范围并建立真实成功率基线

**Files:**
- Create: `docs/reviews/2026-07-27-agent-install-model-baseline.md`
- Modify: `docs/DEVELOPMENT_WIKI.md`
- Modify: `docs/runbooks/agent-reliability-release-gates.md`

**Interfaces:**
- Consumes: 当前组件安装日志、模型接线错误、发行冒烟结果。
- Produces: 每个 Agent、Windows 版本、模型供应商和失败类型的基线表。

- [ ] **Step 1: 固定测试矩阵**

记录 Windows 10 x64、Windows 11 x64，全新安装、覆盖安装、离线重开四种环境；每种环境分别验证 Codex、Claude Code、OpenCode。

- [ ] **Step 2: 固定五段用户旅程**

每次测试都按“安装 LOOM → 登录账号 → 安装 Agent → 选择模型 → 首轮对话”记录步骤耗时、结果和错误码。

- [ ] **Step 3: 建立故障域统计**

故障只能归入以下之一：`loom_installer`、`agent_package`、`local_environment`、`account_auth`、`model_permission`、`provider_upstream`、`network`、`unknown`。

- [ ] **Step 4: 增加发行门禁入口**

在 `docs/runbooks/agent-reliability-release-gates.md` 中加入基线执行方法和证据保存路径。

- [ ] **Step 5: 运行当前基线**

Run:

```powershell
.\scripts\verify.ps1 -Area platform
```

Expected: 自动化测试通过；真实账号和真实 Agent 测试结果写入基线文档，不把未执行项标记为成功。

- [ ] **Step 6: Commit**

```powershell
git add docs/reviews/2026-07-27-agent-install-model-baseline.md docs/DEVELOPMENT_WIKI.md docs/runbooks/agent-reliability-release-gates.md
git commit -m "docs: freeze agent install and model reliability baseline"
```

---

## Task 2: 将安装器收敛为可验证事务

**Files:**
- Modify: `apps/loom-platform/openclaw_new_launcher/python/core/component_installer.py`
- Modify: `apps/loom-platform/openclaw_new_launcher/python/api/routes_components.py`
- Modify: `apps/loom-platform/openclaw_new_launcher/src/components/agents/AgentInstallerPage.tsx`
- Modify: `apps/loom-platform/release-manifest.json`
- Test: `apps/loom-platform/openclaw_new_launcher/python/tests/test_component_installer.py`
- Test: `apps/loom-platform/openclaw_new_launcher/python/tests/test_routes_components.py`
- Test: `apps/loom-platform/openclaw_new_launcher/python/tests/test_agent_installer_page_contract.py`

**Interfaces:**
- Consumes: 受签名或受哈希保护的组件清单。
- Produces: `preflight → download → verify → install → launch_probe → ready` 状态机和结构化失败结果。

- [ ] **Step 1: 为三个首批 Agent 增加失败测试**

覆盖错误架构、包损坏、入口缺失、PATH 不可用、残留进程、启动超时和用户配置已存在。

- [ ] **Step 2: 定义统一安装结果**

安装 API 必须返回：

```json
{
  "ok": false,
  "componentId": "claude-code",
  "phase": "launch_probe",
  "errorCode": "component_wrong_architecture",
  "message": "当前组件与 Windows x64 不兼容。",
  "retryable": false,
  "preservedUserData": true
}
```

- [ ] **Step 3: 实现安装事务**

下载进入临时目录，校验大小与 SHA256 后解压到 staging；真实运行 `--version` 或受控健康命令成功后，才原子替换受管目录。

- [ ] **Step 4: 保留用户数据**

安装、修复和重新配置不能删除 Agent 的会话目录、用户级配置或 LOOM 之外创建的自定义 provider。

- [ ] **Step 5: 更新中文 UI**

UI 显示当前阶段和可执行动作；错误详情默认折叠，主文案不直接展示 Python traceback、HTTP body 或英文供应商原文。

- [ ] **Step 6: 运行定向测试**

Run:

```powershell
python -m pytest python/tests/test_component_installer.py python/tests/test_routes_components.py python/tests/test_agent_installer_page_contract.py -q
```

Expected: PASS，且不存在“安装成功但启动验证失败”仍返回 `ok: true` 的用例。

- [ ] **Step 7: Commit**

```powershell
git add python/core/component_installer.py python/api/routes_components.py src/components/agents/AgentInstallerPage.tsx release-manifest.json python/tests/test_component_installer.py python/tests/test_routes_components.py python/tests/test_agent_installer_page_contract.py
git commit -m "fix: make managed agent installation transactional"
```

---

## Task 3: 建立统一模型目录与能力协商

**Files:**
- Create: `apps/loom-platform/openclaw_new_launcher/python/core/model_catalog.py`
- Modify: `apps/loom-platform/openclaw_new_launcher/python/core/newapi_account_manager.py`
- Modify: `apps/loom-platform/openclaw_new_launcher/python/api/routes_account.py`
- Modify: `apps/loom-platform/openclaw_new_launcher/src/components/models/ModelsPage.tsx`
- Create: `apps/loom-platform/openclaw_new_launcher/python/tests/test_model_catalog.py`
- Test: `apps/loom-platform/openclaw_new_launcher/python/tests/test_newapi_account_manager.py`
- Test: `apps/loom-platform/openclaw_new_launcher/python/tests/test_models_page_contract.py`

**Interfaces:**
- Consumes: 中转站模型列表、账号权限和供应商元数据。
- Produces: `ModelDescriptor`，供配置、原生 Agent、创作和 UI 共同读取。

- [ ] **Step 1: 定义模型描述**

`ModelDescriptor` 必须包含：

```python
@dataclass(frozen=True)
class ModelDescriptor:
    model_id: str
    display_name: str
    provider_id: str
    capabilities: frozenset[str]
    protocols: frozenset[str]
    available: bool
    unavailable_reason: str | None
```

能力值限定为 `chat`、`tools`、`vision`、`image_generation`、`video_generation`、`coding`。

- [ ] **Step 2: 增加目录归一化测试**

覆盖 OpenAI 兼容目录、NewAPI 分组权限、重复模型、空模型列表、账号无权模型和供应商临时下线。

- [ ] **Step 3: 实现目录归一化**

模型必须来自账号实际可见目录；静态推荐列表只能用于排序和中文说明，不能把不存在的模型标成可配置。

- [ ] **Step 4: 更新模型页面**

按“对话与编程、视觉、生图、生视频”分组；不可用模型禁用选择，并显示“无权限、上游下线、协议不兼容”等具体原因。

- [ ] **Step 5: 运行定向测试**

Run:

```powershell
python -m pytest python/tests/test_model_catalog.py python/tests/test_newapi_account_manager.py python/tests/test_models_page_contract.py -q
```

Expected: PASS；`selected_model_not_listed` 在进入配置写入前被识别。

- [ ] **Step 6: Commit**

```powershell
git add python/core/model_catalog.py python/core/newapi_account_manager.py python/api/routes_account.py src/components/models/ModelsPage.tsx python/tests/test_model_catalog.py python/tests/test_newapi_account_manager.py python/tests/test_models_page_contract.py
git commit -m "feat: add account-aware model capability catalog"
```

---

## Task 4: 配置前探测、原子写入与回滚

**Files:**
- Create: `apps/loom-platform/openclaw_new_launcher/python/core/model_probe.py`
- Modify: `apps/loom-platform/openclaw_new_launcher/python/core/wire_config.py`
- Modify: `apps/loom-platform/openclaw_new_launcher/python/api/routes_wire.py`
- Test: `apps/loom-platform/openclaw_new_launcher/python/tests/test_wire_config.py`
- Create: `apps/loom-platform/openclaw_new_launcher/python/tests/test_model_probe.py`
- Test: `apps/loom-platform/openclaw_new_launcher/python/tests/test_routes_wire.py`

**Interfaces:**
- Consumes: `ModelDescriptor`、Base URL、受保护凭据和目标 Agent。
- Produces: `ProbeResult` 与可回滚配置事务。

- [ ] **Step 1: 定义探测结果**

```python
@dataclass(frozen=True)
class ProbeResult:
    ok: bool
    protocol: str
    latency_ms: int
    error_code: str | None
    retryable: bool
    provider_request_id: str | None
```

- [ ] **Step 2: 增加已知错误映射测试**

至少覆盖 `401`、`403`、`404 model_not_found`、`429`、`500`、`502`、`503`、`504`、连接超时、DNS 失败、TLS 失败和工具调用不支持。

- [ ] **Step 3: 实现最小真实探测**

对话模型使用最小非流式请求；工具模型额外验证一次工具协议；探测不能触发手机、发布、媒体生成或其他外部副作用。

- [ ] **Step 4: 事务化配置写入**

执行顺序固定为：目录校验 → 真实探测 → 备份 → staging 写入 → 解析回读 → 目标 Agent 检测 → 提交。任何步骤失败都恢复原文件。

- [ ] **Step 5: 保护历史配置**

LOOM 只更新自己的 managed block 或 profile；用户自定义模型、第三方中转站和历史会话引用不得被删除。

- [ ] **Step 6: 运行定向测试**

Run:

```powershell
python -m pytest python/tests/test_model_probe.py python/tests/test_wire_config.py python/tests/test_routes_wire.py -q
```

Expected: PASS；上游 `503/504` 返回 `provider_upstream_unavailable`，本地格式错误返回 `agent_config_invalid`。

- [ ] **Step 7: Commit**

```powershell
git add python/core/model_probe.py python/core/wire_config.py python/api/routes_wire.py python/tests/test_model_probe.py python/tests/test_wire_config.py python/tests/test_routes_wire.py
git commit -m "fix: validate and commit agent model wiring safely"
```

---

## Task 5: 首次使用向导与中文首轮成功

**Files:**
- Modify: `apps/loom-platform/openclaw_new_launcher/src/components/agents/AgentInstallerPage.tsx`
- Modify: `apps/loom-platform/openclaw_new_launcher/src/components/models/ModelsPage.tsx`
- Modify: `apps/loom-platform/openclaw_new_launcher/python/core/official_codex.py`
- Modify: `apps/loom-platform/openclaw_new_launcher/python/core/wire_config.py`
- Test: `apps/loom-platform/openclaw_new_launcher/python/tests/test_agent_installer_page_contract.py`
- Test: `apps/loom-platform/openclaw_new_launcher/python/tests/test_models_page_contract.py`
- Test: `apps/loom-platform/openclaw_new_launcher/python/tests/test_wire_config.py`

**Interfaces:**
- Consumes: 安装状态、账号状态、模型目录和探测结果。
- Produces: 四步首次使用状态与首轮验证回执。

- [ ] **Step 1: 固定四步流程**

首次使用只显示：登录模型账号 → 选择 Agent → 选择可用模型 → 发送测试消息。

- [ ] **Step 2: 禁止越级成功**

只有目标 Agent 已启动、模型探测成功且真实测试消息返回后，才能显示“配置完成”。

- [ ] **Step 3: 默认中文**

LOOM 托管的 Codex 和其他 Agent 配置写入简体中文默认指导；已有用户语言设置不覆盖。

- [ ] **Step 4: 支持中断恢复**

关闭或重启 LOOM 后从最后一个已验证步骤继续，不重复下载安装，不重复写入相同配置。

- [ ] **Step 5: 运行合同测试**

Run:

```powershell
python -m pytest python/tests/test_agent_installer_page_contract.py python/tests/test_models_page_contract.py python/tests/test_wire_config.py -q
```

Expected: PASS；页面不存在“未探测即写入”和“未启动即完成”路径。

- [ ] **Step 6: Commit**

```powershell
git add src/components/agents/AgentInstallerPage.tsx src/components/models/ModelsPage.tsx python/core/official_codex.py python/core/wire_config.py python/tests/test_agent_installer_page_contract.py python/tests/test_models_page_contract.py python/tests/test_wire_config.py
git commit -m "feat: guide first successful Chinese agent session"
```

---

## Task 6: 上游健康快照、熔断和备用模型

**Files:**
- Create: `apps/loom-platform/openclaw_new_launcher/python/core/model_health.py`
- Modify: `apps/loom-platform/openclaw_new_launcher/python/core/loom_model_client.py`
- Modify: `apps/loom-platform/openclaw_new_launcher/python/core/native_agent_runtime.py`
- Modify: `apps/loom-platform/openclaw_new_launcher/python/api/routes_wire.py`
- Modify: `apps/loom-platform/openclaw_new_launcher/src/components/models/ModelsPage.tsx`
- Create: `apps/loom-platform/openclaw_new_launcher/python/tests/test_model_health.py`
- Test: `apps/loom-platform/openclaw_new_launcher/python/tests/test_loom_model_client.py`
- Test: `apps/loom-platform/openclaw_new_launcher/python/tests/test_native_agent_runtime.py`

**Interfaces:**
- Consumes: `ProbeResult` 和实际请求结果。
- Produces: 有有效期的健康快照、熔断状态和同能力备用模型决策。

- [ ] **Step 1: 定义健康状态**

状态限定为 `healthy`、`degraded`、`rate_limited`、`upstream_down`、`auth_failed`、`incompatible`、`unknown`。

- [ ] **Step 2: 增加缓存和并发测试**

同一 provider/model 在快照有效期内只发起一次探测；并发页面、Agent 和创作请求共享同一结果。

- [ ] **Step 3: 实现熔断**

连续三次可重试上游失败后短时熔断；认证失败不自动重试；成功探测后恢复。

- [ ] **Step 4: 实现受控备用模型**

只在用户配置了备用模型、能力兼容且当前动作无外部副作用时自动切换；切换记录必须在回复和审计日志中可见。

- [ ] **Step 5: 停止 Agent 探测刷屏**

原生 Agent 查询状态时复用健康快照；多个只读检查折叠为一个执行过程，不在对话流中生成重复工具卡片。

- [ ] **Step 6: 运行定向测试**

Run:

```powershell
python -m pytest python/tests/test_model_health.py python/tests/test_loom_model_client.py python/tests/test_native_agent_runtime.py -q
```

Expected: PASS；上游故障不会被显示为本地 Agent 配置损坏。

- [ ] **Step 7: Commit**

```powershell
git add python/core/model_health.py python/core/loom_model_client.py python/core/native_agent_runtime.py python/api/routes_wire.py src/components/models/ModelsPage.tsx python/tests/test_model_health.py python/tests/test_loom_model_client.py python/tests/test_native_agent_runtime.py
git commit -m "feat: add shared model health and controlled failover"
```

---

## Task 7: 中转站账号与 LOOM 权益分离

**Files:**
- Create: `apps/loom-platform/openclaw_new_launcher/python/core/entitlements.py`
- Modify: `apps/loom-platform/openclaw_new_launcher/python/core/member_manager.py`
- Modify: `apps/loom-platform/openclaw_new_launcher/python/core/feature_access.py`
- Modify: `apps/loom-platform/openclaw_new_launcher/python/api/routes_member.py`
- Modify: `apps/loom-platform/openclaw_new_launcher/python/api/routes_license.py`
- Modify: `apps/loom-platform/license_server/luming_license/domains/accounts.py`
- Create: `apps/loom-platform/openclaw_new_launcher/python/tests/test_entitlements.py`
- Test: `apps/loom-platform/openclaw_new_launcher/python/tests/test_routes_account.py`
- Test: `apps/loom-platform/openclaw_new_launcher/python/tests/test_account_ui_contract.py`

**Interfaces:**
- Consumes: 中转站账号会话、服务端套餐和设备绑定。
- Produces: `AccountIdentity`、`ModelBalance`、`LoomEntitlements` 和 `DeviceSeats` 四类独立状态。

- [ ] **Step 1: 固定权益模型**

```python
@dataclass(frozen=True)
class LoomEntitlements:
    plan_id: str
    features: frozenset[str]
    device_seats: int
    expires_at: str | None
    offline_grace_until: str | None
```

- [ ] **Step 2: 增加迁移测试**

旧授权码继续可兑换，兑换后权益绑定账号；API Key 不能作为授权凭据；已有设备绑定不因升级丢失。

- [ ] **Step 3: 实现账号同步**

登录后分别同步模型余额、模型权限、LOOM 权益和设备席位；任一子系统故障不伪造其他子系统失败。

- [ ] **Step 4: 保留 BYOK**

没有托管模型余额的用户仍可使用自定义中转站或自己的 API Key；LOOM 权益按产品套餐独立判断。

- [ ] **Step 5: 实现离线宽限**

已验证设备在服务短时不可达时继续使用 3 至 7 天；高风险在线动作仍遵循现有审批和审计规则。

- [ ] **Step 6: 运行账号测试**

Run:

```powershell
python -m pytest python/tests/test_entitlements.py python/tests/test_routes_account.py python/tests/test_account_ui_contract.py -q
```

Expected: PASS；账号、余额、权益和设备席位错误不会相互覆盖。

- [ ] **Step 7: Commit**

```powershell
git add python/core/entitlements.py python/core/member_manager.py python/core/feature_access.py python/api/routes_member.py python/api/routes_license.py ../license_server/luming_license/domains/accounts.py python/tests/test_entitlements.py python/tests/test_routes_account.py python/tests/test_account_ui_contract.py
git commit -m "feat: separate relay account balance and loom entitlements"
```

---

## Task 8: 诊断、客服证据和隐私保护

**Files:**
- Modify: `apps/loom-platform/openclaw_new_launcher/python/api/routes_diagnostics.py`
- Modify: `apps/loom-platform/openclaw_new_launcher/src/components/diagnostics/DiagnosticsPage.tsx`
- Modify: `docs/runbooks/agent-reliability-release-gates.md`
- Test: `apps/loom-platform/openclaw_new_launcher/python/tests/test_routes_diagnostics.py`

**Interfaces:**
- Consumes: 安装事务、模型探测、账号同步、健康快照和更新结果。
- Produces: 不含密钥的结构化诊断包和用户可读摘要。

- [ ] **Step 1: 定义诊断摘要**

摘要必须包含 LOOM 版本、Windows 架构、目标 Agent、安装阶段、模型 ID、故障域、错误码、上游请求 ID、最近成功时间和建议动作。

- [ ] **Step 2: 增加脱敏测试**

诊断包不得包含 API Key、Bearer Token、手机令牌、完整邮箱、本地授权密钥或未脱敏请求正文。

- [ ] **Step 3: 将日志分成两层**

普通用户只看中文结论和修复按钮；高级详情提供时间线、错误码和脱敏原文，避免 traceback 在主界面刷屏。

- [ ] **Step 4: 运行诊断测试**

Run:

```powershell
python -m pytest python/tests/test_routes_diagnostics.py -q
```

Expected: PASS；相同故障重复出现时摘要合并计数，不重复铺满日志页。

- [ ] **Step 5: Commit**

```powershell
git add python/api/routes_diagnostics.py src/components/diagnostics/DiagnosticsPage.tsx python/tests/test_routes_diagnostics.py docs/runbooks/agent-reliability-release-gates.md
git commit -m "feat: add actionable redacted reliability diagnostics"
```

---

## Task 9: 手机矩阵进入稳定维护门禁

**Files:**
- Modify: `docs/runbooks/agent-reliability-release-gates.md`
- Modify: `apps/loom-platform/openclaw_new_launcher/python/core/phone_matrix.py`
- Modify: `apps/loom-platform/openclaw_new_launcher/python/api/routes_matrix.py`
- Test: `apps/loom-platform/openclaw_new_launcher/python/tests/test_routes_matrix.py`
- Test: `apps/loom-platform/openclaw_new_launcher/python/tests/test_matrix_control_plane.py`

**Interfaces:**
- Consumes: 现有手机快速通道、ADB 兜底、截图缓存和任务状态。
- Produces: 不阻塞 `2.4.x` 主线的 P0/P1 修复规则，以及恢复新功能开发的量化门槛。

- [ ] **Step 1: 限制允许变更**

`2.4.x` 只接受连接错误、任务假成功、错误设备目标、急停失效、截图阻塞、密钥泄露和升级回归。

- [ ] **Step 2: 保持单一执行通道**

手机连接页、Matrix、原生 Agent、CLI 和 MCP 必须继续复用现有 Bridge/phone daemon 能力，禁止新增旁路端口。

- [ ] **Step 3: 增加回归门禁**

Run:

```powershell
python -m pytest python/tests/test_routes_matrix.py python/tests/test_matrix_control_plane.py -q
```

Expected: PASS；矩阵维护修改不能改变模型安装和账号主链路。

- [ ] **Step 4: 固定恢复条件**

恢复矩阵功能开发前必须完成 10 台实体手机、2 小时、任务/截图/急停/恢复综合 soak，并保存 P50、P95、失败率和误超时率。

- [ ] **Step 5: Commit**

```powershell
git add python/core/phone_matrix.py python/api/routes_matrix.py python/tests/test_routes_matrix.py python/tests/test_matrix_control_plane.py docs/runbooks/agent-reliability-release-gates.md
git commit -m "test: freeze phone matrix behind reliability gates"
```

---

## Task 10: 全量验证、灰度与商业指标

**Files:**
- Modify: `docs/runbooks/agent-reliability-release-gates.md`
- Create: `docs/reviews/2.4.0-agent-model-release-readiness.md`
- Modify: `apps/loom-platform/docs/LOOM_RELEASE_TEST_AND_DEMO_CHECKLIST.md`

**Interfaces:**
- Consumes: Tasks 1-9 的自动化与真实环境证据。
- Produces: `2.4.0` 发布决定和灰度监控指标。

- [ ] **Step 1: 运行工作区门禁**

```powershell
.\scripts\verify.ps1 -Area workspace
.\scripts\verify.ps1 -Area platform
.\scripts\verify.ps1 -Area phone
```

Expected: 全部通过；已知非阻断警告写入发布准备文档。

- [ ] **Step 2: 运行三个 Agent 的真实安装矩阵**

在 Windows 10/11 干净环境和覆盖升级环境分别验证 Codex、Claude Code、OpenCode，不用同一台开发机结果替代。

- [ ] **Step 3: 运行三类模型路径**

分别验证 LOOM 托管中转站、自定义中转站、用户自带 Key；每类都验证成功、无权限、模型下线、上游 `503/504` 和超时。

- [ ] **Step 4: 运行首轮对话验收**

每个 Agent 必须完成中文首轮对话；支持工具的模型额外完成一次只读工具调用。

- [ ] **Step 5: 运行安装包冒烟**

构建 NSIS 后执行全新安装、覆盖升级、保留历史会话、失败回滚和卸载残留检查。

- [ ] **Step 6: 小流量灰度**

先向内部和少量真实用户发布，观察安装成功率、配置成功率、首轮对话成功率、上游错误占比和客服工单数量，再扩大范围。

- [ ] **Step 7: 发布判断**

只有本计划第 2 节全部达到门槛才发布 `2.4.0`；否则继续修复主链路，不以新增功能调整版本叙事。

- [ ] **Step 8: Commit**

```powershell
git add docs/runbooks/agent-reliability-release-gates.md docs/reviews/2.4.0-agent-model-release-readiness.md apps/loom-platform/docs/LOOM_RELEASE_TEST_AND_DEMO_CHECKLIST.md
git commit -m "docs: gate loom 2.4.0 on first-use reliability"
```

---

## 5. 执行顺序与并行边界

推荐顺序：

1. Task 1 建立事实基线。
2. Task 2 安装事务与 Task 3 模型目录可并行。
3. Task 4 依赖 Task 3。
4. Task 5 依赖 Tasks 2-4。
5. Task 6 依赖 Task 4。
6. Task 7 可以与 Task 6 并行，但不得改变 Task 4 的配置事务。
7. Task 8 汇总 Tasks 2、4、6、7 的结构化错误。
8. Task 9 独立维护，不占用主线架构修改。
9. Task 10 最后执行。

每个任务使用独立分支和 worktree；一个任务只允许一个主写入者。跨任务共享接口先在本计划中更新后再编码，避免多个会话各自发明不同字段。

---

## 6. 完成定义

本计划完成不是指“页面和接口已经存在”，而是同时满足：

- 新用户能在 5 分钟内安装一个首批 Agent、选择真实可用模型并完成首轮中文对话。
- 配置失败不会破坏历史会话和已有配置。
- 上游宕机时明确说明是上游问题，并允许使用备用模型或 BYOK。
- 客服不需要阅读 traceback 就能判断故障属于安装、环境、账号、权限、网络还是供应商。
- 手机矩阵保持现有可用能力，没有因为主线重构产生回归。
- 自动更新和覆盖安装能够把这些修复可靠交付给旧版本用户。

## 7. 商业观察指标

`2.4.x` 发布后按周观察：

- LOOM 安装完成率。
- Agent 安装完成率。
- 模型配置完成率。
- 首轮对话完成率。
- 从注册到首次有效调用的耗时。
- 托管中转站使用率与 BYOK 使用率。
- 付费转化率、续费率和模型余额消耗。
- 每 100 个活跃用户产生的安装/模型客服工单数。
- 上游不可用占失败总量的比例。

若首轮对话成功率未达标，下一迭代继续投入安装与模型链路；不得用新增手机或创作功能掩盖基础使用问题。
