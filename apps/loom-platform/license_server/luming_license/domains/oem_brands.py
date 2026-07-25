"""Per-OEM public commerce configuration with merchant ownership isolation."""

from __future__ import annotations

import re
import sqlite3
from typing import Any, Callable
from urllib.parse import urlparse

from ..errors import ActivationError


_BRAND_ID_RE = re.compile(r"^[a-z][a-z0-9-]{2,39}$")
_VALID_STATUSES = {"active", "suspended"}


def _brand_id(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if not _BRAND_ID_RE.fullmatch(normalized):
        raise ActivationError("品牌 ID 必须是 3-40 位小写 slug")
    return normalized


def _https_url(value: Any, label: str) -> str:
    text = str(value or "").strip()
    parsed = urlparse(text)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ActivationError(f"{label} 必须是无凭据的 HTTPS 地址")
    if len(text) > 2048:
        raise ActivationError(f"{label} 不能超过 2048 个字符")
    return text


def _public(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "brandId": row["brand_id"],
        "displayName": row["display_name"],
        "ownerAccountId": int(row["owner_account_id"]),
        "status": row["status"],
        "purchaseUrl": row["purchase_url"],
        "supportUrl": row["support_url"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def list_rows(
    *,
    owner_account_id: int,
    include_all: bool,
    connect_fn: Callable[[], sqlite3.Connection],
) -> list[dict[str, Any]]:
    with connect_fn() as conn:
        if include_all:
            rows = conn.execute(
                "select * from oem_brands order by brand_id"
            ).fetchall()
        else:
            rows = conn.execute(
                "select * from oem_brands where owner_account_id = ? order by brand_id",
                (owner_account_id,),
            ).fetchall()
    return [_public(row) for row in rows]


def get_row(
    brand_id: Any,
    *,
    connect_fn: Callable[[], sqlite3.Connection],
) -> sqlite3.Row | None:
    normalized = _brand_id(brand_id)
    with connect_fn() as conn:
        return conn.execute(
            "select * from oem_brands where brand_id = ?",
            (normalized,),
        ).fetchone()


def public_config(
    brand_id: Any,
    *,
    connect_fn: Callable[[], sqlite3.Connection],
) -> dict[str, Any]:
    row = get_row(brand_id, connect_fn=connect_fn)
    if row is None:
        raise ActivationError(
            "OEM 品牌不存在",
            status=404,
            code="OEM_BRAND_NOT_FOUND",
        )
    if row["status"] != "active":
        raise ActivationError(
            "OEM 品牌已停用",
            status=403,
            code="OEM_BRAND_SUSPENDED",
        )
    return {
        "brandId": row["brand_id"],
        "purchaseUrl": row["purchase_url"],
        "supportUrl": row["support_url"],
        "cardSite": {
            "enabled": bool(row["purchase_url"]),
            "label": "购买授权码",
            "url": row["purchase_url"],
        },
    }


def upsert(
    body: dict[str, Any],
    *,
    actor_account_id: int,
    is_super_admin: bool,
    connect_fn: Callable[[], sqlite3.Connection],
    get_account_by_id_fn: Callable[[int], Any],
    utc_now_fn: Callable[[], str],
) -> dict[str, Any]:
    brand_id = _brand_id(body.get("brandId"))
    display_name = str(body.get("displayName") or "").strip()
    if not display_name:
        raise ActivationError("品牌显示名称不能为空")
    if len(display_name) > 120:
        raise ActivationError("品牌显示名称不能超过 120 个字符")
    status = str(body.get("status") or "active").strip().lower()
    if status not in _VALID_STATUSES:
        raise ActivationError("品牌状态必须是 active 或 suspended")
    purchase_url = _https_url(body.get("purchaseUrl"), "购买地址")
    support_url = _https_url(body.get("supportUrl"), "支持地址")
    requested_owner = int(body.get("ownerAccountId") or actor_account_id or 0)
    owner_account_id = requested_owner if is_super_admin else actor_account_id
    if owner_account_id <= 0:
        raise ActivationError("品牌必须归属有效商户")
    owner = get_account_by_id_fn(owner_account_id)
    if not owner or str(owner["status"] or "") != "active":
        raise ActivationError("品牌归属商户不存在或已停用")

    now = utc_now_fn()
    with connect_fn() as conn:
        existing = conn.execute(
            "select * from oem_brands where brand_id = ?",
            (brand_id,),
        ).fetchone()
        if (
            existing is not None
            and not is_super_admin
            and int(existing["owner_account_id"]) != actor_account_id
        ):
            raise ActivationError("无权修改其他商户的 OEM 品牌", status=403)
        created_at = existing["created_at"] if existing is not None else now
        conn.execute(
            """
            insert into oem_brands (
                brand_id, display_name, owner_account_id, status,
                purchase_url, support_url, created_at, updated_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(brand_id) do update set
                display_name = excluded.display_name,
                owner_account_id = excluded.owner_account_id,
                status = excluded.status,
                purchase_url = excluded.purchase_url,
                support_url = excluded.support_url,
                updated_at = excluded.updated_at
            """,
            (
                brand_id,
                display_name,
                owner_account_id,
                status,
                purchase_url,
                support_url,
                created_at,
                now,
            ),
        )
        row = conn.execute(
            "select * from oem_brands where brand_id = ?",
            (brand_id,),
        ).fetchone()
        conn.commit()
    if row is None:
        raise ActivationError("保存 OEM 品牌失败", status=500)
    return _public(row)


__all__ = ["get_row", "list_rows", "public_config", "upsert"]
