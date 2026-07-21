# License Admin Frontend Modularization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the 148 KB inline admin console with a resilient native ES-module control panel that implements the approved operations-first information architecture without changing the stable authorization APIs.

**Architecture:** Keep `/admin` as the only entry page and serve an intentionally small HTML shell plus allowlisted `/admin/assets/*` files from the existing Python service. Shared API, session, state, dialogs, formatting, and page-lifecycle modules own cross-cutting behavior; each business page owns its loading, ready, empty, and error states. The stable modular backend remains the final authorization and RBAC boundary.

**Tech Stack:** Python standard-library HTTP server, SQLite-backed stable API package, native HTML/CSS/ES2022 modules, Python `unittest`, browser `fetch`, and Playwright or Computer Use for visual verification. No Node build dependency or frontend framework.

## Global Constraints

- Preserve every existing public/admin URL, HTTP method, success status, stable error code, cookie behavior, and LOOM client payload.
- Keep `admin_console.html` as the `/admin` entry and `Secure; HttpOnly; SameSite=Strict` as the session boundary.
- Do not persist passwords, API keys, cookies, session tokens, complete authorization codes, invite codes, or reveal/export results in browser storage.
- Use only same-origin requests with `credentials: "same-origin"`; do not add CORS exceptions.
- Keep dangerous actions behind typed confirmation and server-side confirmation validation.
- All metrics must come from live API responses. An unavailable metric renders `Temporarily unavailable`, never a fabricated zero.
- A page failure must not blank the navigation, authentication shell, or another page.
- Super admins can access all modules. Merchant accounts see only owned authorization, gateway configuration, and required documentation; server RBAC remains authoritative.
- Keep frontend page modules below 500 lines and shared modules single-purpose.
- Do not add npm, Vite, React, Vue, a CDN runtime, Redis, or a second service.
- Production deployment must preserve `license.db`, `private_key.b64`, environment files, and tokens. Roll back program files only.

---

## Stable API Contract Used By Phase 2

The frontend consumes the deployed Phase 1 routes without adding backend business APIs:

```text
Authentication:
  GET  /admin/api/auth/status
  GET  /admin/api/me
  POST /admin/api/auth/login
  POST /admin/api/auth/register
  POST /admin/api/auth/bootstrap
  POST /admin/api/auth/logout

Overview and authorization:
  GET  /admin/api/codes
  GET  /admin/api/activations
  GET  /admin/api/accounts
  GET  /admin/api/plans
  GET  /admin/api/audit-logs
  POST /admin/api/codes
  POST /admin/api/codes/reveal
  POST /admin/api/codes/export
  POST /admin/api/codes/update
  POST /admin/api/codes/bulk-update
  POST /admin/api/codes/toggle
  POST /admin/api/codes/delete
  POST /admin/api/codes/clear
  POST /admin/api/activations/delete

Customers and sales:
  GET/POST /admin/api/accounts
  POST     /admin/api/accounts/toggle
  GET/POST /admin/api/invites
  POST     /admin/api/invites/toggle
  GET      /admin/api/plans
  POST     /admin/api/plans/update
  POST     /admin/api/plans/delete
  GET/POST /admin/api/account-gateway
  GET/POST /admin/api/public-settings

AI and operations:
  GET/POST /admin/api/beta/config
  GET/POST /admin/api/templates
  POST     /admin/api/templates/delete
  GET      /health
  GET      /api/client/config
```

All request wrappers must accept the current response envelope variants (`{ok,data}`, direct arrays, and stable error bodies) exactly as the existing console does.

## File Structure

```text
license_server/
  admin_console.html                 # minimal login/navigation/page host
  admin_assets/
    styles/
      tokens.css                     # colors, type, spacing, focus, status tokens
      shell.css                      # title bar, nav, page host, responsive layout
      components.css                 # tables, fields, dialogs, badges, empty/error states
      pages.css                      # page-specific grids; no nested card layout
    js/
      api.js                         # same-origin fetch, envelopes, session expiry
      state.js                       # in-memory non-secret state and subscriptions
      dialogs.js                     # confirm, typed danger, result, editor dialogs
      format.js                      # escaping, dates, statuses, masks, downloads
      app.js                         # boot, auth, navigation, role visibility, page lifecycle
      pages/
        overview.js                  # real operating metrics and recent activity
        issuance.js                  # quick issue form and one-time result handling
        licenses.js                  # codes, filters, reveal/export, activations
        customers.js                 # accounts, ownership, invites
        sales.js                     # plans, public purchase settings, gateway settings
        ai.js                        # beta configuration and prompt templates
        governance.js                # audit, diagnostics, documentation
  luming_license/http/
    routes_public.py                 # allowlisted admin asset response
    handler.py                       # secure `/admin/assets/` prefix dispatch
  tests/
    test_admin_console_contract.py
    test_admin_asset_contract.py
    test_admin_frontend_module_contract.py
    test_admin_frontend_security_contract.py
```

