# APKClaw / LOOM Fast Path 压测更新 - 2026-07-02

## 结论

本轮压测对象是 LOOM CLI 调用 APKClaw 手机端的快路径链路：

- `observe_fast`：读屏/页面摘要，不走 LLM。
- `action_fast`：打开设置、Home、Back 等固定动作，不走 Agent Loop。
- `screenshot`：快速截图。
- 中文自然语言固定任务：例如“打开系统设置”自动命中 `action_fast`。

核心结论：

- 快路径固定任务已经从优化前的 Agent 多轮调用约 `17.073s / 3 rounds`，降到常规 `0 rounds`。
- 手机端执行耗时多数在 `3ms - 252ms` 区间；LOOM/Codex 侧 wall time 主要消耗在 Node 进程启动、签名、HTTP、JSON 解析和并发调度。
- `observe_fast`、截图、单类动作并发稳定；混合并发同时执行 `open-settings/home/back/read-screen` 时会产生真实屏幕状态竞态，应由中枢按设备串行动作、并行读屏来调度。

## 环境

- 日期：2026-07-02 23:39-23:45，Asia/Shanghai。
- 设备：Android 模拟器，通过本机 HTTP 转发访问 APKClaw。
- LOOM 入口：`scripts/openclaw-phone-agent.mjs`
- APKClaw 版本：已安装 `6.38-stability` 正式版构建。
- 统计口径：
  - `wallMs`：LOOM/Codex 侧真实等待时间。
  - `deviceTotalMs`：APKClaw 返回的手机端执行耗时 `metrics.totalMs`。
  - 所有核心快路径期望 `rounds=0`。

## 干净压测结果

| 套件 | 并发 | 次数 | 成功 | mode | wall P50 / P95 | device P50 / P95 | rounds |
| --- | ---: | ---: | ---: | --- | ---: | ---: | ---: |
| `observe-fast-100-c16` | 16 | 100 | 100 | `observe_fast` | 569ms / 918ms | 4ms / 8ms | 0 |
| `screenshot-30-c6` | 6 | 30 | 30 | `screenshot` | 669ms / 850ms | 419ms / 673ms | 0 |
| `natural-cn-open-settings-30-c10` | 10 | 30 | 30 | `action_fast` | 626ms / 1705ms | 32ms / 1311ms | 0 |
| `open-settings-only-60-c16` | 16 | 60 | 60 | `action_fast` | 1073ms / 2038ms | 9ms / 22ms | 0 |
| `home-only-60-c16` | 16 | 60 | 60 | `action_fast` | 703ms / 1416ms | 23ms / 72ms | 0 |
| `back-only-60-c16` | 16 | 60 | 60 | `action_fast` | 663ms / 1142ms | 11ms / 40ms | 0 |

补充烟测：

- 三路并发：`open-settings + read-screen + screenshot` 全部成功。
- 结果：
  - `open-settings`：wall `259ms`，device `7ms`，`action_fast`。
  - `read-screen`：wall `249ms`，device `3ms`，`observe_fast`。
  - `screenshot`：wall `368ms`，device `206ms`，`screenshot`。

## 混合压测观察

混合压测 `mixed-fast-path-100-c12` 同时发起 `open-settings/read-screen/home/back`：

- 总数：100
- 成功：96
- 失败：4
- 失败原因：`read-screen` 返回 `System dialog blocked the screen`

这不是 LLM 或 Lumi 签名问题，而是同一台手机被多种改屏幕动作并发抢占时出现的真实屏幕状态竞态。建议中枢调度规则：

- 同一设备的写动作串行：`action_fast`、Agent 任务、模板动作。
- 读动作可并行或限流：`observe_fast`、截图。
- 如果读屏遇到系统弹窗，先上报异常状态，不自动越权点击隐私/授权/支付类弹窗。

## 已验证修复点

- 固定任务优先快路径，不再默认进 Agent Loop。
- `read-screen/observe` 不要求模型配置。
- 中文自然语言“打开系统设置”可自动命中 `action_fast`。
- Lumi launcherId 在无显式配置时按 `phoneUrl + token hash` 生成稳定匿名 ID，并发 CLI 不再互相顶掉签名。
- 快路径结果包含 `metrics.totalMs`、`metrics.rounds`、`mode`，方便中枢展示进度和耗时。

## 当前瓶颈

1. 手机端核心执行已经很快，主要剩余开销在 LOOM/Codex 每次启动 Node CLI 进程。
2. 截图耗时主要在设备截图和 base64 传输。
3. 同一台手机的动作并发会互相改变屏幕状态，不适合无限并行。

## 下一步建议

1. 给 LOOM 增加常驻 phone-agent daemon / 长连接通道，复用 Node 进程、Lumi pairing、HTTP keep-alive。
2. 中枢按设备维护动作队列：写动作单通道，读屏/截图限流并发。
3. 截图接口增加元数据模式或缩略图模式，任务进度只回传摘要，必要时再取完整图片。
4. 对 `System dialog blocked the screen` 增加结构化异常码，让 Codex 能直接判断是弹窗、无障碍、前台丢失还是权限问题。

