# 麓鸣获客工作台真实闭环路线

日期：2026-07-07
分支：codex/customer-acquisition-v1

## 一句话方向

获客工作台不是只做 UI 表单，也不是直接调用 TikTok、小红书、RedNote、Lemon8 等平台官方接口；它的真实形态是：

```text
Codex / 麓鸣工作台
-> 本地 CLI / Bridge
-> 局域网或 USB ADB 调度手机 Agent
-> 手机 Agent 操作真实 App 并返回结构化结果
-> 后端沉淀线索、草稿、触达日志
-> 飞书 CLI 写入飞书多维表格
```

## 目标产品形态

把“麓鸣AI矩阵获客工作台”做成一个可运营的 AI 私域获客平台：

- 用户在工作台创建获客任务，选择平台、手机、模板、飞书表。
- Codex/麓鸣通过本地 CLI 调度手机 Agent。
- 手机 Agent 在真实手机 App 内执行读取、发布、回复、草稿填充等动作。
- 所有评论、私信、加微、发布动作默认停在草稿或确认页。
- 手机 Agent 返回结构化 JSON，包含线索、草稿、截图、执行状态、错误和日志。
- 后端把结果沉淀到线索池、客户池、草稿队列和任务日志。
- 飞书集成通过 lark-cli / 飞书 CLI 创建或写入多维表格。

## 关键架构

### 1. UI 工作台

职责：

- 创建获客任务。
- 选择目标平台：TikTok、RedNote、小红书、Lemon8、抖音、微信等。
- 选择目标设备：单台手机或多台手机矩阵。
- 选择内容/话术/行业模板。
- 展示线索池、客户池、草稿队列、飞书同步、任务日志和统计。

UI 不应该承担平台自动化逻辑，只负责配置任务、展示状态和触发后端/CLI。

### 2. CLI / Bridge 编排层

职责：

- 接收 UI 或 Codex 发起的获客任务。
- 生成手机 Agent 可执行的任务 payload。
- 调用已有手机控制能力，例如 Matrix、phone task、publish、desktop reply、logs。
- 回收手机 Agent 执行结果。
- 把结果交给获客后端处理。

目标接口形态：

```text
POST /api/matrix/acquisition/agent/run
loom_cli.py acquisition agent-run ...
```

### 3. 手机 Agent 执行层

职责：

- 通过局域网手机服务或 USB ADB forward 控制真实手机。
- 打开目标 App。
- 读取评论区、搜索结果、主页、私信会话或发布页面。
- 选择素材、填标题、填正文、填标签。
- 默认停在确认页，不自动触发大规模外发。
- 返回结构化结果。

推荐结果格式：

```json
{
  "schema": "loom.acquisition.agent_result.v1",
  "taskId": "acq_task_xxx",
  "deviceId": "phone-1",
  "platform": "tiktok",
  "action": "discover_leads",
  "status": "pending_human_confirm",
  "leadExample": {
    "platform": "tiktok",
    "nickname": "user_name",
    "summary": "用户在评论区询问报价和案例",
    "profileUrl": "",
    "contentUrl": "",
    "rawContent": "原始可公开内容摘要"
  },
  "draftExample": {
    "channel": "dm",
    "body": "建议话术草稿",
    "requiresHumanReview": true,
    "sendEnabled": false
  },
  "screenshotCount": 0,
  "logCount": 0
}
```

### 4. 获客状态与飞书沉淀层

职责：

- 把手机 Agent 返回的 leads/drafts/logs 合并进本地获客状态。
- 对线索去重、评分、生成客户池记录。
- 生成或更新跟进草稿。
- 通过飞书 CLI 写入飞书多维表格。
- 在飞书不可用时进入本地 pending sync 队列，后续可重试。

现有能力已经包含：

- 真实线索导入：CSV / 评论 JSON / 剪贴板。
- 规则评分、客户池、草稿队列。
- 飞书创建表、绑定表、测试写入、重试同步。
- 人工确认、人工发送记录、客户回复、下一次跟进。

下一步要补的是手机 Agent 结果接入，不是继续只做本地表单。

## 安全边界

禁止默认实现：

- 无确认批量私信。
- 无确认批量评论。
- 无确认批量加好友。
- 自动骚扰式群发。
- 绕过验证码、风控、封禁策略。
- 写入真实账号密码、token、Gitee 令牌或用户私密数据。

允许默认实现：

- 读取用户已授权、已登录手机里的可见页面内容。
- 生成草稿。
- 填入草稿并停在确认页。
- 人工确认后记录状态。
- 写入飞书多维表格。
- 失败、验证码、账号异常时暂停并要求人工处理。

## 近期实现顺序

1. 保持当前本地闭环：
   真实线索导入 -> 去重评分 -> 草稿 -> 人工确认 -> 人工发送记录 -> 飞书写入。

2. 新增手机 Agent 任务入口：
   工作台创建任务，后端转成 phone/matrix task payload。

3. 新增 Agent 结果接收接口：
   手机 Agent 返回结构化 JSON，后端复用现有 import_acquisition_leads 和 draft/log 状态。

4. 新增平台模板：
   TikTok 发现线索、TikTok 发布草稿、RedNote/Lemon8 发布草稿、评论读取草稿。

5. 新增飞书同步增强：
   按 leadId/taskId 更新状态，追加触达日志和下一次跟进时间。

