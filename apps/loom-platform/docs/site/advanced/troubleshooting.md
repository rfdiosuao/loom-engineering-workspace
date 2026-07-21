# 故障排查矩阵

排障建议先定位失败层级，再查看具体错误。避免同时修改 UI、Bridge、手机端和模型配置。

## 快速定位

| 现象 | 层级 | 第一动作 |
| --- | --- | --- |
| 401 AuthenticationError | 模型网关 | 检查 Base URL、API Key、Model |
| Invalid Lumi signature | 手机安全通道 | 重新保存设备并验证 Token 与签名 |
| Task timeout 120s | 手机任务执行 | 查锁屏、无障碍、任务是否过大 |
| 广告等待超时 | 手机定时任务 | 检查 `maxWatchSeconds`、链式广告和未知弹窗 |
| 403 blocked | 桌面策略或手机签名 | 看错误体，确认是 Bridge policy 还是 Lumi |
| fetch failed | 网络或服务未启动 | 检查 URL、端口、Bridge、manifest 源 |
| 模板缺失 | 打包层 | 检查 OpenClaw `src/agents/templates` |
| 点击新增刷新页面 | 前端状态或表单提交 | 检查按钮 type、事件阻止和状态更新 |

## 手机控制

| 报错 | 可能原因 | 处理 |
| --- | --- | --- |
| `Invalid Lumi signature` | Token 或签名状态不一致 | 删除旧设备，重新配对，确认时间同步 |
| `lumi_signature_repair_failed` | 自动修复签名失败 | 重新保存 Token，重启手机端 Agent |
| `Task timed out after 120s` | 锁屏、无障碍关闭、任务太大 | 解锁，检查无障碍，拆小任务 |
| 广告任务一直不结束 | 链式广告、奖励按钮未出现或页面变化 | 限制最大等待，遇到未知弹窗停止并留截图 |
| 截图一直加载 | 手机端截图接口慢或异常 | 先请求 `/api/device/status` |
| 显示已连接但任务失败 | 连接只证明基础 HTTP 可达 | 再查签名、无障碍和任务接口 |

## 桌面 RPA

| 报错 | 可能原因 | 处理 |
| --- | --- | --- |
| 组件未安装 | 在线包未包含 Luminode | 点击安装组件或放入 agents 目录 |
| 同步 RPA 配置失败 | URL、API Key、Bridge Token 或组件缺失 | 回到统一设置同步配置，再运行 health |
| health 失败 | sidecar 未启动 | 通过启动器按钮启动，避免手写端口 |
| 403 blocked | policy 禁止点击/输入/发送 | 打开策略，并在 CLI 带 `--confirmed` |
| 401 | Bridge token 不匹配 | 让 CLI 自动读取 token，避免直连 |
| 截图黑屏 | 权限、锁屏或组件异常 | 解锁桌面，重启组件，重新截图 |

## 授权与模型

| 报错 | 判断 |
| --- | --- |
| 授权页未授权 | OpenClaw 能力门控问题 |
| 模型 401 | API Key 或网关问题 |
| OpenAI OAuth unsupported_region | 网络路线、地区或代理传递问题 |
| OAuth callback timeout | 浏览器回调没有回到本机端口 |
| Base URL 显示但 schema 没字段 | 渲染层或本地 Provider 配置桥接需要核对 |

## 打包与发行

| 问题 | 检查 |
| --- | --- |
| 包太大 | 是否打了开发缓存、target、node_modules 过多层 |
| 包太瘦跑不起来 | bootstrap 是否能拉 runtime，manifest 是否多源 |
| 缺 SOUL.md 或模板 | 检查 `node_modules/openclaw/src/agents/templates` |
| Mac 端同步失败 | 源码包是否排除了 Windows 二进制和用户状态 |
| GitHub Actions 构建不一致 | release workflow 的 openclaw_version 和脚本参数是否一致 |

## 排障记录模板

```text
现象：
复现步骤：
当前版本：
启动器页面：
错误原文：
是否预览模式：
Bridge URL：
Phone URL：
最近一次成功时间：
已尝试：
下一步证据：
```

提交排障信息时，建议附上这段记录，便于工程人员复现和定位。
