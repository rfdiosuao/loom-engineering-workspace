# 手机自动化 MVP 验证说明

本页记录“闲鱼自动化、任务模板库、定时任务、执行日志、启动器性能”的本地可验证范围。

## 已纳入启动器的能力

- 任务模板库：内置闲鱼维护、闲鱼只读巡检、闲鱼曝光评估、通用读屏和通用截图模板。
- 风险分级：模板包含 `low`、`medium`、`high` 结构化风险等级；UI 显示风险、模式和确认要求。
- 定时任务：支持选择模板、设备、频率、时间窗口、执行模式，并可创建、启停、删除。
- 试运行：当前试运行只做本地调度和日志留痕，不触发真实闲鱼支付、发布、改价、删除、聊天或投放确认。
- 执行日志：日志记录模板、设备、计划 ID、状态、错误原因、时间和截图路径。
- 性能烟测：构建后记录前端 JS/CSS 体量，并输出冷启动复测命令。

## 本地验证命令

```powershell
npm run build
npm run verify:automation
npm run verify:performance
```

`verify:automation` 会生成：

```text
data/logs/phone-automation-smoke.json
```

`verify:performance` 会生成：

```text
data/logs/launcher-performance-smoke.json
```

完整便携包冷启动复测命令：

```powershell
npm run measure:cold-start -- --root <portable-root> --budget-ms 30000 --output-path data/logs/cold-start.json
```

源码根可以用于验证脚本口径，但不能替代完整便携包：

```powershell
npm run measure:cold-start -- --root D:\Axiangmu\AUSTART\openclaw_ui_integration --budget-ms 30000 --stop-after-measure --output-path D:\Axiangmu\AUSTART\openclaw_ui_integration\data\logs\cold-start-source-root.json
```

当前源码根测量会失败，因为源码目录不包含便携包的 `node/node.exe`。这是预期边界，完整冷启动仍需对 `release/OpenClaw-Portable-...` 根目录复测。

## 真机验证边界

真机闲鱼验证只允许低风险和只读路径：

- 打开闲鱼并读取当前页面。
- 商品列表只读巡检。
- 擦亮按钮存在时，仅执行平台明确的“擦亮/立即擦亮”维护动作。
- 曝光权益只做评估，停在最终确认前。

以下动作必须暂停并交给人工确认：

- 支付、投放确认、发布商品、改价、删除商品。
- 发送聊天、回复买家、授权新协议。
- 验证码、风控、登录异常、账号安全提示。
- 任何无法明确判断后果的弹窗或跳转。

## 交付判定

本地交付以三项通过为准：

1. `npm run build` 通过。
2. `npm run verify:automation` 通过，报告显示模板、计划、队列和失败日志均可归一化。
3. `npm run verify:performance` 通过，报告包含构建体量和冷启动复测命令。

真机交付需要额外保存 APKClaw 截图、任务日志和执行结果，且不得越过上面的安全边界。
