from __future__ import annotations

import json
import secrets
import sqlite3
from collections.abc import Callable
from datetime import date
from typing import Any

from ..errors import ActivationError
from ..serialization import load_json_value
from ..timeutils import utc_now


ConnectFn = Callable[[], sqlite3.Connection]
ContextFn = Callable[[dict[str, Any] | None], bool]
AccountIdFn = Callable[[dict[str, Any] | None], int]
BuildLicenseFn = Callable[..., dict[str, Any]]


def activation_row_public(row: sqlite3.Row) -> dict[str, Any]:
    try:
        license_data = json.loads(row["license_json"] or "{}")
    except (TypeError, json.JSONDecodeError):
        license_data = {}
    return {
        "id": row["id"],
        "codeHash": row["code_hash"],
        "installId": row["install_id"],
        "deviceId": row["device_id"],
        "licenseId": license_data.get("licenseId", ""),
        "memberId": license_data.get("memberId", ""),
        "plan": license_data.get("plan") or license_data.get("edition", ""),
        "activatedAt": row["activated_at"],
    }


def get_activation_rows(
    code_hash_value: str,
    current_account: dict[str, Any] | None = None,
    *,
    connect_fn: ConnectFn | None = None,
    is_super_admin_context_fn: ContextFn | None = None,
    context_account_id_fn: AccountIdFn | None = None,
    activation_row_public_fn: Callable[[sqlite3.Row], dict[str, Any]] = activation_row_public,
) -> list[dict[str, Any]]:
    super_admin = is_super_admin_context_fn or _missing_context
    account_id = context_account_id_fn or _missing_account_id
    owner_clause = ""
    params: tuple[Any, ...] = (code_hash_value,)
    if current_account and not super_admin(current_account):
        owner_clause = "and c.owner_account_id = ?"
        params += (account_id(current_account),)
    with (connect_fn or _missing_connect)() as conn:
        code_row = conn.execute(
            f"select c.owner_account_id from codes c where c.code_hash = ? {owner_clause}", params
        ).fetchone()
        if not code_row:
            raise ActivationError("授权码不存在或无权访问", 404)
        rows = conn.execute(
            f"""
            select a.id, a.code_hash, a.install_id, a.device_id, a.license_json, a.activated_at
            from activations a
            join codes c on c.code_hash = a.code_hash
            where a.code_hash = ? {owner_clause}
            order by a.activated_at desc
            """,
            params,
        ).fetchall()
    return [activation_row_public_fn(row) for row in rows]


def get_all_activation_rows(
    current_account: dict[str, Any] | None = None,
    *,
    connect_fn: ConnectFn | None = None,
    is_super_admin_context_fn: ContextFn | None = None,
    context_account_id_fn: AccountIdFn | None = None,
) -> list[dict[str, Any]]:
    super_admin = is_super_admin_context_fn or _missing_context
    account_id = context_account_id_fn or _missing_account_id
    where_clause = ""
    params: tuple[Any, ...] = ()
    if current_account and not super_admin(current_account):
        where_clause = "where c.owner_account_id = ?"
        params = (account_id(current_account),)
    with (connect_fn or _missing_connect)() as conn:
        rows = conn.execute(
            f"""
            select a.id, a.code_hash, a.install_id, a.device_id, a.activated_at,
                   c.code_label, c.plan, c.owner_account_id,
                   coalesce(acc.display_name, '') as owner_display_name
            from activations a
            join codes c on c.code_hash = a.code_hash
            left join accounts acc on acc.id = c.owner_account_id
            {where_clause}
            order by a.activated_at desc, a.id desc
            """,
            params,
        ).fetchall()
    return [
        {
            "activationId": int(row["id"]),
            "codeHash": row["code_hash"],
            "codeLabel": row["code_label"],
            "installId": row["install_id"],
            "deviceId": row["device_id"],
            "plan": row["plan"],
            "ownerDisplayName": row["owner_display_name"],
            "activatedAt": row["activated_at"],
        }
        for row in rows
    ]


