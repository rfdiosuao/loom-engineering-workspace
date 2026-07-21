# APKClaw + LOOM Real Douyin Agent Test - 2026-07-03

## Scope

This report records the first real app/business-path test after installing Douyin into the Android emulator. It does not claim account warm-up is fully validated. The tested safe boundary was:

- Install Douyin from a verified official Douyin short-link APK source.
- Use LOOM to submit APKClaw Agent tasks.
- Allow only low-risk app opening, observation, screenshots, and waits.
- Do not log in, register, grant account authorization, like, follow, comment, message, publish, pay, delete, or export private data.

## Environment

- Test time: 2026-07-03 17:56-18:01 CST
- LOOM path: `D:\Axiangmu\AUSTART\openclaw_new_launcher`
- LOOM launcher root used for model config: `D:\Axiangmu\AUSTART\artifacts\nsis-designed-full\LOOM`
- APKClaw package: `com.apk.claw.android`
- APKClaw version: `6.38-stability`, versionCode `907`
- Device: `emulator-5554`, AVD `APKClaw_API36`
- Android: 16, SDK 36
- Phone URL: `http://127.0.0.1:9527`
- APKClaw runtime model during successful Agent tests: `claude-fable-5`
- LOOM account/wire phone model still reports: `agnes-2.0-flash`, but real gateway probe returns `model_not_found`

## Douyin Install

Source discovery:

```powershell
Invoke-WebRequest https://z.douyin.com/p53t
```

Resolved official APK link found in page:

```text
https://lf9-apk.ugapk.cn/package/apk/aweme/5072_390401/aweme_43633312a_v5072_390401_11df_1782898275.apk?v=1782898294
```

Downloaded artifact:

```text
D:\Axiangmu\AUSTART\openclaw_new_launcher\data\phone-test-artifacts\douyin-install\douyin-official-zdouyin-p53t.apk
```

APK evidence:

- Size: `349577046` bytes
- SHA256: `59857D8B77285A0B3D0179478E6F7DEE9B21A6019DD69E589946B3D6B3A74955`
- Package: `com.ss.android.ugc.aweme`
- Version: `39.4.0`, versionCode `390401`
- Label: `抖音`
- Min SDK: `23`
- Target SDK: `34`
- Signer DN: `CN=Aweme Douyin, OU=ByteDance, O=ByteDance, L=Beijing, ST=Beijing, C=CN`
- Signer SHA-256: `5182ae3b1b85337bb182cf24882449f84447ded18e296a747a9f6a0a2622512e`

Install command:

```powershell
adb -s emulator-5554 install -r D:\Axiangmu\AUSTART\openclaw_new_launcher\data\phone-test-artifacts\douyin-install\douyin-official-zdouyin-p53t.apk
```

Result:

```text
Performing Streamed Install
Success
```

Installed package confirmation:

```text
com.ss.android.ugc.aweme/.splash.SplashActivity
versionName=39.4.0
versionCode=390401
```

## Real Agent Task

Command entry:

```powershell
node .\scripts\openclaw-phone-agent.mjs run --daemon off --phone-url http://127.0.0.1:9527 --phone-token <redacted> --execution-layer agent --mode safe --max-rounds 12 --step-timeout-sec 15 --timeout-sec 210 --max-wait-sec 220 --json --prompt "<real Douyin safe observation prompt>"
```

Task:

- Task ID: `0e12fc0e-e9dc-46f8-90d1-8ef54c735ec2`
- Result status: `success`
- Mode: `agent`
- Rounds: `4`
- Total: `53208ms`
- LLM round time: `42622ms`
- Tool call time: `10488ms`
- Tokens: `24449`

Observed Agent actions:

1. Called `open_app` for `com.ss.android.ugc.aweme`.
2. Confirmed foreground package `com.ss.android.ugc.aweme`.
3. Called `get_screen_info`.
4. Observed `个人信息保护指引` text through accessibility.
5. Called `take_screenshot`.
6. Stopped without clicking login/allow/agree.

Agent reported:

- It identified a privacy consent screen and stopped.
- It did not click consent, login, permission, like, follow, comment, message, publish, pay, delete, or export private data.

However, the captured screenshot showed a later/changed state:

```text
D:\Axiangmu\AUSTART\openclaw_new_launcher\data\phone-test-artifacts\douyin-install\douyin-privacy-guide-agent-screenshot.png
```

That screenshot displayed Android notification permission UI over Douyin:

```text
Allow 抖音 to send you notifications?
Allow / Don’t allow
```

Fresh vision capture after the task:

```text
D:\Axiangmu\AUSTART\openclaw_new_launcher\data\phone-test-artifacts\douyin-install\douyin-current-after-agent.png
D:\Axiangmu\AUSTART\openclaw_new_launcher\data\phone-test-artifacts\douyin-install\douyin-after-system-dialog-blocked.png
```

The visible screen then showed Douyin 首页 / 推荐 loading state, but APKClaw vision metadata still reported:

```json
{
  "packageName": "com.android.systemui",
  "nodeCount": 0,
  "vision": {
    "recommended": true,
    "reason": "no_accessibility_nodes"
  }
}
```

## Follow-Up Agent Task

Command entry:

```powershell
node .\scripts\openclaw-phone-agent.mjs run --daemon off --phone-url http://127.0.0.1:9527 --phone-token <redacted> --execution-layer agent --mode safe --max-rounds 8 --step-timeout-sec 15 --timeout-sec 150 --max-wait-sec 160 --json --prompt "<continue Douyin read-only observation prompt>"
```

Task:

- Task ID: `fd7d53f9-c222-496f-a640-dfa8544d12d0`
- Result status: `error`
- Error: `System dialog blocked the screen`
- Mode: `agent`
- Rounds: `1`
- Total: `17392ms`
- Last tool: `get_screen_info`
- Tool result message: `__SYSTEM_DIALOG_BLOCKED__`

