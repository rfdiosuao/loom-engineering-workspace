# License Backend Modularization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the production authorization server into a tested modular monolith while preserving every public URL, SQLite record, LOOM client contract, CLI command, and current admin page behavior.

**Architecture:** Keep one Python process, one SQLite database, and the standard-library `ThreadingHTTPServer`. Turn `license_server/server.py` into a compatibility facade over a `luming_license` package; migrate one business domain at a time behind characterization tests, then move HTTP dispatch and CLI startup last.

**Tech Stack:** Python 3.10+, standard library HTTP/SQLite, `cryptography` Ed25519, `unittest`, static HTML/JavaScript, systemd.

## Global Constraints

- Do not migrate or recreate the production SQLite database.
- Do not replace or regenerate the production Ed25519 private key.
- Do not change existing public URLs, HTTP methods, stable error codes, or the LOOM activation/member/public-config payloads.
- Keep `serve`, `create-code`, `list-codes`, and `public-key` CLI commands callable through `license_server/server.py`.
- Do not introduce FastAPI, Django, React, Vue, Redis, a message queue, or a second service.
- Keep the deployed admin UI byte-for-byte behaviorally equivalent during this backend phase; UI modularization is a separate follow-up plan.
- Keep browser authentication on `Secure`, `HttpOnly`, `SameSite=Strict` cookies while retaining Bearer, `X-Admin-Session`, and `X-Admin-Token` compatibility.
- Every database write remains transactional; secret reveal/export and dangerous mutation must fail closed when backup or audit fails.
- Never add credentials, tokens, production rows, private keys, or customer data to source control, test fixtures, logs, or plan artifacts.
- Run the focused test after every extraction and the full `license_server/tests` suite before every commit.

## Scope Split

This is phase 1 of the approved design and produces an independently deployable backend refactor. Phase 2 will modularize `admin_console.html` and apply the approved UI information architecture against the stable package interfaces created here. Phase 3 will introduce release directories and atomic `current` switching after both application phases are stable.

## Target File Map

```text
license_server/
  server.py                         # Compatibility exports and CLI entry only
  luming_license/
    __init__.py                     # Package identity; no side effects
    config.py                       # Environment parsing and Settings
    errors.py                       # ActivationError and HTTP-safe error metadata
    timeutils.py                    # UTC/date helpers
    serialization.py                # Canonical JSON, masking and parsing helpers
    db.py                           # Connections, schema, seeds and online backup
    signing.py                      # Ed25519 key loading, public key and license signing
    security.py                     # Password/session/cookie/CORS/rate-limit primitives
    audit.py                        # Audit serialization, snapshots and writes
    domains/
      __init__.py
      accounts.py                   # Accounts, roles, invites and registration
      sessions.py                   # Admin sessions and auth status
      plans.py                      # Plans, gateway inheritance and public settings
      templates.py                  # Prompt templates and beta claims
      licenses.py                   # Code creation, inventory, reveal/export and updates
      activations.py                # Activation inventory, signed license and member APIs
      relay.py                      # Publish relay queue and leases
    http/
      __init__.py
      responses.py                  # Response/CORS/security-header mixin
      routes_public.py              # Health, root, public config, activation/member/template APIs
      routes_auth.py                # Login/register/bootstrap/logout
      routes_admin.py               # Protected admin reads and writes
      routes_relay.py               # Relay health/poll/status/submit/complete
      handler.py                    # Handler composition and request context
    cli.py                          # serve/create/list/public-key command implementations
  tests/
    test_backend_refactor_contract.py
    test_config_module.py
    test_db_module.py
    test_security_module.py
    test_domain_module_boundaries.py
    test_http_route_inventory.py
```

---

### Task 1: Freeze Compatibility Exports, Routes, and Schema

**Files:**
- Create: `license_server/tests/_support.py`
- Create: `license_server/tests/test_backend_refactor_contract.py`
- Create: `license_server/tests/test_http_route_inventory.py`
- Modify: `license_server/tests/test_license_flow.py`

**Interfaces:**
- Consumes: existing `load_server(temp_dir: Path)` test loader.
- Produces: `COMPAT_EXPORTS`, `EXPECTED_TABLE_COLUMNS`, and `EXPECTED_ROUTE_MARKERS`, which remain unchanged throughout this plan.

- [ ] **Step 1: Add the compatibility export and schema tests**

Create `_support.py` so both importlib-loaded compatibility tests and direct package tests resolve one package identity:

```python
from __future__ import annotations

import sys
from pathlib import Path

LICENSE_SERVER_ROOT = Path(__file__).resolve().parents[1]
root_text = str(LICENSE_SERVER_ROOT)
if root_text not in sys.path:
    sys.path.insert(0, root_text)
```

Import `LICENSE_SERVER_ROOT` near the top of `test_license_flow.py` before loading `server.py`:

```python
from _support import LICENSE_SERVER_ROOT

SERVER_PATH = LICENSE_SERVER_ROOT / "server.py"
```

Create `test_backend_refactor_contract.py` with concrete export and schema assertions:

```python
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from test_license_flow import load_server


COMPAT_EXPORTS = {
    "Handler", "ActivationError", "connect", "init_db", "make_db_backup",
    "create_account_record", "create_admin_session", "create_code_records",
    "get_code_rows", "get_code_secret_rows", "get_activation_rows",
    "get_plan_rows", "client_public_config", "update_public_settings",
    "activate_code", "find_member_license", "publish_relay_enqueue",
    "publish_relay_claim", "publish_relay_complete", "publish_relay_status",
    "main", "serve",
}

EXPECTED_TABLE_COLUMNS = {
    "codes": {"code_hash", "full_code", "licensee", "expires", "max_activations", "owner_account_id"},
    "activations": {"id", "code_hash", "install_id", "device_id", "license_json", "activated_at"},
    "accounts": {"id", "username", "password_hash", "role", "status"},
    "admin_sessions": {"session_hash", "account_id", "expires_at", "revoked_at"},
    "plans": {"plan_key", "features_json", "duration_days", "disabled"},
    "settings": {"key", "value_json", "updated_at"},
    "audit_logs": {"id", "action", "before_json", "after_json", "created_at"},
    "publish_relay_packets": {"packet_id", "status", "packet_json", "lease_id", "attempts"},
}


class BackendRefactorContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.server = load_server(Path(self.temp.name))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_server_facade_exports_stable_names(self) -> None:
        self.assertEqual(set(), COMPAT_EXPORTS - set(dir(self.server)))

    def test_schema_keeps_required_columns(self) -> None:
        with self.server.connect() as connection:
            for table, required in EXPECTED_TABLE_COLUMNS.items():
                actual = {row[1] for row in connection.execute(f"pragma table_info({table})")}
                self.assertEqual(set(), required - actual, table)
```

- [ ] **Step 2: Add the route inventory test**

Create `test_http_route_inventory.py` and assert all externally consumed markers remain registered:

