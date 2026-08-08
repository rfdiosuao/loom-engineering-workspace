# Agent reliability release gates

Harness 6.0.1 / Prompt `LOOM-COMMANDER-6.0.1` / Protocol 6.0 把证据分成三类。三类报告不可互相冒充，尤其不能用 virtual fixture 报告替代真实设备门禁。

## 1. Read-only gate（默认）

无 `--profile` 与显式 `--profile read-only` 等价。默认仍是 2 台设备、300 秒、每 5 秒轮询一次；调用 `/api/matrix/status`，并在未指定 `--no-screens` 时调用只读 `/api/matrix/screens`。它不会 submit、cancel 或 restart 任务，也绝不能标成 lifecycle evidence。

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
python scripts/loom-matrix-soak.py --profile read-only --min-devices 2 --duration-sec 300
```

read-only 报告继续使用 `loom.matrix.soak.v1`，保留原有 `createdAt`、`passed`、`requirements`、`summary` 和 `rounds` 语义；新增的 `profile=read-only`、`commit`、`artifactHashes`、协议版本和设备清单仅用于审计。它只证明观测期间的在线数、截图结果、failure rate 和 P50/P95，不证明 submit→terminal、cancel confirmation 或 restart reconcile。

Bridge status 当前没有可信硬件 attestation contract。因此 observed device 必须 fail-closed 为 `provenance=unknown`、`virtual=null`、`realDeviceEligible=false`；不能相信 device 自报的 `virtual=false`。即使 read-only `passed=true` 且在线数达到 2 或 10，也只表示 read-only count observation 通过；`realDeviceEligibility.gateProven=false`，不能升级成真实硬件门禁。

## 2. Virtual lifecycle evidence（非真实设备门禁）

`lifecycle` 仅接受显式 JSON fixture。fixture 必须同时声明：

```json
{
  "schema": "loom.matrix.lifecycle-fixture.v1",
  "virtual": true,
  "safe": true,
  "sideEffectFree": true,
  "name": "short-virtual-check",
  "devices": [{"deviceId": "virtual-1"}],
  "events": [
    {"atMs": 0, "type": "device", "deviceId": "virtual-1", "online": true, "epoch": "e1", "pid": 100},
    {"atMs": 2, "type": "resource", "deviceId": "virtual-1", "epoch": "e1", "pid": 100, "rssMb": 100, "handles": 20, "threads": 4, "heartbeat": 1},
    {"atMs": 5, "type": "submit", "deviceId": "virtual-1", "taskId": "task-1", "epoch": "e1"},
    {"atMs": 10, "type": "progress", "deviceId": "virtual-1", "taskId": "task-1", "progress": 50, "heartbeat": 2, "epoch": "e1"},
    {"atMs": 15, "type": "terminal", "deviceId": "virtual-1", "taskId": "task-1", "status": "succeeded", "epoch": "e1"},
    {"atMs": 20, "type": "restart-checkpoint", "deviceId": "virtual-1", "epoch": "e1", "pid": 100, "taskIds": []},
    {"atMs": 25, "type": "restart-reconcile", "deviceId": "virtual-1", "previousEpoch": "e1", "epoch": "e2", "pid": 101, "taskIds": []},
    {"atMs": 26, "type": "resource", "deviceId": "virtual-1", "epoch": "e2", "pid": 101, "rssMb": 90, "handles": 18, "threads": 4, "heartbeat": 1},
    {"atMs": 30, "type": "submit", "deviceId": "virtual-1", "taskId": "task-2", "epoch": "e2"},
    {"atMs": 35, "type": "cancel-request", "deviceId": "virtual-1", "taskId": "task-2", "epoch": "e2", "accepted": true},
    {"atMs": 40, "type": "terminal", "deviceId": "virtual-1", "taskId": "task-2", "status": "cancelled", "epoch": "e2"}
  ]
}
```

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
python scripts/loom-matrix-soak.py --profile lifecycle --fixture "$env:TEMP\loom-safe-virtual-fixture.json" --max-resource-growth-mb 64 --max-handle-growth 128 --max-thread-growth 8 --report "$env:TEMP\loom-safe-virtual-report.json"
```

缺 fixture、fixture 不是 `virtual=true`、不是 `safe=true` 或未显式声明 `sideEffectFree=true` 时，CLI 在读取 Bridge 会话或发起任何网络请求之前拒绝执行。lifecycle runner 只回放 fixture 事件，本身没有 HTTP callback，因此不会默认向真实设备下发任务。

