# 麓鸣 Desktop `2.4.15` 发布说明

> 配套边界：LumiAgent `6.67-stability`（Android 7 为
> `6.67-stability-android7`），手机 versionCode `936`。本 Desktop 发布说明不声明或发布新的 Phone 构建。

## 本次更新

- 在写入 Codex 第三方模型配置前，对用户显式设置的 Windows sandbox 执行本机 Codex CLI 无副作用创建探针；沙盒无法创建时停止事务，不再写入半可用配置。
- Windows sandbox 失败改为简短中文提示，不向界面暴露 `CreateProcessAsUserW`、本机路径或底层命令信息。
- Codex 模型与 Provider 继续作为同一事务写入并回读验证，阻止 DeepSeek 模型错误路由到 `openai` 等不匹配 Provider。
- 关闭第三方模型时记录 LOOM 实际写入配置的哈希；用户没有改动时逐字恢复原官方配置，避免残留 DeepSeek 认证、模型目录或 reasoning 字段。
- 用户在配置后新增或修改 MCP、插件及其他个人设置时，恢复流程只清理 LOOM 管理字段并保留用户改动。

## 安全与会话边界

- 沙盒探针只执行 `cmd.exe /d /c exit 0`，不访问项目文件、不联网、不修改用户 Codex 配置。
- API Key 仍通过 `LOOM_CODEX_API_KEY` 注入，不写入 `config.toml`。
- 配置、失败回滚和关闭第三方渠道都继续验证 Codex 历史会话数量与索引文件未减少。
- 本次 Desktop 更新不包含新的 Phone 二进制；实体设备 instrumentation 与 signed Phone APK 仍需单独验收。