```python
from __future__ import annotations

import unittest
from pathlib import Path


SERVER = Path(__file__).resolve().parents[1] / "server.py"
EXPECTED_ROUTE_MARKERS = {
    "/health", "/admin", "/api/client/config", "/activate",
    "/api/member/activate", "/api/member/current", "/api/member/usage",
    "/admin/api/auth/login", "/admin/api/auth/register", "/admin/api/auth/logout",
    "/admin/api/codes", "/admin/api/codes/reveal", "/admin/api/codes/export",
    "/admin/api/activations/delete", "/admin/api/plans", "/admin/api/public-settings",
    "/api/templates", "/api/beta/status", "/api/lumi/relay/health",
    "/api/lumi/relay/poll", "/api/lumi/relay/status",
}


class HttpRouteInventoryTests(unittest.TestCase):
    def test_compatibility_entry_references_every_route_until_router_migration(self) -> None:
        source = SERVER.read_text(encoding="utf-8")
        missing = sorted(marker for marker in EXPECTED_ROUTE_MARKERS if marker not in source)
        self.assertEqual([], missing)
```

The route test deliberately starts as a source contract. Task 10 changes it to inspect the new router registry while preserving the same marker set.

- [ ] **Step 3: Run the new safety-net tests**

Run:

```powershell
.\openclaw_new_launcher\python-runtime\python.exe -m unittest discover -s license_server\tests -p "test_backend_refactor_contract.py"
.\openclaw_new_launcher\python-runtime\python.exe -m unittest discover -s license_server\tests -p "test_http_route_inventory.py"
```

Expected: both commands pass before extraction begins.

- [ ] **Step 4: Run and record the full baseline**

Run:

```powershell
.\openclaw_new_launcher\python-runtime\python.exe -m unittest discover -s license_server\tests -p "test_*.py"
```

Expected: all tests pass; the current baseline is at least 49 tests after adding the two contract files.

- [ ] **Step 5: Commit the safety net**

```powershell
git add license_server/tests/_support.py license_server/tests/test_license_flow.py license_server/tests/test_backend_refactor_contract.py license_server/tests/test_http_route_inventory.py
git commit -m "test: freeze license backend compatibility"
```

---

### Task 2: Create Core Package, Errors, Time, and Configuration

**Files:**
- Create: `license_server/luming_license/__init__.py`
- Create: `license_server/luming_license/errors.py`
- Create: `license_server/luming_license/timeutils.py`
- Create: `license_server/luming_license/config.py`
- Create: `license_server/tests/test_config_module.py`
- Modify: `license_server/server.py`

**Interfaces:**
- Produces: `ActivationError`, `utc_now()`, `now_ms()`, `add_days_iso()`, `add_days_date()`, `utc_filename_stamp()`, `bounded_int_env()`, `Settings.from_env()` and module-level `SETTINGS`.
- Preserves: existing `server.ActivationError` and configuration constants through re-export aliases.

- [ ] **Step 1: Write failing configuration tests**

```python
from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from _support import LICENSE_SERVER_ROOT
from luming_license.config import Settings, bounded_int_env


class ConfigModuleTests(unittest.TestCase):
    def test_bounded_integer_falls_back_and_clamps(self) -> None:
        with patch.dict(os.environ, {"LIMIT": "invalid"}, clear=False):
            self.assertEqual(10, bounded_int_env("LIMIT", 10, 1, 20))
        with patch.dict(os.environ, {"LIMIT": "99"}, clear=False):
            self.assertEqual(20, bounded_int_env("LIMIT", 10, 1, 20))

    def test_settings_normalize_origins_and_paths(self) -> None:
        with patch.dict(os.environ, {
            "LICENSE_DB": "C:/tmp/license.db",
            "LICENSE_ADMIN_CORS_ORIGINS": "https://license.heang.top/, https://admin.example.com",
            "LICENSE_PORT": "19001",
        }, clear=False):
            settings = Settings.from_env()
        self.assertEqual(19001, settings.port)
        self.assertEqual("C:/tmp/license.db", settings.db_path)
        self.assertEqual(
            {"https://license.heang.top", "https://admin.example.com"},
            settings.admin_cors_allowed_origins,
        )
```

- [ ] **Step 2: Run the focused test and confirm the package is missing**

Run:

```powershell
.\openclaw_new_launcher\python-runtime\python.exe -m unittest discover -s license_server\tests -p "test_config_module.py"
```

Expected: fail with `ModuleNotFoundError: No module named 'luming_license'`.

- [ ] **Step 3: Implement the core interfaces**

Use immutable settings and keep import-time environment behavior:

```python
# luming_license/errors.py
class ActivationError(RuntimeError):
    def __init__(self, message: str, status: int = 400, code: str = "REQUEST_INVALID"):
        super().__init__(message)
        self.status = status
        self.code = code
```

