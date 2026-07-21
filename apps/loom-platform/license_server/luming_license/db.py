from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from typing import Any

from .config import Settings
from .timeutils import utc_now


def default_values(settings: Settings) -> dict[str, Any]:
    commercial_features = [
        "acquisition.workbench", "acquisition.feishu", "matrix.devices", "templates.cloud",
        "publishing.draft", "diagnostics.export",
    ]
    default_features = ["openclaw", "image", "video", "storyboard", *commercial_features]
    vip_default_features = [*default_features, "phoneAgent", "desktopAgent"]
    return {
        "public_settings": {
            "cardSiteEnabled": True,
            "cardSiteLabel": "购买授权码",
            "cardSiteUrl": "",
            "supportUrl": settings.support_url,
        },
        "commercial_features": commercial_features,
        "plans": [
            ("monthly", "月卡", 31, default_features, {"image": 100, "video": 20}, settings.gateway_image_model, settings.gateway_video_model),
            ("quarterly", "季卡", 93, default_features, {"image": 300, "video": 60}, settings.gateway_image_model, settings.gateway_video_model),
            ("yearly", "年卡", 366, default_features, {"image": 1200, "video": 240}, settings.gateway_image_model, settings.gateway_video_model),
            ("vip_monthly", "VIP 月卡", 31, vip_default_features, {"image": 300, "video": 80, "phoneAgent": True, "desktopAgent": True}, settings.gateway_image_model, settings.gateway_video_model),
        ],
        "gateway_base_url": settings.gateway_base_url,
        "gateway_image_base_url": settings.gateway_image_base_url,
        "gateway_video_base_url": settings.gateway_video_base_url,
        "gateway_token": settings.gateway_token,
        "gateway_image_token": settings.gateway_image_token,
        "gateway_video_token": settings.gateway_video_token,
        "gateway_default_model": settings.gateway_default_model,
        "gateway_models": list(settings.gateway_models),
    }


def _resolved(settings: Settings | None, defaults: dict[str, Any] | None) -> tuple[Settings, dict[str, Any]]:
    active_settings = settings or Settings.from_env()
    return active_settings, defaults or default_values(active_settings)


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> bool:
        try:
            return bool(super().__exit__(exc_type, exc_value, traceback))
        finally:
            self.close()


def connect(
    *,
    settings: Settings | None = None,
    defaults: dict[str, Any] | None = None,
    timeout: float = 5.0,
) -> sqlite3.Connection:
    active_settings, active_defaults = _resolved(settings, defaults)
    os.makedirs(os.path.dirname(active_settings.db_path), exist_ok=True)
    conn = sqlite3.connect(
        active_settings.db_path,
        timeout=timeout,
        factory=ClosingConnection,
    )
    conn.row_factory = sqlite3.Row
    try:
        init_db(conn, defaults=active_defaults)
    except BaseException:
        conn.close()
        raise
    return conn


def ensure_column(conn: sqlite3.Connection, table: str, name: str, definition: str) -> None:
    columns = {row["name"] for row in conn.execute(f"pragma table_info({table})").fetchall()}
    if name not in columns:
        conn.execute(f"alter table {table} add column {name} {definition}")