## Daemon Pressure Update

- Date: 2026-07-03 Asia/Shanghai
- APKClaw version: LOOM launcher package `2.1.42`; real phone endpoint at `http://127.0.0.1:19527`
- LOOM commit/worktree: `d55e94bbd792bf3dd5ce07812281bc7199c78a73` on `codex/xinflo-style-super-installer`
- Daemon mode: reused existing daemon runtime (`pid 2636`, `port 11151`), all validation commands used `--daemon require`
- Results table:

| Suite | Shape | Success | Wall P50 / P95 | Device P50 / P95 | Mode / rounds | Target notes |
| --- | --- | ---: | ---: | ---: | --- | --- |
| `observe_fast` | 100 calls, concurrency 16 | 100/100 | 583ms / 904ms | 5ms / 10ms | `observe_fast`, rounds `0` | device target met; wall target missed (`>250ms`) |
| `screenshot` | 30 calls, concurrency 6 | 30/30 | 661ms / 830ms | 175ms / 261ms | `screenshot`, rounds `0` | P50 targets met |
| `open-settings` | 60 calls, concurrency 16 | 60/60 | 1714ms / 2002ms | 9ms / 41ms | `action_fast`, rounds `0` | device target met; wall target missed (`>500ms`) |
| `mixed open-settings/home/back/read-screen` | 100 calls, concurrency 12 | 39/100 | 315ms / 3721ms on successful calls | 13ms / 504ms on successful calls | `action_fast` + `observe_fast`, rounds `0` | failed acceptance: repeated `Invalid Lumi signature` errors |

- Failures:
  - Direct daemon-required smoke for natural-language `open-settings` passed once and returned `action_fast` with rounds `0`.
  - `read-screen` smoke passed with `observe_fast` and rounds `0`.
  - `screenshot` smoke passed and returned an image payload (summarized only; no base64 logged here).
  - First scripted pressure attempt using a Chinese prompt inside an inline Node harness degraded to async task submission because the prompt was mojibaked to `??????`; that attempt was discarded and not used as final evidence.
  - Final mixed pressure run still produced repeated CLI stderr `ERROR: Invalid Lumi signature` on action calls, so the "no Lumi signature failures" acceptance target is not met.
- Remaining bottleneck:
  - Device-side fast path work stays low-latency, but launcher-side wall time remains far above target for `observe_fast` and `open-settings` under pressure.
  - Mixed concurrent action/read pressure still exposes Lumi signature instability before queueing or device execution completes.

### Post-fix rerun: Lumi signature repair

- Date: 2026-07-03 Asia/Shanghai
- Daemon mode: restarted daemon with updated `openclaw-phone-secure.mjs`, validation used `--daemon require`
- Fix verified:
  - same-device pairing repair is now single-flight per `phoneUrl + token`
  - HTTP auth failures and JSON payload failures such as `success:false` / `Invalid Lumi signature` both retry through the same repair path
  - retry remains bounded to one repair attempt per request
- Results table:

| Suite | Shape | Success | Wall P50 / P95 | Device P50 / P95 | Mode / rounds | Target notes |
| --- | --- | ---: | ---: | ---: | --- | --- |
| `mixed open-settings/home/back/read-screen` | 100 calls, concurrency 12 | 99/100 | 3568ms / 4182ms on successful calls | 97ms / 522ms on successful calls | `action_fast` + `observe_fast`, rounds `0` | no `Invalid Lumi signature` failures; one real screen-blocking system dialog |

- Failures:
  - `Invalid Lumi signature`: `0`
  - `System dialog blocked the screen`: `1`
- Remaining bottleneck:
  - mixed same-device action/read pressure is now signature-stable, but wall time is still high because the harness launches one CLI process per call and the daemon correctly serializes write actions for a single phone.
  - the remaining failure is a real device-screen state issue, not a Lumi signing failure.

### Post-fix rerun: daemon direct action endpoint

- Date: 2026-07-03 Asia/Shanghai
- APKClaw version: live local APKClaw at `http://127.0.0.1:19527`
- Daemon mode: restarted local daemon and exercised `/v1/run` directly with daemon token; phone token redacted
- Fix verified:
  - `action_fast` now uses `/api/lumi/agent/action_fast?_lumi=1`, matching the APKClaw Lumi compatibility path
  - `observe_fast -> action_fast` no longer triggers `Invalid Lumi signature`
  - mixed read/action pressure remains on fast paths and no longer falls through to async Agent tasks
- Results table:

