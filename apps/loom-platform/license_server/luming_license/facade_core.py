#!/usr/bin/env python3
"""Small online activation server for OpenClaw Launcher."""

# ruff: noqa: F401, F821 - exports and late-bound facade collaborators are explicit

from __future__ import annotations

import html as html_lib
import json
import logging
import os
import secrets
import sqlite3
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from luming_license import (
    audit,
    db,
    security,
    serialization as license_serialization,
    signing,
)
from luming_license.config import (
    DEFAULT_ADMIN_CORS_ORIGINS as CONFIG_DEFAULT_ADMIN_CORS_ORIGINS,
    Settings,
    bounded_int_env,
)
from luming_license.errors import ActivationError
from luming_license.domains import (
    accounts,
    activations,
    licenses,
    plans,
    relay,
    sessions,
    templates,
)
from luming_license.http.handler import Handler as HttpHandler
from luming_license.timeutils import (
    add_days_date,
    add_days_iso,
    now_ms,
    utc_filename_stamp,
    utc_now,
)


LOGGER = logging.getLogger("openclaw-license")
if not logging.getLogger().handlers:
    logging.basicConfig(
        level=getattr(
            logging, os.environ.get("LICENSE_LOG_LEVEL", "INFO").upper(), logging.INFO
        ),
        format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
    )


SETTINGS = Settings.from_env()
APPLICATION_DIR = os.path.dirname(os.path.dirname(__file__))
BASE_DIR = os.environ.get("LICENSE_BASE_DIR", "/opt/openclaw-license")
DB_PATH = SETTINGS.db_path
BACKUP_DIR = SETTINGS.backup_dir
PRIVATE_KEY_FILE = SETTINGS.private_key_file
ADMIN_TOKEN_FILE = SETTINGS.admin_token_file
LOGO_FILE = SETTINGS.logo_file
HOST = SETTINGS.host
PORT = SETTINGS.port
COMMERCIAL_FEATURES = list(licenses.COMMERCIAL_FEATURES)
DEFAULT_FEATURES = list(licenses.DEFAULT_FEATURES)
VIP_DEFAULT_FEATURES = list(licenses.VIP_DEFAULT_FEATURES)
_PLAN_DEFAULTS = plans.gateway_defaults(SETTINGS)
PUBLIC_COMMERCIAL_URL = _PLAN_DEFAULTS["publicCommercialUrl"]
PUBLIC_SUPPORT_URL = _PLAN_DEFAULTS["publicSupportUrl"]
DEFAULT_GATEWAY_BASE_URL = _PLAN_DEFAULTS["gatewayBaseUrl"]
DEFAULT_GATEWAY_IMAGE_BASE_URL = _PLAN_DEFAULTS["gatewayImageBaseUrl"]
DEFAULT_GATEWAY_VIDEO_BASE_URL = _PLAN_DEFAULTS["gatewayVideoBaseUrl"]
DEFAULT_GATEWAY_TOKEN = _PLAN_DEFAULTS["gatewayToken"]
DEFAULT_GATEWAY_IMAGE_TOKEN = _PLAN_DEFAULTS["gatewayImageToken"]
DEFAULT_GATEWAY_VIDEO_TOKEN = _PLAN_DEFAULTS["gatewayVideoToken"]
DEFAULT_GATEWAY_DEFAULT_MODEL = _PLAN_DEFAULTS["gatewayDefaultModel"]
DEFAULT_GATEWAY_IMAGE_MODEL = _PLAN_DEFAULTS["gatewayImageModel"]
DEFAULT_GATEWAY_VIDEO_MODEL = _PLAN_DEFAULTS["gatewayVideoModel"]
DEFAULT_GATEWAY_MODELS = _PLAN_DEFAULTS["gatewayModels"]
DEFAULT_PUBLIC_SETTINGS = _PLAN_DEFAULTS["publicSettings"]
DB_DEFAULTS = {
    "public_settings": DEFAULT_PUBLIC_SETTINGS,
    "commercial_features": COMMERCIAL_FEATURES,
    "plans": [
        (
            "monthly",
            "月卡",
            31,
            DEFAULT_FEATURES,
            {"image": 100, "video": 20},
            DEFAULT_GATEWAY_IMAGE_MODEL,
            DEFAULT_GATEWAY_VIDEO_MODEL,
        ),
        (
            "quarterly",
            "季卡",
            93,
            DEFAULT_FEATURES,
            {"image": 300, "video": 60},
            DEFAULT_GATEWAY_IMAGE_MODEL,
            DEFAULT_GATEWAY_VIDEO_MODEL,
        ),
        (
            "yearly",
            "年卡",
            366,
            DEFAULT_FEATURES,
            {"image": 1200, "video": 240},
            DEFAULT_GATEWAY_IMAGE_MODEL,
            DEFAULT_GATEWAY_VIDEO_MODEL,
        ),
        (
            "vip_monthly",
            "VIP 月卡",
            31,
            VIP_DEFAULT_FEATURES,
            {"image": 300, "video": 80, "phoneAgent": True, "desktopAgent": True},
            DEFAULT_GATEWAY_IMAGE_MODEL,
            DEFAULT_GATEWAY_VIDEO_MODEL,
        ),
    ],
    "gateway_base_url": DEFAULT_GATEWAY_BASE_URL,
    "gateway_image_base_url": DEFAULT_GATEWAY_IMAGE_BASE_URL,
    "gateway_video_base_url": DEFAULT_GATEWAY_VIDEO_BASE_URL,
    "gateway_token": DEFAULT_GATEWAY_TOKEN,
    "gateway_image_token": DEFAULT_GATEWAY_IMAGE_TOKEN,
    "gateway_video_token": DEFAULT_GATEWAY_VIDEO_TOKEN,
    "gateway_default_model": DEFAULT_GATEWAY_DEFAULT_MODEL,
    "gateway_models": DEFAULT_GATEWAY_MODELS,
}
canonical = license_serialization.canonical
parse_json_object = license_serialization.parse_json_object
load_json_value = license_serialization.load_json_value
normalize_string = license_serialization.normalize_string
clamp_int = license_serialization.clamp_int
ClosingConnection = db.ClosingConnection
ensure_column = db.ensure_column
AUDIT_TRANSACTION_LOCAL = threading.local()


