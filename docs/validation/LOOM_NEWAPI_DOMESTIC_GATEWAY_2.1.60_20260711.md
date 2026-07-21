# LOOM 2.1.60 NewAPI Domestic Gateway Validation

Date: 2026-07-11

## Scope

- Make `https://api-cn.heang.top` the default NewAPI account and model gateway.
- Migrate stored managed sessions and re-sync local Codex, OpenClaw, media, and phone configuration.
- Keep `https://api.heang.top` as a controlled compatibility fallback for read-only and idempotent login requests.
- Never replay registration or verification-code delivery requests across gateways.
- Align the production account bridge, template cloud public base, NewAPI public address, logo, FAQ, and homepage links.

## Verification

- Launcher Python suite: 584 tests passed.
- Frontend production build: passed for version 2.1.60.
- NewAPI bridge tests: 15 passed.
- Template cloud tests: 5 passed.
- Installer manifest signature and required component check: passed.
- External `api-cn.heang.top` checks:
  - `/api/status`: 200.
  - `/v1/models` without a token: 401.
  - `/api/loom/templates` without a token: 401.
  - `/template-admin/`: 200.
  - managed Skill download: 200.
  - launcher-token request with a nonexistent test account: 401.
- Exact NSIS smoke passed in ASCII and Chinese install paths:
  - packaged Python and FastAPI Bridge started successfully;
  - Codex default language guidance reported `zh-CN`;
  - license endpoint returned 200;
  - unlicensed matrix and acquisition endpoints returned 403;
  - uninstall cleanup and existing registration/shortcut restoration passed.

## Candidate

- Recommended installer: `artifacts/nsis-release-2.1.60-offline-complete-candidate-r1/LOOM-2.1.60-setup.exe`
- Size: `382275730` bytes.
- SHA256: `a50be7cc256906e5559372d18a8bf8175570b73c974d4444977e3a76f816a637`.
- Authenticode: `NotSigned` engineering candidate.

## Production Changes

- Fire-cloud Nginx now serves both gateway hostnames from one synchronized active/source configuration.
- Template cloud public links now use `api-cn.heang.top`.
- NewAPI account bridge now returns `https://api-cn.heang.top/v1`.
- NewAPI `ServerAddress`, logo, FAQ, About, and homepage links now use the domestic gateway.
- Timestamped server and database backups were created before changes.

## Residual Constraint

NewAPI Passkey RP ID remains `api.heang.top`. Changing it would invalidate or disconnect existing passkeys because the old and new hosts are sibling domains. Password and email-code launcher login use the new gateway; browser Passkey migration requires a separately planned credential transition.

The candidate is not a public stable release until it is Authenticode-signed and the published download checksum is verified.