---

### Task 1: Freeze the Legacy Console and Asset Contract

**Files:**
- Modify: `license_server/tests/test_admin_console_contract.py`
- Create: `license_server/tests/test_admin_asset_contract.py`
- Create: `license_server/tests/test_admin_frontend_module_contract.py`

**Interfaces:**
- Consumes: `/admin` HTML behavior and the deployed Phase 1 route inventory.
- Produces: a failing contract for the shell, exact module list, and asset security behavior.

- [ ] **Step 1: Add a shell and module manifest test**

```python
EXPECTED_MODULES = {
    "api.js", "state.js", "dialogs.js", "format.js", "app.js",
    "pages/overview.js", "pages/issuance.js", "pages/licenses.js",
    "pages/customers.js", "pages/sales.js", "pages/ai.js",
    "pages/governance.js",
}

def test_admin_shell_loads_native_modules_without_inline_business_logic(self):
    source = Path(ADMIN_HTML).read_text(encoding="utf-8")
    self.assertIn('type="module" src="/admin/assets/js/app.js"', source)
    self.assertIn('id="adminPageHost"', source)
    self.assertNotIn("function renderCodes", source)
    self.assertNotIn("localStorage", source)
```

- [ ] **Step 2: Add an asset allowlist test**

```python
def test_admin_assets_reject_traversal_and_unknown_extensions(self):
    self.assertEqual(self.get("/admin/assets/../private_key.b64").status, 404)
    self.assertEqual(self.get("/admin/assets/js/app.js").status, 200)
    self.assertEqual(self.get("/admin/assets/styles/tokens.css").status, 200)
    self.assertEqual(self.get("/admin/assets/js/app.exe").status, 404)
```

- [ ] **Step 3: Run the focused tests and verify RED**

Run:

```powershell
.\openclaw_new_launcher\python-runtime\python.exe -m unittest license_server.tests.test_admin_console_contract license_server.tests.test_admin_asset_contract license_server.tests.test_admin_frontend_module_contract
```

Expected: failures for missing module files and `/admin/assets/` handling only.

- [ ] **Step 4: Commit the contract snapshot**

```powershell
git add license_server/tests/test_admin_console_contract.py license_server/tests/test_admin_asset_contract.py license_server/tests/test_admin_frontend_module_contract.py
git commit -m "test: freeze modular admin frontend contract"
```

---

### Task 2: Serve a Minimal Shell and Allowlisted Assets

**Files:**
- Modify: `license_server/admin_console.html`
- Create: `license_server/admin_assets/styles/tokens.css`
- Create: `license_server/admin_assets/styles/shell.css`
- Create: `license_server/admin_assets/styles/components.css`
- Create: `license_server/admin_assets/styles/pages.css`
- Modify: `license_server/luming_license/config.py`
- Modify: `license_server/luming_license/facade_core.py`
- Modify: `license_server/luming_license/http/handler.py`
- Modify: `license_server/luming_license/http/routes_public.py`
- Test: `license_server/tests/test_admin_asset_contract.py`

**Interfaces:**
- Consumes: `Settings.root_dir`, `ResponseMixin.send_file`, and `/admin`.
- Produces: `get_admin_asset(handler, parsed)` and a stable shell with `#adminPageHost`.

- [ ] **Step 1: Add a failing content-type/cache test**

```python
def test_assets_have_strict_types_and_cache_policy(self):
    js = self.get("/admin/assets/js/app.js")
    css = self.get("/admin/assets/styles/tokens.css")
    self.assertEqual(js.header("Content-Type"), "text/javascript; charset=utf-8")
    self.assertEqual(css.header("Content-Type"), "text/css; charset=utf-8")
    self.assertEqual(js.header("X-Content-Type-Options"), "nosniff")
```

