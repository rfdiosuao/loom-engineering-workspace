# 麓鸣 Desktop `2.4.11` 发布说明

> 配套边界：LumiAgent `6.67-stability`（Android 7 为
> `6.67-stability-android7`），手机 versionCode `936`。本 Desktop 发布说明不声明或发布新的 Phone 构建；当前 2.4.11 集成线包含 Phone 源码变化，但尚无 current-SHA APK 或真机验证证据。

## 桌面集成内容

- 将桌面发布目标显式固定为 `2.4.11`，并继续校验 launcher/UI package、package-lock 根字段、Tauri 配置及 Cargo package/lock 的版本一致性。
- 保留退出登录回归约束：授权租约锚点变化但真实账号会话未变化时，不应误报 `identityChanged` 并阻断退出登录清理。
- 保留模型配置回归约束：模型目录临时不可用时，可对缓存目录中仍匹配的 DeepSeek 模型继续执行远程验证；写入前仍要求 Codex `Responses API` 与原生工具调用兼容。
- 发布工作流所需说明固定放在 launcher-local `docs/RELEASE_NOTES_2.4.11.md`。

## 证据边界

- 上述内容仅基于当前集成线中的版本文件、实现代码和自动化回归测试；尚无 clean-Windows 环境验收证据。
