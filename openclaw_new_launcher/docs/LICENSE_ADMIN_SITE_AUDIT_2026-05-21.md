# License Admin Site Audit - 2026-05-21

Target: `https://license.heang.top/admin`

This note records the production review of the OpenClaw license admin console. The online site was already running the newer admin UI, but several production hardening items were still worth tracking.

## Confirmed Working

- `/health` returned HTTP 200.
- Unauthenticated requests to `/admin/api/codes`, `/admin/api/plans`, and `/admin/api/audit-logs` returned HTTP 401.
- `X-Frame-Options: SAMEORIGIN` and `X-Content-Type-Options: nosniff` were present.
- The admin console included sections for plans, gateway configuration, audit records, and documentation.

## Fixed Items

### Left Navigation

The left-side navigation buttons were changed from static buttons into real anchors:

- Plans jump to the plan template section.
- Gateway configuration jumps to the gateway profile section.
- Audit records jump to the audit table.
- Documentation jumps to the operations notes.

Validation:

- Clicking each navigation item scrolls to the matching section.
- The active navigation item is highlighted.

### Mobile Layout

The mobile top bar previously overflowed on narrow screens. The layout now stacks the top actions under the header when the viewport is narrow.

Validation:

- A 390 x 844 viewport should not show horizontal clipping.
- Refresh, export, batch update, and clear actions should remain visible.

## Remaining Production Debt

### P1: Security Headers

Recommended headers for `/admin` and `/admin/api/*`:

- `Content-Security-Policy`
- `Referrer-Policy`
- `Strict-Transport-Security`
- `Cache-Control: no-store`

### P1: Admin Token Storage

The admin UI still stores the admin token in browser storage. Short-term mitigation is an explicit logout button that clears local state. Longer-term mitigation is server-side session cookies with `HttpOnly`, `Secure`, and `SameSite=Strict`.

### P1: Dangerous Action Confirmation

High-risk actions should use custom confirmation dialogs instead of browser `confirm()`:

- Clear all codes.
- Delete a license code.
- Unbind an activation.

For destructive actions, require explicit confirmation text such as `CLEAR`.

### P1: Unauthenticated State

When no admin token is present, dangerous actions should be disabled and the page should show one clear login-state message instead of repeating per-panel errors.

### P2: Audit Search

Audit records should support filtering by action, target license code, and time range. CSV export should be added when production usage grows.
