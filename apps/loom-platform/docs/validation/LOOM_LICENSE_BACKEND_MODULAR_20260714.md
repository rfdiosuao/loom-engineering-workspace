# LOOM License Backend Modularization Validation

Validation window: 2026-07-14 to 2026-07-15 (Asia/Shanghai)

Branch: `codex/license-site-modular-refactor`

## Outcome

All release-blocking Task 12 findings are closed. Relay claims and completions
use conditional compare-and-set updates, relay lock latency is bounded through
connection and schema initialization, every relay route returns sanitized
generic failures, and database preservation verification now enforces a fixed
canonical schema and a plans-only expected-change policy.

The established facade collaborator contract is also preserved. Relay claim
inspects the late-bound `connect` signature before invocation: a zero-argument
replacement is called without keywords, while the timeout-aware production
collaborator receives the bounded timeout. Invocation-time `TypeError` is never
caught or retried.

The reviewed program is deployed. The service is active, local and public
checks pass, the fresh backup and live database match across all 12 required
tables, aggregate counts are unchanged, and the production signing key matched
before and after the switch. No signing-key digest is recorded.

## Final Whole-Branch Fix

The final review blockers are closed:

- audited request transactions now commit before any successful HTTP headers
  or body are transmitted; a commit failure rolls back and returns a sanitized
  `500`, and repeated finalization is harmless;
- reveal, export, and registration routes retain the pre-refactor public
  collaborator call shapes while private request-transaction collaborators
  provide atomic audit behavior;
- invite credentials are redacted from named fields, nested values, actor and
  target strings, and annotations such as `invite:<credential>` before audit
  JSON is persisted;
- beta claim eligibility, quota, authorization issuance, and claim insertion
  execute under one `BEGIN IMMEDIATE` transaction on one connection, with
  contention mapped to a sanitized stable response.

Adversarial HTTP coverage injects an audit commit failure and proves the client
receives a sanitized `5xx` while both the mutation and audit row are absent.
Base-compatible route replacements prove reveal, export, and registration
succeed without new public kwargs and retain atomic audit semantics. Direct and
HTTP persistence tests prove raw invite values do not enter audit storage.

Deterministic synchronized beta tests prove that concurrent requests from one
IP persist exactly one authorization record and one claim, while two IPs with
quota one also persist exactly one authorization record and one claim. An
injected failure after authorization insertion persists zero records and zero
claims. Held-lock HTTP coverage returns a sanitized `503` without database
paths or SQLite details.

## Prior Exposure Closure

The earlier shadow process used an unsafe wildcard bind with production assets.
The retrospective audit checked effective host ingress policy, the age of the
relevant security configuration, listener state, and preservation-snapshot
timestamps. The effective policy predated the shadow window and had no rule
permitting the shadow port.

A harmless disposable HTTP listener, containing no application data or signing
material, was started on the former shadow port. It answered locally but an
independent external probe from the validation workstation could not reach it.
The listener was stopped and the port was confirmed released. These two pieces
of evidence establish that the former wildcard listener was not externally
reachable during the shadow window.

Sanitized reproduction outline:

```bash
# Host: inspect effective ingress and listener state without exporting rules.
nft list ruleset > /tmp/ingress-audit.txt
ss -ltn > /tmp/listener-audit.txt

# Host: harmless disposable listener; no application files or secrets.
python3 -m http.server <shadow-port> --bind <all-interfaces>

# Validation workstation: external reachability probe.
curl --connect-timeout 5 http://<deployment-host>:<shadow-port>/
```

Summarized result: host ingress did not permit the port; local probe returned
HTTP 200; external probe could not connect; final listener count was zero.
No incident response or key rotation was required.

## Backup Write Audit

The preservation snapshot was opened with SQLite URI `mode=ro` and query-only
mode. Its size and modification time remained unchanged, no journal or WAL
sidecar existed, `quick_check` returned `ok`, and aggregate timestamp checks
over the broad shadow window found zero activity. The checks covered audit,
activation, account, session, settings, relay, and other timestamp-bearing
tables without printing records.

Sanitized reproduction outline:

```bash
stat --format='%s:%Y' <preservation-snapshot>
find <snapshot-directory> -maxdepth 1 \
  -name '<snapshot-name>-journal' -o -name '<snapshot-name>-wal'
python3 verify_db_preservation.py \
  --before <preservation-snapshot> --after <disposable-copy>
```

Summarized result: `quick_check=ok`, sidecars `0`, shadow-window timestamp
activity `0`, snapshot content and metadata unchanged. No unexpected backup
writes were found.

## Relay Corrections

Relay claim behavior now:

- reads eligible candidates without a database-wide writer reservation;
- claims with one conditional update that rechecks status, lease expiry,
  availability, and attempt limits;
- accepts a claim only when exactly one row changes;
- bounds each connection and schema-initialization wait to 100 milliseconds;
- retries lock contention at most three times with short bounded delays;
- returns a stable sanitized `503` after exhausted contention.

Relay completion requires packet, lease, and client identity. Success and
failure completion each execute one conditional update requiring the packet to
remain leased to that exact lease and client; `rowcount` must be one. A stale
completer therefore cannot overwrite a newer lease.

Poll, status, enqueue, and complete routes log unexpected exceptions only on
the server and return `Internal server error` without SQLite text or paths.

The facade claim adapter uses `inspect.signature(...).bind_partial(...)` only
to choose the supported call shape. Signature inspection failures use the
timeout-aware production call shape; errors raised by the collaborator itself
propagate unchanged. Regression coverage proves zero-argument replacement
compatibility, the real `db.connect` receives 100 milliseconds, and an internal
collaborator `TypeError` is raised exactly once.

Adversarial coverage includes 12 synchronized claimers, empty-poll behavior
under an unrelated writer, held-writer contention during real schema and plan
initialization, exhausted-lock `503` sanitization, required completion identity,
a deterministic stale-completer interleaving, and generic-error sanitization on
all four routes.

## Preservation Verifier

`verify_db_preservation.py` now:

- requires two distinct existing regular files and rejects the same path or a
  hardlink to the same file;
- opens both files with SQLite URI `mode=ro` and query-only mode and closes a
  connection if read-only setup fails;
- never creates a missing input;
- requires a canonical minimum column set for all 11 protected tables and the
  `plans` expected-change table;
- rejects look-alike tables, missing required columns, and disappearance of
  any pre-deployment preservation column;
- permits expected changes only for `plans`; authorization, account, session,
  activation, invite, and audit tables can never be allowlisted;
- compares counts and digests over every pre-deployment column without
  printing record contents.

Tests cover nonexistent and empty files, same path, hardlinks where supported,
all table names with bogus schemas, missing canonical columns, forbidden
authorization allowlisting, read-only setup cleanup, protected-data changes,
matching real copies, and an allowed plan-only change.

## Local Validation

All commands used the bundled interpreter:

```text
D:\Axiangmu\AUSTART\openclaw_new_launcher\python-runtime\python.exe
```

Sanitized commands:

```powershell
& <bundled-python> -m unittest discover `
  -s license_server\tests -p 'test_verify_db_preservation.py' -v
& <bundled-python> -m unittest discover `
  -s license_server\tests -p 'test_relay_module.py' -v
& <bundled-python> -m unittest discover `
  -s license_server\tests -p 'test_*.py' -v
& <bundled-python> -m py_compile <server-and-package-python-files>
git diff --check
```

Recorded results:

- earlier release gate: 143 tests passed in 53.421 seconds;
- second-review focused verifier: 11/11 passed in 0.403 seconds;
- second-review focused relay: 10/10 passed in 2.507 seconds;
- second-review pre-deployment full suite: 148/148 passed in 54.329 seconds;
- pre-deployment `py_compile` and `git diff --check`: passed;
- final post-report full suite: 148/148 passed in 54.938 seconds;
- final focused verifier: 11/11 passed in 0.429 seconds;
- final focused relay: 10/10 passed in 2.477 seconds;
- final `py_compile`, `git diff --check`, and sensitive-data scan: passed.
- third-review focused relay: 13/13 passed in 2.696 seconds;
- third-review report/facade contracts: 3/3 passed in 0.095 seconds;
- third-review pre-deployment full suite: 152/152 passed in 54.299 seconds;
- third-review pre-deployment compile, diff, and sensitive-data gates: passed;
- third-review final focused relay: 13/13 passed in 2.684 seconds;
- third-review final report/facade contracts: 3/3 passed in 0.096 seconds;
- third-review final full suite: 152/152 passed in 54.362 seconds;
- third-review final `py_compile`, diff, and sensitive-data gates: passed.
- final-fix focused beta/template tests: 7/7 passed in 1.488 seconds;
- final-fix focused domain-boundary tests: 3/3 passed;
- final-fix route inventory: 15/15 passed;
- final-fix module, ownership, route, CLI, facade, and isolation contracts:
  57/57 passed in 2.229 seconds;
- final-fix pre-deployment full suite: 162/162 passed in 60.372 seconds;
- final-fix pre-deployment `py_compile`, diff, and sensitive-data gates: passed.
- final-fix post-report contract and isolation bundle: 62/62 passed in 2.515
  seconds;
- final-fix post-report full suite: 162/162 passed in 59.977 seconds;
- final-fix ownership graph: 24 modules with zero import cycles; all 34 package
  modules remained within the size contract, with `server.py` at 110 lines;
- final-fix final `py_compile`: 36/36 Python files passed;
- final-fix final diff check and 57-file sensitive-data scan: passed with zero
  findings.

## Safe Shadow

The validated stage contained `server.py`, the preservation verifier, and 34
package Python files. Compilation used an external bytecode cache so the stage
returned to Python source files only.

The successful shadow used an empty inherited environment plus:

```bash
shadow=$(mktemp -d)
cp <fresh-online-backup> "$shadow/disposable.sqlite3"
python3 <generate-new-disposable-signing-key> "$shadow/disposable-key"
env -i PATH="$PATH" HOME="$HOME" \
  LICENSE_HOST=<loopback-only> \
  LICENSE_PORT=<shadow-port> \
  LICENSE_BASE_DIR="$shadow" \
  LICENSE_DB="$shadow/disposable.sqlite3" \
  LICENSE_PRIVATE_KEY_FILE="$shadow/disposable-key" \
  python3 <validated-stage>/server.py serve