```python
# luming_license/config.py
from dataclasses import dataclass
import os

DEFAULT_ADMIN_CORS_ORIGINS = frozenset({
    "http://127.0.0.1:18791", "http://localhost:18791",
    "http://118.145.98.220", "http://118.145.98.220:80",
    "https://118.145.98.220", "https://license.heang.top",
})

def bounded_int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)) or default)
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))

@dataclass(frozen=True)
class Settings:
    db_path: str
    backup_dir: str
    private_key_file: str
    admin_token_file: str
    logo_file: str
    host: str
    port: int
    admin_session_ttl_days: int
    admin_cors_allowed_origins: frozenset[str]
    public_url: str
    support_url: str
    gateway_base_url: str
    gateway_image_base_url: str
    gateway_video_base_url: str
    gateway_token: str
    gateway_image_token: str
    gateway_video_token: str
    gateway_default_model: str
    gateway_image_model: str
    gateway_video_model: str
    gateway_models: tuple[str, ...]
    login_rate_limit_attempts: int
    login_rate_limit_window_seconds: int
    login_rate_limit_lockout_seconds: int
    register_rate_limit_attempts: int
    register_rate_limit_window_seconds: int
    register_rate_limit_lockout_seconds: int
    publish_relay_token: str
    publish_relay_default_lease_ms: int
    publish_relay_default_wait_ms: int
    publish_relay_max_attempts: int
    max_bulk_code_hashes: int

    @classmethod
    def from_env(cls) -> "Settings":
        base = os.environ.get("LICENSE_BASE_DIR", "/opt/openclaw-license")
        origins = frozenset(
            item.strip().rstrip("/")
            for item in os.environ.get("LICENSE_ADMIN_CORS_ORIGINS", "").split(",")
            if item.strip()
        ) or DEFAULT_ADMIN_CORS_ORIGINS
        gateway_models = tuple(
            item.strip()
            for item in os.environ.get("MEMBER_GATEWAY_MODELS", "").replace("，", ",").split(",")
            if item.strip()
        )
        public_url = os.environ.get("LICENSE_PUBLIC_URL", "https://license.heang.top/").strip()
        return cls(
            db_path=os.environ.get("LICENSE_DB", os.path.join(base, "license.db")),
            backup_dir=os.environ.get("LICENSE_BACKUP_DIR", os.path.join(base, "backups")),
            private_key_file=os.environ.get("LICENSE_PRIVATE_KEY_FILE", os.path.join(base, "private_key.b64")),
            admin_token_file=os.environ.get("LICENSE_ADMIN_TOKEN_FILE", os.path.join(base, "admin_token.txt")),
            logo_file=os.environ.get("LICENSE_LOGO_FILE", os.path.join(base, "logo.ico")),
            host=os.environ.get("LICENSE_HOST", "0.0.0.0"),
            port=int(os.environ.get("LICENSE_PORT", "18791")),
            admin_session_ttl_days=bounded_int_env("LICENSE_ADMIN_SESSION_TTL_DAYS", 30, 1, 3650),
            admin_cors_allowed_origins=origins,
            public_url=public_url,
            support_url=os.environ.get("LICENSE_SUPPORT_URL", public_url).strip(),
            gateway_base_url=os.environ.get("MEMBER_GATEWAY_BASE_URL", "").strip().rstrip("/"),
            gateway_image_base_url=os.environ.get("MEMBER_GATEWAY_IMAGE_BASE_URL", "").strip().rstrip("/"),
            gateway_video_base_url=os.environ.get("MEMBER_GATEWAY_VIDEO_BASE_URL", "").strip().rstrip("/"),
            gateway_token=os.environ.get("MEMBER_GATEWAY_TOKEN", "").strip(),
            gateway_image_token=os.environ.get("MEMBER_GATEWAY_IMAGE_TOKEN", "").strip(),
            gateway_video_token=os.environ.get("MEMBER_GATEWAY_VIDEO_TOKEN", "").strip(),
            gateway_default_model=os.environ.get("MEMBER_GATEWAY_DEFAULT_MODEL", "").strip(),
            gateway_image_model=os.environ.get("MEMBER_GATEWAY_IMAGE_MODEL", "").strip(),
            gateway_video_model=os.environ.get("MEMBER_GATEWAY_VIDEO_MODEL", "").strip(),
            gateway_models=gateway_models,
            login_rate_limit_attempts=bounded_int_env("LICENSE_LOGIN_RATE_LIMIT_ATTEMPTS", 10, 1, 100),
            login_rate_limit_window_seconds=bounded_int_env("LICENSE_LOGIN_RATE_LIMIT_WINDOW_SECONDS", 600, 60, 86400),
            login_rate_limit_lockout_seconds=bounded_int_env("LICENSE_LOGIN_RATE_LIMIT_LOCKOUT_SECONDS", 900, 60, 86400),
            register_rate_limit_attempts=bounded_int_env("LICENSE_REGISTER_RATE_LIMIT_ATTEMPTS", 8, 1, 100),
            register_rate_limit_window_seconds=bounded_int_env("LICENSE_REGISTER_RATE_LIMIT_WINDOW_SECONDS", 600, 60, 86400),
            register_rate_limit_lockout_seconds=bounded_int_env("LICENSE_REGISTER_RATE_LIMIT_LOCKOUT_SECONDS", 900, 60, 86400),
            publish_relay_token=(os.environ.get("OPENCLAW_PUBLISH_RELAY_TOKEN") or os.environ.get("PUBLISH_RELAY_TOKEN") or "").strip(),
            publish_relay_default_lease_ms=bounded_int_env("PUBLISH_RELAY_DEFAULT_LEASE_MS", 30000, 1000, 900000),
            publish_relay_default_wait_ms=bounded_int_env("PUBLISH_RELAY_DEFAULT_WAIT_MS", 15000, 0, 900000),
            publish_relay_max_attempts=bounded_int_env("PUBLISH_RELAY_MAX_ATTEMPTS", 5, 1, 20),
            max_bulk_code_hashes=bounded_int_env("LICENSE_MAX_BULK_CODE_HASHES", 1000, 1, 5000),
        )

SETTINGS = Settings.from_env()
```

Move the existing UTC/date helper bodies into `timeutils.py` and add the deterministic filename helper:

```python
def utc_filename_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
```

Import and re-export them from `server.py`; remove the duplicate `ActivationError` definition only after all tests pass.

- [ ] **Step 4: Run configuration and compatibility tests**

```powershell
.\openclaw_new_launcher\python-runtime\python.exe -m unittest discover -s license_server\tests -p "test_config_module.py"
.\openclaw_new_launcher\python-runtime\python.exe -m unittest discover -s license_server\tests -p "test_backend_refactor_contract.py"
```

Expected: both pass.

- [ ] **Step 5: Run the full suite and commit**

```powershell
.\openclaw_new_launcher\python-runtime\python.exe -m unittest discover -s license_server\tests -p "test_*.py"
git add license_server/server.py license_server/luming_license license_server/tests/test_config_module.py
git commit -m "refactor: extract license core configuration"
```

Expected: full suite passes before commit.

---

### Task 3: Extract Serialization, Signing, and Database Infrastructure

**Files:**
- Create: `license_server/luming_license/serialization.py`
- Create: `license_server/luming_license/signing.py`
- Create: `license_server/luming_license/db.py`
- Create: `license_server/tests/test_db_module.py`
- Modify: `license_server/server.py`
- Modify: `license_server/tests/test_license_flow.py`

**Interfaces:**
- Produces: `canonical()`, `load_json_value()`, `parse_json_object()`, `parse_models()`, `connect()`, `init_db()`, `ensure_column()`, `seed_default_settings()`, `seed_default_plans()`, `online_backup(label)`, `load_private_key()`, `public_key_b64()`, `sign_license()`.
- `connect()` continues returning a context-manageable SQLite connection with `row_factory=sqlite3.Row`.

- [ ] **Step 1: Add database ownership tests**

```python
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from test_license_flow import load_server


class DatabaseModuleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.server = load_server(Path(self.temp.name))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_connect_initializes_schema_idempotently(self) -> None:
        with self.server.connect() as first:
            first.execute("insert into settings (key, value_json, updated_at) values ('proof', '{}', 'now')")
            first.commit()
        with self.server.connect() as second:
            self.assertEqual(1, second.execute("select count(*) from settings where key='proof'").fetchone()[0])

    def test_online_backup_preserves_authorization_rows(self) -> None:
        code = self.server.create_code_records(
            count=1, licensee="Backup", edition="pro", features=["openclaw"],
            expires="2099-01-01", max_activations=1,
        )[0]
        backup = Path(self.server.make_db_backup("module-test"))
        self.assertTrue(backup.is_file())
        import sqlite3
        with sqlite3.connect(backup) as copied:
            self.assertEqual(1, copied.execute("select count(*) from codes where full_code=?", (code,)).fetchone()[0])
```

- [ ] **Step 2: Run the test before extraction**

Run the file and confirm it passes against the monolith, establishing behavior rather than a missing-symbol failure.

```powershell
.\openclaw_new_launcher\python-runtime\python.exe -m unittest discover -s license_server\tests -p "test_db_module.py"
```

- [ ] **Step 3: Move infrastructure with unchanged behavior**