- [ ] **Step 2: Implement a containment-checked asset resolver**

```python
ADMIN_ASSET_TYPES = {".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8"}

def resolve_admin_asset(root: Path, request_path: str) -> tuple[Path, str] | None:
    relative = unquote(request_path.removeprefix("/admin/assets/")).replace("\\", "/")
    if not relative or relative.startswith("/"):
        return None
    base = (root / "admin_assets").resolve()
    candidate = (base / relative).resolve()
    if base not in candidate.parents or candidate.suffix not in ADMIN_ASSET_TYPES or not candidate.is_file():
        return None
    return candidate, ADMIN_ASSET_TYPES[candidate.suffix]
```

- [ ] **Step 3: Replace the monolith with the error-safe shell**

```html
<body>
  <div id="appShell" data-auth-state="loading">
    <header class="topbar"><a class="brand" href="/admin">Luming License</a></header>
    <aside id="adminNav" aria-label="Admin navigation"></aside>
    <main id="adminPageHost" tabindex="-1">
      <section class="module-state" data-state="loading">Loading...</section>
    </main>
  </div>
  <div id="dialogHost"></div>
  <div id="toastHost" aria-live="polite"></div>
  <script type="module" src="/admin/assets/js/app.js"></script>
</body>
```

- [ ] **Step 4: Add restrained control-panel CSS tokens**

Use fixed type sizes, 4/8/12/16/24 spacing, 4-8 px radii, dark green shell, white content, teal status, amber warning, and red danger. Add `:focus-visible`, reduced motion, 44 px minimum touch targets on narrow screens, horizontal table scroll, and no viewport-scaled fonts.

- [ ] **Step 5: Run asset, HTTP inventory, and security tests**

```powershell
.\openclaw_new_launcher\python-runtime\python.exe -m unittest license_server.tests.test_admin_asset_contract license_server.tests.test_http_route_inventory license_server.tests.test_security_module
```

Expected: all pass; unknown/traversal assets return 404 without filesystem details.

- [ ] **Step 6: Commit**

```powershell
git add license_server/admin_console.html license_server/admin_assets license_server/luming_license license_server/tests/test_admin_asset_contract.py
git commit -m "feat: serve modular admin shell assets"
```

---

### Task 3: Extract API, Session, State, Formatting, and Error Boundaries

**Files:**
- Create: `license_server/admin_assets/js/api.js`
- Create: `license_server/admin_assets/js/state.js`
- Create: `license_server/admin_assets/js/format.js`
- Create: `license_server/admin_assets/js/app.js`
- Test: `license_server/tests/test_admin_frontend_module_contract.py`
- Test: `license_server/tests/test_admin_frontend_security_contract.py`

**Interfaces:**
- Produces: `request`, `publicRequest`, `SessionExpiredError`, `createStore`, `escapeHtml`, `formatTime`, `mountPage`.

- [ ] **Step 1: Write static security tests**

```python
def test_modules_do_not_persist_secrets(self):
    source = self.read_all_js()
    for forbidden in ("localStorage", "sessionStorage", "document.cookie", "eval(", "new Function("):
        self.assertNotIn(forbidden, source)
    self.assertIn('credentials: "same-origin"', self.read_js("api.js"))
```

- [ ] **Step 2: Implement the API wrapper**

```javascript
export class SessionExpiredError extends Error {}

export async function request(path, options = {}) {
  const response = await fetch(`/admin/${String(path).replace(/^\/+/, "")}`, {
    credentials: "same-origin",
    cache: "no-store",
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const payload = await response.json().catch(() => ({}));
  if (response.status === 401) throw new SessionExpiredError("Session expired");
  if (!response.ok || payload.ok === false) throw new Error(payload.error || `Request failed (${response.status})`);
  return Object.prototype.hasOwnProperty.call(payload, "data") ? payload.data : payload;
}
```

- [ ] **Step 3: Implement non-secret in-memory state**

```javascript
const state = { me: null, page: "overview", cache: new Map() };
const listeners = new Set();
export const store = {
  get: () => state,
  set(patch) { Object.assign(state, patch); listeners.forEach((fn) => fn(state)); },
  subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); },
};
```

