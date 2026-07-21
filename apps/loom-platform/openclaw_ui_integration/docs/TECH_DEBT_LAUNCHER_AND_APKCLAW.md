# 启动器与 APKClaw 技术债台账

> 更新时间：2026-05-24
> 作用：只保留当前仍需推进的高优先级债务。
> 执行清单以 `docs/task.md` 为准，交付校验以 `docs/RELEASE_CHECKLIST.md` 为准。

## 已确认的当前状态

- 启动器主线已收敛到 Tauri + React + Python Bridge。
- 手机 Agent 的硬约束已落到 `launcher-cli-wrapper`，不再直连手机端点。
- 离线包校验已具备：
  - `verify-release.ps1`
  - `verify-portable-smoke.ps1`
  - `build-portable.ps1` 接入 smoke 验收
- 云端会员网关已支持：
  - 通用 API Key
  - 生图专用 API Key
  - 视频专用 API Key

## 仍然要还的高优先级债

### 1. 交付与发布

- 统一 Release 附件：portable zip、sha256、安装器/发行包的产物口径。
- 跑一次完整 GitHub tag release，确认 Actions 产物和中文 Release notes。
- 版本号、包名、APK 版本、校验脚本的自动一致性检查。

### 2. 启动稳定性

- 500 元级一体机的真实冷启动计时与边界验证。当前已补齐 `npm run measure:cold-start -- --root <portable-root> --budget-ms 30000`，并输出机器画像、预算判定和启动快照；还缺低配机上的真实跑测证据。
- 启动失败后，给出更明确的可恢复提示，而不是只报“启动失败”。
- 继续减少首屏阻塞，把非关键检查保留在诊断页。

### 3. APKClaw 稳定性

- 崩溃日志导出。
- worker 异常兜底，避免 HTTP 服务一起挂掉。
- 长任务超过上限时返回部分结果和 follow-up 建议。
- 固化几个可重复 demo 场景。

### 4. 文档与说明

- 清理乱码历史文档，保留真正有用的手册。
- 补客户交付说明和 APKClaw 安装说明。
- 把 release / smoke / 手工验收流程写成固定动作。

## 建议的推进顺序

1. 先把 Release 与 smoke 的证据收口。
2. 再做低配机器启动稳定性。
3. 然后补 APKClaw 崩溃和长任务债。
4. 最后收口文档和发布自动化。

## 备注

- 这份文件不是执行清单。
- 具体任务、状态和验收点都以 `docs/task.md` 为准。
- 旧的长篇路线说明若与当前状态冲突，优先相信 `docs/task.md` 和真实验收结果。
