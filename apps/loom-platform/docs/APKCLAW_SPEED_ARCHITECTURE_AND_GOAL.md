# APKClaw Speed Architecture And Goal

> 新会话交接说明：先读完本文档，再开始改 APKClaw 或 LOOM 手机桥接层。目标不是把 UI 做得更花，而是让手机 Agent 的执行体感明显变快、可观测、可验证、可回滚。

## 1. 目标

把 APKClaw 从“每一步都靠 Agent 思考”的慢执行器，改成“快路径优先、Agent 兜底、模板沉淀”的手机自动化内核。

最终效果：

- 读取当前手机屏幕不需要调用 LLM。
- 常见固定流程优先走模板或高阶动作。
- Agent 只处理不确定、页面复杂、模板失败的情况。
- LOOM / Codex / Claude Code / MCP / CLI 调用手机时能看到持续进度，而不是长时间像卡死。
- 每次任务都有耗时指标，能知道慢在读屏、模型、工具调用、等待还是手机状态。

## 2. 当前源码位置

APKClaw 源码：

```text
D:\Axiangmu\AUSTART\apkclaw\Hermes-Agent-phone-codex-template-parameter-extraction
```

LOOM 手机桥接层：

```text
D:\Axiangmu\AUSTART\openclaw_new_launcher
```

优先阅读文件：

```text
APKClaw:
app/src/main/java/com/apk/claw/android/server/AgentApiController.kt
app/src/main/java/com/apk/claw/android/agent/DefaultAgentService.kt
app/src/main/java/com/apk/claw/android/service/ClawAccessibilityService.java
app/src/main/java/com/apk/claw/android/tool/impl/GetScreenInfoTool.java
app/src/main/java/com/apk/claw/android/agent/llm/OpenAiLlmClient.kt
app/src/main/java/com/apk/claw/android/workflow/WorkflowTemplateManager.kt

LOOM:
openclaw_new_launcher/python/api/routes_phone.py
openclaw_new_launcher/python/api/routes_matrix.py
openclaw_new_launcher/python/core/phone_matrix.py
openclaw_new_launcher/scripts/openclaw-phone-agent.mjs
openclaw_new_launcher/scripts/openclaw-phone-vision.mjs
openclaw_new_launcher/src/components/phone/PhoneDemoPage.tsx
```

## 3. 当前链路

```text
LOOM / CLI / MCP
  -> APKClaw HTTP API
  -> AgentApiController
  -> DefaultAgentService
  -> LLM
  -> ToolRegistry
  -> ClawAccessibilityService
  -> 手机动作 / 观察
```

当前体感慢的主要来源：

- 每轮都可能调用 LLM。
- `get_screen_info` 会抓取并序列化 UI 树。
- 任务轮次默认偏高。
- 固定流程没有足够强的快路径。
- LOOM 侧轮询任务状态，但用户看到的阶段反馈还不够细。
- 手机端只有全局单任务锁，适合安全，但对矩阵调度需要更清晰的 busy / queued / running / failed 状态。

## 4. 目标架构

```text
LOOM / CLI / MCP
  -> Phone Task Control Plane
  -> APKClaw Fast Path
      -> observe_fast
      -> action_fast
      -> template_run
  -> Agent Loop Fallback
      -> compressed screen context
      -> limited tool policy
      -> limited rounds
      -> progress events
```

### 4.1 observe_fast

只读快路径，不调用 LLM。

返回：

- 当前包名
- 当前 Activity 或页面特征
- 屏幕摘要
- 关键可点击节点
- 关键输入框
- 关键文本
- `screenHash`
- `capturedAt`
- `durationMs`

目标：P50 小于 1 秒，P95 小于 2 秒。

### 4.2 action_fast

确定性动作快路径，不经过 Agent 思考。

建议动作：

- `tap_text`
- `tap_id`
- `tap_bounds`
- `input_text`
- `wait_until_text`
- `wait_until_package`
- `press_back`
- `open_app`

每个动作执行后返回：