def get_activation_snapshot(
    activation_id: int,
    current_account: dict[str, Any] | None = None,
    *,
    connect_fn: ConnectFn | None = None,
    is_super_admin_context_fn: ContextFn | None = None,
    context_account_id_fn: AccountIdFn | None = None,
    activation_row_public_fn: Callable[[sqlite3.Row], dict[str, Any]] = activation_row_public,
) -> dict[str, Any] | None:
    super_admin = is_super_admin_context_fn or _missing_context
    account_id = context_account_id_fn or _missing_account_id
    owner_clause = ""
    params: tuple[Any, ...] = (activation_id,)
    if current_account and not super_admin(current_account):
        owner_clause = "and c.owner_account_id = ?"
        params += (account_id(current_account),)
    with (connect_fn or _missing_connect)() as conn:
        row = conn.execute(
            f"""
            select a.id, a.code_hash, a.install_id, a.device_id, a.license_json, a.activated_at
            from activations a
            left join codes c on c.code_hash = a.code_hash
            where a.id = ? {owner_clause}
            """,
            params,
        ).fetchone()
    return activation_row_public_fn(row) if row else None


def apply_member_fields(
    payload: dict[str, Any],
    code_row: sqlite3.Row,
    *,
    default_gateway_base_url: str = "",
    default_gateway_image_base_url: str = "",
    default_gateway_video_base_url: str = "",
    default_gateway_token: str = "",
    default_gateway_image_token: str = "",
    default_gateway_video_token: str = "",
    default_gateway_default_model: str = "",
    default_gateway_image_model: str = "",
    default_gateway_video_model: str = "",
    default_gateway_models: list[str] | None = None,
    load_json_value_fn: Callable[[Any, Any], Any] = load_json_value,
) -> dict[str, Any]:
    if not bool(code_row["member_mode"]):
        return payload

    allow_global_gateway_fallback = int(code_row["owner_account_id"] or 0) <= 0
    fallback_base_url = default_gateway_base_url if allow_global_gateway_fallback else ""
    fallback_image_base_url = default_gateway_image_base_url if allow_global_gateway_fallback else ""
    fallback_video_base_url = default_gateway_video_base_url if allow_global_gateway_fallback else ""
    fallback_token = default_gateway_token if allow_global_gateway_fallback else ""
    fallback_image_token = default_gateway_image_token if allow_global_gateway_fallback else ""
    fallback_video_token = default_gateway_video_token if allow_global_gateway_fallback else ""

    gateway_base_url = str(code_row["gateway_base_url"] or fallback_base_url).strip().rstrip("/")
    gateway_image_base_url = str(code_row["gateway_image_base_url"] or fallback_image_base_url or gateway_base_url).strip().rstrip("/")
    gateway_video_base_url = str(code_row["gateway_video_base_url"] or fallback_video_base_url or gateway_base_url).strip().rstrip("/")
    gateway_token = str(code_row["gateway_token"] or fallback_token).strip()
    if not gateway_base_url or not gateway_token:
        raise ActivationError("会员网关未配置，缺少 Base URL 或 Token", 500)

    gateway_models = load_json_value_fn(code_row["gateway_models_json"], [])
    if not isinstance(gateway_models, list):
        gateway_models = []
    gateway_models = [str(item).strip() for item in gateway_models if str(item).strip()] or list(default_gateway_models or [])

    default_model = str(code_row["gateway_default_model"] or default_gateway_default_model or "").strip()
    if not default_model and gateway_models:
        default_model = gateway_models[0]

    image_model = str(code_row["gateway_image_model"] or default_gateway_image_model or "").strip()
    video_model = str(code_row["gateway_video_model"] or default_gateway_video_model or "").strip()
    image_token = str(code_row["gateway_image_token"] or fallback_image_token or gateway_token).strip() or gateway_token
    video_token = str(code_row["gateway_video_token"] or fallback_video_token or gateway_token).strip() or gateway_token

    quotas = load_json_value_fn(code_row["quotas_json"], {})
    if not isinstance(quotas, dict):
        quotas = {}

    payload.update(
        {
            "memberMode": True,
            "memberId": f"member_{code_row['code_label']}",
            "plan": str(code_row["plan"] or code_row["edition"] or "monthly").strip(),
            "leaseExpiresAt": payload.get("expires"),
            "gatewayBaseUrl": gateway_base_url,
            "gatewayImageBaseUrl": gateway_image_base_url,
            "gatewayVideoBaseUrl": gateway_video_base_url,
            "gatewayAccessToken": gateway_token,
            "gatewayToken": gateway_token,
            "gatewayImageAccessToken": image_token,
            "gatewayVideoAccessToken": video_token,
            "gatewayImageToken": image_token,
            "gatewayVideoToken": video_token,
            "gatewayDefaultModel": default_model,
            "gatewayImageModel": image_model,
            "gatewayVideoModel": video_model,
            "gatewayModels": gateway_models,
            "quotas": quotas,
            "usage": {},
        }
    )
    return payload


