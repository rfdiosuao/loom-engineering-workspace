# 新会话 Goal：LOOM 前后端分离

更新时间：2026-07-02

把下面整段发给新的 Codex 会话。

```text
/goal 在 D:\Axiangmu\AUSTART 内推进 LOOM / 麓鸣第一阶段前后端分离：主线只改 openclaw_new_launcher，把前端页面从散落业务逻辑、裸 fetch/invoke、模型/账号/手机/安装细节判断中剥离出来，收敛到统一 LoomClient；后端 FastAPI routes、core services、loom_cli.py、loom_mcp.py 作为同一套能力面，支撑 UI、CLI、MCP、Codex、ClaudeCode、OpenCode 共同调用。

先读取：
1. D:\Axiangmu\AUSTART\docs\LOOM_FRONTEND_BACKEND_SEPARATION_CONSTRAINTS.md
2. D:\Axiangmu\AUSTART\docs\LOOM_FRONTEND_BACKEND_SEPARATION_EXECUTION.md
3. D:\Axiangmu\AUSTART\docs\LOOM_PHONE_DUAL_CHANNEL_ADB_ARCHITECTURE.md
4. D:\Axiangmu\AUSTART\docs\APKCLAW_SPEED_ARCHITECTURE_AND_GOAL.md
5. D:\Axiangmu\AUSTART\openclaw_new_launcher\package.json
6. D:\Axiangmu\AUSTART\openclaw_new_launcher\python\tests

目标结果：
1. 新增或整理统一前端调用层，例如 src/services/loomClient.ts、loomContracts.ts、loomErrors.ts、loomMock.ts；已迁移页面只能通过该调用层访问后端。
2. 优先迁移模型账号页、Agent 安装配置页、手机矩阵工作台、创作媒体页中最影响交付的 1-2 个页面；不要一次性大重写。
3. 后端 API 保持稳定，账号、wire、phone、matrix、MCP 字段不得破坏兼容；必要时只做向后兼容新增。
4. CLI/MCP 与 UI 共享同一后端能力，不能复制一套业务逻辑。
5. 登录态保持、验证码登录、订阅页 URL、模型权限兜底、组件安装状态、手机矩阵任务状态尽量由后端统一判断，前端只展示结果和交互。
6. 白标主题、品牌文案、订阅入口、模型默认值不得硬编码在页面组件深处。

验证：
1. 先做基线搜索并记录结果：
   - rg -n "fetch\\(|invoke\\(|localStorage|sessionStorage|qwen3\\.7-plus|gpt-image|phone|matrix|account|subscription" D:\Axiangmu\AUSTART\openclaw_new_launcher\src
2. 每迁移一个页面后，补或更新对应 contract 测试。
3. 至少运行：
   - cd D:\Axiangmu\AUSTART
   - git diff --check
   - cd D:\Axiangmu\AUSTART\openclaw_new_launcher
   - python -m py_compile python\bridge.py python\loom_cli.py python\loom_mcp.py
   - python -m pytest python\tests\test_routes_account.py python\tests\test_routes_wire.py python\tests\test_routes_components.py python\tests\test_routes_phone.py python\tests\test_routes_matrix.py python\tests\test_loom_cli_contract.py python\tests\test_loom_mcp_contract.py
   - npm run build
4. 如果只改前端页面，也至少运行 npm run build 和相关 Python contract 测试；如果测试缺少依赖，写清楚缺什么。
5. 如果真机不可用，不要伪造真机结果；用 mock/contract 测试证明接口、错误提示、超时、重试、确认边界没有破坏。

约束：
1. 主线只认 D:\Axiangmu\AUSTART\openclaw_new_launcher，不要扩大 openclaw_ui_integration 旧 UI 改动。
2. 不要重写整个架构，不要一次性重命名所有 routes，不要改协议兼容字段名。
3. 不要破坏 Lumi / APKClaw 签名链路、phone HTTP 快速通道、ADB 兜底、Codex/ClaudeCode/OpenCode/Hermes 已有安装路径。
4. 不要把 token、私钥、真实账号、手机号、验证码、cookie、客户数据、运行日志、缓存写入源码或发布包。
5. 不要把手机矩阵做成无确认批量骚扰工具；外发消息、评论、私信、报价、承诺、批量触达必须有人确认或有明确模板授权。
6. UI 文案保持克制，页面只讲状态、动作、下一步，不塞长段说明。

边界：
1. 允许修改：
   - D:\Axiangmu\AUSTART\openclaw_new_launcher\src
   - D:\Axiangmu\AUSTART\openclaw_new_launcher\python
   - D:\Axiangmu\AUSTART\openclaw_new_launcher\scripts
   - D:\Axiangmu\AUSTART\openclaw_new_launcher\docs
   - D:\Axiangmu\AUSTART\docs
   - 与本次分离直接相关的 tests / mocks / fixtures
2. 禁止修改：
   - 用户私钥、真实账号凭证、生产服务器配置
   - release 包里的用户本地配置
   - 与本次分离无关的旧 UI 大范围重构
   - apkclaw 源码，除非只读参考或用户另开任务明确要求
3. 如必须改服务器、中转站、生产账号或真实设备批量任务，先写变更方案和回滚方案，暂停等待确认。

迭代策略：
1. 先冻结范围，第一阶段只做“统一 client + 1-2 个高价值页面迁移 + contract tests”。
2. 每次只迁移一个页面或一个能力域，修完立刻重跑对应测试。
3. 同一问题连续失败 2 次后必须换证据来源：看日志、看接口响应、写最小复现、查调用链，不允许盲改。
4. 页面迁移优先级：模型账号页 -> Agent 安装配置页 -> 手机矩阵工作台 -> 创作媒体页。
5. 每个模块最多 3 轮自修复；仍失败则写清楚阻塞、影响范围和下一步。

完成条件：
1. 至少 1-2 个核心页面已经通过 LoomClient 调后端，不再散落裸 fetch/invoke 和业务默认值判断。
2. 后端 routes/core/CLI/MCP 的字段兼容未破坏，相关 contract tests 通过。
3. 登录态、订阅、模型配置、组件安装或手机矩阵中至少一个关键链路完成前后端职责拆分。
4. git diff --check、Python py_compile、相关 pytest、npm run build 通过，或明确记录缺失依赖/外部条件。
5. 输出最终报告：迁移了哪些页面、剩余哪些直接调用、哪些 API 需要下一阶段整理、CLI/MCP 是否同源、还有哪些发布风险。

暂停条件：
1. 需要真实账号验证码、手机解锁、生产服务器权限、支付、真实批量触达用户时暂停。
2. 发现真实密钥、隐私、账号、token 进入源码或发布包时暂停并先清理。
3. 需要改变商业策略、允许某类自动外发、改生产中转站、改 APKClaw 签名链路时暂停。
4. 前端/后端契约需要破坏兼容才能继续时暂停，先给兼容迁移方案。
```