def init_db(conn: sqlite3.Connection, *, defaults: dict[str, Any] | None = None) -> None:
    active_defaults = defaults or default_values(Settings.from_env())
    statements = (
        """create table if not exists codes (
            code_hash text primary key, code_label text not null, full_code text not null default '',
            licensee text not null, edition text not null, features_json text not null, expires text not null,
            max_activations integer not null default 1, disabled integer not null default 0,
            member_mode integer not null default 0, plan text not null default '',
            gateway_base_url text not null default '', gateway_image_base_url text not null default '',
            gateway_video_base_url text not null default '', gateway_token text not null default '',
            gateway_image_token text not null default '', gateway_video_token text not null default '',
            gateway_default_model text not null default '', gateway_image_model text not null default '',
            gateway_video_model text not null default '', gateway_models_json text not null default '[]',
            quotas_json text not null default '{}', created_at text not null)""",
        """create table if not exists activations (
            id integer primary key autoincrement, code_hash text not null, install_id text not null,
            device_id text not null, license_json text not null, activated_at text not null,
            unique(code_hash, install_id))""",
        """create table if not exists accounts (
            id integer primary key autoincrement, username text not null unique,
            display_name text not null default '', password_hash text not null,
            role text not null default 'merchant', status text not null default 'active', note text not null default '',
            created_by integer not null default 0, created_at text not null, updated_at text not null,
            last_login_at text not null default '', last_login_ip text not null default '')""",
        """create table if not exists admin_sessions (
            session_hash text primary key, account_id integer not null, created_at text not null,
            updated_at text not null, expires_at text not null, revoked_at text not null default '',
            request_ip text not null default '', user_agent text not null default '')""",
        """create table if not exists invite_codes (
            id integer primary key autoincrement, invite_code text not null unique,
            role text not null default 'merchant', status text not null default 'active',
            max_uses integer not null default 1, used_count integer not null default 0, note text not null default '',
            created_by integer not null default 0, created_at text not null, updated_at text not null,
            expires_at text not null default '', last_used_at text not null default '',
            last_used_ip text not null default '', last_used_username text not null default '',
            last_used_account_id integer not null default 0)""",
        """create table if not exists audit_logs (
            id integer primary key autoincrement, actor text not null default '', action text not null,
            target_type text not null default '', target_id text not null default '',
            before_json text not null default '{}', after_json text not null default '{}',
            request_ip text not null default '', backup_path text not null default '', created_at text not null)""",
        """create table if not exists plans (
            plan_key text primary key, display_name text not null, duration_days integer not null default 31,
            features_json text not null default '[]', gateway_base_url text not null default '',
            gateway_image_base_url text not null default '', gateway_video_base_url text not null default '',
            gateway_token text not null default '', gateway_image_token text not null default '',
            gateway_video_token text not null default '', gateway_default_model text not null default '',
            gateway_image_model text not null default '', gateway_video_model text not null default '',
            gateway_models_json text not null default '[]', quotas_json text not null default '{}',
            disabled integer not null default 0, created_at text not null, updated_at text not null)""",
        """create table if not exists settings (
            key text primary key, value_json text not null default '{}', updated_at text not null)""",
        """create table if not exists beta_claims (
            id integer primary key autoincrement, day text not null, ip text not null,
            full_code text not null, expires text not null, created_at text not null, unique(day, ip))""",
        """create table if not exists prompt_templates (
            id integer primary key autoincrement, kind text not null, title text not null, prompt text not null,
            params_json text not null default '{}', cover_url text not null default '', tags text not null default '',
            sort integer not null default 0, enabled integer not null default 1,
            created_at text not null, updated_at text not null)""",
        """create table if not exists account_gateway_settings (
            account_id integer primary key, gateway_base_url text not null default '',
            gateway_image_base_url text not null default '', gateway_video_base_url text not null default '',
            gateway_token text not null default '', gateway_image_token text not null default '',
            gateway_video_token text not null default '', gateway_default_model text not null default '',
            gateway_image_model text not null default '', gateway_video_model text not null default '',
            gateway_models_json text not null default '[]', created_at text not null, updated_at text not null)""",
        """create table if not exists publish_relay_packets (
            seq integer primary key autoincrement, packet_id text not null unique, channel_id text not null,
            packet_json text not null, status text not null default 'pending', attempts integer not null default 0,
            created_at text not null, updated_at text not null, leased_by text not null default '',
            lease_id text not null default '', lease_until_ms integer not null default 0,
            next_available_at_ms integer not null default 0, completed_at text not null default '',
            result_json text not null default '', last_error text not null default '')""",
    )
    for statement in statements:
        conn.execute(statement)
    conn.execute("create index if not exists idx_publish_relay_channel_status on publish_relay_packets (channel_id, status, seq)")
    for table, name, definition in (
        ("codes", "owner_account_id", "integer not null default 0"),
        ("codes", "full_code", "text not null default ''"),
        ("codes", "member_mode", "integer not null default 0"),
        ("codes", "plan", "text not null default ''"),
        ("codes", "gateway_base_url", "text not null default ''"),
        ("codes", "gateway_image_base_url", "text not null default ''"),
        ("codes", "gateway_video_base_url", "text not null default ''"),
        ("codes", "gateway_token", "text not null default ''"),
        ("codes", "gateway_image_token", "text not null default ''"),
        ("codes", "gateway_video_token", "text not null default ''"),
        ("codes", "gateway_default_model", "text not null default ''"),
        ("codes", "gateway_image_model", "text not null default ''"),
        ("codes", "gateway_video_model", "text not null default ''"),
        ("codes", "gateway_models_json", "text not null default '[]'"),
        ("codes", "quotas_json", "text not null default '{}'"),
        ("plans", "gateway_base_url", "text not null default ''"),
        ("plans", "gateway_image_base_url", "text not null default ''"),
        ("plans", "gateway_video_base_url", "text not null default ''"),
        ("plans", "gateway_token", "text not null default ''"),
        ("plans", "gateway_image_token", "text not null default ''"),
        ("plans", "gateway_video_token", "text not null default ''"),
        ("plans", "gateway_default_model", "text not null default ''"),
        ("plans", "gateway_image_model", "text not null default ''"),
        ("plans", "gateway_video_model", "text not null default ''"),
        ("plans", "gateway_models_json", "text not null default '[]'"),
        ("plans", "quotas_json", "text not null default '{}'"),
    ):
        ensure_column(conn, table, name, definition)
    seed_default_settings(conn, defaults=active_defaults)
    seed_default_plans(conn, defaults=active_defaults)
    conn.commit()