def build_signed_license(
    code_row: sqlite3.Row,
    install_id: str,
    device_id: str,
    *,
    license_id: str | None = None,
    activated_at: str | None = None,
    apply_member_fields_fn: Callable[[dict[str, Any], sqlite3.Row], dict[str, Any]] | None = None,
    sign_license_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    utc_now_fn: Callable[[], str] = utc_now,
) -> dict[str, Any]:
    full_code = str(code_row["full_code"] or "").strip()
    code_label = str(code_row["code_label"] or "").strip()
    code_last8 = "".join(ch for ch in (full_code or code_label).upper() if ch.isalnum())[-8:]
    payload = {
        "licenseId": license_id or secrets.token_hex(12),
        "licensee": code_row["licensee"],
        "edition": code_row["edition"],
        "plan": str(code_row["plan"] or code_row["edition"] or "monthly").strip(),
        "features": json.loads(code_row["features_json"]),
        "expires": code_row["expires"],
        "expiresAt": code_row["expires"],
        "installId": install_id,
        "deviceId": device_id,
        "deviceLimit": int(code_row["max_activations"] or 1),
        "activatedAt": activated_at or utc_now_fn(),
        "activationCodeLabel": code_label,
        "activationCodeLast8": code_last8,
    }
    payload = (apply_member_fields_fn or apply_member_fields)(payload, code_row)
    return (sign_license_fn or _missing_sign_license)(payload)