Move these exact functions from `server.py`:

```text
serialization.py: canonical, parse_features, parse_models, parse_json_object,
                  parse_optional_models, load_json_value, normalize_string, clamp_int
signing.py:       load_private_key, public_key_b64, sign_license
db.py:            ClosingConnection, connect, ensure_column, init_db,
                  seed_default_settings, seed_default_plans, make_db_backup
```

`db.py` must use the online SQLite backup API rather than copying a live database:

```python
def make_db_backup(label: str) -> str:
    os.makedirs(SETTINGS.backup_dir, exist_ok=True)
    safe_label = "".join(character if character.isalnum() or character in "-_" else "-" for character in label.strip()) or "backup"
    destination = os.path.join(SETTINGS.backup_dir, f"{safe_label}-{utc_filename_stamp()}.db")
    with connect() as source, sqlite3.connect(destination) as target:
        source.backup(target)
    return destination
```

Retain the current filename convention if it differs; the invariant is online backup plus a returned absolute path. Re-export every moved function from `server.py`.

Import the module as `from luming_license import db` and change existing mutation call sites to `db.make_db_backup(label)`. This keeps one live function owner and makes failure/race tests patch the exact callable being executed.

- [ ] **Step 4: Patch test monkeypatch ownership**

Where a test replaces `self.server.make_db_backup`, patch the owning module instead:

```python
from _support import LICENSE_SERVER_ROOT
from luming_license import db

original_make_db_backup = db.make_db_backup
db.make_db_backup = change_owner_after_snapshot
self.addCleanup(setattr, db, "make_db_backup", original_make_db_backup)
```

Only change patch targets; do not relax expected HTTP results.

- [ ] **Step 5: Run database, preservation, and full tests**

```powershell
.\openclaw_new_launcher\python-runtime\python.exe -m unittest discover -s license_server\tests -p "test_db_module.py"
.\openclaw_new_launcher\python-runtime\python.exe -m unittest discover -s license_server\tests -p "test_verify_db_preservation.py"
.\openclaw_new_launcher\python-runtime\python.exe -m unittest discover -s license_server\tests -p "test_*.py"
```

Expected: all pass.

- [ ] **Step 6: Commit**

```powershell
git add license_server/server.py license_server/luming_license license_server/tests/test_db_module.py license_server/tests/test_license_flow.py
git commit -m "refactor: extract license database infrastructure"
```

---

### Task 4: Extract Security, Accounts, Invites, and Sessions

**Files:**
- Create: `license_server/luming_license/security.py`
- Create: `license_server/luming_license/domains/__init__.py`
- Create: `license_server/luming_license/domains/accounts.py`
- Create: `license_server/luming_license/domains/sessions.py`
- Create: `license_server/tests/test_security_module.py`
- Modify: `license_server/server.py`

**Interfaces:**
- `security.py`: password and token helpers, `require_confirmation()`, cookie parsing/creation, CORS checks, rate-limit functions.
- `accounts.py`: existing account/invite CRUD and registration function names.
- `sessions.py`: `create_admin_session()`, `revoke_admin_session()`, `load_admin_context_from_session()`, `load_legacy_admin_context()`, `auth_status_snapshot()`.

- [ ] **Step 1: Write direct security tests**

```python
from __future__ import annotations

import unittest
from email.message import Message

from _support import LICENSE_SERVER_ROOT
from luming_license.errors import ActivationError
from luming_license.security import admin_session_cookie, password_hash, request_admin_token, require_confirmation, verify_password


class SecurityModuleTests(unittest.TestCase):
    def test_password_round_trip_and_wrong_password(self) -> None:
        encoded = password_hash("correct-password-123")
        self.assertTrue(verify_password("correct-password-123", encoded))
        self.assertFalse(verify_password("wrong-password-123", encoded))

    def test_cookie_token_is_used_when_headers_are_absent(self) -> None:
        headers = Message()
        headers["Cookie"] = "__Host-luming_admin_session=session-value"
        self.assertEqual("session-value", request_admin_token(headers))

    def test_dangerous_confirmation_fails_closed(self) -> None:
        with self.assertRaises(ActivationError):
            require_confirmation({}, "DELETE")

    def test_session_cookie_has_required_attributes(self) -> None:
        cookie = admin_session_cookie("session-value", max_age=60)
        for marker in ("HttpOnly", "Secure", "SameSite=Strict", "Path=/", "Max-Age=60"):
            self.assertIn(marker, cookie)
```

- [ ] **Step 2: Run the focused test and observe missing modules**

```powershell
.\openclaw_new_launcher\python-runtime\python.exe -m unittest discover -s license_server\tests -p "test_security_module.py"
```

Expected: fail until `security.py` exists.

- [ ] **Step 3: Extract exact function groups**

Move without changing signatures:

```text
security.py: password_hash, verify_password, admin_session_token_hash,
             generate_admin_session_token, normalize_code_expires,
             require_confirmation, extract_bearer_token,
             extract_admin_session_cookie, request_admin_token,
             admin_session_cookie, rate_limit_storage_key,
             rate_limit_check, rate_limit_record_failure,
             rate_limit_clear, rate_limit_consume,
             admin_cors_origin_allowed, is_admin_request_path
accounts.py: normalize_username, normalize_account_role,
             normalize_account_status, role_rank, account_row_public,
             get_account_by_username, get_account_by_id,
             list_account_rows, account_summary_row,
             normalize_invite_code, generate_invite_code,
             invite_row_public, count_invites, list_invite_rows,
             get_invite_by_code, _create_account_record_on_connection,
             create_invite_record, toggle_invite_record,
             register_account_with_invite, create_account_record,
             update_account_record, count_accounts,
             count_active_super_admins
sessions.py: admin_context_from_row, load_admin_context_from_session,
             load_legacy_admin_context, create_admin_session,
             revoke_admin_session, auth_status_snapshot
```

Keep account role/status constants in `accounts.py` and re-export them from `server.py`.

- [ ] **Step 4: Run security and authentication flow tests**

```powershell
.\openclaw_new_launcher\python-runtime\python.exe -m unittest discover -s license_server\tests -p "test_security_module.py"
.\openclaw_new_launcher\python-runtime\python.exe -m unittest discover -s license_server\tests -p "test_license_flow.py"
```

Expected: cookie, login, registration, invite, CORS, rate-limit and cross-tenant tests pass unchanged.

- [ ] **Step 5: Run the full suite and commit**

```powershell
.\openclaw_new_launcher\python-runtime\python.exe -m unittest discover -s license_server\tests -p "test_*.py"
git add license_server/server.py license_server/luming_license license_server/tests/test_security_module.py
git commit -m "refactor: extract license identity modules"
```

---

### Task 5: Extract Audit Infrastructure

**Files:**
- Create: `license_server/luming_license/audit.py`
- Create: `license_server/tests/test_domain_module_boundaries.py`
- Modify: `license_server/server.py`
- Modify: `license_server/tests/test_license_flow.py`

