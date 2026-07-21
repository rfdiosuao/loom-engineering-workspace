# 麓鸣获客工作台方向锁

日期：2026-07-07  
分支：`codex/customer-acquisition-v1`  
适用范围：`D:\Axiangmu\AUSTART\openclaw_new_launcher`

## 一句话方向

麓鸣 AI 矩阵获客工作台要做成一个“AI 私域获客助手 / 手机端智能销售助理 / 本地生活商家线索助手”，而不是脚本、群控、外挂、自动骚扰工具。

真正的产品闭环是：

```text
工作台创建获客任务
-> 本地 Bridge / CLI 调度麓鸣手机 Agent
-> 手机 Agent 在真实 App 里读公开线索、填写草稿、停在确认页
-> 手机 Agent 返回结构化 JSON
-> 后端沉淀线索池、客户池、草稿、SOP 命中、任务日志
-> 飞书 CLI 写入飞书多维表格
-> 用户在工作台人工确认、跟进、复盘、放大到多设备
```

## 不要走偏

不要把它做成只会展示营销文案的 UI。每一个看起来很厉害的卖点，都必须落到真实状态、真实接口、真实日志、真实飞书写入。

不要把它做成平台 API 群发器。TikTok、小红书、RedNote、Lemon8、抖音、微信等平台动作，优先通过用户已登录、已授权的真实手机 App 路径执行；所有真实对外动作默认停在“草稿/人工确认”。

不要重做底层 CLI。继续复用现有 LOOM 手机控制、Matrix、多设备调度、发布、桌面回复、日志、飞书 CLI、模板沉淀能力。

不要破坏安装器和发布流程。除非用户明确要求，不碰 installer、release、证书、部署、Gitee 上传和历史 release 产物。

## 允许默认实现的能力

- 从工作台创建获客任务：平台、行业、关键词、地域、目标客户画像、设备、SOP、飞书表。
- 读取真实手机 App 中用户可见的公开内容：评论、搜索结果、主页摘要、会话摘要、发布页面状态。
- 把手机 Agent 返回内容整理成结构化线索：来源平台、昵称、线索内容、意向评分、来源链接、任务 ID、设备 ID。
- 生成评论回复、私信、微信跟进、二次触达草稿。
- 把草稿填入手机 App 或桌面输入框，但默认停在人工确认页。
- 人工确认后记录“已手动发送”“客户回复”“下次跟进”“备注”。
- 写入飞书多维表格；飞书不可用时进入本地 pending sync 队列。
- 用户沉淀的 SOP、话术、模板默认脱敏后上传到服务器，后台可查看模板列表和状态。
- 多台手机作为放大能力：设备选择、任务队列、频控、失败隔离、日志聚合。

## 禁止默认实现的能力

- 无确认批量私信。
- 无确认批量评论。
- 无确认批量加好友或加微信。
- 自动骚扰式群发。
- 绕过验证码、平台风控、封禁策略。
- 保存真实账号密码、token、cookie、Gitee 令牌、用户私密客户数据。
- 用真实生产客户数据做测试或演示。
- 未经用户确认修改 DNS、服务器 root 权限、生产密钥、支付配置。

所有真实对外发送、评论、私信、加微、发布动作都必须默认走：

```text
生成草稿 -> 人工确认 -> 白名单/频控 -> 日志留痕 -> 状态回写
```

## 当前应该优先补的真实闭环

P0：手机 Agent 结果入库。

```text
UI 创建手机 Agent 获客任务
-> POST /api/matrix/acquisition/agent/run
-> loom_cli.py acquisition agent-run
-> 手机 Agent dry-run 或真机执行
-> 返回 loom.acquisition.agent_result.v1
-> 后端 ingest
-> 线索池 / 客户池 / 草稿队列 / 日志 / 飞书同步状态更新
```

验收标准：

- dry-run 能返回结构化结果并进入线索池。
- 真机路径必须停在人工确认页。
- 结果包含 `taskId`、`deviceId`、`platform`、`action`、`status`、`leads`、`drafts`、`logs`。
- 日志能看到 `agent.result_ingested` 或同等含义事件。

P0：飞书多维表格成为真实客户池。

验收标准：

