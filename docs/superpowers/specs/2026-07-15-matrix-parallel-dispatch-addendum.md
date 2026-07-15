# 超级矩阵真实并发调度补充规格

日期：2026-07-15
状态：冻结，作为公共合同 PR 的输入
关联 Epic：`rfdiosuao/loom-engineering-workspace#3`

## 1. 为什么需要补充

原生产化规格覆盖了手机墙、设备租约、人工接管和 Agent 编排，但现有矩阵下发仍以“一份任务复制给多台设备”为主，路由层也可能逐台等待执行。只改 UI 会形成并发假象，不能满足以下真实业务：

- 100 台手机同时处理不同简历、不同候选人或不同账号队列。
- 一台手机失败时，其他手机继续执行。
- 只重试失败设备的失败步骤，不重放整个批次。
- 中枢智能体能按设备看到独立任务、进度、证据和结果。

因此阶段 0 和阶段 1 必须先加入“设备分片 + 有界并发”合同。

## 2. 核心语义

1. 一个 `campaignId` 代表一次矩阵批次。
2. 一个 `assignmentId` 代表一台设备在该批次中的独立业务任务。
3. 一个 `deviceTaskId` 代表该设备任务的可重试执行记录。
4. 一个 `jobId` 代表交给 Phone Agent 的实际异步作业。
5. 同一设备的写操作严格串行，不同设备在 `concurrency` 上限内并行。
6. 批次状态由设备任务聚合，不得用单台设备结果覆盖整个批次。
7. 所有外发、发布、私信、加好友、支付、登录、验证码和账号变更继续经过审批边界。

## 3. 下发合同

新合同 schema 为 `loom.matrix.dispatch.v2`：

```json
{
  "schema": "loom.matrix.dispatch.v2",
  "campaignId": "cmp_20260715_001",
  "concurrency": 8,
  "mode": "safe",
  "profile": "standard",
  "deviceAssignments": [
    {
      "assignmentId": "asg_candidate_001",
      "deviceId": "LUMI-P01",
      "prompt": "筛选候选人张三的简历，只读取并返回结构化结论，不发送消息。",
      "templateId": "boss_resume_screening_v1",
      "input": {
        "candidateId": "candidate_001"
      },
      "timeoutSec": 180,
      "retryBudget": 1
    }
  ]
}
```

字段约束：

| 字段 | 约束 |
|---|---|
| `campaignId` | 可由调用方提供；重复请求必须幂等 |
| `concurrency` | 整数，最小 1，最大值由服务端配置限制 |
| `deviceAssignments` | 不能为空；同一请求内 `assignmentId` 唯一 |
| `deviceId` | 必须指向已注册设备；一台设备在同一批次只允许一个活动 assignment |
| `prompt` / `templateId` | 至少提供一个；模板输入必须通过模板 schema 校验 |
| `timeoutSec` | 每设备超时，不是整个 campaign 的统一超时 |
| `retryBudget` | 自动重试预算；高风险动作不得自动重试 |

兼容旧调用：

- 现有 `deviceIds + prompt/template/action` 请求继续接受。
- 服务端在入口处将旧请求规范化为每台设备一条 `deviceAssignment`。
- 内部调度、存储和事件只使用 v2 规范化模型，避免维护两套执行器。

## 4. 下发响应

```json
{
  "schema": "loom.matrix.campaign.v2",
  "campaignId": "cmp_20260715_001",
  "status": "queued",
  "concurrency": 8,
  "counts": {
    "total": 2,
    "queued": 2,
    "running": 0,
    "completed": 0,
    "failed": 0,
    "needsHuman": 0
  },
  "deviceTasks": [
    {
      "assignmentId": "asg_candidate_001",
      "deviceTaskId": "dt_001",
      "deviceId": "LUMI-P01",
      "jobId": null,
      "status": "queued",
      "attempt": 0
    }
  ]
}
```

允许的设备任务状态：

```text
queued -> preflight -> running -> completed
                            |-> failed
                            |-> needs_human
                            |-> paused -> running
                            |-> cancelled
failed -> retrying -> preflight
```

Campaign 聚合状态：`queued | running | partial | completed | failed | paused | cancelled`。

## 5. 幂等与重试

调度幂等键：

