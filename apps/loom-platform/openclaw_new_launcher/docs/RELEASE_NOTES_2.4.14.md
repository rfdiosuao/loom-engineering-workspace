# 麓鸣 Desktop `2.4.14` 发布说明

> 配套边界：LumiAgent `6.67-stability`（Android 7 为
> `6.67-stability-android7`），手机 versionCode `936`。本 Desktop 发布说明不声明或发布新的 Phone 构建；实体设备 instrumentation 与 signed Phone APK 仍需单独验收。

## 本次更新

- 修复 LOOM 配置 Codex 第三方模型时 DeepSeek 无法写入或写入后不可用的问题，按官方 DeepSeek Responses API 使用 `https://api.deepseek.com` 与 `wire_api = "responses"`。
- 更新 DeepSeek 模型目录，支持 `deepseek-v4-flash` 与 `deepseek-v4-pro`，并为 Codex 生成当前 CLI 可解析的 `models.json` 模型元数据。
- 第三方密钥继续通过 `LOOM_CODEX_API_KEY` 环境变量引用，不把 API Key 明文写入 Codex 配置文件。
- 修复关闭或切换第三方配置时的模型目录恢复逻辑：仅在 LOOM 写入的文件未被用户修改时恢复原目录，避免覆盖用户后续编辑。

## 会话与回滚保护

- 配置、切换或关闭 DeepSeek 不删除 Codex 历史会话；不同认证通道导致的会话分组变化不等于历史记录丢失。
- 配置事务继续执行写前快照、失败回滚和原有会话清单保护。
- 原有 `models.json` 会在启用第三方模型前保存；关闭配置时按内容哈希安全恢复。

## 验证边界

- 已使用官方 Codex CLI `0.147.0` 对 LOOM 生成的 `config.toml` 与 `models.json` 做真实解析验证。
- 自动化测试覆盖 DeepSeek 配置生成、模型映射、配置关闭、目录恢复、用户改动保护及历史会话保留。
- 实际 API 请求仍取决于用户 DeepSeek API Key、账户额度和本地网络；LOOM 在写入时执行模型目录及 Responses 能力探测。
- 本次 Desktop 更新不包含新的 Phone 二进制；真实手机连接、API24/API36 instrumentation 和 signed Phone APK 不作为本安装包证据。
