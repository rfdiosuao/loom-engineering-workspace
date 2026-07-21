# OpenClaw Launcher 文档索引

> 更新日期：2026-06-14
> 用途：作为启动器、APKClaw、交付、发布和技术债文档的唯一入口。旧的 handoff 和历史测试记录可以保留，但不要再作为当前事实源。

## 当前必读

| 文档 | 用途 |
| --- | --- |
| `task.md` | 当前任务、技术债优先级和下一步执行顺序 |
| `TECH_DEBT_LAUNCHER_AND_APKCLAW.md` | 启动器与 APKClaw 的统一技术债台账 |
| `PROJECT_STRUCTURE.md` | 项目结构、目录职责和清理规则 |
| `RELEASE_CHECKLIST.md` | 人工发包检查清单 |
| `SUPPORT_TROUBLESHOOTING.md` | 售后排障说明 |
| `CUSTOMER_GUIDE.md` | 客户使用说明 |
| `DELIVERY_ACCEPTANCE.md` | 客户交付验收标准 |

## 手机 Agent / APKClaw

| 文档 | 用途 |
| --- | --- |
| `PHONE_CONNECTOR_API_CONTRACT.md` | 当前 Lumi/OpenClaw 对接 APKClaw 的接口契约 |
| `APKCLAW_LAUNCHER_SECURE_CHANNEL.md` | APKClaw launcher-only 安全通道设计 |
| `APKCLAW_LUMI_INTEGRATION_HANDOFF.md` | APKClaw 长期集成历史和版本演进记录 |
| `APKCLAW_PHONE_CONTROL_ROADMAP.md` | 手机控制、AI 指针、多模态控制路线 |
| `OPENCLAW_APKCLAW_COMBINED_CAPABILITIES.md` | OpenClaw + APKClaw 的产品能力场景 |
| `OPENCLAW_APKCLAW_FULL_TEST_2026-05-11.md` | 2026-05-11 全链路测试记录 |
| `APKCLAW_STRESS_TEST_2026-05-11.md` | APKClaw 真机压测记录 |
| `OPENCLAW_AGENT_DIRECTED_TEST_2026-05-11.md` | OpenClaw 指挥 APKClaw 的测试记录 |
| `CLI_IMAGE_TO_PHONE.md` | PC 图片/AI 生图导入手机相册 CLI |
| `PHONE_VIDEO_CAPTURE.md` | 手机录屏、停止和 MP4 拉回 PC |

## OpenClaw 工作区

| 文档 | 用途 |
| --- | --- |
| `OPENCLAW_PORTABLE_WORKSPACE.md` | 便携包内 OpenClaw 工作区、skills、runtime context 说明 |
| `OPENCLAW_MEMORY_RECOVERY.md` | OpenClaw 丢失上下文后的恢复提示与回链规则 |
| `BRIDGE_MIGRATION_GUARD.md` | Bridge/FastAPI 迁移保护和 smoke 检查 |
| `RUNTIME_PATHS.md` | Windows/Mac runtime 路径规则 |
| `MODULE_BOUNDARIES.md` | 模块职责边界 |
| `MODULE_EXTENSION_GUIDE.md` | 新增启动器模块/页面的方法 |

## 产品和 UI

| 文档 | 用途 |
| --- | --- |
| `PRODUCT_ROADMAP.md` | 产品路线和阶段目标 |
| `LUMI_AGENT_PLATFORM_ROADMAP.md` | 长期 Agent 平台路线 |
| `LUMI_PERSONAL_UI_DESIGN.md` | Lumi 个人版 UI 方向 |
| `UI_CUSTOMIZATION_DESIGN.md` | 品牌/主题定制设计 |
| `广告视频使用文档.md` | 广告视频功能客户使用文档 |

## 发布和仓库

| 文档 | 用途 |
| --- | --- |
| `GIT_CICD_PLAN.md` | CI/CD 设计和实施计划 |
| `GITEE_SETUP.md` | Gitee 同步和发布说明 |
| `2026-05-10更新日志.md` | 2026-05-10 中文更新日志 |
| `2026-05-11更新日志.md` | 2026-05-11 中文更新日志 |
| `2026-05-23-v2.0.6-更新日志.md` | 2026-05-23 v2.0.6 更新日志 |
| `2026-06-14-v2.1.8-更新日志.md` | 2026-06-14 v2.1.8 稳定性、调度、安全与交付质量更新日志 |
| `2026-06-14-授权模型与视频压测报告.md` | 授权码模型 smoke、Agnes 视频压测问题和优化记录 |

## 授权后台

| 文档 | 用途 |
| --- | --- |
| `LICENSE_SERVER_SAAS_ADMIN_GUIDE.md` | 授权后台月卡、套餐、网关、批量编辑的保姆级操作手册 |
| `LICENSE_SERVER_PRODUCTION_DEBT.md` | 授权后台生产级技术债台账 |
| `LICENSE_ADMIN_SITE_AUDIT_2026-05-21.md` | 线上授权后台站点问题记录和后续修复建议 |

## 桌面 Agent / Luminode

| 文档 | 状态 |
| --- | --- |
| `LUMINODE_DESKTOP_AGENT_INTEGRATION.md` | 本地已有设计和实验，暂不进入本批 GitHub 推送范围 |

## 历史 / 待归档

这些文件仅作为历史记录，不作为当前事实源。后续清理时优先保留有验收价值的记录，删除备份和重复稿。

| 文档 | 状态 |
| --- | --- |
| `DOCS_INDEX.md.bak-20260523173905` | 备份文件，待删除或移出仓库 |
| `openclaw能力恢复文档.md` | 与 `OPENCLAW_MEMORY_RECOVERY.md` 重复，待合并 |
| `APKCLAW_LUMI_INTEGRATION_HANDOFF.md` | 长历史流水账，仅用于追溯版本演进 |
| `2026-05-10更新日志.md` | 历史更新日志 |
| `2026-05-11更新日志.md` | 历史更新日志 |
| `CYBER_DIARY_2026-05-11.md` | 历史记录，当前交付不依赖 |

## 文档维护规则

- `task.md` 只保留当前可执行任务，不再堆历史流水账。
- `TECH_DEBT_LAUNCHER_AND_APKCLAW.md` 记录债务来源、风险和验收口径。
- `APKCLAW_LUMI_INTEGRATION_HANDOFF.md` 保留历史版本细节，遇到冲突时以当前代码、`PHONE_CONNECTOR_API_CONTRACT.md` 和 `task.md` 为准。
- 新增接口必须同步更新契约文档和验收脚本。
- 新增发布流程必须同步更新 `RELEASE_CHECKLIST.md` 和 `task.md`。
