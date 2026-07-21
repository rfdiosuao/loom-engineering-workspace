# Playwright control audit harness

The E2E suite runs the Vite UI in installed Microsoft Edge. Tauri IPC, event streams, and backend proxy responses are replaced before application code loads. The fixture permits requests to the local Vite origin only; every other browser request is blocked and reported as a test failure.

## Run the suite

```powershell
$env:PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD = '1'
npm ci
npm run test:e2e
```

`playwright.config.ts` runs the suite in Edge at `960x640`, `1200x800`, and `1440x900`.

## Start a page test

Import the shared fixture and open the authorized development shell. Use `PAGE_REGISTRY` when a test should follow the same page keys and readiness selectors as the smoke audit.

```ts
import { expect, PAGE_REGISTRY, test } from './support/audit-fixture';

test('shows the local account snapshot', async ({ audit, page }) => {
  await audit.openAuthorizedShell();
  await audit.navigateTo(PAGE_REGISTRY.find(({ key }) => key === 'license')!);

  await expect(page.getByText('audit@example.invalid')).toBeVisible();
});
```

`navigateTo` imports the existing Zustand store through Vite and changes `currentPage`. This covers hidden registry pages without adding production test hooks.

## Register deterministic responses

Register a Tauri command by its exact command name:

```ts
await audit.registerCommand('get_portable_base_path', {
  value: 'C:\\LOOM\\future-page-test',
});
```

Register a proxied backend response by exact HTTP method and path, including its query string:

```ts
await audit.registerRoute('GET', '/api/jobs/list?limit=5', {
  value: { jobs: [] },
});
```

Registrations can be made before `openAuthorizedShell()` or later, before the UI action that needs them. Use `{ error: 'deterministic failure' }` to exercise an expected backend rejection.

There is deliberately no fallback response. An unknown invoke command or proxy route is recorded in `audit.unexpectedCommandFailures`, rejected in the page, and fails fixture teardown. Add only the command or route required by the test.

## Inspect the audit

Call `await audit.sync()` before asserting browser-side IPC history:

```ts
await audit.sync();
expect(audit.callLogs).toContainEqual({
  command: 'get_bridge_port',
  args: {},
});
expect(audit.consoleErrors).toEqual([]);
expect(audit.unexpectedCommandFailures).toEqual([]);
expect(audit.blockedNetworkRequests).toEqual([]);
```

Responses are JSON-cloned on every call, so tests cannot mutate shared fixture state. Side-effecting flows such as phone control, Feishu operations, payment, login, publishing, component installation, and uninstall are not registered in the baseline catalog. If a future UI test needs to render one of those states, register a local mock response for that single test; the browser still cannot reach an external service.

## Control-action release gate

The release gate is organized around grouped user workflows rather than one test per DOM node:

- `control-actions-shell-utility.spec.ts` covers native window controls, sidebar navigation, dashboard routes, Agent Access clipboard actions, settings, diagnostics, and terminal actions.
- `control-actions-workflows.spec.ts` covers creative media, acquisition and Feishu, phone control, and matrix workbench actions.
- `control-actions-account-runtime.spec.ts` covers agent installation, model configuration, account, subscription, payment-link, and logout actions.
- `control-audit.contract.spec.ts` locks the baseline visible-control count for the global shell and all 13 `PAGE_REGISTRY` pages. A count change must be accompanied by an action audit or an explicit unavailable-state classification.

The grouped workflows assert the result that proves the real UI handler ran: exact proxy method/path/body, exact Tauri invoke command, route transition, clipboard value, modal, toast, or rendered state. Role and label selectors are preferred; stable `data-*` hooks are used where the UI has no useful semantic name.

| Surface | Baseline action coverage |
| --- | --- |
| Global shell | Minimize, maximize/restore, close, all sidebar routes, account shortcut |
| Dashboard | Primary workbench route and all legacy route cards/rows |
| Agents | Refresh, prerequisite detection, clipboard, card selection, source modes, per-agent detection, guarded install intent, details |
| Creative | Image/video modes, config controls, test/save, generate, polling, refresh |
| Acquisition | Refresh, Feishu login/bind/write confirmations, clipboard, external link intent |
| Phone | Connection form, modes/profiles, quick tasks, clipboard, status/screenshot/model/history/read/task, refresh, delete |
| Workbench | Worker and policy selection, authorization, feed state, refresh, mocked publish intent |
| License | Account/subscription refresh, model route/sync, external payment links, logout |
| Agent Access | One-shot and advanced payload clipboard actions |
| Capabilities | Read-only unavailable surface; zero actionable controls |
| Settings | Appearance, update check/install confirmation, data routes, about surface |
| Models | Refresh, source modes, managed selection/save/sync, rollback confirmation, custom provider |
| Diagnostics | Copy, rerun, export/open paths, details, repair confirmation |
| Terminal | Scroll, export/open, cancel and confirm clear |

## Side-effect boundary

The browser may request only the configured local Vite origin. Every backend path is an exact in-page Tauri proxy mock; every unregistered command or route fails teardown. External anchors and `window.open` are captured as intent, while Tauri shell-open calls are replaced with a strict command mock. Phone operations, Feishu writes, publishing, update installation, component installation, payment links, logout, and repair actions therefore exercise production handlers without contacting a device, account service, payment provider, installer, or host filesystem.

## Unavailable and conditional controls

Baseline unavailable controls pass only when the UI explains the state:

- Agent one-click model configuration is disabled with `登录后解锁：请先同步托管模型`; its dependent model selector and write action remain unavailable in the not-installed fixture.
- Workbench publish is disabled without a phone and paired with `暂无手机。先到手机页保存并检测设备。`; the enabled publish path is covered with a seeded mock phone.
- Diagnostics repair is disabled as `无可修复项`; the enabled confirmation path is covered with an isolated repairable diagnostic.
- Agent prerequisite repair is disabled while the fixture visibly reports `前置环境已就绪`.

Workbench `急停` is disabled with an explicit explanation when no task is active. Its enabled path is covered with an isolated running campaign, dangerous-action confirmation, exact selected-device request body, success feedback, and refresh; no real phone process is stopped by the browser test.

Conditional controls outside the stable release gate are reported rather than expanded into brittle state permutations: installed/upgrade/start/uninstall and installer-log export states; agent model write/restart/failure recovery; logged-out email-code/password/register/legacy-license submission flows; offline cached-account states; media-result local-file open actions; per-job running/failed/cancel controls beyond Matrix emergency stop; and failure-only retry/recovery controls. Add one owned fixture and a grouped workflow when one of these states becomes release-critical.
