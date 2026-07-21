# Task 5 Report: Extract Audit Infrastructure

## Status

Complete.

## RED

The brief's relative runtime command could not run because this worktree does not contain `openclaw_new_launcher/python-runtime/python.exe`.

Fallback command:

```powershell
& 'D:\Axiangmu\AUSTART\openclaw_new_launcher\python-runtime\python.exe' -m unittest discover -s license_server\tests -p "test_domain_module_boundaries.py"
```

Result: expected failure. `ImportError: cannot import name 'audit' from 'luming_license'` before the audit module existed.

## GREEN And Verification

```powershell
& 'D:\Axiangmu\AUSTART\openclaw_new_launcher\python-runtime\python.exe' -m unittest discover -s license_server\tests -p "test_domain_module_boundaries.py"
```

Result: 2 tests passed.

```powershell
& 'D:\Axiangmu\AUSTART\openclaw_new_launcher\python-runtime\python.exe' -m unittest discover -s license_server\tests -p "test_license_flow.py"
```

Result: 41 tests passed.

```powershell
& 'D:\Axiangmu\AUSTART\openclaw_new_launcher\python-runtime\python.exe' -m unittest discover -s license_server\tests -p "test_*.py"
```

Result: 81 tests passed.

`git diff --check` also passed.

## Files

- Created `license_server/luming_license/audit.py` with audit serialization, recursive redaction, persistence, secret masking, and audit-row rendering.
- Created `license_server/tests/test_domain_module_boundaries.py` with ownership and nested-secret redaction assertions.
- Updated `license_server/server.py` with per-server facade wrappers and direct handler use of the owning audit module.
- Updated `license_server/tests/test_license_flow.py` so audit-failure testing patches `luming_license.audit.add_audit_log` and confirms no reveal/export secret is returned.

## Self-Review

- `audit.py` imports only database, serialization, and UTC-time infrastructure; it has no dependency on license records, snapshots, handlers, or domains, so it introduces no audit/license import cycle.
- Code and inventory snapshots remain in `server.py` for Task 8.
- Facade wrappers inject the loaded server's `connect`, `utc_now`, `audit_json`, and `load_json_value` helpers, preserving per-server isolation and monkeypatch compatibility.
- Audit writes recursively redact values before JSON serialization while retaining actor, target, request-IP, backup-path, timestamp, row ordering, and response payload fields.
- Reveal/export invokes `audit.add_audit_log` before sending any secret; an audit failure continues to return the established generic 500 response with no secret. Existing backup-before-mutation ordering is unchanged.

## Concerns

- No code concerns found. The worktree-local runtime path from the brief is absent, so verification used the equivalent runtime in the parent repository.

## Follow-up Fixes

### Facade Compatibility

- Restored `Handler.audit_admin_change()` to call `server.add_audit_log` so existing facade monkeypatches and call observation remain effective.
- The server facade now injects both `server.audit_json` and `server.audit_public_value` into the extracted audit module. Audit reads also use the facade public-value collaborator.
- Added explicit collaborator-path coverage for facade redaction/serialization calls, plus persisted audit actor, request IP, backup path, timestamp, and descending-order fields.

### Fail-Closed Mutation Transactions

- Added a request-thread-local SQLite connection proxy for audited mutations. Existing helper commits are deferred until the facade audit write succeeds; a failed audit rolls the connection back and closes it.
- Audit persistence commits the mutation and audit row together. No database backup is used as a rollback mechanism.
- Kept backup ordering stable by starting the shared transaction only after each existing backup completes.
- Inventory covered: account create/update/toggle; invite create/toggle; account gateway update; code create/update/bulk-update/toggle/clear/delete; plan update/delete; activation delete; public-settings update; and invite registration.
- Reveal/export remain non-mutating and still audit before a secret response is sent.

### RED/GREEN Evidence

- RED: changing the secret-failure test to patch `server.add_audit_log` made reveal return HTTP 200 with the secret, proving the handler bypassed the facade.
- GREEN: restoring the handler facade call made the focused flow suite pass.
- RED: new rollback tests showed failed audit writes left account registration and account mutation data committed.
- GREEN: the request-scoped transaction made all new rollback tests pass. An existing owner-race test then exposed transaction activation before backup; moving activation after backup restored that behavior.

### Follow-up Verification

```powershell
& 'D:\Axiangmu\AUSTART\openclaw_new_launcher\python-runtime\python.exe' -m unittest discover -s license_server\tests -p "test_domain_module_boundaries.py"
& 'D:\Axiangmu\AUSTART\openclaw_new_launcher\python-runtime\python.exe' -m unittest discover -s license_server\tests -p "test_license_flow.py"
& 'D:\Axiangmu\AUSTART\openclaw_new_launcher\python-runtime\python.exe' -m unittest discover -s license_server\tests -p "test_backend_refactor_contract.py"
& 'D:\Axiangmu\AUSTART\openclaw_new_launcher\python-runtime\python.exe' -m unittest discover -s license_server\tests -p "test_*.py"
git diff --check
```