- [ ] **Step 4: Implement isolated page lifecycle**

`mountPage(name)` must abort the previous page with `AbortController`, render a loading state, dynamically import only the selected page, and replace failures with a retry panel inside `#adminPageHost`. It must never replace `#appShell`.

- [ ] **Step 5: Run tests and commit**

```powershell
.\openclaw_new_launcher\python-runtime\python.exe -m unittest license_server.tests.test_admin_frontend_module_contract license_server.tests.test_admin_frontend_security_contract
git add license_server/admin_assets/js license_server/tests
git commit -m "feat: add admin frontend runtime modules"
```

---

### Task 4: Extract Dialogs and Typed Dangerous Actions

**Files:**
- Create: `license_server/admin_assets/js/dialogs.js`
- Modify: `license_server/admin_console.html`
- Modify: `license_server/admin_assets/styles/components.css`
- Test: `license_server/tests/test_admin_frontend_security_contract.py`

**Interfaces:**
- Produces: `confirmAction`, `confirmDanger`, `openEditor`, `showOneTimeResult`.

- [ ] **Step 1: Add tests for typed confirmation and secret lifetime**

Assert that `confirmDanger` compares an exact required phrase, Escape and Cancel reject, focus returns to the opener, and `showOneTimeResult` clears its text on close.

- [ ] **Step 2: Implement the dialog API**

```javascript
export function confirmDanger({ title, message, requiredText }) {
  return openDialog(({ body, accept }) => {
    body.innerHTML = `<h2>${escapeHtml(title)}</h2><p>${escapeHtml(message)}</p>`;
    const input = document.createElement("input");
    input.autocomplete = "off";
    input.addEventListener("input", () => { accept.disabled = input.value !== requiredText; });
    body.append(input);
  });
}
```

- [ ] **Step 3: Preserve required server phrases**

Use `DELETE`, `CLEAR`, and `UNBIND` exactly where the existing endpoints require them. Reveal/export dialogs must explain audit/backup behavior before calling the API.

- [ ] **Step 4: Test and commit**

```powershell
.\openclaw_new_launcher\python-runtime\python.exe -m unittest license_server.tests.test_admin_frontend_security_contract license_server.tests.test_admin_console_contract
git add license_server/admin_console.html license_server/admin_assets license_server/tests
git commit -m "feat: add secure admin dialogs"
```

---

### Task 5: Build Overview and Quick Issuance First

**Files:**
- Create: `license_server/admin_assets/js/pages/overview.js`
- Create: `license_server/admin_assets/js/pages/issuance.js`
- Modify: `license_server/admin_assets/js/app.js`
- Modify: `license_server/admin_assets/styles/pages.css`
- Test: `license_server/tests/test_admin_frontend_module_contract.py`

**Interfaces:**
- Overview consumes codes, activations, accounts, plans, audit logs, health, and public config.
- Issuance consumes plans/accounts and posts to `/admin/api/codes`.

- [ ] **Step 1: Add real-data and partial-failure tests**

Require `Promise.allSettled`, an unavailable label, recent audit rendering, and no hard-coded business counts. Verify one failed metric does not hide successful metrics.

- [ ] **Step 2: Implement overview metrics**

Render total authorization, active authorization, activated devices, codes issued today, service health, purchase configuration state, relay/public config state, and recent operations. Metric failures render `Temporarily unavailable` with a local retry button.

- [ ] **Step 3: Implement the minimal issuance flow**

The form includes plan, owner, quantity, expiry, device limit, and optional note. Before submission render a plain summary. After success show codes only in `showOneTimeResult`; copying/download is explicit and closing destroys the value.

- [ ] **Step 4: Verify admin and merchant visibility**

Super admin sees owner selection and batch quantity. Merchant mode fixes owner to the current account and follows server limits; hidden controls are not treated as authorization.

- [ ] **Step 5: Test and commit**

```powershell
.\openclaw_new_launcher\python-runtime\python.exe -m unittest license_server.tests.test_admin_frontend_module_contract license_server.tests.test_license_flow
git add license_server/admin_assets license_server/tests
git commit -m "feat: add admin overview and issuance"
```

---

### Task 6: Migrate Authorization Codes and Activations

