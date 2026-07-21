# 麓鸣手机应用场景生成器设计

- 日期：2026-07-15
- Skill 名称：`luming-phone-scenario-builder`
- 设计状态：已确认，待实现
- 探索模式：安全导航

## 1. 目标

把用户用自然语言描述的手机任务，例如“打开某 App，找到指定内容并导出结果”，转换成一个经过真实页面探索、可以复用且能够验收的麓鸣场景 Skill。

生成器必须先探索，再生成步骤。任何没有通过手机页面实际观察和成功信号验证的操作，都不能被写成已确认步骤。

系统必须主动发现并报告运行前提缺口，包括但不限于：手机离线、App 未安装、账号缺失、登录失效、验证码、会员、付费、系统权限、网络、地区限制、App 版本和目标数据缺失。

## 2. 非目标

- 不修改 LOOM Matrix、FastAPI、手机 Agent 或桌面端产品代码。
- 不绕过验证码、双重验证、登录、权限、会员、付费或平台风控。
- 不在探索阶段发布、评论、私信、下单、付款、修改账号或产生其他外部副作用。
- 不依靠模型常识猜测按钮名称、页面路径或任务完成状态。
- 不把存在关键缺口的草稿安装到正式 Skill 库。

## 3. 方案选择

采用“安全探索器 + Skill 编译器”的两阶段架构。

第一阶段在手机上完成环境预检和安全页面导航，形成带证据的页面路线图、缺口报告和可恢复检查点。第二阶段只使用第一阶段已验证的路线生成执行 Skill。

未选择“边探索边写”，因为未完成的页面路径容易被误写成事实。未选择“每个 App 预制模板”，因为它对陌生 App 的覆盖不足且维护成本较高。

## 4. 用户入口

典型触发语句：

- “帮我生成一个手机 Agent 操作抖音搜索指定关键词并整理结果的 Skill。”
- “探索这个 App，然后把完成任务的步骤做成麓鸣 Skill。”
- “我想让手机 Agent 完成这个业务，你先探索再生成执行 Skill。”

最少输入包括：

| 字段 | 必填 | 说明 |
|---|---:|---|
| `goal` | 是 | 手机 Agent 最终要完成的任务 |
| `app_name` | 是 | 目标 App 名称 |
| `device_id` | 多手机时必填 | 指定探索手机，避免在多台手机间混淆页面状态 |
| `entry_hint` | 否 | 已知入口、关键词、对象或页面提示 |
| `expected_result` | 是 | 可观察的任务完成结果 |
| `confirmation_boundary` | 否 | 用户额外指定的人工确认边界；未提供时使用默认安全边界 |

## 5. 架构组件

### 5.1 任务解释器

把自然语言任务归一化为目标 App、入口提示、目标对象、预期结果、禁止动作和验收证据。若任务本身不明确，只询问会改变探索路径的最少问题。

### 5.2 环境预检器

在打开目标流程前检查：

- 指定手机是否在线且可控制。
- 目标 App 是否安装且可启动。
- 网络是否可用。
- 当前账号是否满足任务要求。
- 登录、权限、会员、版本和地区条件是否满足。
- 用户要求的关键词、文件、联系人或业务对象是否已提供。

预检失败时生成缺口报告，不尝试绕过阻塞条件。

### 5.3 安全探索器

允许执行的导航动作：

- 打开目标 App。
- 点击普通页面入口、标签、菜单和非提交型按钮。
- 滚动、翻页、展开内容、输入无敏感性的搜索词。
- 返回上一页或回到 App 首页。
- 截图、读取页面文字和记录可见控件。

每次动作前后都记录页面证据。探索器使用“App + 页面标题 + 关键文字 + 主要控件”形成页面指纹，并记录已访问的“页面指纹 + 动作”边，防止在同一路径循环。

默认探索预算为 40 个导航动作或 15 分钟，以先到者为准；连续三次回到同一页面且没有新控件时停止当前分支。预算可以由用户显式调整。

### 5.4 缺口报告器

将阻塞条件标准化为以下错误类型：

| 类型 | 示例 |
|---|---|
| `device_offline` | 手机离线或 Agent 不可用 |
| `app_missing` | 目标 App 未安装 |
| `account_missing` | 没有任务所需账号 |
| `login_required` | 当前页面要求登录 |
| `session_expired` | 登录状态失效 |
| `captcha_required` | 出现验证码 |
| `two_factor_required` | 需要短信、扫码或双重验证 |
| `membership_required` | 目标能力仅会员可用 |
| `payment_required` | 继续操作将产生付款或订单 |
| `permission_required` | 需要系统或 App 权限 |
| `network_unavailable` | 网络不可用 |
| `region_restricted` | 地区、商店或服务范围受限 |
| `app_version_unsupported` | App 版本不符合要求 |
| `target_data_missing` | 缺少关键词、文件、对象或业务数据 |
| `unsupported_ui` | 页面无法可靠识别或控制 |
| `unsafe_action_required` | 完成路线必然进入风险动作 |

每个缺口必须包含发现位置、可见证据、影响、需要用户完成的动作和恢复检查点。

### 5.5 路线验证器

只有满足以下条件的步骤才标记为 `verified`：

