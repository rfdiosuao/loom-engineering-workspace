# OpenClaw Launcher 当前任务清单

> 更新日期：2026-05-25
> 当前重点：离线包稳定交付、授权后台生产可用、手机 Agent 硬约束、低配机器启动稳定性。

## 当前状态

- 启动器版本基线：`2.0.6`
- APKClaw 验收基线：`v6.26 / versionCode 860`
- 手机 Agent 协作方式：OpenClaw 只能通过 launcher CLI wrapper 指挥 APKClaw，默认命令是 `npm run phone:agent`
- 手机端 runtime context：不暴露手机 IP、端口、token 和底层 `/api/lumi/*` 任务端点
- 发包校验：`verify-release.ps1` 与 `verify-portable-smoke.ps1` 已接入正式打包流程
- OpenClaw 运行时：离线包打包时更新到 `openclaw@2026.5.22`

## P0 交付稳定性

- [x] `verify-release.ps1` 检查 OpenClaw workspace、runtime context、phone wrapper 和敏感配置
- [x] `verify-portable-smoke.ps1` 检查 Python 依赖、Node CLI 脚本和 runtime-context 基础结构
- [x] `build-portable.ps1` 接入目录校验、smoke 验收、zip 校验和 SHA256 输出
- [x] 打包默认不携带 `AgentPhone_latest.apk`，避免离线包过大；只有传 `-IncludePhoneAgentApk` 才内置 APK
- [x] 打包清理历史 `agents/sightflow-*` 重复目录，只保留 `agents/luminode-desktop`
- [x] 低配机器启动超时放宽，并记录 `openclaw-startup-snapshot.json`
- [x] Bridge 日志固定落盘到 `data/logs/bridge-service.log`
- [x] 环境诊断能识别 Python、Node、WebView2、端口占用、残留进程、授权异常和启动失败摘要

## P0 授权与会员后台

- [x] 授权后台改成可读的 SaaS 控制台
- [x] 会员套餐、网关配置、操作审计、文档拆成独立页面
- [x] 支持套餐模板启用 / 停用 / 编辑
- [x] 支持 LLM、AI 生图、AI 视频分别配置 Base URL、API Key 和模型
- [x] 配额 JSON 从授权后台移除，配额统一放到 API 网关后台管理
- [x] 授权码列表支持搜索、筛选、分页、批量改套餐、启停、删除和激活详情
- [x] 客户端授权成功后只显示授权码后八位，方便后台查询
- [x] 操作审计记录后台操作、目标授权码、来源 IP 和自动备份文件
- [x] 新增发卡网站配置，客户端授权管理页可跳转到后台配置的购买页面

## P1 手机 Agent / APKClaw

- [x] 新增 `npm run phone:agent`
- [x] `AGENTS.md` 和 runtime context 写入 wrapper-only 硬约束
- [x] `phone:agent` 增加任务历史落盘和失败分类
- [x] `phone:agent` 默认发送 `max_rounds=60`
- [x] 固化购物、只读屏幕、游戏视觉 fallback 三个 demo 命令
- [ ] 继续补真实低配一体机上的长任务压测证据

## P1 发布与 CI/CD

- [x] GitHub Release notes 默认中文
- [x] Release 附件包含 portable zip、sha256 和安装器
- [x] 版本一致性检查覆盖 `package.json`、Tauri 配置和包名版本
- [x] 正式 tag release 已跑通过一次完整 GitHub Actions
- [ ] 下一次发版继续验证 Release 附件是否包含最新离线包

## P1 文档债

- [x] `DOCS_INDEX.md` 作为当前文档入口
- [x] `RELEASE_CHECKLIST.md` 纳入 smoke 验收
- [x] `CUSTOMER_GUIDE.md` 补 WebView2 和环境诊断说明
- [x] `task.md` 清理乱码并恢复为可执行任务清单
- [ ] 后续每次新增后台字段时，同步更新生产操作文档

## P2 桌面 Agent / Luminode

- [x] 打包脚本支持携带 Luminode 桌面控制 sidecar
- [x] 打包前清理重复的历史 Luminode/SightFlow 目录
- [ ] 桌面控制功能与 UI 仍按独立方向继续验收
- [ ] 微信 / QQ / 拼多多客服场景需要单独做真实窗口识别和发送策略验收

## 下一步

1. 完成本轮授权后台与启动器发卡入口改动的服务端部署。
2. 运行完整离线包打包，确认 OpenClaw 运行时为 `2026.5.22`。
3. 对新包执行 `verify-release.ps1` 与 `verify-portable-smoke.ps1`。
4. 在启动器授权管理页验证“购买授权码”按钮能读取后台配置并打开外部链接。