**Files:**
- Create: `license_server/admin_assets/js/pages/licenses.js`
- Modify: `license_server/admin_assets/styles/pages.css`
- Test: `license_server/tests/test_admin_frontend_module_contract.py`

**Interfaces:**
- Consumes all code and activation routes listed in the stable contract.
- Produces a filterable code table and activation drawer without permanent secret storage.

- [ ] **Step 1: Add contract markers for filters and state views**

Require search, status, plan, owner filters; loading/empty/error states; masked code display; typed deletion/clear; and activation pagination.

- [ ] **Step 2: Implement table rendering with stable dimensions**

Use semantic tables, sticky headers only on desktop, horizontal scrolling on narrow screens, masked code values, status badges, and icon buttons with tooltips. A row action menu owns reveal, edit, enable/disable, activations, and delete.

- [ ] **Step 3: Implement protected reveal/export**

Always call the server reveal/export endpoint after explicit confirmation. Keep returned raw codes in a function-local variable, render them only inside the result dialog, and overwrite the variable on close.

- [ ] **Step 4: Test and commit**

```powershell
.\openclaw_new_launcher\python-runtime\python.exe -m unittest license_server.tests.test_admin_frontend_module_contract license_server.tests.test_security_module license_server.tests.test_license_flow
git add license_server/admin_assets license_server/tests
git commit -m "feat: migrate license operations page"
```

---

### Task 7: Migrate Customers, Ownership, and Invites

**Files:**
- Create: `license_server/admin_assets/js/pages/customers.js`
- Test: `license_server/tests/test_admin_frontend_module_contract.py`

**Interfaces:**
- Consumes account and invite GET/POST/toggle routes.
- Produces account list/editor, owned-license drill-down, and one-time invite display.

- [ ] **Step 1: Add ownership and invite secrecy tests**

Require owner filtering, status controls, invite expiry/use limits, no invite persistence, and one-time copy behavior.

- [ ] **Step 2: Implement account operations**

Display account status, role, owned authorization count, quota use, and gateway status. Keep account edit and enable/disable commands separate. Merchant role must not mount invite/admin account controls.

- [ ] **Step 3: Implement invites**

Creation returns the raw invite only in a one-time result dialog. Existing rows show masked/status metadata only. Copy is allowed only from the one-time result or a server-authorized reveal flow if later added.

- [ ] **Step 4: Test and commit**

```powershell
.\openclaw_new_launcher\python-runtime\python.exe -m unittest license_server.tests.test_admin_frontend_module_contract license_server.tests.test_license_flow
git add license_server/admin_assets license_server/tests
git commit -m "feat: migrate customer and invite operations"
```

---

### Task 8: Migrate Plans, Purchase Entry, and Gateway Settings

**Files:**
- Create: `license_server/admin_assets/js/pages/sales.js`
- Test: `license_server/tests/test_admin_frontend_module_contract.py`

**Interfaces:**
- Consumes plans, public-settings, account-gateway, and public client-config routes.
- Produces plan editor, purchase/support configuration, and masked model gateway settings.

- [ ] **Step 1: Add dynamic purchase and secret-mask tests**

Require the saved purchase URL to round-trip through `/api/client/config`, API keys to remain masked, and blank secret submissions to preserve existing secrets.

- [ ] **Step 2: Implement plan editor**

Include duration, device quota, feature permissions, model defaults, enabled state, and inheritance summary. Disable and delete remain separate commands; deletion uses typed confirmation.

- [ ] **Step 3: Implement purchase/public settings**

Show where the URL appears in LOOM and the public authorization page. Validate only supported `https://` URLs client-side while relying on server validation as final authority.

- [ ] **Step 4: Implement gateway settings**

Render Base URL, model, key-present status, and plan inheritance. Never read a stored key back into an input. Submitting an empty key means preserve, not clear.

- [ ] **Step 5: Test and commit**

```powershell
.\openclaw_new_launcher\python-runtime\python.exe -m unittest license_server.tests.test_admin_frontend_module_contract license_server.tests.test_plans_module license_server.tests.test_license_flow
git add license_server/admin_assets license_server/tests
git commit -m "feat: migrate sales and gateway configuration"
```

---

### Task 9: Migrate AI Beta and Template Operations