- 动作前页面与预期页面一致。
- 动作来自当前页面实际可见控件。
- 动作后出现可观察的成功信号。
- 截图或页面读取记录可以追溯。
- 失败时存在明确错误分类和恢复策略。

无法验证的步骤标记为 `unknown`，不能进入可运行 Skill 的主流程。

### 5.6 Skill 编译器

路线达到目标页面并验证任务结果后，生成场景 Skill。每个执行步骤包含：

| 字段 | 说明 |
|---|---|
| `step_id` | 稳定的步骤编号 |
| `precondition` | 执行该步前必须满足的状态 |
| `expected_screen` | 预期页面及关键可见文字 |
| `action` | 单一、明确的手机操作 |
| `success_signal` | 判断该步成功的页面证据 |
| `evidence` | 需要保存的截图或日志 |
| `failure_code` | 失败时使用的标准分类 |
| `recovery` | 可恢复方式或停止原因 |
| `requires_confirmation` | 是否必须由人工确认 |

编译器不得把探索假设改写为确定步骤。存在关键阻塞时，只输出探索报告和未注册草稿；补齐条件并恢复探索后，才能生成 `runnable: true` 的 Skill。

## 6. 数据流与状态

```text
任务描述
  -> 任务解释
  -> 环境预检
  -> 安全探索
  -> 页面路线与证据
  -> 路线验证
  -> Skill 编译
  -> 验证并加入 Skill 库
```

运行状态：

```text
collecting_inputs
  -> preflight
  -> exploring
  -> blocked_by_prerequisite | explored
  -> compiling
  -> draft | ready
```

`blocked_by_prerequisite` 必须保存 `resume_from`。恢复时先重新验证缺口是否解除，再从检查点继续，不能默认沿用旧账号、旧页面或旧权限状态。

## 7. 风险边界

以下动作一律停止并请求人工确认：

- 登录、退出登录、切换账号和账号资料修改。
- 验证码、短信码、扫码和双重验证。
- 系统权限和敏感 App 权限授权。
- 开通会员、下单、付款、退款和购买。
- 发布、评论、回复、私信、加好友和批量触达。
- 删除内容、覆盖文件或其他不可逆操作。

探索器可以识别并记录上述入口，但不能点击确认按钮或提交动作。

## 8. 输出契约

一次探索至少输出：

```json
{
  "schema": "loom.phone-scenario.discovery.v1",
  "goal": "用户任务",
  "appName": "目标 App",
  "deviceId": "探索手机",
  "mode": "safe_navigation",
  "status": "explored",
  "runnable": true,
  "route": [],
  "evidence": [],
  "missing": [],
  "resumeFrom": null,
  "requiresHumanReview": true
}
```

阻塞项结构：

```json
{
  "type": "membership_required",
  "severity": "blocking",
  "observedAt": "导出页面",
  "evidence": ["screenshot-id"],
  "impact": "无法验证导出流程",
  "requiredAction": "提供具备导出权限的会员账号",
  "resumeFrom": "export_page"
}
```

成功生成的场景 Skill 包含：

```text
luming-<scenario-name>/
  SKILL.md
  agents/openai.yaml
  references/exploration-report.md
  references/page-route.md
  examples/sample-result.json
```

关键阻塞产生的草稿存放在本次任务工作区，不写入 `skills/`，也不加入 `manifest.json`。

## 9. Skill 库集成

生成器自身加入 `luming-skills-library/skills/luming-phone-scenario-builder/`，并登记到 `manifest.json` 和 `README.md`。

生成的新场景 Skill 只有在以下条件全部满足后才能加入正式库：

- `runnable` 为 `true`。
- 主路线全部由 `verified` 步骤组成。
- 缺口列表不存在 `blocking` 项。
- 风险动作均有人工确认门禁。
- Skill 结构验证通过。
- 示例 JSON 可以解析。

## 10. 验证策略

至少使用以下场景验证生成器行为：

1. 正常路径：App 已安装、账号有效、无需会员，能够生成可运行 Skill。
2. App 缺失：报告 `app_missing`，不得生成或注册可运行 Skill。
3. 登录失效：报告 `session_expired` 或 `login_required`，保留恢复检查点。
4. 会员墙：报告 `membership_required`，不得点击购买或开通。
5. 风险提交：能够探索到发布或付款入口，但必须在提交前停止。
6. 页面循环：重复页面达到阈值后停止当前分支并报告探索预算或页面识别问题。
7. 条件恢复：用户补齐前提后从检查点继续，并重新验证账号和页面状态。

最终验收包括：Skill 验证器通过、所有 JSON 示例可解析、库清单可读取、安装脚本可以把生成器安装到本地 Codex Skills 目录、打包脚本可以生成包含新 Skill 的交付包。

## 11. 完成标准

- 用户可以只描述“手机 Agent 要完成什么”，生成器即可启动预检和探索。
- 探索动作严格限制在安全导航范围内。
- 所有步骤都有实际页面证据和成功信号。
- 账号、登录、会员、App、权限等缺口会被准确报告。
- 关键缺口未解决时不会生成或注册可运行 Skill。
- 条件补齐后可以从检查点继续探索。
- 最终 Skill 具备清晰前置条件、逐步操作、异常处理、风险门禁和验收标准。