- 能创建新飞书表或绑定已有表。
- 已登录飞书后能真实写入一条线索。
- 字段至少包含平台、昵称、线索内容、意向评分、跟进草稿、状态、下次跟进时间、任务 ID、设备 ID。
- 写入失败进入 pending sync，并能重试。
- 不把 token、cookie、账号密码写进状态文件或日志。

P1：把营销感按钮变成真实动作。

- “自动找线索”对应手机 Agent 任务或真实导入入口。
- “AI 写话术”对应 SOP/知识库/草稿生成接口。
- “沉淀客户池”对应本地状态和飞书多维表格。
- “多台手机矩阵”对应设备选择、任务队列、频控、失败隔离、日志聚合。
- “模板自动上传”对应脱敏上传、失败重试、服务器后台列表。

P2：海外平台和网络链路。

- 手机上的平台账号由用户登录。
- 手机代理、海外网络、账号风控由用户选择和确认。
- 电脑到手机控制链路优先考虑 USB ADB forward、同网段直连、代理分流、IPv6 可达性验证。
- 如果涉及验证码、风控、账号异常、支付或真实群发合规决策，必须暂停确认。

## 给后续 Codex 的判断标准

- 只新增漂亮卡片，不算真实落地。
- 只做本地模拟，但不能入库、不能写飞书、不能产生日志，不算闭环。
- 能 dry-run 入库、能写飞书、能在 UI 看到状态，算第一阶段可用。
- 能通过手机 Agent 在真实 App 填草稿并停在确认页，算真机闭环。
- 能多设备调度、频控、失败隔离、统一写飞书，算矩阵放大。

## 推荐执行版 `/goal`

```text
/goal 在 D:\Axiangmu\AUSTART 的现有分支 codex/customer-acquisition-v1 上，继续把“麓鸣AI矩阵获客工作台”从营销型 UI 推进成真实可运行的手机 Agent + 飞书多维表格获客闭环。不要重做底层 CLI，不要改主分支，不要破坏安装器、打包、release、证书、部署和 Gitee 上传逻辑。目标链路是：工作台创建获客任务 -> 本地 Bridge/CLI 发起 acquisition agent-run -> 手机 Agent dry-run 或真机执行 -> 返回 loom.acquisition.agent_result.v1 结构化结果 -> 后端 ingest 到线索池、客户池、草稿队列、任务日志 -> 飞书 CLI 写入飞书多维表格 -> UI 显示线索、草稿、人工确认、飞书同步和日志状态。验证：开始先运行 git status --short --branch 并确认仍在 codex/customer-acquisition-v1；实现前先补或更新契约测试，至少覆盖 /api/matrix/acquisition/agent/run、agent_result 入库、loom_cli.py acquisition agent-run、飞书写入 pending/synced 状态；实现后至少运行 npm run build、py -3 -m unittest discover -s openclaw_new_launcher\python\tests -p "test_*.py"；若改 UI，启动本地前端或 Tauri 做关键页面可视化检查，确认“手机 Agent 获客任务”“Agent dry-run”“结构化结果入库”“线索池”“草稿队列”“飞书同步”不空白、不重叠；若接真机，必须先 dry-run 通过，再让真实手机停在人工确认页并保留日志。约束：禁止默认实现无确认批量私信、批量评论、批量加好友、自动骚扰式群发；所有真实外发、评论、私信、加微、发布动作必须默认走生成草稿、人工确认、白名单、频控、日志留痕；不写入真实账号密码、token、Gitee 令牌、cookie 或用户私密数据；不绕过验证码、平台风控或封禁策略；真实平台账号登录、验证码、代理策略、生产客户数据和批量触达合规决策必须暂停确认。边界：主要修改 openclaw_new_launcher/src、openclaw_new_launcher/python、openclaw_new_launcher/scripts、openclaw_new_launcher/python/tests 和必要 docs；优先复用现有 LOOM 手机控制、Matrix、多设备调度、发布、桌面回复、日志、飞书 CLI、模板库上传能力；除非确有必要，不改 installer、release、证书、部署、Gitee 上传、构建产物删除逻辑。迭代策略：先完成一个最小真实闭环：获客任务 -> 手机 Agent dry-run/模拟结果 -> 结构化结果入库 -> 规则/AI 评分 -> 生成跟进草稿 -> 人工确认状态 -> 飞书写入或 pending_sync -> 日志沉淀；每完成一块跑相关测试，失败先读日志定位，不盲目重试；最多 3 轮聚焦修复后报告剩余风险；不要继续堆只展示不落地的 UI 文案。完成条件：工作台有清晰的“手机 Agent 获客任务”入口，至少一个 agent_result 能真实进入线索池、草稿队列、日志流，并能通过飞书 CLI 写入新建或绑定的飞书多维表格；构建和测试通过；最终说明改了哪些文件、怎么验证、演示路径怎么走、还剩哪些真机账号、验证码、代理网络、平台风控、多设备频控和服务器模板后台待补。暂停条件：需要真实平台账号登录、验证码、支付、生产客户数据、外部服务密钥、服务器 root/SSH 私钥操作、DNS 解析变更、平台风控策略选择、批量触达合规决策、破坏性操作或超过当前边界的部署改动时，暂停并向用户确认。
```