**Files:**
- Create: `license_server/admin_assets/js/pages/ai.js`
- Test: `license_server/tests/test_admin_frontend_module_contract.py`

**Interfaces:**
- Consumes beta config and template list/create/update/delete routes.
- Produces a beta enrollment panel and image/video/marketing template manager.

- [ ] **Step 1: Add AI page contract tests**

Require real beta status, plan selection, daily quota, template kind/status/order, editor state, and typed delete confirmation.

- [ ] **Step 2: Implement beta configuration**

Display enabled state, selected plan, expiry policy, and daily quota. Save only changed fields and reload server state after success.

- [ ] **Step 3: Implement templates**

Use tabs for image, video, and marketing templates; rows show name, enabled state, order, and updated time. Editing occurs in a modal with explicit Save. No template body is placed in URL/query/history.

- [ ] **Step 4: Test and commit**

```powershell
.\openclaw_new_launcher\python-runtime\python.exe -m unittest license_server.tests.test_admin_frontend_module_contract license_server.tests.test_templates_module
git add license_server/admin_assets license_server/tests
git commit -m "feat: migrate AI configuration and templates"
```

---

### Task 10: Migrate Audit, Diagnostics, and Documentation

**Files:**
- Create: `license_server/admin_assets/js/pages/governance.js`
- Modify: `license_server/admin_assets/js/app.js`
- Test: `license_server/tests/test_admin_frontend_security_contract.py`

**Interfaces:**
- Consumes audit logs, health, current-user, auth-status, and public client config.
- Produces governance tabs with safe summaries and role-aware navigation.

- [ ] **Step 1: Add tests for redacted audit rendering**

Assert that password, token, key, cookie, invite, raw code, and session-like fields are never inserted through `innerHTML`; structured details use text nodes and the shared formatter.

- [ ] **Step 2: Implement audit view**

Provide time, actor, action, target, result, and safe detail filters. Do not add a client-side raw JSON viewer. Failed requests show a module-local retry state.

- [ ] **Step 3: Implement diagnostics and docs**

Show service health, auth mode, purchase configuration state, and client-config reachability. Documentation is concise operator guidance linked from a tab, not a marketing page.

- [ ] **Step 4: Enforce role-aware navigation**

`app.js` filters navigation using `/admin/api/me`, but every forbidden API call must still rely on server 403. Session expiry returns to the login panel without reloading or losing the shell.

- [ ] **Step 5: Test and commit**

```powershell
.\openclaw_new_launcher\python-runtime\python.exe -m unittest license_server.tests.test_admin_frontend_security_contract license_server.tests.test_security_module license_server.tests.test_license_flow
git add license_server/admin_assets license_server/tests
git commit -m "feat: migrate admin governance pages"
```

---

### Task 11: Remove Legacy Inline Code and Perform Visual QA

**Files:**
- Modify: `license_server/admin_console.html`
- Modify: `license_server/admin_assets/styles/*.css`
- Modify only for defects: `license_server/admin_assets/js/**/*.js`
- Test: `license_server/tests/test_admin_console_contract.py`
- Test: `license_server/tests/test_admin_frontend_module_contract.py`

**Interfaces:**
- Consumes: all migrated page modules.
- Produces: final shell with no duplicate legacy implementation.

- [ ] **Step 1: Add monolith-removal limits**

```python
def test_shell_stays_small_and_pages_have_line_limits(self):
    self.assertLess(len(Path(ADMIN_HTML).read_text(encoding="utf-8").splitlines()), 260)
    for path in PAGE_MODULES:
        self.assertLessEqual(len(path.read_text(encoding="utf-8").splitlines()), 500, path)
```

- [ ] **Step 2: Remove all inline business scripts/styles**

Keep only semantic shell markup, stylesheet links, the dialog/toast hosts, and the single module script. Remove duplicate beta/template IIFEs and obsolete IDs after every page test is green.

- [ ] **Step 3: Start an isolated local server**

Use a temporary database and generated key. Never point visual QA at production mutation endpoints.

- [ ] **Step 4: Verify desktop viewport**

At 1440x900, click every navigation item; verify login, loading, empty, ready, error, dialog, menu, and table states. Confirm no blank modules, nested cards, clipped controls, or invisible focus.

- [ ] **Step 5: Verify narrow viewport**