class _AuditTransactionConnection:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def __enter__(self) -> _AuditTransactionConnection:
        return self

    def __exit__(
        self, _exc_type: object, _exc_value: object, _traceback: object
    ) -> bool:
        return False

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None

    def close(self) -> None:
        return None

    def __getattr__(self, name: str) -> Any:
        return getattr(self.connection, name)


class _AuditTransaction:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        self.proxy = _AuditTransactionConnection(connection)
        self.audit_written = False
        self.response_sent = False


def _active_audit_transaction() -> _AuditTransaction | None:
    return getattr(AUDIT_TRANSACTION_LOCAL, "transaction", None)


def _begin_audit_transaction() -> None:
    if _active_audit_transaction() is None:
        AUDIT_TRANSACTION_LOCAL.transaction = _AuditTransaction(
            db.connect(settings=SETTINGS, defaults=DB_DEFAULTS)
        )


def _finish_audit_transaction() -> None:
    transaction = _active_audit_transaction()
    if transaction is None:
        return
    try:
        if transaction.audit_written and transaction.response_sent:
            try:
                transaction.connection.commit()
            except BaseException:
                try:
                    transaction.connection.rollback()
                except BaseException:
                    LOGGER.exception("Audit transaction rollback failed after commit failure")
                raise
        else:
            transaction.connection.rollback()
    finally:
        try:
            transaction.connection.close()
        finally:
            if _active_audit_transaction() is transaction:
                del AUDIT_TRANSACTION_LOCAL.transaction


def _finalize_audit_response(status: int) -> bool:
    transaction = _active_audit_transaction()
    if transaction is None:
        return True
    transaction.response_sent = 200 <= status < 300
    try:
        _finish_audit_transaction()
    except BaseException:
        LOGGER.exception("Audited request transaction finalization failed")
        return False
    return True


def _run_request_transaction(
    callback: Callable[[], Any], *, timeout: float = 0.25
) -> Any:
    if _active_audit_transaction() is not None:
        return callback()
    connection = db.connect(
        settings=SETTINGS, defaults=DB_DEFAULTS, timeout=max(0.01, float(timeout))
    )
    transaction = _AuditTransaction(connection)
    AUDIT_TRANSACTION_LOCAL.transaction = transaction
    try:
        connection.execute("BEGIN IMMEDIATE")
        result = callback()
        try:
            connection.commit()
        except BaseException:
            try:
                connection.rollback()
            except BaseException:
                LOGGER.exception("Request transaction rollback failed after commit failure")
            raise
        return result
    except BaseException:
        connection.rollback()
        raise
    finally:
        try:
            connection.close()
        finally:
            if _active_audit_transaction() is transaction:
                del AUDIT_TRANSACTION_LOCAL.transaction