**Interfaces:**
- Produces: `audit_json()`, `masked_code_label()`, `audit_public_value()`, `add_audit_log()`, `masked_secret()`, `get_audit_rows()` and snapshot helpers.
- Consumes: `db.connect`, `db.make_db_backup`, account-context helpers and UTC time.

- [ ] **Step 1: Add module ownership assertions**

```python
from __future__ import annotations

import unittest

from _support import LICENSE_SERVER_ROOT
from luming_license import audit
from luming_license.domains import accounts, sessions


class DomainModuleBoundaryTests(unittest.TestCase):
    def test_identity_and_audit_functions_have_single_owners(self) -> None:
        self.assertEqual("luming_license.domains.accounts", accounts.create_account_record.__module__)
        self.assertEqual("luming_license.domains.sessions", sessions.create_admin_session.__module__)
        self.assertEqual("luming_license.audit", audit.add_audit_log.__module__)

    def test_audit_masks_nested_secret_keys(self) -> None:
        masked = audit.audit_public_value({"gatewayToken": "secret", "nested": {"apiKey": "secret-2"}})
        self.assertNotIn("secret", str(masked))
        self.assertNotIn("secret-2", str(masked))
```

- [ ] **Step 2: Run the focused test and confirm audit is not extracted**

```powershell
.\openclaw_new_launcher\python-runtime\python.exe -m unittest discover -s license_server\tests -p "test_domain_module_boundaries.py"
```

Expected: fail importing `luming_license.audit`.

- [ ] **Step 3: Extract the audit group**

Move these exact functions to `audit.py`:

```text
audit_json, masked_code_label, audit_public_value, add_audit_log,
masked_secret, get_audit_rows
```

`add_audit_log()` must retain recursive redaction before JSON serialization. Code and inventory snapshot functions stay with the monolith until Task 8, where they move beside the license records they serialize; this prevents an audit/licenses import cycle.

- [ ] **Step 4: Update monkeypatches to target `luming_license.audit` or `luming_license.db`**

For audit failure tests, patch the function used by the owning domain module, not the facade. Preserve the assertion that reveal/export returns no secret when audit writing fails.

- [ ] **Step 5: Run focused security tests and full suite**

```powershell
.\openclaw_new_launcher\python-runtime\python.exe -m unittest discover -s license_server\tests -p "test_domain_module_boundaries.py"
.\openclaw_new_launcher\python-runtime\python.exe -m unittest discover -s license_server\tests -p "test_license_flow.py"
.\openclaw_new_launcher\python-runtime\python.exe -m unittest discover -s license_server\tests -p "test_*.py"
```

- [ ] **Step 6: Commit**

```powershell
git add license_server/server.py license_server/luming_license/audit.py license_server/tests/test_domain_module_boundaries.py license_server/tests/test_license_flow.py
git commit -m "refactor: extract license audit module"
```

---

### Task 6: Extract Plans, Public Settings, and Account Gateway

**Files:**
- Create: `license_server/luming_license/domains/plans.py`
- Create: `license_server/tests/test_plans_module.py`
- Modify: `license_server/server.py`

**Interfaces:**
- Produces existing plan/public-settings/gateway function signatures and constants.
- Preserves `/api/client/config` fields and the configurable LOOM purchase/support URLs.

- [ ] **Step 1: Add public-config regression tests against the owner module**

```python
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from test_license_flow import load_server


class PlansModuleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.server = load_server(Path(self.temp.name))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_purchase_url_remains_dynamically_configurable(self) -> None:
        self.server.update_public_settings({
            "cardSiteEnabled": True,
            "cardSiteLabel": "购买授权",
            "cardSiteUrl": "https://shop.example.com/luming",
            "supportUrl": "https://support.example.com/luming",
        })
        config = self.server.client_public_config()
        self.assertEqual("https://shop.example.com/luming", config["purchaseUrl"])
        self.assertEqual("https://support.example.com/luming", config["supportUrl"])

    def test_plan_application_does_not_expose_gateway_secret(self) -> None:
        rows = self.server.get_plan_rows(include_disabled=True)
        self.assertTrue(rows)
        self.assertNotIn("gatewayToken", rows[0])
```

- [ ] **Step 2: Run the tests before extraction**

```powershell
.\openclaw_new_launcher\python-runtime\python.exe -m unittest discover -s license_server\tests -p "test_plans_module.py"
```

Expected: pass against the facade baseline.

- [ ] **Step 3: Extract the plan and gateway group**

Move:

```text
normalize_plan_key, plan_row_public, get_plan_rows, get_plan_row,
public_settings, client_public_config, update_public_settings,
validate_gateway_url, default_account_gateway_settings,
account_gateway_settings_public, get_account_gateway_settings,
upsert_account_gateway_settings, has_explicit_gateway_value,
apply_account_gateway_defaults, upsert_plan_record,
disable_plan_record, apply_plan_template
```

Keep `DEFAULT_PUBLIC_SETTINGS`, default gateway values and default model lists in this module, sourced from `config.SETTINGS` or explicit environment-backed config fields. Re-export all compatibility names from `server.py`.

- [ ] **Step 4: Run plan/public config and full tests**

```powershell
.\openclaw_new_launcher\python-runtime\python.exe -m unittest discover -s license_server\tests -p "test_plans_module.py"
.\openclaw_new_launcher\python-runtime\python.exe -m unittest discover -s license_server\tests -p "test_license_flow.py"
.\openclaw_new_launcher\python-runtime\python.exe -m unittest discover -s license_server\tests -p "test_*.py"
```

- [ ] **Step 5: Commit**

```powershell
git add license_server/server.py license_server/luming_license/domains/plans.py license_server/tests/test_plans_module.py
git commit -m "refactor: extract license plan configuration"
```

---

### Task 7: Extract Templates and Beta Claims

**Files:**
- Create: `license_server/luming_license/domains/templates.py`
- Create: `license_server/tests/test_templates_module.py`
- Modify: `license_server/server.py`

**Interfaces:**
- Produces existing beta and template function names with unchanged dictionaries.
- Consumes account defaults, plans, code creation and database functions.

- [ ] **Step 1: Add template and quota tests**

```python
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from test_license_flow import load_server


class TemplatesModuleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.server = load_server(Path(self.temp.name))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_default_templates_seed_idempotently(self) -> None:
        self.server.seed_default_templates()
        first = self.server.list_templates()
        self.server.seed_default_templates()
        self.assertEqual(first, self.server.list_templates())

    def test_beta_status_never_reports_negative_remaining(self) -> None:
        status = self.server.beta_status_snapshot()
        self.assertGreaterEqual(status["remaining"], 0)
```

- [ ] **Step 2: Run the baseline tests**

```powershell
.\openclaw_new_launcher\python-runtime\python.exe -m unittest discover -s license_server\tests -p "test_templates_module.py"
```

- [ ] **Step 3: Extract exact beta/template functions and constants**

```text
beta_today, get_beta_config, set_beta_config, beta_owner_account_id,
beta_claims_count_today, beta_status_snapshot, beta_claim_code,
template_public, seed_default_templates, list_templates,
save_template, delete_template
```

