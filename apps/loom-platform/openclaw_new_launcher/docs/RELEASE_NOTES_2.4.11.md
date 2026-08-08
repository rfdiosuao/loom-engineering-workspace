# 麓鸣 Desktop `2.4.11` 发布说明

> 配套边界：LumiAgent `6.67-stability`（Android 7 为
> `6.67-stability-android7`），手机 versionCode `936`。本 Desktop 发布说明不声明或发布新的 Phone 构建；当前 2.4.11 集成线包含 Phone 源码变化，但尚无 current-SHA APK 或真机验证证据。

## 桌面集成内容

- 将桌面发布目标显式固定为 `2.4.11`，并继续校验 launcher/UI package、package-lock 根字段、Tauri 配置及 Cargo package/lock 的版本一致性。
- 保留退出登录回归约束：授权租约锚点变化但真实账号会话未变化时，不应误报 `identityChanged` 并阻断退出登录清理。
- 保留模型配置回归约束：模型目录临时不可用时，可对缓存目录中仍匹配的 DeepSeek 模型继续执行远程验证；写入前仍要求 Codex `Responses API` 与原生工具调用兼容。
- 修复产品目录由 `Luming AI Matrix Acquisition Workbench` 改为 `麓鸣` 后首启丢失账号状态的问题；本地账号管理器可安全恢复受保护的旧会话，且不会覆盖新目录中的现有会话。
- 为直接运行安装包的升级路径增加旧产品数据迁移：仅从同级、精确命名的旧目录复制新目录中缺失的文件，保留旧数据和新目录现值，并拒绝 reparse point，避免链接逃逸和意外覆盖。
- 兼容生产支付服务曾返回的单字符串 `payment.channels`，在本地 Bridge 边界统一规范为受支持、去重后的数组，避免已开通支付宝时前端仍显示“服务暂未开放”。
- 登录页会先验证本机真实会话，再采用远端缓存；本机会话缺失时清理陈旧登录显示，并向用户展示支付套餐接口返回的实际阻断原因。
- 余额继续遵循生产计费合同 `500000 quota = ¥1.00`，没有把模型 quota 原值直接当成人民币展示。
- 发布工作流所需说明固定放在 launcher-local `docs/RELEASE_NOTES_2.4.11.md`。

## 证据边界

- 支付账户、路由、安装迁移、NSIS smoke、服务端支付 Bridge 与前端平台合同均有自动化回归证据；旧目录到新目录的数据迁移也已在本机执行并完成幂等复验。
- 尚未在真实商户环境创建付费订单或触发回调/对账，避免在未经单独确认时产生真实交易；这仍是发布后的商户验收项。
- Phone Agent 的实体设备 instrumentation 与 signed release APK 仍不在本 Desktop 安装包证据范围内。