| Suite | Shape | Success | Wall P50 / P95 | Device P50 / P95 | Mode / rounds | Target notes |
| --- | --- | ---: | ---: | ---: | --- | --- |
| `observe_fast_direct_daemon` | 100 calls, concurrency 16 | 100/100 | 410ms / 432ms | 4ms / 8ms | `observe_fast`, rounds `0` | device target met; wall target still above `250ms` |
| `screenshot_direct_daemon` | 30 calls, concurrency 6 | 30/30 | 621ms / 651ms | 154ms / 175ms | `screenshot`, rounds `0` | P50 targets met |
| `open_settings_direct_daemon` | 60 calls, concurrency 16 | 60/60 | 1688ms / 1852ms | 9ms / 12ms | `action_fast`, rounds `0` | device target met; wall target limited by same-device write serialization |
| `mixed_direct_daemon` | 100 calls, concurrency 12 | 100/100 | 4761ms / 5067ms | 12ms / 490ms | `action_fast` + `observe_fast`, rounds `0` | no Lumi signature failures; fast path preserved |

- Failures:
  - `Invalid Lumi signature`: `0`
  - async Agent fallback: `0`
  - failed calls: `0`
- Remaining bottleneck:
  - Direct daemon pressure removed CLI process startup as the dominant cost for read/screenshot flows.
  - Single-phone write-heavy pressure still queues by design because same-device write actions must remain serialized.
  - Mixed wall P50 therefore measures queue wait under contention more than device execution time; device execution stays in the fast-path budget.

### Post-fix rerun: ready cache and idempotent action coalescing

- Date: 2026-07-03 Asia/Shanghai
- APKClaw version: live local APKClaw at `http://127.0.0.1:19527`
- Daemon mode: restarted local daemon with captured startup banner `{"ok":true,"type":"phone_daemon_started","port":9352,"pid":55268}`
- Fix verified:
  - fast-path readiness is cached inside the per-device daemon session for a short TTL instead of probing `/api/device/status` before every action
  - concurrent identical idempotent actions (`open_app:<package>`, `home`) share one serialized write result
  - non-idempotent actions such as `back` remain serialized
  - `/api/lumi/*`, `X-LUMI-*`, `lumiLauncherId`, and `lumiLauncherSecret` semantics remain unchanged
- Direct daemon results table:

| Suite | Shape | Success | Wall P50 / P95 | Device P50 / P95 | Mode / rounds | Target notes |
| --- | --- | ---: | ---: | ---: | --- | --- |
| `observe_fast_direct_daemon_cached_coalesced` | 100 calls, concurrency 16 | 100/100 | 209ms / 227ms | 4ms / 8ms | `observe_fast`, rounds `0` | targets met |
| `screenshot_direct_daemon_cached_coalesced` | 30 calls, concurrency 6 | 30/30 | 532ms / 625ms | 178ms / 238ms | `screenshot`, rounds `0` | targets met |
| `open_settings_direct_daemon_cached_coalesced` | 60 calls, concurrency 16 | 60/60 | 50ms / 56ms | 8ms / 9ms | `action_fast`, rounds `0` | targets met |
| `mixed_direct_daemon_cached_coalesced` | 100 calls, concurrency 12 | 100/100 | 573ms / 1403ms | 12ms / 774ms | `action_fast` + `observe_fast`, rounds `0` | P50 target met; no Lumi signature failures |

- CLI daemon-required evidence:

| Suite | Shape | Success | Wall P50 / P95 | Device P50 / P95 | Target notes |
| --- | --- | ---: | ---: | ---: | --- |
| `observe_fast_cli_daemon_cached_coalesced` | 100 calls, concurrency 16 | 100/100 | 712ms / 1060ms | 4ms / 42ms | includes one Node CLI process startup per call |
| `screenshot_cli_daemon_cached_coalesced` | 30 calls, concurrency 6 | 30/30 | 574ms / 787ms | 191ms / 252ms | fast path preserved |
| `open_settings_cli_daemon_cached_coalesced` | 60 calls, concurrency 16 | 60/60 | 469ms / 969ms | 13ms / 20ms | P50 target met even through CLI |
| `mixed_cli_daemon_cached_coalesced` | 100 calls, concurrency 12 | 99/100 | 1090ms / 1849ms | 75ms / 926ms | one real system dialog block; `Invalid Lumi signature`: `0` |

- Failures:
  - Direct daemon: none
  - CLI daemon-required: one real `System dialog blocked the screen` during mixed pressure; no Lumi signature failures
- Remaining bottleneck:
  - Direct daemon service latency now satisfies the written Task 9 P50 targets.
  - CLI-per-call pressure is still bounded by Windows Node process startup and should not be used as the daemon service-latency benchmark.

## Rollback

The old direct path remains available and does not require reverting APKClaw:

```powershell
node scripts\openclaw-phone-agent.mjs run --daemon off --prompt "open settings" --json
```

To disable daemon use for a shell session:

```powershell
$env:OPENCLAW_PHONE_DAEMON = "off"
```

If the daemon runtime points to a stale process, remove only the runtime file:

```powershell
Remove-Item -LiteralPath D:\Axiangmu\AUSTART\openclaw_new_launcher\data\.openclaw\runtime\phone-daemon.json -Force
```