def _commit_audit_connection(connection: Any) -> None:
    transaction = _active_audit_transaction()
    if transaction and connection is transaction.proxy:
        transaction.audit_written = True
    else:
        connection.commit()


def _commit_registration_normalization(connection: Any) -> None:
    transaction = _active_audit_transaction()
    if transaction and connection is transaction.proxy:
        return
    else:
        connection.commit()


def parse_features(raw: str) -> list[str]:
    return license_serialization.parse_features(raw, default_features=DEFAULT_FEATURES)


def parse_models(raw: Any) -> list[str]:
    return license_serialization.parse_models(
        raw, default_gateway_models=DEFAULT_GATEWAY_MODELS
    )


def parse_optional_models(raw: Any, fallback: list[str] | None = None) -> list[str]:
    return license_serialization.parse_optional_models(
        raw,
        fallback,
        default_gateway_models=DEFAULT_GATEWAY_MODELS,
    )


def load_private_key() -> Any:
    return signing.load_private_key(private_key_file=PRIVATE_KEY_FILE)


def public_key_b64() -> str:
    return signing.public_key_b64(private_key_file=PRIVATE_KEY_FILE)


def sign_license(payload: dict[str, Any]) -> dict[str, Any]:
    return signing.sign_license(payload, private_key_file=PRIVATE_KEY_FILE)


def connect(*, timeout: float = 5.0) -> sqlite3.Connection:
    transaction = _active_audit_transaction()
    if transaction:
        return transaction.proxy
    return db.connect(settings=SETTINGS, defaults=DB_DEFAULTS, timeout=timeout)


def init_db(conn: sqlite3.Connection) -> None:
    db.init_db(conn, defaults=DB_DEFAULTS)


def seed_default_settings(conn: sqlite3.Connection) -> None:
    db.seed_default_settings(conn, defaults=DB_DEFAULTS)


def seed_default_plans(conn: sqlite3.Connection) -> None:
    db.seed_default_plans(conn, defaults=DB_DEFAULTS)


def make_db_backup(label: str) -> str:
    return db.make_db_backup(label, settings=SETTINGS, defaults=DB_DEFAULTS)


def make_audited_backup(label: str) -> str:
    backup_path = make_db_backup(label)
    _begin_audit_transaction()
    return backup_path


PUBLISH_RELAY_TOKEN = SETTINGS.publish_relay_token
PUBLISH_RELAY_DEFAULT_LEASE_MS = SETTINGS.publish_relay_default_lease_ms
PUBLISH_RELAY_DEFAULT_WAIT_MS = SETTINGS.publish_relay_default_wait_ms
PUBLISH_RELAY_MAX_ATTEMPTS = SETTINGS.publish_relay_max_attempts
PUBLISH_RELAY_BACKOFF_MS = relay.PUBLISH_RELAY_BACKOFF_MS
PUBLISH_RELAY_MAX_BACKOFF_MS = relay.PUBLISH_RELAY_MAX_BACKOFF_MS
MAX_BULK_CODE_HASHES = SETTINGS.max_bulk_code_hashes
MAX_CODE_SECRET_EXPORT = licenses.MAX_CODE_SECRET_EXPORT
LOGIN_RATE_LIMIT_ATTEMPTS = SETTINGS.login_rate_limit_attempts
LOGIN_RATE_LIMIT_WINDOW_SECONDS = SETTINGS.login_rate_limit_window_seconds
LOGIN_RATE_LIMIT_LOCKOUT_SECONDS = SETTINGS.login_rate_limit_lockout_seconds
REGISTER_RATE_LIMIT_ATTEMPTS = SETTINGS.register_rate_limit_attempts
REGISTER_RATE_LIMIT_WINDOW_SECONDS = SETTINGS.register_rate_limit_window_seconds
REGISTER_RATE_LIMIT_LOCKOUT_SECONDS = SETTINGS.register_rate_limit_lockout_seconds
DEFAULT_ADMIN_CORS_ORIGINS = set(CONFIG_DEFAULT_ADMIN_CORS_ORIGINS)
ADMIN_CORS_ALLOWED_ORIGINS = set(SETTINGS.admin_cors_allowed_origins)
ADMIN_SESSION_COOKIE_NAME = security.ADMIN_SESSION_COOKIE_NAME
RATE_LIMIT_STATE = security.RateLimitState()
RATE_LIMIT_LOCK = RATE_LIMIT_STATE.lock
RATE_LIMITS = RATE_LIMIT_STATE.entries
ADMIN_HTML_FALLBACK = """<!doctype html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>OpenClaw Admin</title></head>
<body><h1>OpenClaw Admin</h1><p>admin_console.html is missing. Please deploy it with server.py.</p></body>
</html>
"""
PUBLIC_HTML_FALLBACK = """<!doctype html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>麓鸣商业授权中心</title></head>
<body><h1>麓鸣商业授权中心</h1><p><a href="/admin">进入授权管理后台</a></p></body>
</html>
"""


