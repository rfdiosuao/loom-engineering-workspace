from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import sqlite3
from collections.abc import Callable
from typing import Any

from .. import audit, db
from ..errors import ActivationError
from ..timeutils import utc_now


COMMERCIAL_FEATURES = [
    "acquisition.workbench",
    "acquisition.feishu",
    "matrix.devices",
    "templates.cloud",
    "publishing.draft",
    "diagnostics.export",
]
DEFAULT_FEATURES = ["openclaw", "image", "video", "storyboard", *COMMERCIAL_FEATURES]
VIP_DEFAULT_FEATURES = [*DEFAULT_FEATURES, "phoneAgent", "desktopAgent"]
MAX_BULK_CODE_HASHES = 1000
MAX_CODE_SECRET_EXPORT = 500

ConnectFn = Callable[[], sqlite3.Connection]
NormalizeExpiresFn = Callable[[str], str]
ParseFeaturesFn = Callable[[str], list[str]]
ParseModelsFn = Callable[[Any], list[str]]
ParseJsonObjectFn = Callable[[Any], dict[str, Any]]
LoadJsonValueFn = Callable[[Any, Any], Any]
MaskedSecretFn = Callable[[Any], str]


def code_hash(code: str) -> str:
    normalized = code.strip().upper()
    return hashlib.sha256(f"openclaw-license-v1:{normalized}".encode("utf-8")).hexdigest()


def normalize_code_hashes(value: Any, *, max_bulk_code_hashes: int = MAX_BULK_CODE_HASHES) -> list[str]:
    if not isinstance(value, list):
        raise ActivationError("批量更新需要授权码列表")
    if len(value) > max_bulk_code_hashes:
        raise ActivationError(f"批量更新一次最多支持 {max_bulk_code_hashes} 个授权码", 400)
    seen: set[str] = set()
    normalized: list[str] = []
    for item in value:
        item_hash = str(item or "").strip().lower()
        if not item_hash:
            continue
        if len(item_hash) != 64 or any(ch not in "0123456789abcdef" for ch in item_hash):
            raise ActivationError("授权码哈希格式不正确", 400)
        if item_hash not in seen:
            seen.add(item_hash)
            normalized.append(item_hash)
    return normalized


def make_code(edition: str = "PRO") -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    chunks = ["".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(4)]
    return f"OC-{edition.upper()}-" + "-".join(chunks)


def is_super_admin_context(
    context: dict[str, Any] | None,
    *,
    account_role_super_admin: str = "super_admin",
) -> bool:
    return bool(context) and str(context.get("role") or "").strip() == account_role_super_admin


def context_account_id(context: dict[str, Any] | None) -> int:
    if not context:
        return 0
    try:
        return int(context.get("accountId") or 0)
    except (TypeError, ValueError):
        return 0


def code_row_owned_by_context(
    row: sqlite3.Row,
    context: dict[str, Any] | None,
    *,
    is_super_admin_context_fn: Callable[[dict[str, Any] | None], bool] | None = None,
    context_account_id_fn: Callable[[dict[str, Any] | None], int] = context_account_id,
) -> bool:
    super_admin = is_super_admin_context_fn or is_super_admin_context
    if not context or super_admin(context):
        return True
    return int(row["owner_account_id"] or 0) == context_account_id_fn(context)


