#!/usr/bin/env python3
"""Verify that a license-server deployment preserved customer data."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


PROTECTED_TABLES = (
    "codes",
    "activations",
    "accounts",
    "admin_sessions",
    "invite_codes",
    "audit_logs",
    "settings",
    "beta_claims",
    "prompt_templates",
    "account_gateway_settings",
    "publish_relay_packets",
)
ALLOWED_EXPECTED_CHANGES = frozenset({"plans"})
TABLE_REQUIRED_COLUMNS = {
    "codes": (
        "code_hash", "code_label", "full_code", "licensee", "edition",
        "features_json", "expires", "max_activations", "disabled", "member_mode",
        "plan", "gateway_base_url", "gateway_image_base_url", "gateway_video_base_url",
        "gateway_token", "gateway_image_token", "gateway_video_token",
        "gateway_default_model", "gateway_image_model", "gateway_video_model",
        "gateway_models_json", "quotas_json", "created_at", "owner_account_id",
    ),
    "activations": (
        "id", "code_hash", "install_id", "device_id", "license_json", "activated_at",
    ),
    "accounts": (
        "id", "username", "display_name", "password_hash", "role", "status", "note",
        "created_by", "created_at", "updated_at", "last_login_at", "last_login_ip",
    ),
    "admin_sessions": (
        "session_hash", "account_id", "created_at", "updated_at", "expires_at",
        "revoked_at", "request_ip", "user_agent",
    ),
    "invite_codes": (
        "id", "invite_code", "role", "status", "max_uses", "used_count", "note",
        "created_by", "created_at", "updated_at", "expires_at", "last_used_at",
        "last_used_ip", "last_used_username", "last_used_account_id",
    ),
    "audit_logs": (
        "id", "actor", "action", "target_type", "target_id", "before_json",
        "after_json", "request_ip", "backup_path", "created_at",
    ),
    "settings": ("key", "value_json", "updated_at"),
    "beta_claims": ("id", "day", "ip", "full_code", "expires", "created_at"),
    "prompt_templates": (
        "id", "kind", "title", "prompt", "params_json", "cover_url", "tags", "sort",
        "enabled", "created_at", "updated_at",
    ),
    "account_gateway_settings": (
        "account_id", "gateway_base_url", "gateway_image_base_url",
        "gateway_video_base_url", "gateway_token", "gateway_image_token",
        "gateway_video_token", "gateway_default_model", "gateway_image_model",
        "gateway_video_model", "gateway_models_json", "created_at", "updated_at",
    ),
    "publish_relay_packets": (
        "seq", "packet_id", "channel_id", "packet_json", "status", "attempts",
        "created_at", "updated_at", "leased_by", "lease_id", "lease_until_ms",
        "next_available_at_ms", "completed_at", "result_json", "last_error",
    ),
    "plans": (
        "plan_key", "display_name", "duration_days", "features_json", "gateway_base_url",
        "gateway_image_base_url", "gateway_video_base_url", "gateway_token",
        "gateway_image_token", "gateway_video_token", "gateway_default_model",
        "gateway_image_model", "gateway_video_model", "gateway_models_json", "quotas_json",
        "disabled", "created_at", "updated_at",
    ),
}


class DatabaseVerificationError(ValueError):
    pass


@dataclass(frozen=True)
class TableComparison:
    table: str
    before_count: int
    after_count: int
    equal: bool
    expected_change: bool = False


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _table_names(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute(
            "select name from sqlite_master where type = 'table' and name not like 'sqlite_%'"
        )
    }


def _columns(connection: sqlite3.Connection, table: str) -> list[str]:
    return [str(row[1]) for row in connection.execute(f"pragma table_info({_quote_identifier(table)})")]


def _safe_value(value: object) -> tuple[str, str]:
    if value is None:
        return ("null", "")
    if isinstance(value, bytes):
        return ("bytes-sha256", hashlib.sha256(value).hexdigest())
    return (type(value).__name__, str(value))


def _row_digest(connection: sqlite3.Connection, table: str, columns: Iterable[str]) -> tuple[int, str]:
    column_list = list(columns)
    query = "select " + ",".join(_quote_identifier(column) for column in column_list)
    query += " from " + _quote_identifier(table)
    rows = sorted(tuple(_safe_value(value) for value in row) for row in connection.execute(query))
    payload = json.dumps(rows, ensure_ascii=False, separators=(",", ":"), sort_keys=False).encode("utf-8")
    return len(rows), hashlib.sha256(payload).hexdigest()


def _existing_regular_file(value: str, label: str) -> Path:
    path = Path(value).expanduser()
    if not path.exists():
        raise DatabaseVerificationError(f"{label} database does not exist")
    if not path.is_file():
        raise DatabaseVerificationError(f"{label} database is not a regular file")
    return path.resolve(strict=True)


def _open_read_only(path: Path, label: str) -> sqlite3.Connection:
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
        connection.execute("pragma query_only = on")
        return connection
    except sqlite3.Error:
        if connection is not None:
            connection.close()
        raise DatabaseVerificationError(f"{label} database is not readable SQLite") from None


def _validate_required_schema(
    connection: sqlite3.Connection,
    label: str,
) -> None:
    table_names = _table_names(connection)
    missing_tables = sorted(set(TABLE_REQUIRED_COLUMNS) - table_names)
    if missing_tables:
        raise DatabaseVerificationError(
            f"required tables unavailable in {label}: " + ",".join(missing_tables)
        )

    invalid_tables = []
    for table, required_columns in TABLE_REQUIRED_COLUMNS.items():
        if not set(required_columns).issubset(_columns(connection, table)):
            invalid_tables.append(table)
    if invalid_tables:
        raise DatabaseVerificationError(
            f"required columns unavailable in {label}: " + ",".join(invalid_tables)
        )


def compare_table(
    before: sqlite3.Connection,
    after: sqlite3.Connection,
    table: str,
    *,
    expected_change: bool = False,
) -> TableComparison:
    before_names = _table_names(before)
    after_names = _table_names(after)
    if table not in before_names or table not in after_names:
        return TableComparison(table, -1, -1, table not in before_names and table not in after_names, expected_change)

    before_columns = _columns(before, table)
    after_columns = _columns(after, table)
    after_column_names = set(after_columns)
    if not before_columns or not after_columns or not set(before_columns).issubset(after_column_names):
        return TableComparison(table, -1, -1, False, expected_change)

    before_count, before_digest = _row_digest(before, table, before_columns)
    after_count, after_digest = _row_digest(after, table, before_columns)
    return TableComparison(table, before_count, after_count, before_digest == after_digest, expected_change)


def verify_databases(
    before_path: str,
    after_path: str,
    *,
    expected_changes: Iterable[str] = ("plans",),
) -> tuple[list[TableComparison], list[str]]:
    comparisons: list[TableComparison] = []
    failures: list[str] = []
    expected = tuple(dict.fromkeys(str(item).strip() for item in expected_changes if str(item).strip()))
    unsupported = sorted(set(expected) - ALLOWED_EXPECTED_CHANGES)
    if unsupported:
        raise DatabaseVerificationError(
            "unsupported expected-change table: " + ",".join(unsupported)
        )
    before_file = _existing_regular_file(before_path, "before")
    after_file = _existing_regular_file(after_path, "after")
    if before_file.samefile(after_file):
        raise DatabaseVerificationError("before and after databases refer to the same file")
    try:
        with closing(_open_read_only(before_file, "before")) as before, closing(
            _open_read_only(after_file, "after")
        ) as after:
            _validate_required_schema(before, "before")
            _validate_required_schema(after, "after")
            for table in TABLE_REQUIRED_COLUMNS:
                expected_change = table in expected
                result = compare_table(before, after, table, expected_change=expected_change)
                comparisons.append(result)
                if result.before_count < 0 or (not result.equal and not expected_change):
                    failures.append(table)
    except DatabaseVerificationError:
        raise
    except sqlite3.Error:
        raise DatabaseVerificationError("database schema or contents are not readable SQLite") from None
    return comparisons, failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", required=True)
    parser.add_argument("--after", required=True)
    parser.add_argument("--expect-change", action="append", default=["plans"])
    args = parser.parse_args()

    try:
        comparisons, failures = verify_databases(
            args.before,
            args.after,
            expected_changes=args.expect_change,
        )
    except DatabaseVerificationError as error:
        print(f"verification_error={error}")
        return 2
    for item in comparisons:
        print(
            f"{item.table}=before:{item.before_count},after:{item.after_count},"
            f"equal:{str(item.equal).lower()},expected_change:{str(item.expected_change).lower()}"
        )
    if failures:
        print("protected_tables_changed=" + ",".join(failures))
        return 1
    print("protected_tables=preserved")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