def load_admin_html() -> str:
    candidate_paths = [
        os.path.join(APPLICATION_DIR, "admin_console.html"),
        os.path.join(BASE_DIR, "admin_console.html"),
    ]
    for path in candidate_paths:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as file:
                return file.read()
    return ADMIN_HTML_FALLBACK


def load_public_html() -> str:
    candidate_paths = [
        os.path.join(APPLICATION_DIR, "public_home.html"),
        os.path.join(BASE_DIR, "public_home.html"),
    ]
    for path in candidate_paths:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as file:
                return file.read()
    return PUBLIC_HTML_FALLBACK


ADMIN_HTML = load_admin_html()
PUBLIC_HTML = load_public_html()


def render_public_html() -> str:
    config = client_public_config()
    purchase_url = (
        str(config.get("purchaseUrl") or config.get("cardSiteUrl") or "/admin").strip()
        or "/admin"
    )
    support_url = str(config.get("supportUrl") or purchase_url).strip() or purchase_url
    return PUBLIC_HTML.replace(
        "{{PURCHASE_URL}}", html_lib.escape(purchase_url, quote=True)
    ).replace("{{SUPPORT_URL}}", html_lib.escape(support_url, quote=True))


def code_hash(code: str) -> str:
    return licenses.code_hash(code)


def load_admin_token() -> str | None:
    token = os.environ.get("LICENSE_ADMIN_TOKEN")
    if token:
        return token.strip()
    try:
        with open(ADMIN_TOKEN_FILE, "r", encoding="utf-8") as file:
            token = file.read().strip()
        return token or None
    except FileNotFoundError:
        return None
    except (PermissionError, OSError) as error:
        LOGGER.warning(
            "Unable to read admin token file %s: %s", ADMIN_TOKEN_FILE, error
        )
        return None


ADMIN_SESSION_TTL_DAYS = SETTINGS.admin_session_ttl_days
ACCOUNT_ROLE_MERCHANT = accounts.ACCOUNT_ROLE_MERCHANT
ACCOUNT_ROLE_SUPER_ADMIN = accounts.ACCOUNT_ROLE_SUPER_ADMIN
ACCOUNT_STATUS_ACTIVE = accounts.ACCOUNT_STATUS_ACTIVE
ACCOUNT_STATUS_DISABLED = accounts.ACCOUNT_STATUS_DISABLED
INVITE_CODE_STATUS_ACTIVE = accounts.INVITE_CODE_STATUS_ACTIVE
INVITE_CODE_STATUS_DISABLED = accounts.INVITE_CODE_STATUS_DISABLED
INVITE_CODE_STATUS_USED = accounts.INVITE_CODE_STATUS_USED
INVITE_CODE_STATUS_EXPIRED = accounts.INVITE_CODE_STATUS_EXPIRED
INVITE_CODE_ALPHABET = accounts.INVITE_CODE_ALPHABET