## Goal Draft (English-compatible)

```text
/goal In D:\Axiangmu\AUSTART, complete the first phase of LOOM frontend/backend separation inside openclaw_new_launcher: move frontend pages away from scattered business logic, raw fetch/invoke calls, and model/account/phone/installer decisions, and route migrated UI through a unified LoomClient. Keep FastAPI routes, Python core services, loom_cli.py, and loom_mcp.py as the shared capability surface for UI, CLI, MCP, Codex, ClaudeCode, and OpenCode.

Verification: inspect the existing docs and tests first; baseline-search frontend direct calls; migrate only 1-2 high-value pages; update contract tests; run git diff --check, Python py_compile for bridge/CLI/MCP, relevant pytest route/CLI/MCP tests, and npm run build. If dependencies or real devices are unavailable, report the missing condition and use mock/contract tests without faking real-device success.

Constraints: work only on openclaw_new_launcher and directly related docs/tests/scripts; do not rewrite the whole architecture; do not break account/wire/phone/matrix/MCP compatibility fields; do not touch secrets, production server config, real account credentials, release user configs, or unrelated old UI rewrites. High-risk phone outreach actions must require explicit confirmation or be rejected.

Boundaries: allowed writes are openclaw_new_launcher/src, python, scripts, docs, repository docs, and directly related tests/mocks/fixtures. Do not modify apkclaw source unless the user explicitly opens a separate task.

Iteration policy: freeze scope to a unified client plus 1-2 page migrations; migrate one page or capability domain at a time; rerun relevant tests after each meaningful change; after two failed attempts, inspect logs/responses/reproductions/call chains before changing code again; stop after three focused self-repair rounds per module and report remaining blockers.

Stop when: migrated pages call backend through LoomClient, related contract tests pass, build/check commands pass or missing prerequisites are documented, and the final report lists migrated pages, remaining direct calls, next API cleanup, CLI/MCP alignment, and release risks.

Pause if: real credentials, phone unlock, production server access, payment, real bulk outreach, privacy leaks, signing-chain changes, production relay changes, or compatibility-breaking API changes are required.
```