def member_response(license_data: dict[str, Any]) -> dict[str, Any]:
    image_token = license_data.get("gatewayImageAccessToken") or license_data.get("gatewayImageToken") or license_data.get("gatewayAccessToken")
    video_token = license_data.get("gatewayVideoAccessToken") or license_data.get("gatewayVideoToken") or license_data.get("gatewayAccessToken")
    image_base_url = license_data.get("gatewayImageBaseUrl") or license_data.get("gatewayBaseUrl")
    video_base_url = license_data.get("gatewayVideoBaseUrl") or license_data.get("gatewayBaseUrl")
    gateway = {
        "baseUrl": license_data.get("gatewayBaseUrl"),
        "imageBaseUrl": image_base_url,
        "videoBaseUrl": video_base_url,
        "accessToken": license_data.get("gatewayAccessToken"),
        "token": license_data.get("gatewayAccessToken"),
        "imageAccessToken": image_token,
        "videoAccessToken": video_token,
        "imageToken": image_token,
        "videoToken": video_token,
        "defaultModel": license_data.get("gatewayDefaultModel"),
        "imageModel": license_data.get("gatewayImageModel"),
        "videoModel": license_data.get("gatewayVideoModel"),
        "models": license_data.get("gatewayModels") or [],
    }
    member = {
        "memberId": license_data.get("memberId"),
        "memberName": license_data.get("licensee"),
        "plan": license_data.get("plan") or license_data.get("edition"),
        "status": "active",
        "expiresAt": license_data.get("expires"),
        "leaseExpiresAt": license_data.get("leaseExpiresAt") or license_data.get("expires"),
        "gatewayBaseUrl": license_data.get("gatewayBaseUrl"),
        "gatewayImageBaseUrl": image_base_url,
        "gatewayVideoBaseUrl": video_base_url,
        "gatewayAccessToken": license_data.get("gatewayAccessToken"),
        "gatewayToken": license_data.get("gatewayAccessToken"),
        "gatewayImageAccessToken": image_token,
        "gatewayVideoAccessToken": video_token,
        "gatewayImageToken": image_token,
        "gatewayVideoToken": video_token,
        "gatewayDefaultModel": license_data.get("gatewayDefaultModel"),
        "gatewayImageModel": license_data.get("gatewayImageModel"),
        "gatewayVideoModel": license_data.get("gatewayVideoModel"),
        "gatewayModels": license_data.get("gatewayModels") or [],
        "features": license_data.get("features") or [],
        "quotas": license_data.get("quotas") or {},
        "usage": license_data.get("usage") or {},
        "gateway": gateway,
        "lease": {
            "memberId": license_data.get("memberId"),
            "plan": license_data.get("plan") or license_data.get("edition"),
            "expiresAt": license_data.get("expires"),
            "leaseExpiresAt": license_data.get("leaseExpiresAt") or license_data.get("expires"),
            "features": license_data.get("features") or [],
            "gatewayDefaultModel": license_data.get("gatewayDefaultModel"),
            "gatewayImageBaseUrl": image_base_url,
            "gatewayVideoBaseUrl": video_base_url,
            "gatewayImageModel": license_data.get("gatewayImageModel"),
            "gatewayVideoModel": license_data.get("gatewayVideoModel"),
            "gatewayImageAccessToken": image_token,
            "gatewayVideoAccessToken": video_token,
        },
    }
    return {"license": license_data, "member": member, "lease": member["lease"], "gateway": gateway, "usage": member["usage"]}


def find_member_license(
    body: dict[str, Any],
    *,
    connect_fn: ConnectFn | None = None,
    build_signed_license_fn: BuildLicenseFn | None = None,
) -> dict[str, Any] | None:
    member_id = str(body.get("memberId") or "").strip()
    token = str(
        body.get("memberToken") or body.get("leaseToken") or body.get("gatewayAccessToken")
        or body.get("gatewayImageAccessToken") or body.get("gatewayVideoAccessToken")
        or body.get("gatewayToken") or body.get("gatewayImageToken")
        or body.get("gatewayVideoToken") or ""
    ).strip()
    install_id = str(body.get("installId") or "").strip()
    device_id = str(body.get("deviceId") or "").strip()
    if not token or not install_id:
        return None
    build_license = build_signed_license_fn or build_signed_license
    with (connect_fn or _missing_connect)() as conn:
        rows = conn.execute(
            "select id, code_hash, install_id, device_id, license_json, activated_at from activations order by activated_at desc"
        ).fetchall()
        for row in rows:
            try:
                old_license = json.loads(row["license_json"])
            except (TypeError, json.JSONDecodeError):
                continue
            if install_id and row["install_id"] != install_id:
                continue
            if device_id and row["device_id"] != device_id:
                continue
            if member_id and str(old_license.get("memberId") or "") != member_id:
                continue
            token_candidates = [
                old_license.get("gatewayAccessToken"), old_license.get("gatewayToken"),
                old_license.get("gatewayImageAccessToken"), old_license.get("gatewayVideoAccessToken"),
                old_license.get("gatewayImageToken"), old_license.get("gatewayVideoToken"),
            ]
            if token not in {str(item or "").strip() for item in token_candidates if str(item or "").strip()}:
                continue
            code_row = conn.execute("select * from codes where code_hash = ?", (row["code_hash"],)).fetchone()
            if not code_row or code_row["disabled"] or not bool(code_row["member_mode"]):
                continue
            license_data = build_license(
                code_row,
                str(row["install_id"] or ""),
                str(row["device_id"] or ""),
                license_id=str(old_license.get("licenseId") or "") or None,
                activated_at=str(old_license.get("activatedAt") or row["activated_at"] or "") or None,
            )
            conn.execute(
                "update activations set license_json = ? where id = ?",
                (json.dumps(license_data, ensure_ascii=False), row["id"]),
            )
            conn.commit()
            return license_data
    return None