This is reproducible while the visible screenshot looks like Douyin loading/home, but APKClaw reports `com.android.systemui` and `nodeCount=0`.

## Supporting Core Evidence

SSE events:

- `/api/lumi/events` produced `hello` and `snapshot`.
- Snapshots included APKClaw status, metrics, queue state, and recent Agent tasks.

Concurrency:

- 5 concurrent read-screen calls: `5/5` success, P50 `189ms`, P95 `196ms`, all marked `stalePossible=true`.
- 3 concurrent write actions (`home`, `open-settings`, `back`): `3/3` success, serialized timing pattern from `340ms` to `7464ms`.
- Mixed `1 write + 3 reads`: `4/4` success. One read observed the launcher while the write transition was underway; later reads observed Settings. This is expected state race and must be avoided by central scheduling.

Model probe:

- `wire verify` reported phone target `ok=true`.
- Real gateway probe:
  - `claude-fable-5`: HTTP 200
  - `agnes-2.0-flash`: HTTP 503 `model_not_found`
  - `qwen3.7-plus`: HTTP 503 `model_not_found`

## Issues

### P0 - LOOM phone model is reported OK but unusable

Repro:

1. Run `python .\python\loom_cli.py wire verify --json`.
2. Observe phone target `ok=true` and phone model `agnes-2.0-flash`.
3. Send a minimal OpenAI-compatible chat completion request to the same base URL and token with model `agnes-2.0-flash`.

Actual:

- Gateway returns HTTP 503 `model_not_found`.
- APKClaw Agent cannot run with the configured phone model.

Expected:

- `wire verify` should include a real phone model completion probe, or mark phone model unavailable.

Suggested fix area:

- LOOM account/wire verification and phone model config generation.

### P1 - APKClaw Agent final report can be stale compared with screenshot/current screen

Repro:

1. Install and launch Douyin first run.
2. Submit safe Agent task to open Douyin and stop on privacy/permission/login screens.
3. Compare Agent text report with screenshot artifact.

Actual:

- Agent report says privacy guide.
- Screenshot shows Android notification permission prompt.
- Later screenshot shows Douyin homepage/loading state.

Expected:

- Final Agent report should include last verified frame/screen state, or explicitly say a transition occurred after the last accessibility observation.

Suggested fix area:

- `AgentApiController.kt`
- `PhoneAgentReportBuilder.kt`
- Agent loop finalization in APKClaw runtime.

### P1 - System dialog blocked false positive / no vision fallback

Repro:

1. With Douyin foreground/loading screen visible, submit a read-only Agent observation.
2. Let Agent call `get_screen_info`.

Actual:

- Tool returns `__SYSTEM_DIALOG_BLOCKED__`.
- Agent stops with `System dialog blocked the screen`.
- Vision frame can still capture the screen and recommends vision mode, but Agent does not fallback to screenshot/vision reasoning.

Expected:

- If `get_screen_info` reports system dialog but screenshot shows app content, Agent should capture frame and classify whether it is a real blocking dialog.
- If `nodeCount=0`, Agent should use vision fallback instead of terminating blindly.

Suggested fix area:

- APKClaw screen-info/system-dialog classifier.
- Agent tool error recovery path.
- Vision fallback handling.

### P1 - Douyin/WebView style screens expose zero accessibility nodes

Repro:

1. Open Douyin current homepage/loading state.
2. Run `observe_fast` or vision status.

Actual:

- `nodeCount=0`
- `visibleNodeCount=0`
- `vision.reason=no_accessibility_nodes`

Expected:

- APKClaw should support a vision-first path for apps whose UI is not available through accessibility.

Suggested fix area:

- `observe_fast`
- Vision frame and Agent planning integration.

### P2 - Agent completion marked success for a blocked business path

Repro:

1. Submit real Douyin task with safe policy.
2. Agent stops at privacy/permission boundary.

Actual:

- Task status can be `success`, because the Agent obeyed safety.
- For business testing, this can be misread as "business path passed".

Expected:

- Report should distinguish `safety_stop`, `business_blocked`, and `business_completed`.

Suggested fix area:

- `PhoneAgentReportBuilder.kt`
- Agent task result schema.

### P2 - PowerShell Start-Job can corrupt CLI JSON with Chinese text

Repro:

1. Run multiple `openclaw-phone-agent.mjs` calls under PowerShell `Start-Job`.
2. Pipe job stdout through `ConvertFrom-Json`.

Actual:

- Chinese strings can become mojibake and break JSON parse.

Expected:

- Documentation should recommend Node orchestration or enforce UTF-8 job output for PowerShell concurrency tests.

Suggested fix area:

- `docs/PHONE_POWERSHELL_CLI.md`

## Not Bugs But Scheduler Must Avoid

- Read actions are intentionally concurrent and can observe intermediate screen states while a write action is transitioning.
- Same-device write actions are serialized by LOOM, but reads can still see pre/post transition states. The central scheduler should not make business decisions from stale read results during writes unless it re-observes after the write completes.
- App first-run privacy and permission prompts require user/central policy decisions. The phone Agent should not click them by default.

## Next Fix Priority

1. Fix LOOM `wire verify` and phone model availability: do a real phone model completion probe before declaring phone target OK.
2. Add APKClaw Agent vision fallback for `nodeCount=0` and system-dialog-blocked cases.
3. Add result states such as `safety_stop` and `business_blocked` so safe stops do not look like business success.
4. Improve final report freshness: include last screenshot timestamp, observed package, and whether state changed after the last text tree.
5. Add a Douyin first-run smoke scenario to regression tests: install app, open app, stop at privacy/permission boundary, verify no sensitive click occurred.
