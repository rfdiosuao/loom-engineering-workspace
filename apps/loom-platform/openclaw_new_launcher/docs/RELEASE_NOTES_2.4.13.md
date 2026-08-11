# 麓鸣 Desktop `2.4.13` 发布说明

> 配套边界：LumiAgent `6.67-stability`（Android 7 为
> `6.67-stability-android7`），手机 versionCode `936`。本 Desktop 发布说明不声明或发布新的 Phone 构建；实体设备 instrumentation 与 signed Phone APK 仍需单独验收。

## 本次更新

- 修复 LOOM 托管模型账号无法写入 Codex Desktop 配置的问题：模型站瞬时返回 `429` 限流或 `503` 上游不可用时，不再让额外的 `/responses` 能力探测阻断整个配置事务。
- 托管账号在刷新后的模型目录中确认所选模型后即可安全写入；目录刷新短暂失败时，只允许使用本机已缓存且精确匹配的模型条目。
- 保留模型目录淘汰保护：所选模型不在最新目录时仍拒绝写入，并要求重新选择。
- 自定义 Provider 继续执行严格在线协议和工具调用验证，不降低 API Key、Responses API 或 function-call 能力约束。

## 安全与兼容性

- 不改变模型站登录、额度、计费、套餐或商业授权规则。
- 不允许任意模型名绕过目录验证；只有托管账号目录中已确认的模型可以免除重复在线探测。
- Codex 配置事务、会话保留、写前快照和失败回滚机制保持不变。

## 验证边界

- 托管账号最新目录、缓存目录降级、自定义 Provider 在线验证及版本一致性均纳入自动化合同测试。
- 本次 Desktop 更新不包含新的 Phone 二进制；真实手机连接、API24/API36 instrumentation 和 signed Phone APK 不作为本安装包证据。