Results: boundary `2` passed, flow `45` passed, backend contract `2` passed, full license-server suite `85` passed, and `git diff --check` passed. No `accounts.py` change was required, so the separate account security-module target was not rerun.

## Second Follow-up Fixes

### RED

- Added lifecycle and rollback coverage before changing production code. The flow suite failed as expected: audit persistence committed account and invite data before session/last-login completion; bootstrap and beta/template writes succeeded when the audit facade failed; and deferred expired/used invite normalization rolled back its status update.
- The first complete-suite attempt also exposed a Windows-only fixture race: flow HTTP-server cleanups ran after temporary database deletion. The request had completed successfully, but the open server thread retained the file handle during teardown.

### GREEN

- `_commit_audit_connection` now records that an audit row was written and leaves the sole physical commit to `do_POST()`'s transaction finalizer. The lifecycle test asserts zero commits and invisible rows before finalization, then exactly one commit and both rows afterward.
- The finalizer now additionally requires a successfully sent 2xx response. A new RED/GREEN registration test makes `auth_status_snapshot()` fail after the audit write and confirms account, invite, session, and audit rows all roll back.
- Registration now creates the account, consumes the invite, creates the session, updates last-login, and only then calls the `server.add_audit_log` facade. Failure of session creation, last-login update, or audit persistence rolls all of those successful-registration writes back together.
- The direct `server.register_account_with_invite()` facade retains its established default audit behavior; only the HTTP handler opts into deferred audit for its request transaction.
- Expired and exhausted invites use the new optional `normalization_commit_fn` only on their established error path, so status normalization remains durable while audited successful registration stays deferred and atomic.
- Bootstrap, beta configuration, template save, and template delete now use the same request-scoped mutation-plus-audit transaction and fail closed on an audit failure.
- The flow fixture now runs registered HTTP-server cleanups before deleting its temporary database, eliminating the Windows handle race without changing production behavior or test assertions.

### Mutation Inventory

- Already backuped, audited, and atomic: account create/update/toggle; invite create/toggle; account gateway; code create/update/bulk-update/toggle/clear/delete; plan update/delete; activation delete; and public settings.
- Added here: privileged bootstrap, beta configuration, template save, and template delete. Successful invite registration is audited atomically without a backup, because it has no pre-existing backup contract.
- Explicitly non-management paths: login/logout session lifecycle; public beta claim issuance; public activation/member state; publish-relay packet enqueue/claim/complete; and startup template seeding. They retain their established domain-specific behavior and are covered by the focused/full flow suite; none is an administrative dangerous mutation.

### Coverage Added

- Exact one-commit lifecycle and invisibility before finalization.
- Registration audit call order: session, last-login update, then facade audit; rollback for session, last-login, response assembly, and audit failures.
- Durable expired and used invite normalization on registration errors.
- Audit-failure rollback for privileged bootstrap, beta configuration, template save, and template delete.
- Existing assertions continue to cover persisted audit serialization, actor/IP/backup/timestamp fields, descending order, facade collaborators, account/code/plan rollback, and reveal/export fail-closed behavior.

### Verification

```powershell
& 'D:\Axiangmu\AUSTART\openclaw_new_launcher\python-runtime\python.exe' -m unittest discover -s license_server\tests -p "test_domain_module_boundaries.py"
& 'D:\Axiangmu\AUSTART\openclaw_new_launcher\python-runtime\python.exe' -m unittest discover -s license_server\tests -p "test_license_flow.py"
& 'D:\Axiangmu\AUSTART\openclaw_new_launcher\python-runtime\python.exe' -m unittest discover -s license_server\tests -p "test_security_module.py"
& 'D:\Axiangmu\AUSTART\openclaw_new_launcher\python-runtime\python.exe' -m unittest discover -s license_server\tests -p "test_backend_refactor_contract.py"
& 'D:\Axiangmu\AUSTART\openclaw_new_launcher\python-runtime\python.exe' -m unittest discover -s license_server\tests -p "test_*.py"
git diff --check
```

Results: boundary `2` passed, focused flow `51` passed, security `22` passed, backend contract `2` passed, full license-server suite `91` passed, and `git diff --check` passed.

### Self-Review And Concerns

- Handler audit calls still reach `server.add_audit_log`; the facade continues to inject per-server serialization/redaction collaborators. No audit/domain circular import was introduced.
- Reveal/export still audits before returning secrets. No backup restore is used for transaction rollback.
- No code concerns found. The worktree-local runtime remains absent, so the equivalent parent-repository runtime was used for every command above.
