# LOOM Engineering Workspace

麓鸣 AI 矩阵获客工作台的私有工程总控仓库。这里负责看全局、定合同、开任务和管理并行 PR，应用源码仍由各自的私有仓库维护。

## 当前重点

1. 稳定保存 LOOM 平台和手机 Agent 的最新核心代码。
2. 多手机按设备分片、并发执行、取消链和全应用按钮门禁已经进入工程基线。
3. 下一阶段：真机矩阵验收，并在招聘劳务场景验证 BOSS 直聘简历筛选闭环。

## 核心入口

| 模块 | 路径 | 职责 | GitHub |
| --- | --- | --- | --- |
| LOOM 平台 | `apps/loom-platform` | 桌面总控、Matrix、模型、媒体、飞书和交付 | `rfdiosuao/loom-luming-launcher` |
| 手机 Agent | `apps/loom-phone-agent` | Android Worker、RPA、视觉、长连接和设备 API | `rfdiosuao/lumiapkclaw` |
| 跨端合同 | `packages/contracts` | 任务、事件、结果和错误 Schema | 本仓库 |
| 业务 Skills | `packages/skills` | 招聘、获客和矩阵监督能力 | 本仓库 |
| 工程文档 | `docs` | 架构、决策、计划和操作手册 | 本仓库 |

## 每天只用这四条命令

首次克隆后先初始化本机依赖：

```powershell
.\scripts\bootstrap.ps1
```

```powershell
# 看所有仓库、分支、脏文件和 worktree
.\scripts\status.ps1

# 为一个 Issue 创建独立功能工作树
.\scripts\new-feature.ps1 -Repository platform -Issue 101 -Name matrix-device-assignments

# 拉取所有私有仓库的远端状态
.\scripts\sync.ps1

# 验证总工作区和两个核心仓库
.\scripts\verify.ps1
```

## 并行开发规则

- 一个功能只对应一个 Issue 和一个 PR。
- 一个 Agent 只进入一个 worktree，禁止多个 Agent 共用同一源码目录。
- 分支统一使用 `codex/<issue>-<feature>`。
- 跨平台修改拆成平台 PR、手机 PR和合同 PR，用同一个 Issue 关联。
- 合同 PR 先合并，依赖它的实现 PR 再更新基线。
- APK、截图、日志、数据库、Token、签名文件和本地配置禁止提交。

当前 GitHub 套餐不支持私有仓库服务端分支保护。`bootstrap.ps1` 会为总控、平台和手机仓库安装版本化 `pre-push` Hook，默认阻止向 `main` 或 `master` 直接推送；GitHub Actions 继续承担远端检查。

详细流程见 [并行开发手册](docs/runbooks/parallel-development.md)和[工作区架构图](docs/architecture/workspace-map.md)。

## 仓库边界

`rfdiosuao/lumi` 是公开展示和公开发布仓库，不承载麓鸣私有开发源码。工程开发只使用本仓库以及上表中的两个私有源码仓库。

## 旧工作区

迁移源 `D:\Axiangmu\AUSTART` 暂时完整保留。新工作区验证完成前，不删除、不清理、不重命名旧目录。
