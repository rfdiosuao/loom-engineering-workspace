# FAQ

## OpenClaw 和 Lumi 是什么关系

当前文档把产品称为 OpenClaw / Lumi。OpenClaw 更偏核心运行时和项目名，Lumi 更偏启动器、控制台和能力层语境。实际命名以后应由品牌口径统一。

## 当前启动器版本是多少

当前交付口径是 `openclaw_ui_integration` 版本 `2.1.19`。最新完整离线包和在线包使用 OpenClaw runtime `2026.6.5`。

发布资产在 [openclaw-runtime-layers v2.1.19](https://github.com/rfdiosuao/openclaw-runtime-layers/releases/tag/v2.1.19)。在线包运行时组件 GitHub 优先、自有镜像与 Gitee 兜底。

## 为什么有时显示 Mock 预览

Mock 预览用于 UI 验收和文档截图，不代表真实核心服务已启动。正式使用时要切到真实桥接，并看 Bridge 与核心服务状态。

## 手机显示已连接，为什么任务还失败

“已连接”只说明基础 HTTP 可达。任务还需要 Token、Lumi 签名、无障碍、锁屏状态和任务接口都正常。

## Invalid Lumi signature 怎么办

重新复制手机端 Token，删除旧设备，重新保存并验证。仍失败时检查手机和电脑时间、手机端版本、请求是否被代理改写。

## 600 秒超时是否表示启动器异常

不一定。该提示表示某条手机任务没有按预期结束。建议检查锁屏、无障碍、截图和任务 prompt 是否过大，再拆成观察、判断、执行三步。

## OpenAI Codex OAuth 登录失败是否由回调凭证引起

有可能，也可能由网络路线、地区限制、代理未传给 OpenClaw 进程、本地回调端口超时或手动粘贴 URL 不完整导致。建议先使用 `openclaw onboard` 走原生命令引导，再回到启动器检查 auth profile。

## 桌面 RPA 在哪里

启动器侧栏的“桌面 RPA”。它通过 Bridge 管理 Luminode/SightFlow 桌面组件，并提供截图、未读、显式回复等入口。

## 桌面 RPA 能不能自动回复微信

可以配置自动回复项目，但发送动作必须走策略和确认。建议先执行 `observe`，再生成候选回复，最后由策略允许发送。

## Skills 工作区是否等同于记忆系统

不是。当前定位是自动化工具底座，Skills 是能力模块管理和调用入口，不承担长期记忆系统职责。

## 文档站为什么用 VitePress

VitePress 适合长期维护的产品文档：Markdown 写内容，默认主题提供导航、侧边栏、搜索和构建产物，比单页 HTML 更适合持续扩展。

## 旧 HTML 文档站归档位置

旧文件已归档到 `docs/site/legacy-html/`，用于回溯和迁移对照。