```

The process environment and listener state confirmed an explicit loopback-only
bind, the disposable database copy, and the generated disposable key. It had
no production signing setting or credential source. Results were:

```text
shadow_bind=localhost
shadow_assets=disposable
shadow_probes=7/7
shadow_unauthorized=1/1
shadow_security_headers=5/5
shadow_tables=12/12
shadow_key_match=yes
shadow_log_errors=0
backup_unchanged=yes
shadow_cleanup=complete
```

The preservation backup was never used directly by the process. The shadow was
stopped, its port was released, and all disposable database and key files were
removed.

At resume, the interrupted-run audit found no matching staged-server PID and
no disposable database/key directory. Three bytecode files created during the
aborted import were removed from the stage. Existing listeners belonged to
unrelated long-running services and were left untouched. The clean rerun moved
to an unused loopback port. One validation-only assertion initially checked an
internal configuration name instead of the public compatibility field; its
trap cleaned the process and assets, and the corrected full shadow then passed
the results above.

## Deployment Evidence

The latest program and SQLite online backup, created for the final whole-branch
fix, is:

```text
/opt/openclaw-license/backups/backend-modular-finalfix-20260714T192856Z
```

It contains the pre-switch server program, package, and an online SQLite
backup. The database returned `quick_check=ok`, and a temporary copy of both
program components compiled before any active path was changed.

Historical deployment evidence is preserved: two earlier guarded attempts
automatically restored program files only. The first encountered an upstream
denial while probing the public edge from the host; the second encountered a
journal timestamp syntax unsupported by the host. Neither rollback replaced or
restored the database or signing key. The subsequent deployment succeeded.

For this second-review deployment, one source-only stage preflight stopped
before the service or active program was touched because an earlier compile had
left bytecode in the temporary stage. The active program still matched its
backup. The bytecode was removed, compilation was redirected outside the
stage, and the guarded program-only deployment then succeeded without rollback.

For the third-review deployment, the fresh source-only stage compiled with an
external bytecode cache. The localhost shadow used a disposable copy of the new
online backup and a generated disposable key, then passed 7/7 endpoints, 12/12
exact table comparisons, and a zero-error log scan. The guarded program-only
switch passed rollback preflight and completed without rollback.

For the final-fix deployment, the first guarded switch deliberately retained
the old program paths until all checks passed. A validation-only curl HEAD
invocation expected a response body and failed on the correct empty HEAD body;
the guard automatically restored program files only. The restored program
matched the backup, all 12 protected tables remained exact, aggregates were
unchanged, the database passed `quick_check`, and the service key remained
consistent. After correcting the probe to use a real HEAD request, the guarded
switch and independent public validation succeeded. The database, signing key,
static assets, service configuration, environment, and authentication files
were never replaced or restored.

Only these active paths were replaced:

- `/opt/openclaw-license/server.py`
- `/opt/openclaw-license/luming_license/`

The database, signing key, static pages, service configuration, environment,
and authentication files were not replaced.

Sanitized deployment command outline and output:

```bash
# Preflight, before systemctl stop or active-path modification.
test -f <backup>/server.py
test -d <backup>/luming_license
rollback_preflight=$(mktemp -d)
cp -a <backup>/server.py "$rollback_preflight/server.py"
cp -a <backup>/luming_license "$rollback_preflight/luming_license"
PYTHONPYCACHEPREFIX=<temporary-cache> python3 -m py_compile \
  "$rollback_preflight/server.py" \
  $(find "$rollback_preflight/luming_license" -name '*.py')

