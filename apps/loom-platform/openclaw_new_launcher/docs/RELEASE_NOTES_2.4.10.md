# 麓鸣 2.4.10 更新日志

- 修复授权租约状态变化被误判成账号切换、导致退出登录一直失败的问题。
- 修复模型目录临时不可用时，缓存中仍有效的 DeepSeek 等模型无法继续配置的问题。
- 缓存模型仍需通过 Codex Responses API 和原生工具调用验证后才会写入。
- 保持 LumiAgent `6.67-stability`、Android 7 兼容版和手机 versionCode `936` 不变。