- `success`
- `actionMs`
- `verifyMs`
- `beforeHash`
- `afterHash`
- `currentPackage`
- `changed`
- `errorCode`

### 4.3 template_run

固定业务模板优先执行，不把稳定流程交给 LLM 自由发挥。

优先模板：

- 闲鱼一键擦亮
- 闲鱼一键上架
- 闲鱼一键曝光
- 签到
- 等待广告 30 秒
- 读取发布状态

模板失败时再进入 Agent fallback，并带上失败节点、当前页面、已执行步骤。

### 4.4 Agent Loop Fallback

Agent 兜底只解决不确定任务。

原则：

- observe 任务默认 1 轮。
- safe 任务默认 8 到 12 轮。
- full 任务默认不超过 30 轮。
- 不再默认 60 轮起步。
- 屏幕上下文默认压缩。
- 只有 debug / deep 模式允许全量树。

## 5. P0 优化清单

1. 性能埋点

为任务结果和状态增加：

```json
{
  "metrics": {
    "totalMs": 0,
    "precheckMs": 0,
    "screenTreeMs": 0,
    "screenshotMs": 0,
    "llmRoundMs": 0,
    "toolCallMs": 0,
    "actionVerifyMs": 0,
    "rounds": 0,
    "mode": "observe_fast|action_fast|template|agent"
  }
}
```

2. 快速读屏

新增或完善 `observe_fast` API。不要依赖 LLM，不要拿全量截图走 VLM。

3. 屏幕树压缩

默认只保留：

- 可见节点
- 有文本节点
- 可点击节点
- 可输入节点
- 重要 bounds
- 当前包名
- 当前屏幕尺寸

全量树仅用于 debug。

4. 默认轮次收紧

建议默认：

```text
observe: 1
safe: 8-12
full: 30
```

请求可以显式覆盖，但要有上限。

5. 高阶动作

把多轮工具调用合并成一次服务端动作，例如：

```text
wait_until_text("一键擦亮", timeoutMs=8000)
tap_text("一键擦亮", verifyChange=true)
input_text(selector, value, submit=true)
```

6. 模板优先

模板命中并且参数齐全时直接跑模板；模板失败时进入 Agent，不重复从零分析。

7. LOOM 侧适配

LOOM 手机页和 CLI 需要识别：

- `mode`
- `metrics`
- `progress`
- `screenHash`
- `taskId`
- `errorCode`

不要因为新字段破坏旧接口。

## 6. 不要做的事

- 不要先重做 UI。
- 不要绕开 Token / Lumi 签名。
- 不要默认开放支付、删除、登录授权、隐私 App 自动点击。
- 不要把 timeout 改大来假装稳定。
- 不要把所有任务都丢给 VLM。
- 不要硬编码真实 token、apikey、账号、私钥。

## 7. 验收指标

最低验收：

- `observe_fast` P50 小于 1 秒，P95 小于 2 秒。
- 单步安全点击 P50 小于 6 秒，P95 小于 12 秒。
- 固化模板任务比 Agent 全流程减少 50% 以上耗时。
- 任务提交后 300ms 内返回 taskId 或明确进度。
- 任务结果包含 metrics。
- 旧的 `/api/agent/execute_task` 兼容。
- Token / Lumi 签名不破坏。

## 8. 验证命令

APKClaw：

```powershell
cd D:\Axiangmu\AUSTART\apkclaw\Hermes-Agent-phone-codex-template-parameter-extraction
.\gradlew.bat :app:assembleDebug
.\gradlew.bat test
```

LOOM：

```powershell
cd D:\Axiangmu\AUSTART\openclaw_new_launcher
python -m pytest python/tests/test_routes_phone.py python/tests/test_phone_fast_path_contract.py python/tests/test_phone_demo_page_contract.py
node --check scripts/openclaw-phone-agent.mjs
node --check scripts/openclaw-phone-vision.mjs
```

真机烟测，如手机可用：