def seed_default_settings(conn: sqlite3.Connection, *, defaults: dict[str, Any] | None = None) -> None:
    active_defaults = defaults or default_values(Settings.from_env())
    row = conn.execute("select 1 from settings where key = ?", ("public",)).fetchone()
    if row:
        return
    conn.execute(
        "insert into settings (key, value_json, updated_at) values (?, ?, ?)",
        ("public", json.dumps(active_defaults["public_settings"], ensure_ascii=False, sort_keys=True), utc_now()),
    )


def seed_default_plans(conn: sqlite3.Connection, *, defaults: dict[str, Any] | None = None) -> None:
    active_defaults = defaults or default_values(Settings.from_env())
    existing = conn.execute("select count(*) from plans").fetchone()[0]
    if existing:
        for plan_key in ("monthly", "quarterly", "yearly", "vip_monthly"):
            row = conn.execute("select features_json from plans where plan_key = ?", (plan_key,)).fetchone()
            if not row:
                continue
            try:
                current = json.loads(row["features_json"])
            except (TypeError, json.JSONDecodeError):
                current = []
            if not isinstance(current, list):
                current = []
            merged = list(dict.fromkeys([*(str(item) for item in current if str(item)), *active_defaults["commercial_features"]]))
            if merged != current:
                conn.execute(
                    "update plans set features_json = ?, updated_at = ? where plan_key = ?",
                    (json.dumps(merged, ensure_ascii=False), utc_now(), plan_key),
                )
        return
    now = utc_now()
    for plan_key, display_name, duration_days, features, quotas, image_model, video_model in active_defaults["plans"]:
        conn.execute(
            """insert into plans (
                plan_key, display_name, duration_days, features_json, gateway_base_url,
                gateway_image_base_url, gateway_video_base_url, gateway_token, gateway_image_token,
                gateway_video_token, gateway_default_model, gateway_image_model, gateway_video_model,
                gateway_models_json, quotas_json, disabled, created_at, updated_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)""",
            (
                plan_key, display_name, duration_days, json.dumps(features, ensure_ascii=False),
                active_defaults["gateway_base_url"], active_defaults["gateway_image_base_url"], active_defaults["gateway_video_base_url"],
                active_defaults["gateway_token"], active_defaults["gateway_image_token"], active_defaults["gateway_video_token"],
                active_defaults["gateway_default_model"], image_model, video_model,
                json.dumps(active_defaults["gateway_models"], ensure_ascii=False), json.dumps(quotas, ensure_ascii=False), now, now,
            ),
        )


def make_db_backup(
    label: str,
    *,
    settings: Settings | None = None,
    defaults: dict[str, Any] | None = None,
) -> str:
    active_settings, active_defaults = _resolved(settings, defaults)
    if not os.path.exists(active_settings.db_path):
        return ""
    safe_label = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in label.strip())[:48] or "change"
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    os.makedirs(active_settings.backup_dir, exist_ok=True)
    backup_path = os.path.abspath(os.path.join(active_settings.backup_dir, f"license-{timestamp}-{safe_label}.db"))
    with connect(settings=active_settings, defaults=active_defaults) as source, closing(sqlite3.connect(backup_path)) as target:
        source.backup(target)
    return backup_path
