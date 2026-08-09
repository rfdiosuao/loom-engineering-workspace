# 麓鸣 Desktop `2.4.12` 发布说明

> 配套边界：LumiAgent `6.67-stability`（Android 7 为
> `6.67-stability-android7`），手机 versionCode `936`。本 Desktop 发布说明不声明或发布新的 Phone 构建；实体设备 instrumentation 与 signed Phone APK 仍需单独验收。

## 本次更新

- 修复“连接手机”入口错误进入付费墙：进入 Phone Matrix 前会先刷新签名授权，再以最新 `matrix.devices` 权限决定是否放行；授权、离线宽限与拒绝路径继续 fail-closed。
- 为授权刷新增加 single-flight 去重，避免 React Strict Mode 或并发入口重复请求；后续重新进入仍会再次获取最新状态。
- 模型账户页面改为打开即自动刷新账户、余额、套餐与授权数据；已有安全快照只用于首屏和网络失败降级。
- 删除“当前显示上次安全快照”黄色横幅、“上次快照/在线数据”标签及账户级手动验证按钮，避免把内部缓存状态暴露成用户操作负担。
- 在线刷新成功后自动替换安全快照；失败时保留最后可用数据，不伪造余额、套餐或授权结果。

## 安全与兼容性

- 不改变服务端计费、套餐、签名租约或商业授权规则。
- 缓存数据不会被提升为在线授权结果；Phone Matrix 仍要求服务端签名授权与 feature gate 同时通过。
- 保留历史 Account cache 的敏感字段清理规则，不缓存 token、gateway 地址或授权兑换码。

## 验证边界

- Account UI、Phone entitlement、Platform TypeScript/Node contracts 与版本一致性 gate 纳入发布验证。
- 本次 Desktop 更新不包含新的 Phone 二进制；真实手机连接、API24/API36 instrumentation 和 signed Phone APK 不作为本安装包证据。
