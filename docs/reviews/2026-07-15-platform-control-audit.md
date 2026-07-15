# LOOM 平台控制完整性审查

日期：2026-07-15

## 结论

LOOM 平台的多手机并行可靠性、隔离式按钮审计和可用控制修复已合入平台工程基线。全局 Shell 与 13 个注册页面的基线可见控件均被归类为：有可观察结果的可用动作、有明确原因的不可用动作，或无交互控件的只读界面。

独立代码审查在第一版急停实现中复现了两个阻断问题：终态选中项可能漏停同 campaign 的活动兄弟任务；重复急停可能漏掉后来出现的同 campaign Job。两项均已修复并加入永久回归，复审结果为 CLEAN，无剩余 Critical 或 Important 问题。

## 已合并平台 PR

| PR | 内容 | 合并提交 |
| --- | --- | --- |
| [#3](https://github.com/rfdiosuao/loom-luming-launcher/pull/3) | 多设备目标、并发持久化、取消和日志游标可靠性 | `fbcf634` |
| [#4](https://github.com/rfdiosuao/loom-luming-launcher/pull/4) | 隔离式 Playwright 控制审计基础设施 | `a673611` |
| [#5](https://github.com/rfdiosuao/loom-luming-launcher/pull/5) | 全应用可见控件审计、问题修复与可靠急停 | `eaac89a` |

## 修复的问题

1. Matrix `急停` 从永久禁用按钮变为真实、鉴权、campaign 原子的控制链。
2. 模型关闭操作增加危险确认，并准确描述托管配置回滚结果。
3. 创作结果没有本地路径时不再显示无效的“复制路径”按钮。
4. 网页注册器打开失败会在账户页明确提示。
5. Agent 检测失败后立即停止，不再继续发送安装请求。
6. 发布与急停互斥；派发拿到 campaign 编号前不会虚假宣称可以急停。

## 验证证据

| 门禁 | 结果 |
| --- | --- |
| Python 全量 | 819 passed，1 个既有 collection warning |
| 手机 Agent Node | 39 passed |
| 平台 TypeScript 契约 | 31 passed |
| 生产构建 | passed |
| Playwright | 156 passed，Edge `960x640`、`1200x800`、`1440x900` |

浏览器审计使用独占严格端口，禁止复用旧开发服务。Tauri、Bridge、手机、安装、支付、飞书和外部链接均被精确隔离桩替代；未知原生调用、未知后端路由、控制台错误或外网请求会直接使测试失败。

平台内的详细审计记录见 `apps/loom-platform/openclaw_new_launcher/docs/tests/visible-control-audit-2026-07-15.md`。

## 尚未替代的验收

这次审查证明的是工程控制链和 UI 行为，不替代真实设备验收。下一阶段仍需在真实 APKClaw 手机、权限、平台账号和外部服务凭据下验证多机执行，并以招聘劳务的简历筛选场景做首个垂直业务闭环。