At 390x844, verify navigation, table horizontal scroll, fixed dialog positioning, dynamic text wrapping, and buttons. No text or controls may overlap.

- [ ] **Step 6: Verify failure isolation**

Block one API at a time in browser tooling. The affected page must show retry while navigation and other pages remain usable. Expire the session and confirm the login state appears without a white screen.

- [ ] **Step 7: Run full local tests and commit**

```powershell
.\openclaw_new_launcher\python-runtime\python.exe -m unittest discover -s license_server\tests -p "test_*.py"
git diff --check
git add license_server/admin_console.html license_server/admin_assets license_server/tests
git commit -m "refactor: complete modular admin console"
```

---

### Task 12: Release-Level Frontend Verification and Program-Only Deployment

**Files:**
- Create: `docs/validation/LOOM_LICENSE_ADMIN_FRONTEND_MODULAR_20260714.md`
- Modify only for defects: Phase 2 frontend and asset-serving files.

**Interfaces:**
- Consumes: complete Phase 2 files and the Phase 1 deployment process.
- Produces: a release report, program backup, deployed manifest, and program-only rollback command.

- [ ] **Step 1: Run final automated gates**

```powershell
.\openclaw_new_launcher\python-runtime\python.exe -m py_compile license_server\server.py
.\openclaw_new_launcher\python-runtime\python.exe -m unittest discover -s license_server\tests -p "test_*.py"
git diff --check
```

Expected: zero failures, shell below 260 lines, each page below 500 lines, no secret persistence markers, all asset paths present.

- [ ] **Step 2: Create a fresh online SQLite and program backup**

Use `sqlite3.Connection.backup`; save the current program tree under a timestamped `/opt/openclaw-license/backups/admin-frontend-*` directory. Do not copy the live DB file directly.

- [ ] **Step 3: Shadow with disposable data**

Upload to a staging directory, bind `LICENSE_HOST=127.0.0.1` on a verified-free port, use a copy of the backup DB and a generated disposable key, compile every Python module, and probe `/admin` plus every exact asset path. Stop and clean the shadow before deployment.

- [ ] **Step 4: Deploy program files only**

Replace `server.py`, `luming_license/`, `admin_console.html`, and `admin_assets/` only after the shadow passes. Do not replace the live database, private key, environment, service unit, or token files.

- [ ] **Step 5: Perform public read-only smoke tests**

Verify `/health`, `/`, `/admin`, all CSS/JS assets, unauthenticated admin API 401, CSP/HSTS/no-store/referrer headers, dynamic purchase URL rendering, and service logs. Do not click or call generation, reveal, delete, clear, toggle, unbind, activation, or configuration writes on production.

- [ ] **Step 6: Compare preservation evidence**

Compare protected-table digests and aggregates before/after/final, verify the signing key matches without recording its fingerprint, run `PRAGMA quick_check`, and require zero error markers in the observation window.

- [ ] **Step 7: Write the report and commit**

The report records sanitized commands, asset/program manifest, test results, backup path, visual screenshots, aggregate comparison, logs, and a preflight-first program-only rollback. It contains no credentials, keys, tokens, raw authorization/invite codes, customer rows, or database files.

```powershell
git add docs/validation/LOOM_LICENSE_ADMIN_FRONTEND_MODULAR_20260714.md
git commit -m "docs: validate modular license admin frontend"
```

## Completion Gate

Phase 2 is complete only when:

1. `/admin` loads the small native-module shell and all allowlisted assets with correct security headers.
2. Overview, issuance, licenses, activations, customers, invites, plans, sales, AI, audit, diagnostics, and docs have loading, ready, empty, and error states.
3. All displayed metrics come from real APIs; partial failures never render fake zero values.
4. Dangerous commands retain typed confirmation and server validation.
5. No browser storage or committed asset contains session tokens, API keys, passwords, raw invites, or raw authorization codes.
6. Desktop and 390 px visual checks show no blank pages, overlap, clipped text, hidden dialogs, or unusable tables.
7. All backend compatibility, route, CLI, database, security, and frontend tests pass.
8. Production database aggregates and signing key match before and after deployment, service health is green, and error logs are empty.
9. The deployed program has a tested preflight-first program-only rollback path.

Phase 3 release-directory and atomic `current` symlink work must remain a separate plan after Phase 2 is stable.
