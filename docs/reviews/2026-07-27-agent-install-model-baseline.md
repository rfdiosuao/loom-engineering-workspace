# Agent 安装与模型可靠性基线

## 冻结信息

- 计划基线：`4f2a01e40c2e0b777ec4f279e06969f962b4bc08`
- 基线日期：2026-07-27
- 门禁清单：`packages/contracts/reliability-gates.v1.json`
- 执行器：`scripts/invoke-reliability-gates.ps1`

本文件冻结测试口径，不把未执行的真实环境验证写成成功。自动化合同只能证明代码路径和错误合同；真实账号、真实模型、实体手机、商业签名和公网更新仍需独立证据。

## 固定测试矩阵

| 操作系统 | 安装形态 | Codex | Claude Code | OpenCode | 当前证据 |
| --- | --- | --- | --- | --- | --- |
| Windows 10 x64 | 全新安装 | 未执行 | 未执行 | 未执行 | 需干净机 |
| Windows 10 x64 | 覆盖安装 | 未执行 | 未执行 | 未执行 | 需保留历史会话证据 |
| Windows 11 x64 | 全新安装 | 未执行 | 未执行 | 未执行 | 需干净机 |
| Windows 11 x64 | 覆盖安装 | 未执行 | 未执行 | 未执行 | 需保留历史会话证据 |
| Windows 10/11 x64 | 离线重开 | 未执行 | 未执行 | 未执行 | 需断网场景 |

每个单元必须记录安装包哈希、LOOM 版本、Agent 版本、开始/结束时间、结果、错误码、日志证据路径和是否保留用户数据。

## 固定五段用户旅程

1. 安装 LOOM。
2. 登录模型账号。
3. 安装目标 Agent。
4. 选择并验证可用模型。
5. 完成首轮中文对话。

每段记录耗时、业务结果和结构化错误码。任何一步失败都停止“成功率”计数，但保留后续人工诊断证据。

## 固定故障域

故障只能归入以下之一：

| 故障域 | 说明 |
| --- | --- |
| `loom_installer` | LOOM 安装、升级、回滚或受管文件事务 |
| `agent_package` | Agent 包架构、哈希、入口或启动探针 |
| `local_environment` | PATH、权限、进程、磁盘或本机运行时 |
| `account_auth` | 账号或凭据认证 |
| `model_permission` | 模型未列出、分组或权限不足 |
| `provider_upstream` | 供应商 5xx、模型下线或服务异常 |
| `network` | DNS、TLS、代理、连接或超时 |
| `unknown` | 证据不足，必须补诊断后再归类 |

## 当前自动化基线

```powershell
.\scripts\invoke-reliability-gates.ps1 -Risk high -Ci
.\scripts\test-workspace.ps1
```

2026-07-28 在冻结基线分支执行结果：

| 门禁 | 结果 |
| --- | --- |
| `agent.runtime.contracts` | PASS，13 项 |
| `installer.transaction.contracts` | PASS，169 项 |
| `matrix.control.contracts` | PASS，100 项 |
| `model.wiring.contracts` | PASS，129 项 |
| `ui.first-success.contracts` | PASS，53 项 |
| Workspace contracts | PASS，94 项 |

各门禁之间可能复用同一合同测试，以上数字是每个命令的执行计数，不作为去重后的全量测试总数。真实模型、实体多机和商业签名不属于该自动化基线，状态均为“未执行”。

## 证据目录约定

真实环境证据保存到未入库的 `artifacts/reliability/<date>/<case-id>/`，PR 只记录脱敏摘要和校验值。禁止提交 Token、API Key、客户数据、安装包、APK、截图、录屏或原始日志。
