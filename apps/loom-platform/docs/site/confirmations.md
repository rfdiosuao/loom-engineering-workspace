# 待确认事项

本页记录尚未确认、不能写入正式承诺的信息。确认前，相关页面只能使用“建议”“当前口径”或“待部署”等表述。

## 产品与版本

| 项 | 当前状态 | 需要谁确认 |
| --- | --- | --- |
| 品牌名最终用 OpenClaw、Lumi 还是 LumiClaw | 文档暂用 OpenClaw / Lumi | 产品负责人 |
| 启动器公开版本号 | 当前发布 `2.1.8` | 发版负责人 |
| OpenClaw runtime 默认版本 | 当前完整包使用 `2026.6.5` | 发版负责人 |
| Mac 包发布时间 | 未确认 | Mac 适配负责人 |

## 授权与商业

| 项 | 当前状态 |
| --- | --- |
| 授权权益 | 文档暂不承诺具体权益 |
| 设备数限制 | 以 License Server 返回为准 |
| 会员网关 SLA | 未确认 |
| 公开价格 | 未确认 |

## 下载源与 CDN

| 项 | 当前状态 |
| --- | --- |
| 在线瘦包 manifest 主源 | GitHub Release；生产 OSS/CDN 主源待确认 |
| 备用 CDN | 待确认 |
| 桌面 RPA 组件下载源 | `openclaw-runtime-layers` Release 中的 `luminode-desktop.tar.gz`；生产镜像待确认 |
| 手机 APK 下载源 | 待确认 |
| ghproxy 是否保留 | 可作为临时兜底，不作为生产唯一源 |

## 截图资产

当前文档使用 `ui-redesign-preview` 的本地预览截图。正式发布前建议替换：

| 文件 | 需要补充 |
| --- | --- |
| `launcher-dashboard.png` | 当前正式版首页 |
| `phone-control.png` | 真机连接但不暴露隐私的手机控制截图 |
| `desktop-rpa.png` | 已安装桌面组件的健康截图 |
| `settings-models.png` | 不显示真实 Base URL 和模型密钥的设置截图 |
| `skills-cli.png` | Skills 工作区正式截图 |

## 技术待拍板

| 问题 | 建议 |
| --- | --- |
| 扫码配对优先方案 | 优先实现 6 位短码中转，再补充局域网二维码 |
| 桌面 RPA 是否默认内置 | 完整包可内置，瘦包建议下载安装 |
| Runtime Adapter 是否进入短期路线 | 完成稳定性和文档后，再拆分进程层 |
| 设备能力是否 MCP 化 | 以 phone.screenshot 和 publish.post 两个工具作为试点 |

## 文档后续任务

1. 补正式截图。
2. 给每个 CLI 命令补真实 JSON 输出样例。
3. 从 release workflow 自动生成版本页。
4. 给 Mac 适配建立单独验收清单。
5. 把旧 `openclaw-cli/SKILL.md` 重新保存为 UTF-8 并更新目录口径。