报告必须直接包含 `profile=lifecycle`、`evidenceMode=virtual`、fixture hash、设备清单、阶段计数、failure rate、P50/P95、false-timeout、recovery success/duration、按 PID 分段的 RSS/handles/threads/heartbeat 趋势、queue consistency、restart reconcile 和 cancel confirmation。virtual device 固定为 `provenance=virtual`、`realDeviceEligible=false`，顶层 `realDeviceEligibility.gateProven=false`。`realDeviceGate.executed` 固定为 `false`，并列出未执行的 `2-device/20-round` 与 `10-device/7200-second` 门禁。

每个非 cancel 的成功 task 必须有有效、严格单调前进的 progress；数值回退直接产生 `progress-regression`，不能计为普通成功。progress/heartbeat、metadata 和 resource sample 都执行严格 schema 校验，缺失、NaN、负值、错 epoch 或错 PID 不能静默归零；metadata 必须显式携带当前 device 的 epoch 与 PID。device/restart/resource/metadata 的 PID 必须是 finite、非负 integer，bool、numeric string、NaN/inf 和缺失值都不能建立绑定。所有 epoch token 都必须是 trim 后非空的 string。restart checkpoint 的 PID/epoch 必须匹配当前 device，并完整列出该设备当前 epoch 的所有活跃 task；reconcile 的 `previousEpoch` 必须匹配 checkpoint epoch，并形成新 PID 边界；reconcile 可把存活 task 迁移到新的非空 epoch（示例为 e1→e2），成功后才更新当前 PID/epoch。RSS、handles、threads 分别有独立 growth threshold；heartbeat 在同一 PID 内不得倒退，换 PID 后可重置。

虚拟失败注入至少应覆盖：offline-before-submit（0 submit）、offline-mid、heartbeat 前进但 progress 固定、同 task/epoch reconnect recovery、restart lost state、cancel accepted 但无 confirmed terminal、PID 边界 resource growth、queue ID/depth 不守恒，以及 late terminal/false-timeout。late terminal 不能计为普通成功。

## 3. 真实设备 release gates

真实设备结果必须来自可审计的、带可信硬件 attestation 的设备清单，不能把 fixture 中的 `virtual-*` 或 provenance unknown 的 observed device 当真机。当前 Harness 6.0.1 能执行 read-only count observation，但尚无可信硬件 attestation contract；下面两条命令只是候选门禁的观测命令，不足以单独证明真实设备门禁。真实 lifecycle 操作需在单独获批、隔离且可恢复的设备实验台完成，不能通过本 harness 的 virtual profile 声称已经完成。

### 2-device / 20-round gate

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
python scripts/loom-matrix-soak.py --profile read-only --min-devices 2 --iterations 20 --report "$env:TEMP\matrix-real-2x20.json"
```

报告可以验证至少 2 个 observed device、20 rounds、failure-rate 与 P95；但只要 inventory 仍是 `provenance=unknown` / `realDeviceEligibility.gateProven=false`，真实 2-device gate 就是 **not proven / not executed**。它仍是 read-only observation，不是 lifecycle gate，也不是 attested hardware gate。

### 10-device / 7200-second gate

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
python scripts/loom-matrix-soak.py --profile read-only --min-devices 10 --duration-sec 7200 --report "$env:TEMP\matrix-real-10x7200.json"
```

报告可以验证至少 10 个 observed device 和完整 7200 秒观测窗口；中途低于 count 门槛、failure rate 或 P95 超标会让 observation 失败。即使 observation 通过，没有 attested hardware inventory 时真实 10-device gate 仍是 **not proven / not executed**。

## 判定纪律

- 本次短时 virtual CLI 只验证 harness 行为，不代表已执行 2 台/20 轮或 10 台/7200 秒真实设备门禁。
- read-only `passed=true` 不能覆盖 `realDeviceEligibility.gateProven=false`；没有 attestation 时只允许称 count observation 通过。
- `adb devices` 为空表示没有可供验证的真实设备；它既不是通过，也不能生成“通过”的真实 soak artifact。
- 不得手工改 `profile`、`evidenceMode`、`fixture.virtual` 或 `realDeviceGate.executed` 来升级证据等级。
- CLI 报告的 `commit` 与工作树绑定：clean source 使用裸 HEAD；授权 harness source 任一文件 dirty 时使用 `<HEAD>+dirty`。结构化 `sourceIdentity` 同时记录 `headCommit`、`dirty` 和按四个 harness/source 文件实际内容复算的 SHA-256 fingerprint，不能把 dirty harness 表述成纯 HEAD。
- `commit`、source fingerprint 或 artifact hash 无法获取时必须明确为 `unknown`；正式 release gate 应补齐可追溯值，未知值不能伪造。
- 报告应写到受控 artifact 位置或系统临时目录。本地试跑不要把虚拟报告提交进仓库。