6. 最后才做多设备放大：
   单台手机可证明稳定后，再做多台设备队列、频控、错误隔离。

## 可复制 /goal

```text
/goal 在 D:\Axiangmu\AUSTART 的现有分支 codex/customer-acquisition-v1 上，继续把“麓鸣AI矩阵获客工作台”做成真实的 Codex/麓鸣手机 Agent 获客闭环，而不是只做 UI 表单或直接调平台官方 API。目标链路是：UI 创建获客任务 -> 本地 CLI/Bridge 调度手机 Agent -> 手机 Agent 在真实 App 内读取/填草稿/停在确认页 -> 返回结构化 JSON -> 后端沉淀线索、客户、草稿、日志 -> 使用飞书 CLI 写入飞书多维表格。
验证：开始先运行 git status 并确认仍在 codex/customer-acquisition-v1；实现每个后端能力先补契约测试；至少运行 npm run build、python -m unittest discover -s openclaw_new_launcher\python\tests -p "test_*.py"；若改 UI，启动本地前端或 Tauri 做关键页面可视化检查，确认获客任务入口、手机 Agent 任务状态、线索池、草稿队列、飞书同步按钮不空白、不重叠；若接 CLI/手机 Agent，必须用 dry-run 或模拟结果测试接口契约，再用真实手机时停在人工确认页。
约束：禁止无确认批量私信、批量评论、批量加好友、自动骚扰式群发；真实外发、评论、私信、加微、发布动作默认必须走生成草稿/人工确认/白名单/频控/日志留痕；不写入真实账号密码、token、Gitee 令牌或用户私密数据；不破坏现有安装器、打包、release 产物和底层 CLI。
边界：主要修改 openclaw_new_launcher/src、openclaw_new_launcher/python、openclaw_new_launcher/scripts、openclaw_new_launcher/python/tests 和必要文档；优先复用现有 LOOM 手机控制、Matrix、多设备调度、发布、桌面回复、日志、飞书 CLI 能力；除非必要，不改 installer、release、证书、部署、Gitee 上传逻辑。
迭代策略：先接通一个最小可演示路径：获客任务 -> 手机 Agent dry-run/模拟结果 -> 结果入库 -> AI/规则评分 -> 草稿 -> 人工确认 -> 飞书写入；每完成一块跑相关测试，遇到失败先读日志定位，不盲目重试；最多 3 轮聚焦修复后报告剩余风险。
完成条件：工作台里有清晰的“手机 Agent 获客任务”入口，至少一个 Agent 结果能真实进入线索池和飞书多维表格，构建和测试通过，最终说明改了哪些文件、怎么验证、还剩哪些平台账号/验证码/风控接入待补。
暂停条件：需要真实平台账号登录、验证码、支付、生产客户数据、平台风控策略选择、外部服务密钥、批量触达合规决策或破坏性操作时暂停并向用户确认。
```

## Goal Draft (English-compatible)

```text
/goal In D:\Axiangmu\AUSTART on the existing branch codex/customer-acquisition-v1, continue turning “Luming AI Matrix Customer Acquisition Workbench” into a real Codex/Luming phone-Agent acquisition loop, not just UI forms and not direct platform API integration. The target flow is: UI creates an acquisition task -> local CLI/Bridge dispatches a phone Agent -> phone Agent operates the real mobile app, reads/fills drafts/stops at confirmation -> returns structured JSON -> backend persists leads, customers, drafts, and logs -> Feishu CLI writes rows into Feishu Bitable.
Verification: first run git status and confirm the branch is still codex/customer-acquisition-v1; add contract tests before each backend capability; at minimum run npm run build and python -m unittest discover -s openclaw_new_launcher\python\tests -p "test_*.py"; if UI changes, start the local frontend or Tauri and visually check the acquisition task entry, phone Agent task state, lead pool, draft queue, and Feishu sync controls are not blank or overlapping; if CLI/phone Agent integration changes, test the contract with dry-run or simulated results before using a real phone, and real-phone flows must stop at human confirmation.
Constraints: no unconfirmed bulk DMs, bulk comments, bulk friend adds, or spam-like outreach; real external send/comment/DM/add-friend/publish actions must default to draft generation, human confirmation, whitelist, frequency cap, and audit logs; do not write real passwords, tokens, Gitee tokens, or private user data; do not break existing installer, packaging, release artifacts, or the underlying CLI.
Boundaries: primarily edit openclaw_new_launcher/src, openclaw_new_launcher/python, openclaw_new_launcher/scripts, openclaw_new_launcher/python/tests, and necessary docs; reuse existing LOOM phone control, Matrix scheduling, publish, desktop reply, logs, and Feishu CLI capabilities; avoid installer, release, certificates, deployment, and Gitee upload logic unless truly necessary.
Iteration policy: first connect one minimal demonstrable path: acquisition task -> phone Agent dry-run/simulated result -> persisted result -> AI/rule qualification -> draft -> human confirmation -> Feishu write; run relevant tests after each block, inspect logs before retrying failures, and make at most 3 focused repair rounds before reporting remaining risks.
Stop when: the workbench has a clear “phone Agent acquisition task” entry, at least one Agent result can enter the lead pool and Feishu Bitable, build and tests pass, and the final report lists changed files, verification, and remaining platform account/captcha/risk-control gaps.
Pause if: real platform account login, captcha, payment, production customer data, platform risk-control choice, external service keys, bulk outreach compliance decisions, or destructive operations are required.
```
