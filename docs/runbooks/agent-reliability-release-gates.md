# 智能体可靠性发行门禁

本文档用于在发布 LOOM 安装包前验证智能体、模型接线、媒体配置、矩阵状态和手机连接。命令默认从 `apps/loom-platform/openclaw_new_launcher` 目录执行。

## 快速发行冒烟

```powershell
npm run smoke:release
```

该命令检查：

- LOOM CLI 与 Bridge 基础状态；
- 生图和生视频配置是否可用；
- 模型供应商接线与本地配置是否完整；
- Matrix 状态接口是否返回业务成功；
- 已配置手机数量和状态响应。

要求至少一台手机在线时执行：

```powershell
npm run smoke:release:phones
```

门禁会读取本机受保护的 Bridge 会话，不在命令行、报告或日志中输出令牌。`wire verify` 只验证供应商接线和配置，不会发起付费模型推理；真实模型、媒体生成和发布动作必须使用专门测试账号另行验收。

## 多机矩阵稳定性

默认执行只读 Matrix 状态与批量截图循环：

```powershell
npm run smoke:matrix:soak
```

10 台实体手机、2 小时发行压测示例：

```powershell
python scripts/loom-matrix-soak.py --duration-sec 7200 --min-devices 10 --max-failure-rate 0.01 --max-p95-ms 30000 --report artifacts/matrix-soak-10-phone.json
```

快速回归可使用固定轮数：

```powershell
python scripts/loom-matrix-soak.py --iterations 20 --interval-sec 1 --min-devices 2
```

压测门禁失败条件包括：

- 任一轮 Matrix 状态或批量截图返回业务失败；
- 观测到的最少设备数低于 `--min-devices`；
- 总失败率超过 `--max-failure-rate`；
- P95 延迟超过 `--max-p95-ms`。

该脚本只访问 `127.0.0.1` 的本地 Bridge，且只调用状态与截图接口，不会下发点击、输入、发布或其他写操作。

## 审计日志轮转

默认单个审计 JSONL 文件最大 8 MB，保留 5 份归档。可按部署规模调整：

```powershell
$env:LOOM_AUDIT_MAX_BYTES = "16777216"
$env:LOOM_AUDIT_ARCHIVE_COUNT = "8"
```

CLI 的日志查询会跨当前文件和归档文件读取；修改参数后无需迁移历史文件。