__all__ = [
    "html_lib",
    "json",
    "logging",
    "os",
    "secrets",
    "sqlite3",
    "sys",
    "threading",
    "time",
    "datetime",
    "timedelta",
    "timezone",
    "ThreadingHTTPServer",
    "Any",
    "parse_qs",
    "urlparse",
    "audit",
    "db",
    "security",
    "license_serialization",
    "signing",
    "CONFIG_DEFAULT_ADMIN_CORS_ORIGINS",
    "Settings",
    "bounded_int_env",
    "ActivationError",
    "accounts",
    "activations",
    "licenses",
    "plans",
    "relay",
    "sessions",
    "templates",
    "HttpHandler",
    "add_days_date",
    "add_days_iso",
    "now_ms",
    "utc_filename_stamp",
    "utc_now",
    "LOGGER",
    "SETTINGS",
    "APPLICATION_DIR",
    "BASE_DIR",
    "DB_PATH",
    "BACKUP_DIR",
    "PRIVATE_KEY_FILE",
    "ADMIN_TOKEN_FILE",
    "LOGO_FILE",
    "HOST",
    "PORT",
    "COMMERCIAL_FEATURES",
    "DEFAULT_FEATURES",
    "VIP_DEFAULT_FEATURES",
    "_PLAN_DEFAULTS",
    "PUBLIC_COMMERCIAL_URL",
    "PUBLIC_SUPPORT_URL",
    "DEFAULT_GATEWAY_BASE_URL",
    "DEFAULT_GATEWAY_IMAGE_BASE_URL",
    "DEFAULT_GATEWAY_VIDEO_BASE_URL",
    "DEFAULT_GATEWAY_TOKEN",
    "DEFAULT_GATEWAY_IMAGE_TOKEN",
    "DEFAULT_GATEWAY_VIDEO_TOKEN",
    "DEFAULT_GATEWAY_DEFAULT_MODEL",
    "DEFAULT_GATEWAY_IMAGE_MODEL",
    "DEFAULT_GATEWAY_VIDEO_MODEL",
    "DEFAULT_GATEWAY_MODELS",
    "DEFAULT_PUBLIC_SETTINGS",
    "DB_DEFAULTS",
    "canonical",
    "parse_json_object",
    "load_json_value",
    "normalize_string",
    "clamp_int",
    "ClosingConnection",
    "ensure_column",
    "AUDIT_TRANSACTION_LOCAL",
    "PUBLISH_RELAY_TOKEN",
    "PUBLISH_RELAY_DEFAULT_LEASE_MS",
    "PUBLISH_RELAY_DEFAULT_WAIT_MS",
    "PUBLISH_RELAY_MAX_ATTEMPTS",
    "PUBLISH_RELAY_BACKOFF_MS",
    "PUBLISH_RELAY_MAX_BACKOFF_MS",
    "MAX_BULK_CODE_HASHES",
    "MAX_CODE_SECRET_EXPORT",
    "LOGIN_RATE_LIMIT_ATTEMPTS",
    "LOGIN_RATE_LIMIT_WINDOW_SECONDS",
    "LOGIN_RATE_LIMIT_LOCKOUT_SECONDS",
    "REGISTER_RATE_LIMIT_ATTEMPTS",
    "REGISTER_RATE_LIMIT_WINDOW_SECONDS",
    "REGISTER_RATE_LIMIT_LOCKOUT_SECONDS",
    "DEFAULT_ADMIN_CORS_ORIGINS",
    "ADMIN_CORS_ALLOWED_ORIGINS",
    "ADMIN_SESSION_COOKIE_NAME",
    "RATE_LIMIT_STATE",
    "RATE_LIMIT_LOCK",
    "RATE_LIMITS",
    "ADMIN_HTML_FALLBACK",
    "PUBLIC_HTML_FALLBACK",
    "ADMIN_HTML",
    "PUBLIC_HTML",
    "ADMIN_SESSION_TTL_DAYS",
    "ACCOUNT_ROLE_MERCHANT",
    "ACCOUNT_ROLE_SUPER_ADMIN",
    "ACCOUNT_STATUS_ACTIVE",
    "ACCOUNT_STATUS_DISABLED",
    "INVITE_CODE_STATUS_ACTIVE",
    "INVITE_CODE_STATUS_DISABLED",
    "INVITE_CODE_STATUS_USED",
    "INVITE_CODE_STATUS_EXPIRED",
    "INVITE_CODE_ALPHABET",
    "_AuditTransactionConnection",
    "_AuditTransaction",
    "_active_audit_transaction",
    "_begin_audit_transaction",
    "_finish_audit_transaction",
    "_finalize_audit_response",
    "_run_request_transaction",
    "_commit_audit_connection",
    "_commit_registration_normalization",
    "parse_features",
    "parse_models",
    "parse_optional_models",
    "load_private_key",
    "public_key_b64",
    "sign_license",
    "connect",
    "init_db",
    "seed_default_settings",
    "seed_default_plans",
    "make_db_backup",
    "make_audited_backup",
    "load_admin_html",
    "load_public_html",
    "render_public_html",
    "code_hash",
    "load_admin_token",
]