## Goal Draft (English-compatible)

```text
/goal In D:\Axiangmu\AUSTART on the existing branch codex/customer-acquisition-v1, continue turning “Luming AI Matrix Customer Acquisition Workbench” from marketing-style UI into a real phone-Agent plus Feishu Bitable customer-acquisition loop. Do not rebuild the underlying CLI, do not change the main branch, and do not break installer, packaging, release artifacts, certificates, deployment, or Gitee upload logic. Target flow: workbench creates an acquisition task -> local Bridge/CLI starts acquisition agent-run -> phone Agent dry-run or real-phone run -> returns loom.acquisition.agent_result.v1 structured result -> backend ingests into lead pool, customer pool, draft queue, and task logs -> Feishu CLI writes rows into Feishu Bitable -> UI shows leads, drafts, human confirmation, Feishu sync, and logs. Verification: first run git status --short --branch and confirm the branch is still codex/customer-acquisition-v1; add or update contract tests before implementation, covering /api/matrix/acquisition/agent/run, agent_result ingestion, loom_cli.py acquisition agent-run, and Feishu pending/synced write states; after implementation run at least npm run build and py -3 -m unittest discover -s openclaw_new_launcher\python\tests -p "test_*.py"; if UI changes, start local frontend or Tauri and visually check that phone Agent acquisition task, Agent dry-run, structured result ingestion, lead pool, draft queue, and Feishu sync are not blank or overlapping; if real-phone integration is touched, dry-run must pass first and the real phone must stop at human confirmation with logs retained. Constraints: do not implement unconfirmed bulk DMs, bulk comments, bulk friend adds, or spam-like mass outreach by default; all real external send/comment/DM/add-WeChat/publish actions must default to draft generation, human confirmation, whitelist, frequency caps, and audit logs; do not write real passwords, tokens, Gitee tokens, cookies, or private user data; do not bypass captchas, platform risk controls, or ban policies; real platform login, captcha, proxy strategy, production customer data, and bulk-outreach compliance decisions must pause for user confirmation. Boundaries: primarily edit openclaw_new_launcher/src, openclaw_new_launcher/python, openclaw_new_launcher/scripts, openclaw_new_launcher/python/tests, and necessary docs; reuse existing LOOM phone control, Matrix, multi-device scheduling, publishing, desktop reply, logs, Feishu CLI, and template-upload capabilities; unless truly necessary, avoid installer, release, certificates, deployment, Gitee upload, and build artifact deletion logic. Iteration policy: first complete one minimal real loop: acquisition task -> phone Agent dry-run/simulated result -> structured result ingestion -> rule/AI qualification -> follow-up draft -> human confirmation status -> Feishu write or pending_sync -> log persistence; run relevant tests after each block, inspect logs before retrying failures, make at most 3 focused repair rounds before reporting remaining risks, and do not keep adding display-only UI copy. Stop when: the workbench has a clear phone Agent acquisition task entry, at least one agent_result can enter the lead pool, draft queue, and log stream, and can be written through Feishu CLI into a new or bound Feishu Bitable; build and tests pass; the final report lists changed files, verification, demo path, and remaining real-phone account, captcha, proxy network, platform risk-control, multi-device frequency-cap, and server template-admin gaps. Pause if: real platform account login, captcha, payment, production customer data, external service keys, server root/SSH private-key operations, DNS changes, platform risk-control strategy, bulk outreach compliance decisions, destructive operations, or deployment changes outside the current boundary are required.
```
