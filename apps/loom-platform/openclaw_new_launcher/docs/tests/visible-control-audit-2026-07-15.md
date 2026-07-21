# Visible control audit - 2026-07-15

## Scope

This release audit covers the global application shell and the baseline visible controls on all 13 registered pages:

`dashboard`, `agents`, `creative`, `acquisition`, `phone`, `workbench`, `license`, `agentAccess`, `capabilities`, `settings`, `models`, `diagnostics`, and `terminal`.

The audit classifies every baseline visible control as one of:

- an enabled action with an observable result;
- an intentionally unavailable action with a truthful visible explanation;
- a read-only surface with no actionable control.

The browser suite also exercises release-critical conditional states for installation detection failure, media output without a local path, logged-out web registration opener failure, model rollback confirmation, repair confirmation, and Matrix emergency stop.

## Findings fixed

1. Matrix `急停` was a permanently disabled button. It now confirms the current campaign, selected-device, or global scope; calls the authenticated control-plane endpoint; cancels campaigns atomically; locks publishing while stopping; reports authoritative counts; refreshes state; and handles repeated requests safely.
2. Model shutdown rolled back configuration immediately and described the outcome ambiguously. It now requires a danger confirmation and states that the managed configuration was removed.
3. Creative results rendered a copy-path action even when the backend returned no local path. The action now renders only for a real path; otherwise the result states `未返回本地路径`.
4. Web registration opener failure was silent. The account page now reports shell and browser fallback failure visibly.
5. Agent detection failure could continue into installation. Detection errors now stop the preparation flow before any install request.

The logged-out account branch also carries the same page readiness marker as the logged-in branch, so automated diagnostics identify both states consistently.

## Matrix emergency-stop contract

- Request accepts exactly one non-empty scope: `all`, `campaignId`, `deviceIds`, or `deviceTaskIds`.
- Authentication is checked before body-driven mutation.
- Device and device-task scopes expand to the containing campaign, preventing a partial campaign from continuing after an emergency stop.
- Only queued or running child tasks become cancelled; terminal children remain unchanged.
- All live job records from a matched campaign receive cancellation intent, including jobs that appear after task state is already terminal.
- Response order and counts are deterministic. Repeated requests are state-idempotent but still cancel matching live jobs.

## Isolation boundary

Playwright starts the current Vite working tree on an exclusive strict port and never reuses an existing development server. Only that local origin is allowed.

Tauri IPC, backend proxy routes, clipboard, shell-open, window controls, update installation, component installation, payment links, Feishu writes, publishing, and phone operations are exact in-page mocks. Unknown native commands, unknown backend paths, console errors, page errors, or external network requests fail the test. No real phone, account, payment provider, installer, filesystem mutation, or external service is touched by the browser audit.

## Verification evidence

Executed from `openclaw_new_launcher` on 2026-07-15:

| Gate | Result |
| --- | --- |
| `python -m pytest -q python/tests` | 819 passed, 1 existing collection warning |
| `node --test scripts/openclaw-phone-agent-fast-path.test.mjs scripts/openclaw-phone-daemon.test.mjs` | 39 passed |
| `npm run test:platform-contracts` | 31 passed |
| `npm run build` | production build completed |
| `npm run test:e2e -- --reporter=line` | 156 passed across Edge 960x640, 1200x800, and 1440x900 |

An independent code review reproduced two cancellation defects in the first implementation. Both received permanent regressions, and the follow-up review reported no remaining Critical or Important findings.

## Remaining boundary

This is a release-control audit, not a claim that every hidden permutation of every backend is executable without its real environment. Conditional states listed in `playwright-audit-harness.md` remain outside the stable gate until they become release-critical. Real-device acceptance must separately verify APKClaw connectivity, device permissions, platform account state, and external service credentials.