Keep `DEFAULT_TEMPLATES`, `TEMPLATE_KINDS`, `BETA_CONFIG_KEY` and `BETA_DEFAULTS` with their owning functions. Use function-local imports for `licenses.create_code_records` to prevent a templates/licenses import cycle.

- [ ] **Step 4: Run template, full flow, and full suite tests**

```powershell
.\openclaw_new_launcher\python-runtime\python.exe -m unittest discover -s license_server\tests -p "test_templates_module.py"
.\openclaw_new_launcher\python-runtime\python.exe -m unittest discover -s license_server\tests -p "test_license_flow.py"
.\openclaw_new_launcher\python-runtime\python.exe -m unittest discover -s license_server\tests -p "test_*.py"
```

- [ ] **Step 5: Commit**

```powershell
git add license_server/server.py license_server/luming_license/domains/templates.py license_server/tests/test_templates_module.py
git commit -m "refactor: extract license template domain"
```

---

### Task 8: Extract Licenses, Activations, and Member Responses

**Files:**
- Create: `license_server/luming_license/domains/licenses.py`
- Create: `license_server/luming_license/domains/activations.py`
- Create: `license_server/tests/test_license_domain_modules.py`
- Modify: `license_server/server.py`
- Modify: `license_server/tests/test_license_flow.py`

**Interfaces:**
- `licenses.py` owns code creation, ownership, inventory, secret access and mutation.
- `activations.py` owns activation rows, signed-license building, member lookup/response and `activate_code()`.
- Existing facade function names and HTTP payloads remain unchanged.

- [ ] **Step 1: Add ownership and signed-payload tests**

```python
from __future__ import annotations

import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from test_license_flow import load_server


class LicenseDomainModuleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.server = load_server(Path(self.temp.name))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_created_code_activates_with_same_public_fields(self) -> None:
        expires = (date.today() + timedelta(days=30)).isoformat()
        code = self.server.create_code_records(
            count=1, licensee="Module Customer", edition="pro",
            features=["openclaw", "acquisition.workbench"],
            expires=expires, max_activations=1,
        )[0]
        result = self.server.activate_code({"code": code, "installId": "module-install", "deviceId": "module-device"})
        self.assertEqual("Module Customer", result["payload"]["licensee"])
        self.assertEqual(expires, result["payload"]["expires"])
        self.assertNotIn("privateKey", str(result))
```

- [ ] **Step 2: Run the baseline test**

```powershell
.\openclaw_new_launcher\python-runtime\python.exe -m unittest discover -s license_server\tests -p "test_license_domain_modules.py"
```

- [ ] **Step 3: Extract the license group**

Move to `licenses.py`:

```text
code_hash, normalize_code_hashes, make_code, is_super_admin_context,
context_account_id, code_row_owned_by_context, create_code_records,
update_code_record, bulk_update_code_records, get_code_rows,
get_code_secret_rows, code_row_snapshot, get_code_snapshot,
get_code_snapshots, get_inventory_snapshot, create_codes, list_codes
```

The module imports audit and backup modules, and it must call `audit.add_audit_log` before returning reveal/export secrets. Keep `MAX_BULK_CODE_HASHES`, `MAX_CODE_SECRET_EXPORT`, commercial/default feature constants with this domain.

- [ ] **Step 4: Extract activation/member functions**

Move to `activations.py`:

```text
activation_row_public, get_activation_rows, get_all_activation_rows,
get_activation_snapshot, apply_member_fields, build_signed_license,
member_response, find_member_license, activate_code
```

`activate_code()` continues raising `ActivationError` with `LICENSE_INVALID_REQUEST`, `LICENSE_INVALID`, `LICENSE_DISABLED`, `LICENSE_EXPIRED`, `LICENSE_DATA_INVALID`, and `DEVICE_MISMATCH` where currently applicable.

- [ ] **Step 5: Update monkeypatch targets without weakening race tests**

The owner-change race test patches `luming_license.db.make_db_backup`, which is the callable used by both domains. It must still expect `404` and verify the row remains present when ownership changes after the snapshot.

- [ ] **Step 6: Run all license, member, and isolation tests**

```powershell
.\openclaw_new_launcher\python-runtime\python.exe -m unittest discover -s license_server\tests -p "test_license_domain_modules.py"
.\openclaw_new_launcher\python-runtime\python.exe -m unittest discover -s license_server\tests -p "test_license_flow.py"
.\openclaw_new_launcher\python-runtime\python.exe -m unittest discover -s license_server\tests -p "test_*.py"
```

Expected: masked inventory, secret reveal/export, audit failure, activation limits, member gateway separation and tenant isolation all pass.

- [ ] **Step 7: Commit**

```powershell
git add license_server/server.py license_server/luming_license/domains/licenses.py license_server/luming_license/domains/activations.py license_server/tests/test_license_domain_modules.py license_server/tests/test_license_flow.py
git commit -m "refactor: extract license and activation domains"
```

---

### Task 9: Extract Publish Relay

**Files:**
- Create: `license_server/luming_license/domains/relay.py`
- Create: `license_server/tests/test_relay_module.py`
- Modify: `license_server/server.py`

**Interfaces:**
- Produces all existing `publish_relay_*` functions and constants.
- Preserves lease, retry, token, channel and packet response semantics.

- [ ] **Step 1: Add a direct relay module lifecycle test**

```python
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from test_license_flow import load_server


class RelayModuleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.server = load_server(Path(self.temp.name))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_enqueue_claim_complete_round_trip(self) -> None:
        queued = self.server.publish_relay_enqueue({"channelId": "matrix", "title": "module relay"})
        claimed = self.server.publish_relay_claim("matrix", "module-client", 30000)
        self.assertEqual(queued["id"], claimed["id"])
        completed = self.server.publish_relay_complete({
            "id": claimed["id"], "leaseId": claimed["leaseId"],
            "success": True, "result": {"ok": True},
        })
        self.assertEqual("done", completed["status"])
```

- [ ] **Step 2: Run the relay baseline**

```powershell
.\openclaw_new_launcher\python-runtime\python.exe -m unittest discover -s license_server\tests -p "test_relay_module.py"
```

- [ ] **Step 3: Extract relay functions and constants**

Move every function from `publish_relay_backoff_ms` through `publish_relay_stats`, plus relay token/config constants, to `domains/relay.py`. Use `db.connect`, `timeutils.now_ms`, `serialization.clamp_int`, `serialization.normalize_string`, and `ActivationError` imports.

- [ ] **Step 4: Run relay and full tests**

```powershell
.\openclaw_new_launcher\python-runtime\python.exe -m unittest discover -s license_server\tests -p "test_relay_module.py"
.\openclaw_new_launcher\python-runtime\python.exe -m unittest discover -s license_server\tests -p "test_license_flow.py"
.\openclaw_new_launcher\python-runtime\python.exe -m unittest discover -s license_server\tests -p "test_*.py"
```

- [ ] **Step 5: Commit**