```text
1. 读取当前屏幕
2. 截图
3. observe_fast
4. safe 模式单步点击
5. 闲鱼模板任务
6. task_busy
7. 无障碍关闭
8. 模型未配置
9. 断网/手机离线
```

## 9. 给新会话的 Codex /goal

```text
/goal 优化 APKClaw 手机端执行内核，让 LOOM/Codex 调用手机控制时明显更快：先做只读调研和性能基线，再实现 APKClaw Fast Path、屏幕树压缩、任务进度埋点、低轮次 Agent 策略和模板优先执行；必要时只改 LOOM 手机桥接层来适配新返回字段，不改 LOOM 主 UI 和无关安装器功能。

背景：先阅读 D:\Axiangmu\AUSTART\docs\APKCLAW_SPEED_ARCHITECTURE_AND_GOAL.md 和 D:\Axiangmu\AUSTART\apkclaw\Hermes-Agent-phone-codex-template-parameter-extraction\docs\APKCLAW_SPEED_ARCHITECTURE_AND_GOAL.md。APKClaw 源码在 D:\Axiangmu\AUSTART\apkclaw\Hermes-Agent-phone-codex-template-parameter-extraction。重点阅读 AgentApiController.kt、DefaultAgentService.kt、ClawAccessibilityService.java、GetScreenInfoTool.java、OpenAiLlmClient.kt、WorkflowTemplateManager.kt，以及 LOOM 侧 openclaw_new_launcher/python/api/routes_phone.py、scripts/openclaw-phone-agent.mjs。目标架构是 observe_fast / action_fast / template_run 快路径优先，Agent Loop 兜底。

验收：
1. 增加性能埋点，任务结果或状态里能看到 totalMs、screenTreeMs、llmRoundMs、toolCallMs、rounds、mode。
2. 新增或完善快速读屏能力，不调用 LLM 即可返回当前包名、页面摘要、关键节点、screenHash。
3. 默认屏幕树压缩，只返回对决策有用的节点；保留 full/debug 模式。
4. observe 模式默认 1 轮，safe 模式默认不超过 12 轮，full 模式不超过 30 轮，仍允许请求显式覆盖但有上限。
5. 固定任务优先走模板或高阶动作，失败再进入 Agent。
6. LOOM/CLI 调用保持兼容，旧接口不删除，Token/Lumi 签名不破坏。
7. 给出测试报告：至少覆盖读屏、截图、safe 任务、模板任务、超时、任务 busy、无障碍未开、模型未配置。

验证命令：
- 在 APKClaw 目录运行 .\gradlew.bat :app:assembleDebug
- 运行现有单元测试或最小 Gradle test 任务，如可用则运行 .\gradlew.bat test
- 在 LOOM 目录只运行手机相关契约测试和脚本静态检查，避免全量打包
- 如有真机，使用已配置手机做 observe_fast、截图、safe 点击、模板任务四类烟测，并记录耗时

约束：
- 不硬编码真实 token、apikey、账号、私钥。
- 不改包名、签名、TokenValidator、Lumi 安全协议语义，除非先写兼容说明。
- 不做大规模 UI 重构，不碰无关智能体安装器页面。
- 不把危险动作默认开放；支付、删除、登录授权、隐私数据仍需安全拦截或显式确认。

边界：
允许修改 APKClaw 手机端源码、对应测试、必要的 LOOM 手机桥接脚本/API 适配和文档；禁止清理无关仓库、重写整个 LOOM、改 NewAPI 登录、改发布流程。

迭代策略：
先测量再优化；每次只做一个提速点，跑最小验证；最多 3 轮针对瓶颈继续优化。遇到真机不可用时，先完成源码级契约测试和模拟响应测试，并明确剩余风险。

完成条件：
APKClaw 可构建，核心手机控制链路兼容，读屏/单步任务/模板任务有耗时证据，且报告列出优化前后差异、剩余瓶颈和下一步建议。

暂停条件：
需要真实手机解锁、生产账号、签名私钥、付费操作、敏感 App 自动点击、或连续三次因为外部环境无法验证时暂停并报告。
```