```text
campaignId + taskFingerprint + deviceId
```

其中 `taskFingerprint` 由规范化后的模板、prompt、input、mode 和 profile 计算，不包含密钥、token 或不稳定时间字段。

规则：

- 重复下发返回原 `deviceTaskId` 和当前状态，不创建第二个 Phone Agent 作业。
- `retry(deviceTaskId)` 只创建该设备任务的新 attempt，并保留历史 attempt。
- 定向重试默认从失败检查点继续；无安全检查点时重新执行该设备 assignment。
- 已完成设备不因其他设备重试而重放。
- `outbound` 和 `critical` 动作失败后进入 `needs_human`，不得自动重试。

## 6. 有界并发执行器

- 路由只负责校验、规范化和入队，不逐台阻塞等待手机完成。
- 调度器使用固定上限的 worker pool 或 semaphore。
- worker 获取槽位后先执行设备 preflight，再提交 Phone Agent 异步作业并保存 `jobId`。
- 单设备队列和设备写租约共同保证一台手机不会被两个任务同时写入。
- 一个设备任务异常不得取消健康设备；只有显式 campaign cancel 才传播到全部目标。
- 服务重启后从持久化状态恢复 `queued/running/retrying` 任务，并通过 Phone Agent job status 对账。

## 7. 每设备事件

沿用 `loom.realtime.event.v1` 信封，新增或冻结以下 Matrix 类型：

```text
matrix.campaign.queued
matrix.campaign.started
matrix.assignment.queued
matrix.assignment.preflight
matrix.assignment.started
matrix.assignment.progress
matrix.assignment.completed
matrix.assignment.failed
matrix.assignment.needs_human
matrix.assignment.retrying
matrix.assignment.paused
matrix.assignment.resumed
matrix.assignment.cancelled
matrix.campaign.completed
```

每条 assignment 事件的 `data` 至少包含：

```json
{
  "campaignId": "cmp_...",
  "assignmentId": "asg_...",
  "deviceTaskId": "dt_...",
  "deviceId": "LUMI-P01",
  "jobId": "job_...",
  "attempt": 1,
  "status": "running"
}
```

前端只能依据 `deviceTaskId` 或 `assignmentId + deviceId` 更新对应手机卡，不能用 campaign 的最后一条事件覆盖全部设备。

## 8. UI 必须呈现的真实状态

- 任务编辑器支持“统一任务”和“逐设备任务”两种模式。
- 逐设备模式可导入或编辑 `deviceAssignments`，并在下发前显示目标设备数、并发上限和审批影响范围。
- 每张手机卡显示自己的 `assignmentId` 摘要、`jobId`、attempt、进度和最近事件。
- 批次总览显示聚合计数，不把部分失败显示成整体失败。
- 失败卡提供“仅重试此设备”；批次操作提供“重试全部失败设备”。
- 一台设备进入 `needs_human` 时，健康设备继续运行。

## 9. 首批验收

1. 3 台模拟设备收到 3 个不同 prompt，执行记录和结果不串台。
2. `concurrency=2` 时同时最多运行 2 台，第三台保持 queued。
3. 一台设备失败不影响另外两台完成，campaign 最终为 `partial`。
4. 定向重试只增加失败设备的 attempt，完成设备的 `jobId` 不变化。
5. 重复提交相同 campaign 不产生重复 Phone Agent job。
6. 同一设备同时收到两个批次时，写动作按设备队列串行。
7. 外发任务没有审批时进入 `needs_human`，不自动执行或重试。
8. SSE 断线后使用 `afterSeq` 补发，前端不会重复累计进度。

## 10. 实施顺序修订

原规格阶段 0 增加：

- 冻结 `loom.matrix.dispatch.v2`、`loom.matrix.campaign.v2` 和 assignment 事件字段。
- 增加 Python 合同模型、TypeScript 类型、规范化函数和共享测试夹具。

原规格阶段 1 增加：

- 把路由中的逐设备等待迁移到有界并发调度服务。
- 保存 per-device `assignmentId/deviceTaskId/jobId/attempt`。
- 增加定向重试、设备级取消、重启对账和部分失败聚合。

只有这两项完成后，矩阵前端和中枢智能体才能依赖真实的并发状态开发。