```powershell
git add license_server/server.py license_server/luming_license/domains/relay.py license_server/tests/test_relay_module.py
git commit -m "refactor: extract license publish relay"
```

---

### Task 10: Replace Inline HTTP Branches with Route Modules

**Files:**
- Create: `license_server/luming_license/http/__init__.py`
- Create: `license_server/luming_license/http/responses.py`
- Create: `license_server/luming_license/http/routes_public.py`
- Create: `license_server/luming_license/http/routes_auth.py`
- Create: `license_server/luming_license/http/routes_admin.py`
- Create: `license_server/luming_license/http/routes_relay.py`
- Create: `license_server/luming_license/http/handler.py`
- Modify: `license_server/server.py`
- Modify: `license_server/tests/test_http_route_inventory.py`

**Interfaces:**
- Each route module exports `GET_ROUTES: dict[str, Callable]` and/or `POST_ROUTES: dict[str, Callable]` for exact paths.
- `handler.py` exports `Handler(BaseHTTPRequestHandler)` and `ROUTE_INVENTORY: frozenset[str]`.
- Dynamic aliases with identical behavior may point to the same callable.

- [ ] **Step 1: Change route inventory test to require a registry**

Replace the source scan with:

```python
from _support import LICENSE_SERVER_ROOT
from luming_license.http.handler import ROUTE_INVENTORY

class HttpRouteInventoryTests(unittest.TestCase):
    def test_router_registry_contains_every_external_route(self) -> None:
        self.assertEqual(set(), EXPECTED_ROUTE_MARKERS - set(ROUTE_INVENTORY))
```

- [ ] **Step 2: Run and confirm registry failure**

```powershell
.\openclaw_new_launcher\python-runtime\python.exe -m unittest discover -s license_server\tests -p "test_http_route_inventory.py"
```

Expected: fail importing `luming_license.http.handler`.

- [ ] **Step 3: Extract response behavior first**

`responses.py` defines a mixin containing existing bodies for `read_json`, `send_cors_headers`, `send_security_headers`, `send_json`, `send_html`, and `send_file`. Preserve `write_body=False` for `HEAD` and the exact CSP/HSTS/cache behavior.

```python
class ResponseMixin:
    def _send_bytes(self, status: int, data: bytes, content_type: str, headers: dict[str, str] | None, *, write_body: bool, cache_control: str | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_cors_headers()
        self.send_security_headers(cache_control=cache_control)
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        if write_body:
            self.wfile.write(data)

    def send_json(self, status: int, payload: dict[str, Any], headers: dict[str, str] | None = None, *, write_body: bool = True) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send_bytes(status, data, "application/json; charset=utf-8", headers, write_body=write_body)

    def send_html(self, status: int, html: str, *, write_body: bool = True) -> None:
        self._send_bytes(status, html.encode("utf-8"), "text/html; charset=utf-8", None, write_body=write_body)

    def send_file(self, status: int, path: str, content_type: str, *, write_body: bool = True) -> None:
        try:
            data = Path(path).read_bytes()
        except OSError:
            self.send_json(404, {"error": "file not found"}, write_body=write_body)
            return
        self._send_bytes(status, data, content_type, None, write_body=write_body, cache_control="public, max-age=3600")
```

- [ ] **Step 4: Build route registries by business boundary**

Use exact-path dictionaries and explicit alias registration. Query-sensitive handlers receive the parsed URL object; protected routes call `handler.require_admin()` before domain functions.

```python
Route = Callable[[Any, Any], None]

GET_ROUTES: dict[str, Route] = {
    "/health": get_health,
    "/": get_public_home,
    "/api/client/config": get_client_config,
    "/api/public/config": get_client_config,
    "/client/config": get_client_config,
}
```

Do not use suffix matching or a catch-all that can make admin and public routes overlap.

- [ ] **Step 5: Compose the handler**

`Handler` keeps request context helpers (`admin_context`, `admin_actor`, `request_ip`, `require_admin`, `require_publish_relay_auth`, `audit_admin_change`) and delegates in this order:

```python
def do_GET(self) -> None:
    dispatch(self, "GET")

def do_POST(self) -> None:
    dispatch(self, "POST")

def do_HEAD(self) -> None:
    dispatch(self, "HEAD")

def do_OPTIONS(self) -> None:
    self.send_response(204)
    self.send_cors_headers()
    self.send_security_headers()
    self.end_headers()
```

Unknown routes return the existing `404` JSON. Known routes with unsupported methods retain their explicit `405` behavior.

- [ ] **Step 6: Run HTTP, CORS, auth, and full tests**

```powershell
.\openclaw_new_launcher\python-runtime\python.exe -m unittest discover -s license_server\tests -p "test_http_route_inventory.py"
.\openclaw_new_launcher\python-runtime\python.exe -m unittest discover -s license_server\tests -p "test_license_flow.py"
.\openclaw_new_launcher\python-runtime\python.exe -m unittest discover -s license_server\tests -p "test_*.py"
```

Expected: all pass, including HEAD, security headers, cookie auth, public CORS, admin CORS and every domain flow.

- [ ] **Step 7: Commit**

```powershell
git add license_server/server.py license_server/luming_license/http license_server/tests/test_http_route_inventory.py
git commit -m "refactor: modularize license HTTP routing"
```

---

### Task 11: Make `server.py` a Thin Compatibility Facade and Extract CLI

**Files:**
- Create: `license_server/luming_license/cli.py`
- Modify: `license_server/luming_license/__init__.py`
- Modify: `license_server/server.py`
- Create: `license_server/tests/test_cli_compatibility.py`

**Interfaces:**
- `cli.py` exports `serve(args)`, `create_codes(args)`, `list_codes(args)`, `build_parser()`, and `main()`.
- `server.py` re-exports names required by `COMPAT_EXPORTS` and runs `main()` under `__name__ == "__main__"`.

- [ ] **Step 1: Add CLI compatibility tests**

```python
from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PYTHON = ROOT / "openclaw_new_launcher" / "python-runtime" / "python.exe"
SERVER = ROOT / "license_server" / "server.py"


class CliCompatibilityTests(unittest.TestCase):
    def test_help_keeps_existing_commands(self) -> None:
        result = subprocess.run([str(PYTHON), str(SERVER), "--help"], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(0, result.returncode, result.stderr)
        for command in ("serve", "create-code", "list-codes", "public-key"):
            self.assertIn(command, result.stdout)
```

- [ ] **Step 2: Run the CLI test before extraction**

```powershell
.\openclaw_new_launcher\python-runtime\python.exe -m unittest discover -s license_server\tests -p "test_cli_compatibility.py"
```

Expected: pass against the current facade.

- [ ] **Step 3: Extract CLI and reduce the entry file**

`server.py` must contain only imports/re-exports and the executable guard. Use explicit exports rather than wildcard imports:

```python
#!/usr/bin/env python3
from luming_license.cli import main, serve
from luming_license.errors import ActivationError
from luming_license.db import connect, init_db, make_db_backup
from luming_license.http.handler import Handler
from luming_license.domains.accounts import create_account_record
from luming_license.domains.sessions import create_admin_session
from luming_license.domains.licenses import create_code_records, get_code_rows, get_code_secret_rows
from luming_license.domains.activations import activate_code, find_member_license, get_activation_rows
from luming_license.domains.plans import client_public_config, get_plan_rows, update_public_settings
from luming_license.domains.relay import publish_relay_claim, publish_relay_complete, publish_relay_enqueue, publish_relay_status

if __name__ == "__main__":
    main()
```

Add every remaining name asserted by existing tests as an explicit compatibility import. Keep the file under 300 lines.

- [ ] **Step 4: Run compile, CLI, compatibility and full tests**

```powershell
.\openclaw_new_launcher\python-runtime\python.exe -m py_compile license_server\server.py
.\openclaw_new_launcher\python-runtime\python.exe -m unittest discover -s license_server\tests -p "test_cli_compatibility.py"
.\openclaw_new_launcher\python-runtime\python.exe -m unittest discover -s license_server\tests -p "test_backend_refactor_contract.py"
.\openclaw_new_launcher\python-runtime\python.exe -m unittest discover -s license_server\tests -p "test_*.py"
```

Expected: all pass and `server.py` remains a valid direct script.

- [ ] **Step 5: Check module sizes and import cycles**

Run:

```powershell
(Get-Content license_server\server.py -Encoding utf8).Count
Get-ChildItem license_server\luming_license -Recurse -Filter *.py | ForEach-Object { [pscustomobject]@{File=$_.FullName;Lines=(Get-Content $_.FullName -Encoding utf8).Count} } | Sort-Object Lines -Descending
```

Expected: `server.py` is at most 300 lines; no domain module exceeds 800 lines. If a module exceeds the limit, split by responsibility before commit rather than changing the limit.

- [ ] **Step 6: Commit**

```powershell
git add license_server/server.py license_server/luming_license license_server/tests/test_cli_compatibility.py
git commit -m "refactor: finish modular license backend"
```

---

### Task 12: Adversarial Verification and Behavior-Preserving Deployment

**Files:**
- Create: `docs/validation/LOOM_LICENSE_BACKEND_MODULAR_20260714.md`
- Modify only if verification finds a defect: files owned by the failing task.

**Interfaces:**
- Consumes: modular backend, complete tests and existing production deployment credentials.
- Produces: a validation report with local results, remote backup path, hashes, aggregate counts and rollback command.

- [ ] **Step 1: Run release-level local verification**

```powershell
.\openclaw_new_launcher\python-runtime\python.exe -m py_compile license_server\server.py
.\openclaw_new_launcher\python-runtime\python.exe -m unittest discover -s license_server\tests -p "test_*.py"
```

Expected: zero failures.

- [ ] **Step 2: Start an isolated local server**

Use a temporary database and generated test key, then verify:

```text
GET  /health                         -> 200 and ok=true
HEAD /health                         -> 200 and empty body
GET  /                              -> 200 and 麓鸣商业授权中心
GET  /admin                         -> 200 and 麓鸣授权与客户管理
GET  /admin/api/codes unauthenticated -> 401
GET  /api/client/config             -> 200 with existing field set
```

Do not use `license_server/license.db`, `private_key.b64`, or production credentials for the isolated run.

- [ ] **Step 3: Verify database preservation against a production copy**

Create an online server backup, download only the backup to a restricted temporary directory, start the modular code against a copy, and run:

```powershell
$before = Join-Path $env:TEMP "license-backend-before.db"
$after = Join-Path $env:TEMP "license-backend-after.db"
.\openclaw_new_launcher\python-runtime\python.exe license_server\verify_db_preservation.py --before $before --after $after
```

Expected: authorization-bearing tables are unchanged; only explicitly allowed seed/audit changes may differ. Do not print row contents.

- [ ] **Step 4: Create a remote program and SQLite online backup**

Backup these program files and create the database snapshot under a timestamped directory:

```text
/opt/openclaw-license/backups/backend-modular-20260714T120000Z/server.py
/opt/openclaw-license/backups/backend-modular-20260714T120000Z/luming_license/
/opt/openclaw-license/backups/backend-modular-20260714T120000Z/license.db
```

If the old deployment does not contain `luming_license`, record that fact instead of creating an empty backup directory.

- [ ] **Step 5: Upload to a staging directory and verify remotely**

Set `stamp=$(date -u +%Y%m%dT%H%M%SZ)`, upload `server.py` and `luming_license/` to `stage=/tmp/luming-license-backend-$stamp`, then run:

```bash
stamp=$(date -u +%Y%m%dT%H%M%SZ)
stage="/tmp/luming-license-backend-$stamp"
backup="/opt/openclaw-license/backups/backend-modular-$stamp"
python3 -m compileall -q "$stage"
LICENSE_DB="$backup/license.db" \
LICENSE_PRIVATE_KEY_FILE=/opt/openclaw-license/private_key.b64 \
LICENSE_PORT=18792 \
python3 "$stage/server.py" serve
```

Probe port `18792` locally on the server using the read-only checks from Step 2, then stop the staging process. Do not submit activation, login, generation, mutation, reveal or export requests during this probe.

- [ ] **Step 6: Switch production program files and restart**

Copy the staged package into `/opt/openclaw-license` only after compile and shadow checks pass. Restart `openclaw-license`, then require:

```bash
systemctl is-active openclaw-license
curl -fsS http://127.0.0.1:18791/health
curl -fsS http://127.0.0.1:18791/admin | grep -q '麓鸣授权与客户管理'
```

If any command fails, restore only the backed-up program files and restart. Do not restore `license.db` automatically.

- [ ] **Step 7: Verify public production endpoints and aggregates**

Verify through `https://license.heang.top` with a cache-busting query:

```text
root 200, admin 200, health ok, admin HEAD 200,
unauthenticated admin data 401,
CSP/HSTS/no-store/referrer headers present,
purchase URL still configured and rendered.
```

Compare only aggregate counts for `codes`, `activations`, `accounts`, `plans` and active sessions before and after deployment. Values must be equal unless a real user action occurred during the deployment window; if they differ, inspect timestamps and audit records without printing customer rows.

- [ ] **Step 8: Write and commit the validation report**

The report records commands, pass/fail results, backup path, deployed hashes, aggregate comparison, service log status and program-only rollback commands. It contains no tokens, passwords, private keys, full authorization codes or customer records.

```powershell
git add docs/validation/LOOM_LICENSE_BACKEND_MODULAR_20260714.md
git commit -m "docs: validate modular license backend"
```

## Completion Gate

Phase 1 is complete only when all twelve tasks are committed, the full test suite passes, `server.py` is at most 300 lines, every compatibility export remains available, production aggregate data is preserved, the public purchase configuration remains dynamic, and the production service has a documented program-only rollback path.

After this gate, write the phase 2 plan for admin frontend modules and the approved UI information architecture using the actual stable API package produced by this plan.