def activate_code(
    body: dict[str, Any],
    *,
    connect_fn: ConnectFn | None = None,
    code_hash_fn: Callable[[str], str] | None = None,
    build_signed_license_fn: BuildLicenseFn | None = None,
    utc_now_fn: Callable[[], str] = utc_now,
) -> dict[str, Any]:
    code = str(body.get("code", "")).strip().upper()
    install_id = str(body.get("installId", "")).strip()
    device_id = str(body.get("deviceId", "")).strip()
    if not code or not install_id:
        raise ActivationError("缺少授权码或安装 ID", 400, "LICENSE_INVALID_REQUEST")

    hashed = (code_hash_fn or _missing_code_hash)(code)
    with (connect_fn or _missing_connect)() as conn:
        conn.execute("BEGIN IMMEDIATE")
        code_row = conn.execute("select * from codes where code_hash = ?", (hashed,)).fetchone()
        if not code_row:
            raise ActivationError("授权码不存在", 404, "LICENSE_INVALID")
        if code_row["disabled"]:
            raise ActivationError("授权码已停用", 403, "LICENSE_DISABLED")
        try:
            if date.fromisoformat(str(code_row["expires"])) < date.today():
                raise ActivationError("授权码已过期", 403, "LICENSE_EXPIRED")
        except ValueError as error:
            raise ActivationError("授权码到期日期无效", 500, "LICENSE_DATA_INVALID") from error
        existing = conn.execute(
            "select * from activations where code_hash = ? and install_id = ?", (hashed, install_id)
        ).fetchone()
        if existing:
            existing_device = str(existing["device_id"] or "").strip()
            if existing_device and device_id and existing_device != device_id:
                raise ActivationError("授权码绑定设备与当前设备不匹配", 403, "DEVICE_MISMATCH")
            conn.execute("delete from activations where code_hash = ? and install_id = ?", (hashed, install_id))
        used_count = conn.execute(
            "select count(*) as count from activations where code_hash = ?", (hashed,)
        ).fetchone()["count"]
        if used_count >= code_row["max_activations"]:
            raise ActivationError("授权码已被其他设备激活", 403, "DEVICE_MISMATCH")
        license_data = (build_signed_license_fn or build_signed_license)(code_row, install_id, device_id)
        conn.execute(
            "insert into activations (code_hash, install_id, device_id, license_json, activated_at) values (?, ?, ?, ?, ?)",
            (hashed, install_id, device_id, json.dumps(license_data, ensure_ascii=False), utc_now_fn()),
        )
        conn.commit()
        return license_data


def _missing_connect() -> sqlite3.Connection:
    raise RuntimeError("connect_fn is required")


def _missing_context(_context: dict[str, Any] | None) -> bool:
    raise RuntimeError("is_super_admin_context_fn is required")


def _missing_account_id(_context: dict[str, Any] | None) -> int:
    raise RuntimeError("context_account_id_fn is required")


def _missing_sign_license(_payload: dict[str, Any]) -> dict[str, Any]:
    raise RuntimeError("sign_license_fn is required")


def _missing_code_hash(_code: str) -> str:
    raise RuntimeError("code_hash_fn is required")