# Guarded switch then validates stage manifests, service, endpoints,
# protected data, aggregates, key match, and journal before cleanup.
```

```text
deployment=successful
program_files_only=yes
rollback_preflight=passed
database_quick_check=ok
protected_tables=12/12
key_match=yes
local_probes=8/8
local_unauthorized=1/1
security_headers=5/5
journal_errors=0
public_probes=8/8
public_unauthorized=1/1
public_security_headers=5/5
```

## Source Match

The staged and active `server.py` files matched byte-for-byte. The staged and
active package trees contained the same 34 relative Python source files with
matching bytes. No program digest or signing-key fingerprint is recorded.

## Production Results

Immediate pre-switch, post-switch, and final aggregates were identical:

| Aggregate | Before | After | Final |
|---|---:|---:|---:|
| authorization records | 666 | 666 | 666 |
| activations | 156 | 156 | 156 |
| accounts | 1 | 1 | 1 |
| plans | 4 | 4 | 4 |
| active sessions | 7 | 7 | 7 |

The backup and live database both returned `quick_check=ok`; all 12 required
tables matched exactly by count and digest. The signing key matched before and
after deployment, and the final service public key was consistent with the
unchanged signing key. Only yes/no match results were emitted.

Local service checks: 8/8 endpoints and 5/5 security headers passed. Independent
public checks from the validation workstation: 8/8 endpoints and 5/5 security
headers passed. The configured purchase destination was non-empty without its
value being recorded.

Final state: service active, health HTTP 200, recent error-priority journal
entries `0`, recent `Traceback`/`Exception`/`CRITICAL`/`ERROR` markers `0`,
shadow-port listeners `0`, deployment artifacts `0`, and temporary stage
non-program files `0`.

## Preflight-First Program Rollback

Rollback restores program files only. It must not restore the SQLite database
or signing key. The following procedure fails before touching production when
either backup component is missing or does not compile:

```bash
set -euo pipefail
base=/opt/openclaw-license
backup=/opt/openclaw-license/backups/backend-modular-finalfix-20260714T192856Z
service=openclaw-license

test "$(readlink -f "$base")" = /opt/openclaw-license
test -f "$backup/server.py"
test -d "$backup/luming_license"

# Mandatory preflight occurs entirely in temporary storage.
preflight=$(mktemp -d)
cache=$(mktemp -d)
switched=0
finish() {
  status=$?
  trap - EXIT
  if [ "$status" -ne 0 ] && [ "$switched" -eq 1 ]; then
    systemctl stop "$service" || true
    if [ -f "$base/.server.py.pre-rollback" ]; then
      rm -f -- "$base/server.py"
      mv "$base/.server.py.pre-rollback" "$base/server.py"
    fi
    if [ -d "$base/.luming_license.pre-rollback" ]; then
      rm -rf -- "$base/luming_license"
      mv "$base/.luming_license.pre-rollback" "$base/luming_license"
    fi
    systemctl start "$service" || true
  fi
  rm -rf -- "$preflight" "$cache"
  if [ -n "${next:-}" ]; then rm -rf -- "$next"; fi
  exit "$status"
}
trap finish EXIT
cp -a "$backup/server.py" "$preflight/server.py"
cp -a "$backup/luming_license" "$preflight/luming_license"
PYTHONPYCACHEPREFIX="$cache" python3 -m py_compile \
  "$preflight/server.py" \
  $(find "$preflight/luming_license" -type f -name '*.py' -print)

# Only after both backup components compile may active program paths change.
next=$(mktemp -d "$base/.program-rollback-next.XXXXXX")
cp -a "$preflight/server.py" "$next/server.py"
cp -a "$preflight/luming_license" "$next/luming_license"
systemctl stop "$service"
switched=1
mv "$base/server.py" "$base/.server.py.pre-rollback"
mv "$base/luming_license" "$base/.luming_license.pre-rollback"
mv "$next/server.py" "$base/server.py"
mv "$next/luming_license" "$base/luming_license"
systemctl start "$service"
systemctl is-active --quiet "$service"
curl -fsS http://localhost:18791/health >/dev/null
switched=0
trap - EXIT
rm -f -- "$base/.server.py.pre-rollback" || true
rm -rf -- "$base/.luming_license.pre-rollback" "$next" || true
rm -rf -- "$preflight" "$cache" || true
```

The pre-switch database backup is a preservation artifact. Restoring it would
discard legitimate later writes and requires separate explicit approval.

## Sensitive Data Handling

Deployment authentication was used only by local tooling. This report contains
no credentials, network identifiers, private endpoint values, customer records,
authorization values, signing material, signing-key digest, live database path,
or signing-key path.
