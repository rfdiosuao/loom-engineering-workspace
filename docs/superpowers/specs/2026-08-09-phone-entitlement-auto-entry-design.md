# Phone entitlement auto-entry design

## Problem

`PhoneMatrixAccessGate` treats the global `licenseGate.authorized` snapshot as a prerequisite for checking the current `matrix.devices` entitlement. When account synchronization restores a valid signed lease after the initial application license check, that snapshot can remain unauthorized. Entering the phone surface then renders the paywall without refreshing the signed account entitlement.

The observed installation has a valid `signed_lease` containing `matrix.devices`, but the stale frontend gate still blocks the phone page.

## Desired behavior

- Entering a phone-matrix surface always performs one current license refresh before deciding access.
- While access is unresolved, show a neutral verification state rather than the paywall.
- A valid online entitlement opens the requested phone surface automatically.
- A valid signed lease in offline grace also opens the surface and keeps the existing offline banner.
- Missing, expired, revoked, device-mismatched, or feature-denied authorization renders the existing paywall.
- Network or Bridge errors without a valid signed local lease remain fail-closed and show an actionable retry error.
- Frontend account caches never independently grant access; the backend authorization result remains authoritative.

## Design

`PhoneMatrixAccessGate` owns a single mount/authorization-cycle refresh:

1. Set access state to checking.
2. Call the global `checkLicense()` to refresh `/api/license/current` from the signed account entitlement.
3. Read the refreshed store snapshot, not the render-time closure.
4. If the refreshed license is authorized, call `/api/license/authorized` for `matrix.devices`.
5. Render children only when both checks authorize access.
6. Otherwise render the existing `LicensePaywall` with the precise failure/checking state.

The gate must deduplicate React Strict Mode/effect reruns and must not create a refresh loop when `checkLicense()` updates the store.

## Error handling

- Preserve the current localized error mapping and retry button.
- During the initial refresh, pass `featureChecking=true` and do not describe the account as unpaid.
- Preserve emergency-stop behavior.
- Preserve the offline-grace banner for signed local authorization.

## Verification

Add focused frontend tests for:

1. stale unauthorized snapshot + refreshed signed entitlement => feature check runs and children render;
2. refreshed unauthorized/expired entitlement => paywall remains;
3. authorized license + denied `matrix.devices` => paywall remains;
4. authorized offline-grace license + granted feature => children render with offline banner;
5. refresh failure without a valid lease => fail-closed retry state;
6. effect rerenders do not repeatedly refresh authorization.

Keep the existing commercial-license and navigation contract suites green. No tests or authorization constraints may be removed or weakened.
