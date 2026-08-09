# Phone Entitlement Auto-entry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refresh the authoritative signed entitlement when a phone surface opens and automatically render the phone UI for authorized accounts instead of showing a stale paywall.

**Architecture:** Put the refresh/check sequence in a small dependency-injected TypeScript function. `PhoneMatrixAccessGate` calls it once per mount and on explicit retry, while the existing backend and paywall remain authoritative.

**Tech Stack:** React 18, TypeScript, Zustand, Node test runner with `tsx`.

## Global Constraints

- Never grant access from the cached account snapshot alone.
- `/api/license/current` and `/api/license/authorized` remain the authority.
- Offline grace is accepted only when the refreshed signed license gate is authorized.
- Missing, expired, revoked, mismatched, denied, and error states remain fail-closed.
- Do not remove or weaken existing commercial-license tests.

---

### Task 1: Authoritative phone access resolution and gate integration

**Files:**
- Create: `apps/loom-platform/openclaw_new_launcher/src/components/license/phoneMatrixAccess.ts`
- Create: `apps/loom-platform/openclaw_new_launcher/src/components/license/phoneMatrixAccess.test.ts`
- Modify: `apps/loom-platform/openclaw_new_launcher/src/components/license/PhoneMatrixAccessGate.tsx`
- Modify: `apps/loom-platform/openclaw_new_launcher/package.json`

**Interfaces:**
- Consumes: `refreshLicense(): Promise<void>`, `readLicense(): { authorized: boolean }`, `checkFeature(): Promise<{ authorized: boolean }>`.
- Produces: `resolvePhoneMatrixAccess(dependencies): Promise<{ authorized: boolean; featureChecked: boolean }>`.

- [ ] **Step 1: Write the failing resolver tests**

Cover stale unauthorized state becoming authorized after refresh, refreshed unauthorized state skipping the feature call, feature denial, and refresh failure propagation. The first test must mutate the value returned by `readLicense` inside `refreshLicense` to prove the post-refresh snapshot is used.

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```powershell
node --import tsx --test src/components/license/phoneMatrixAccess.test.ts
```

Expected: FAIL because `phoneMatrixAccess.ts` does not exist.

- [ ] **Step 3: Implement the minimal resolver**

```ts
export async function resolvePhoneMatrixAccess(dependencies: PhoneMatrixAccessDependencies) {
  await dependencies.refreshLicense();
  if (!dependencies.readLicense().authorized) {
    return { authorized: false, featureChecked: false };
  }
  const feature = await dependencies.checkFeature();
  return { authorized: feature.authorized === true, featureChecked: true };
}
```

- [ ] **Step 4: Verify resolver GREEN**

Run the focused Node command again. Expected: all resolver tests pass.

- [ ] **Step 5: Integrate the resolver into the React gate**

Make `refreshFeatureAccess` set checking state, call `resolvePhoneMatrixAccess` with `checkLicense`, `useAppStore.getState().licenseGate`, and `licenseApi.authorized('matrix.devices')`, then store the result. Run its mount effect only from the stable callback; do not depend on `licenseGate.authorized` or signature changes. Make the retry path reuse this one refresh function. Pass `featureChecking={featureAuthorized === null}` so the initial state does not claim the account is unpaid.

- [ ] **Step 6: Add the focused test to the platform contract command**

Append `src/components/license/phoneMatrixAccess.test.ts` to `test:platform-contracts` so CI permanently exercises the regression.

- [ ] **Step 7: Run focused and commercial gate verification**

```powershell
node --import tsx --test src/components/license/phoneMatrixAccess.test.ts src/components/controlIntegrity.test.ts
python -B -m pytest python/tests/test_commercial_license_paywall_contract.py python/tests/test_ui_navigation_contract.py -q
npx tsc --noEmit
```

Expected: all tests pass and TypeScript exits 0.

- [ ] **Step 8: Run the complete platform contract suite and inspect the diff**

```powershell
npm run test:platform-contracts
git diff --check
git status --short
```

Expected: suite exits 0, diff check exits 0, and only the planned source/test/package files plus this plan/spec are present.

- [ ] **Step 9: Commit the tested fix**

```powershell
git add apps/loom-platform/openclaw_new_launcher/src/components/license/phoneMatrixAccess.ts apps/loom-platform/openclaw_new_launcher/src/components/license/phoneMatrixAccess.test.ts apps/loom-platform/openclaw_new_launcher/src/components/license/PhoneMatrixAccessGate.tsx apps/loom-platform/openclaw_new_launcher/package.json docs/superpowers/plans/2026-08-09-phone-entitlement-auto-entry.md
git commit -m "fix(phone): refresh entitlement before paywall"
```