def _insert_code_record(conn: sqlite3.Connection, values: tuple[Any, ...]) -> None:
    conn.execute(
        """
        insert into codes (
            code_hash, code_label, full_code, licensee, edition, features_json, expires,
            max_activations, disabled, member_mode, plan, gateway_base_url, gateway_token,
            gateway_image_base_url, gateway_video_base_url,
            gateway_image_token, gateway_video_token,
            gateway_default_model, gateway_image_model, gateway_video_model,
            gateway_models_json, quotas_json, owner_account_id, created_at
        )
        values (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        values,
    )


def create_code_records(
    *,
    count: int,
    licensee: str,
    edition: str,
    features: list[str],
    expires: str,
    max_activations: int,
    member_mode: bool = False,
    plan: str = "",
    gateway_base_url: str = "",
    gateway_image_base_url: str = "",
    gateway_video_base_url: str = "",
    gateway_token: str = "",
    gateway_image_token: str = "",
    gateway_video_token: str = "",
    gateway_default_model: str = "",
    gateway_image_model: str = "",
    gateway_video_model: str = "",
    gateway_models: list[str] | None = None,
    quotas: dict[str, Any] | None = None,
    owner_account_id: int = 0,
    connect_fn: ConnectFn | None = None,
    normalize_code_expires_fn: NormalizeExpiresFn | None = None,
    make_code_fn: Callable[[str], str] = make_code,
    code_hash_fn: Callable[[str], str] = code_hash,
    utc_now_fn: Callable[[], str] = utc_now,
) -> list[str]:
    connect_db = connect_fn or _missing_connect
    normalize_expires = normalize_code_expires_fn or _missing_normalize_expires
    count = max(1, min(int(count), 100))
    max_activations = max(1, min(int(max_activations), 20))
    expires = normalize_expires(expires)
    codes: list[str] = []
    with connect_db() as conn:
        for _ in range(count):
            code = make_code_fn(edition)
            _insert_code_record(
                conn,
                (
                    code_hash_fn(code), code[-9:], code, licensee, edition,
                    json.dumps(features, ensure_ascii=False), expires, max_activations,
                    1 if member_mode else 0, plan.strip(), gateway_base_url.strip().rstrip("/"),
                    gateway_token.strip(), gateway_image_base_url.strip().rstrip("/"),
                    gateway_video_base_url.strip().rstrip("/"), gateway_image_token.strip(),
                    gateway_video_token.strip(), gateway_default_model.strip(),
                    gateway_image_model.strip(), gateway_video_model.strip(),
                    json.dumps(gateway_models or [], ensure_ascii=False),
                    json.dumps(quotas or {}, ensure_ascii=False), int(owner_account_id or 0), utc_now_fn(),
                ),
            )
            codes.append(code)
        conn.commit()
    return codes


def update_code_record(
    body: dict[str, Any],
    current_account: dict[str, Any] | None = None,
    *,
    connect_fn: ConnectFn | None = None,
    normalize_code_expires_fn: NormalizeExpiresFn | None = None,
    parse_features_fn: ParseFeaturesFn | None = None,
    parse_models_fn: ParseModelsFn | None = None,
    parse_json_object_fn: ParseJsonObjectFn | None = None,
    code_row_owned_by_context_fn: Callable[[sqlite3.Row, dict[str, Any] | None], bool] | None = None,
    default_features: list[str] | None = None,
) -> None:
    connect_db = connect_fn or _missing_connect
    normalize_expires = normalize_code_expires_fn or _missing_normalize_expires
    parse_features = parse_features_fn or _missing_parse_features
    parse_models = parse_models_fn or _missing_parse_models
    parse_json = parse_json_object_fn or _missing_parse_json_object
    owns_row = code_row_owned_by_context_fn or code_row_owned_by_context
    features_default = default_features or DEFAULT_FEATURES
    code_hash_value = str(body.get("codeHash", "")).strip()
    if not code_hash_value:
        raise ActivationError("缺少授权码标识")

    licensee = str(body.get("licensee", "OpenClaw Customer")).strip() or "OpenClaw Customer"
    edition = str(body.get("edition", "pro")).strip() or "pro"
    expires = str(body.get("expires", "")).strip()
    if not expires:
        raise ActivationError("请填写到期时间")
    expires = normalize_expires(expires)

    max_activations = max(1, min(int(body.get("maxActivations", 1)), 999))
    features = parse_features(str(body.get("features", ",".join(features_default))))
    member_mode = bool(body.get("memberMode"))
    plan = str(body.get("plan", "")).strip()
    gateway_base_url = str(body.get("gatewayBaseUrl", "")).strip().rstrip("/")
    gateway_image_base_url = str(body.get("gatewayImageBaseUrl") or body.get("gateway_image_base_url") or "").strip().rstrip("/")
    gateway_video_base_url = str(body.get("gatewayVideoBaseUrl") or body.get("gateway_video_base_url") or "").strip().rstrip("/")
    gateway_token = str(body.get("gatewayToken", "")).strip()
    gateway_image_token = str(body.get("gatewayImageToken") or body.get("gateway_image_token") or "").strip()
    gateway_video_token = str(body.get("gatewayVideoToken") or body.get("gateway_video_token") or "").strip()
    gateway_default_model = str(body.get("gatewayDefaultModel", "")).strip()
    gateway_image_model = str(body.get("gatewayImageModel") or body.get("gateway_image_model") or "").strip()
    gateway_video_model = str(body.get("gatewayVideoModel") or body.get("gateway_video_model") or "").strip()
    gateway_models = parse_models(body.get("gatewayModels", ""))
    quotas = parse_json(body.get("quotas", ""))

    with connect_db() as conn:
        existing = conn.execute(
            """
            select owner_account_id, gateway_image_base_url, gateway_video_base_url,
                   gateway_token, gateway_image_token, gateway_video_token,
                   gateway_image_model, gateway_video_model
            from codes where code_hash = ?
            """,
            (code_hash_value,),
        ).fetchone()
        if not existing:
            raise ActivationError("授权码不存在", 404)
        if current_account and not owns_row(existing, current_account):
            raise ActivationError("无权修改该授权码", 403)
        gateway_image_base_url = gateway_image_base_url or str(existing["gateway_image_base_url"] or "")
        gateway_video_base_url = gateway_video_base_url or str(existing["gateway_video_base_url"] or "")
        gateway_token = gateway_token or str(existing["gateway_token"] or "")
        gateway_image_token = gateway_image_token or str(existing["gateway_image_token"] or "")
        gateway_video_token = gateway_video_token or str(existing["gateway_video_token"] or "")
        gateway_image_model = gateway_image_model or str(existing["gateway_image_model"] or "")
        gateway_video_model = gateway_video_model or str(existing["gateway_video_model"] or "")
        result = conn.execute(
            """
            update codes
            set licensee = ?, edition = ?, features_json = ?, expires = ?, max_activations = ?,
                member_mode = ?, plan = ?, gateway_base_url = ?, gateway_image_base_url = ?,
                gateway_video_base_url = ?, gateway_token = ?, gateway_image_token = ?,
                gateway_video_token = ?, gateway_default_model = ?, gateway_image_model = ?,
                gateway_video_model = ?, gateway_models_json = ?, quotas_json = ?
            where code_hash = ?
            """,
            (
                licensee, edition, json.dumps(features, ensure_ascii=False), expires, max_activations,
                1 if member_mode else 0, plan, gateway_base_url, gateway_image_base_url,
                gateway_video_base_url, gateway_token, gateway_image_token, gateway_video_token,
                gateway_default_model, gateway_image_model, gateway_video_model,
                json.dumps(gateway_models or [], ensure_ascii=False),
                json.dumps(quotas or {}, ensure_ascii=False), code_hash_value,
            ),
        )
        conn.commit()
        if result.rowcount == 0:
            raise ActivationError("授权码不存在", 404)


def bulk_update_code_records(
    body: dict[str, Any],
    current_account: dict[str, Any] | None = None,
    *,
    connect_fn: ConnectFn | None = None,
    normalize_code_hashes_fn: Callable[[Any], list[str]] | None = None,
    code_row_owned_by_context_fn: Callable[[sqlite3.Row, dict[str, Any] | None], bool] | None = None,
    update_code_record_fn: Callable[..., None] | None = None,
    load_json_value_fn: LoadJsonValueFn | None = None,
    default_features: list[str] | None = None,
) -> int:
    connect_db = connect_fn or _missing_connect
    normalize_hashes = normalize_code_hashes_fn or normalize_code_hashes
    owns_row = code_row_owned_by_context_fn or code_row_owned_by_context
    update_record = update_code_record_fn or update_code_record
    load_json = load_json_value_fn or _missing_load_json_value
    features_default = default_features or DEFAULT_FEATURES
    code_hashes = normalize_hashes(body.get("codeHashes"))
    updated = 0
    with connect_db() as conn:
        rows = conn.execute(
            f"select * from codes where code_hash in ({','.join(['?'] * len(code_hashes))})",
            tuple(code_hashes),
        ).fetchall() if code_hashes else []

    for row in rows:
        if current_account and not owns_row(row, current_account):
            raise ActivationError("无权修改该授权码", 403)
        merged = {
            "codeHash": row["code_hash"],
            "licensee": row["licensee"],
            "edition": row["edition"],
            "features": str(body.get("features") or "").strip() or ",".join(load_json(row["features_json"], features_default)),
            "expires": str(body.get("expires") or "").strip() or row["expires"],
            "maxActivations": body.get("maxActivations") or row["max_activations"],
            "memberMode": body.get("memberMode") if "memberMode" in body else bool(row["member_mode"]),
            "plan": str(body.get("plan") or "").strip() or row["plan"] or "monthly",
            "gatewayBaseUrl": str(body.get("gatewayBaseUrl") or "").strip() or row["gateway_base_url"],
            "gatewayImageBaseUrl": str(body.get("gatewayImageBaseUrl") or body.get("gateway_image_base_url") or "").strip() or row["gateway_image_base_url"],
            "gatewayVideoBaseUrl": str(body.get("gatewayVideoBaseUrl") or body.get("gateway_video_base_url") or "").strip() or row["gateway_video_base_url"],
            "gatewayToken": str(body.get("gatewayToken") or "").strip(),
            "gatewayImageToken": str(body.get("gatewayImageToken") or body.get("gateway_image_token") or "").strip(),
            "gatewayVideoToken": str(body.get("gatewayVideoToken") or body.get("gateway_video_token") or "").strip(),
            "gatewayDefaultModel": str(body.get("gatewayDefaultModel") or "").strip() or row["gateway_default_model"],
            "gatewayImageModel": str(body.get("gatewayImageModel") or body.get("gateway_image_model") or "").strip() or row["gateway_image_model"],
            "gatewayVideoModel": str(body.get("gatewayVideoModel") or body.get("gateway_video_model") or "").strip() or row["gateway_video_model"],
            "gatewayModels": str(body.get("gatewayModels") or "").strip() or ",".join(load_json(row["gateway_models_json"], [])),
            "quotas": str(body.get("quotas") or "").strip() or row["quotas_json"] or "{}",
        }
        update_record(merged, current_account=current_account)
        updated += 1
    return updated


def code_row_snapshot(
    row: sqlite3.Row | None,
    *,
    load_json_value_fn: LoadJsonValueFn | None = None,
    masked_secret_fn: MaskedSecretFn | None = None,
    default_features: list[str] | None = None,
) -> dict[str, Any] | None:
    if not row:
        return None
    load_json = load_json_value_fn or _missing_load_json_value
    mask_secret = masked_secret_fn or audit.masked_secret
    row_keys = set(row.keys())
    return {
        "codeHash": row["code_hash"], "codeLabel": row["code_label"],
        "licensee": row["licensee"], "edition": row["edition"],
        "features": load_json(row["features_json"], default_features or DEFAULT_FEATURES),
        "expires": row["expires"], "maxActivations": row["max_activations"],
        "disabled": bool(row["disabled"]), "memberMode": bool(row["member_mode"]),
        "plan": row["plan"], "gatewayBaseUrl": row["gateway_base_url"],
        "gatewayImageBaseUrl": row["gateway_image_base_url"],
        "gatewayVideoBaseUrl": row["gateway_video_base_url"],
        "gatewayToken": mask_secret(row["gateway_token"]),
        "gatewayImageToken": mask_secret(row["gateway_image_token"]),
        "gatewayVideoToken": mask_secret(row["gateway_video_token"]),
        "gatewayDefaultModel": row["gateway_default_model"],
        "gatewayImageModel": row["gateway_image_model"],
        "gatewayVideoModel": row["gateway_video_model"],
        "gatewayModels": load_json(row["gateway_models_json"], []),
        "quotas": load_json(row["quotas_json"], {}),
        "ownerAccountId": int(row["owner_account_id"]) if "owner_account_id" in row_keys and row["owner_account_id"] is not None else 0,
        "ownerUsername": row["owner_username"] if "owner_username" in row_keys else "",
        "ownerDisplayName": row["owner_display_name"] if "owner_display_name" in row_keys else "",
        "ownerRole": row["owner_role"] if "owner_role" in row_keys else "",
        "activations": int(row["activations"]) if "activations" in row_keys else None,
        "createdAt": row["created_at"],
    }


def get_code_snapshot(
    code_hash_value: str,
    current_account: dict[str, Any] | None = None,
    *,
    connect_fn: ConnectFn | None = None,
    code_row_owned_by_context_fn: Callable[[sqlite3.Row, dict[str, Any] | None], bool] | None = None,
    code_row_snapshot_fn: Callable[[sqlite3.Row | None], dict[str, Any] | None] | None = None,
) -> dict[str, Any] | None:
    if not code_hash_value:
        return None
    with (connect_fn or _missing_connect)() as conn:
        row = conn.execute(
            """
            select c.*, count(a.id) as activations,
                   coalesce(acc.username, '') as owner_username,
                   coalesce(acc.display_name, '') as owner_display_name,
                   coalesce(acc.role, '') as owner_role
            from codes c
            left join activations a on a.code_hash = c.code_hash
            left join accounts acc on acc.id = c.owner_account_id
            where c.code_hash = ? group by c.code_hash
            """,
            (code_hash_value,),
        ).fetchone()
    owns_row = code_row_owned_by_context_fn or code_row_owned_by_context
    if row and current_account and not owns_row(row, current_account):
        return None
    return (code_row_snapshot_fn or _missing_code_row_snapshot)(row)


def get_code_snapshots(
    code_hashes: list[Any],
    current_account: dict[str, Any] | None = None,
    *,
    connect_fn: ConnectFn | None = None,
    code_row_snapshot_fn: Callable[[sqlite3.Row | None], dict[str, Any] | None] | None = None,
    is_super_admin_context_fn: Callable[[dict[str, Any] | None], bool] | None = None,
    context_account_id_fn: Callable[[dict[str, Any] | None], int] = context_account_id,
) -> list[dict[str, Any]]:
    clean_hashes = [str(item).strip() for item in code_hashes if str(item).strip()]
    if not clean_hashes:
        return []
    placeholders = ",".join(["?"] * len(clean_hashes))
    with (connect_fn or _missing_connect)() as conn:
        rows = conn.execute(
            f"""
            select c.*, count(a.id) as activations,
                   coalesce(acc.username, '') as owner_username,
                   coalesce(acc.display_name, '') as owner_display_name,
                   coalesce(acc.role, '') as owner_role
            from codes c
            left join activations a on a.code_hash = c.code_hash
            left join accounts acc on acc.id = c.owner_account_id
            where c.code_hash in ({placeholders})
            group by c.code_hash order by c.created_at desc
            """,
            tuple(clean_hashes),
        ).fetchall()
    snapshot_row = code_row_snapshot_fn or _missing_code_row_snapshot
    snapshots = [snapshot for row in rows if (snapshot := snapshot_row(row))]
    super_admin = is_super_admin_context_fn or is_super_admin_context
    if current_account and not super_admin(current_account):
        snapshots = [row for row in snapshots if row.get("ownerAccountId", 0) == context_account_id_fn(current_account)]
    return snapshots


def get_inventory_snapshot(*, connect_fn: ConnectFn | None = None) -> dict[str, Any]:
    with (connect_fn or _missing_connect)() as conn:
        code_count = conn.execute("select count(*) from codes").fetchone()[0]
        activation_count = conn.execute("select count(*) from activations").fetchone()[0]
        sample = conn.execute(
            "select code_hash, code_label, licensee, edition, expires from codes order by created_at desc limit 20"
        ).fetchall()
    return {"codeCount": code_count, "activationCount": activation_count, "sample": [dict(row) for row in sample]}


def create_codes(
    args: argparse.Namespace,
    *,
    create_code_records_fn: Callable[..., list[str]] | None = None,
    parse_models_fn: ParseModelsFn | None = None,
    parse_json_object_fn: ParseJsonObjectFn | None = None,
    default_features: list[str] | None = None,
) -> None:
    features = args.features.split(",") if args.features else (default_features or DEFAULT_FEATURES)
    for code in (create_code_records_fn or create_code_records)(
        count=args.count, licensee=args.licensee, edition=args.edition, features=features,
        expires=args.expires, max_activations=args.max_activations, member_mode=args.member_mode,
        plan=args.plan, gateway_base_url=args.gateway_base_url,
        gateway_image_base_url=args.gateway_image_base_url, gateway_video_base_url=args.gateway_video_base_url,
        gateway_token=args.gateway_token, gateway_image_token=args.gateway_image_token,
        gateway_video_token=args.gateway_video_token, gateway_default_model=args.gateway_default_model,
        gateway_image_model=args.gateway_image_model, gateway_video_model=args.gateway_video_model,
        gateway_models=(parse_models_fn or _missing_parse_models)(args.gateway_models),
        quotas=(parse_json_object_fn or _missing_parse_json_object)(args.quotas),
    ):
        print(code)


def get_code_rows(
    current_account: dict[str, Any] | None = None,
    *,
    connect_fn: ConnectFn | None = None,
    is_super_admin_context_fn: Callable[[dict[str, Any] | None], bool] | None = None,
    context_account_id_fn: Callable[[dict[str, Any] | None], int] = context_account_id,
    masked_secret_fn: MaskedSecretFn | None = None,
) -> list[dict[str, Any]]:
    super_admin = is_super_admin_context_fn or is_super_admin_context
    mask_secret = masked_secret_fn or audit.masked_secret
    where_clause = ""
    params: tuple[Any, ...] = ()
    if current_account and not super_admin(current_account):
        where_clause = "where c.owner_account_id = ?"
        params = (context_account_id_fn(current_account),)
    with (connect_fn or _missing_connect)() as conn:
        rows = conn.execute(
            f"""
            select c.code_hash, c.code_label, c.licensee, c.edition, c.features_json, c.expires, c.max_activations,
                   c.disabled, c.member_mode, c.plan, c.gateway_base_url,
                   c.gateway_image_base_url, c.gateway_video_base_url, c.gateway_token,
                   c.gateway_image_token, c.gateway_video_token, c.gateway_default_model,
                   c.gateway_image_model, c.gateway_video_model, c.gateway_models_json,
                   c.quotas_json, c.owner_account_id,
                   coalesce(acc.username, '') as owner_username,
                   coalesce(acc.display_name, '') as owner_display_name,
                   coalesce(acc.role, '') as owner_role,
                   c.created_at, count(a.id) as activations
            from codes c
            left join activations a on a.code_hash = c.code_hash
            left join accounts acc on acc.id = c.owner_account_id
            {where_clause}
            group by c.code_hash order by c.created_at desc
            """,
            params,
        ).fetchall()
    return [
        {
            "codeHash": row["code_hash"], "codeLabel": row["code_label"],
            "licensee": row["licensee"], "edition": row["edition"],
            "features": json.loads(row["features_json"]), "expires": row["expires"],
            "maxActivations": row["max_activations"], "activations": row["activations"],
            "disabled": bool(row["disabled"]), "memberMode": bool(row["member_mode"]),
            "plan": row["plan"], "gatewayBaseUrl": row["gateway_base_url"],
            "gatewayImageBaseUrl": row["gateway_image_base_url"],
            "gatewayVideoBaseUrl": row["gateway_video_base_url"],
            "gatewayToken": mask_secret(row["gateway_token"]),
            "gatewayImageToken": mask_secret(row["gateway_image_token"]),
            "gatewayVideoToken": mask_secret(row["gateway_video_token"]),
            "gatewayDefaultModel": row["gateway_default_model"],
            "gatewayImageModel": row["gateway_image_model"],
            "gatewayVideoModel": row["gateway_video_model"],
            "gatewayModels": json.loads(row["gateway_models_json"] or "[]"),
            "quotas": json.loads(row["quotas_json"] or "{}"),
            "ownerAccountId": int(row["owner_account_id"] or 0),
            "ownerUsername": row["owner_username"], "ownerDisplayName": row["owner_display_name"],
            "ownerRole": row["owner_role"],
            "gatewayConfigured": bool(row["gateway_base_url"] and row["gateway_token"]),
            "gatewayImageConfigured": bool((row["gateway_image_base_url"] or row["gateway_base_url"]) and (row["gateway_image_token"] or row["gateway_token"])),
            "gatewayVideoConfigured": bool((row["gateway_video_base_url"] or row["gateway_base_url"]) and (row["gateway_video_token"] or row["gateway_token"])),
            "createdAt": row["created_at"],
        }
        for row in rows
    ]


def get_code_secret_rows(
    code_hashes: list[Any],
    current_account: dict[str, Any] | None = None,
    *,
    connect_fn: ConnectFn | None = None,
    normalize_code_hashes_fn: Callable[[Any], list[str]] | None = None,
    code_row_owned_by_context_fn: Callable[[sqlite3.Row, dict[str, Any] | None], bool] | None = None,
    max_code_secret_export: int = MAX_CODE_SECRET_EXPORT,
) -> list[dict[str, Any]]:
    normalized = (normalize_code_hashes_fn or normalize_code_hashes)(code_hashes)
    if not normalized:
        raise ActivationError("请选择授权码", 400)
    if len(normalized) > max_code_secret_export:
        raise ActivationError(f"单次最多导出 {max_code_secret_export} 个授权码", 400)
    placeholders = ",".join(["?"] * len(normalized))
    with (connect_fn or _missing_connect)() as conn:
        rows = conn.execute(
            f"""
            select code_hash, code_label, full_code, licensee, edition, plan, expires,
                   max_activations, owner_account_id, disabled
            from codes where code_hash in ({placeholders})
            """,
            tuple(normalized),
        ).fetchall()
    by_hash = {str(row["code_hash"]): row for row in rows}
    owns_row = code_row_owned_by_context_fn or code_row_owned_by_context
    ordered: list[dict[str, Any]] = []
    for code_hash_value in normalized:
        row = by_hash.get(code_hash_value)
        if not row or not owns_row(row, current_account):
            raise ActivationError("授权码不存在或无权访问", 404)
        ordered.append(
            {
                "codeHash": row["code_hash"], "codeLabel": row["code_label"],
                "code": row["full_code"] or ("OC-" + str(row["edition"]).upper() + "-" + row["code_label"]),
                "licensee": row["licensee"], "plan": row["plan"], "expires": row["expires"],
                "maxActivations": int(row["max_activations"] or 1), "disabled": bool(row["disabled"]),
            }
        )
    return ordered


def list_codes(_args: argparse.Namespace, *, connect_fn: ConnectFn | None = None) -> None:
    with (connect_fn or _missing_connect)() as conn:
        rows = conn.execute(
            """
            select c.code_label, c.licensee, c.edition, c.expires, c.max_activations,
                   count(a.id) as activations, c.disabled
            from codes c left join activations a on a.code_hash = c.code_hash
            group by c.code_hash order by c.created_at desc
            """
        ).fetchall()
    for row in rows:
        status = "disabled" if row["disabled"] else "active"
        print(f"{row['code_label']} | {row['licensee']} | {row['edition']} | {row['expires']} | {row['activations']}/{row['max_activations']} | {status}")


def _missing_connect() -> sqlite3.Connection:
    raise RuntimeError("connect_fn is required")


def _missing_normalize_expires(_value: str) -> str:
    raise RuntimeError("normalize_code_expires_fn is required")


def _missing_parse_features(_value: str) -> list[str]:
    raise RuntimeError("parse_features_fn is required")


def _missing_parse_models(_value: Any) -> list[str]:
    raise RuntimeError("parse_models_fn is required")


def _missing_parse_json_object(_value: Any) -> dict[str, Any]:
    raise RuntimeError("parse_json_object_fn is required")


def _missing_load_json_value(_value: Any, _default: Any) -> Any:
    raise RuntimeError("load_json_value_fn is required")


def _missing_code_row_snapshot(_row: sqlite3.Row | None) -> dict[str, Any] | None:
    raise RuntimeError("code_row_snapshot_fn is required")
