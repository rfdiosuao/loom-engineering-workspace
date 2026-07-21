from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from ..config import SETTINGS, Settings
from ..errors import ActivationError
from ..serialization import load_json_value
from ..timeutils import utc_now


ConnectFn = Callable[[], sqlite3.Connection]
PlanRowPublicFn = Callable[[sqlite3.Row], dict[str, Any]]
PlanRowFn = Callable[[str], sqlite3.Row | None]
PublicSettingsFn = Callable[[], dict[str, Any]]
GatewaySettingsFn = Callable[..., dict[str, Any]]
AccountLookupFn = Callable[[int], sqlite3.Row | None]
NormalizerFn = Callable[[Any], str]
FeaturesParserFn = Callable[[str], list[str]]
ModelsParserFn = Callable[..., list[str]]
JsonObjectParserFn = Callable[[Any], dict[str, Any]]
UtcNowFn = Callable[[], str]


DEFAULT_GATEWAY_BASE_URL = SETTINGS.gateway_base_url
DEFAULT_GATEWAY_IMAGE_BASE_URL = SETTINGS.gateway_image_base_url
DEFAULT_GATEWAY_VIDEO_BASE_URL = SETTINGS.gateway_video_base_url
DEFAULT_GATEWAY_TOKEN = SETTINGS.gateway_token
DEFAULT_GATEWAY_IMAGE_TOKEN = SETTINGS.gateway_image_token
DEFAULT_GATEWAY_VIDEO_TOKEN = SETTINGS.gateway_video_token
DEFAULT_GATEWAY_DEFAULT_MODEL = SETTINGS.gateway_default_model
DEFAULT_GATEWAY_IMAGE_MODEL = SETTINGS.gateway_image_model
DEFAULT_GATEWAY_VIDEO_MODEL = SETTINGS.gateway_video_model
DEFAULT_GATEWAY_MODELS = list(SETTINGS.gateway_models)
DEFAULT_PUBLIC_SETTINGS = {
    "cardSiteEnabled": True,
    "cardSiteLabel": "购买授权码",
    "cardSiteUrl": "",
    "supportUrl": SETTINGS.support_url,
}


def gateway_defaults(settings: Settings) -> dict[str, Any]:
    return {
        "publicCommercialUrl": settings.public_url,
        "publicSupportUrl": settings.support_url,
        "gatewayBaseUrl": settings.gateway_base_url,
        "gatewayImageBaseUrl": settings.gateway_image_base_url,
        "gatewayVideoBaseUrl": settings.gateway_video_base_url,
        "gatewayToken": settings.gateway_token,
        "gatewayImageToken": settings.gateway_image_token,
        "gatewayVideoToken": settings.gateway_video_token,
        "gatewayDefaultModel": settings.gateway_default_model,
        "gatewayImageModel": settings.gateway_image_model,
        "gatewayVideoModel": settings.gateway_video_model,
        "gatewayModels": list(settings.gateway_models),
        "publicSettings": {
            "cardSiteEnabled": True,
            "cardSiteLabel": "购买授权码",
            "cardSiteUrl": "",
            "supportUrl": settings.support_url,
        },
    }


def normalize_plan_key(value: Any) -> str:
    plan_key = str(value or "").strip().lower().replace(" ", "_")
    if not plan_key:
        raise ActivationError("缺少套餐标识")
    if any(not (ch.isalnum() or ch in {"_", "-"}) for ch in plan_key):
        raise ActivationError("套餐标识只能包含字母、数字、下划线和中划线")
    return plan_key[:80]


def plan_row_public(
    row: sqlite3.Row,
    *,
    default_features: list[str],
    load_json_value_fn: Callable[[Any, Any], Any] = load_json_value,
) -> dict[str, Any]:
    return {
        "planKey": row["plan_key"],
        "displayName": row["display_name"],
        "durationDays": row["duration_days"],
        "features": load_json_value_fn(row["features_json"], default_features),
        "gatewayBaseUrl": row["gateway_base_url"],
        "gatewayImageBaseUrl": row["gateway_image_base_url"],
        "gatewayVideoBaseUrl": row["gateway_video_base_url"],
        "gatewayConfigured": bool(row["gateway_base_url"] and row["gateway_token"]),
        "gatewayImageConfigured": bool((row["gateway_image_base_url"] or row["gateway_base_url"]) and (row["gateway_image_token"] or row["gateway_token"])),
        "gatewayVideoConfigured": bool((row["gateway_video_base_url"] or row["gateway_base_url"]) and (row["gateway_video_token"] or row["gateway_token"])),
        "gatewayDefaultModel": row["gateway_default_model"],
        "gatewayImageModel": row["gateway_image_model"],
        "gatewayVideoModel": row["gateway_video_model"],
        "gatewayModels": load_json_value_fn(row["gateway_models_json"], []),
        "quotas": load_json_value_fn(row["quotas_json"], {}),
        "disabled": bool(row["disabled"]),
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def get_plan_rows(
    include_disabled: bool = False,
    *,
    connect_fn: ConnectFn | None = None,
    plan_row_public_fn: PlanRowPublicFn | None = None,
) -> list[dict[str, Any]]:
    where = "" if include_disabled else "where disabled = 0"
    with (connect_fn or _missing_connect)() as conn:
        rows = conn.execute(f"select * from plans {where} order by disabled asc, plan_key asc").fetchall()
    formatter = plan_row_public_fn or _missing_plan_row_public
    return [formatter(row) for row in rows]


def get_plan_row(plan_key: str, *, connect_fn: ConnectFn | None = None) -> sqlite3.Row | None:
    with (connect_fn or _missing_connect)() as conn:
        return conn.execute("select * from plans where plan_key = ?", (plan_key,)).fetchone()


def public_settings(
    *,
    connect_fn: ConnectFn | None = None,
    default_public_settings: dict[str, Any] | None = None,
    public_support_url: str = "",
    load_json_value_fn: Callable[[Any, Any], Any] = load_json_value,
) -> dict[str, Any]:
    with (connect_fn or _missing_connect)() as conn:
        row = conn.execute("select value_json from settings where key = ?", ("public",)).fetchone()
    value = load_json_value_fn(row["value_json"], {}) if row else {}
    settings = dict(default_public_settings or DEFAULT_PUBLIC_SETTINGS)
    if isinstance(value, dict):
        settings.update(value)
    fallback_support_url = public_support_url or str(settings.get("supportUrl") or "")
    settings["cardSiteEnabled"] = bool(settings.get("cardSiteEnabled"))
    settings["cardSiteLabel"] = str(settings.get("cardSiteLabel") or "购买授权码").strip() or "购买授权码"
    settings["cardSiteUrl"] = str(settings.get("cardSiteUrl") or "").strip()
    settings["supportUrl"] = str(settings.get("supportUrl") or fallback_support_url).strip() or fallback_support_url
    return settings


def client_public_config(
    *,
    public_settings_fn: PublicSettingsFn | None = None,
    public_commercial_url: str = "",
    public_support_url: str = "",
) -> dict[str, Any]:
    settings = (public_settings_fn or _missing_public_settings)()
    enabled = bool(settings.get("cardSiteEnabled")) and bool(settings.get("cardSiteUrl"))
    card_url = str(settings.get("cardSiteUrl") or "").strip() if enabled else ""
    return {
        "purchaseUrl": card_url or public_commercial_url,
        "supportUrl": str(settings.get("supportUrl") or public_support_url).strip() or public_support_url,
        "cardSite": {
            "enabled": enabled,
            "label": settings.get("cardSiteLabel") or "购买授权码",
            "url": card_url,
        },
    }


def update_public_settings(
    body: dict[str, Any],
    *,
    connect_fn: ConnectFn | None = None,
    public_settings_fn: PublicSettingsFn | None = None,
    validate_gateway_url_fn: Callable[[str, str], str] | None = None,
    public_support_url: str = "",
    utc_now_fn: UtcNowFn = utc_now,
) -> dict[str, Any]:
    settings = (public_settings_fn or _missing_public_settings)()
    if "cardSiteEnabled" in body:
        settings["cardSiteEnabled"] = bool(body.get("cardSiteEnabled"))
    if "cardSiteLabel" in body:
        settings["cardSiteLabel"] = str(body.get("cardSiteLabel") or "购买授权码").strip() or "购买授权码"
    if "cardSiteUrl" in body:
        card_site_url = str(body.get("cardSiteUrl") or "").strip()
        if card_site_url and not card_site_url.lower().startswith(("http://", "https://")):
            raise ActivationError("发卡网站链接必须以 http:// 或 https:// 开头")
        settings["cardSiteUrl"] = card_site_url
    if "supportUrl" in body:
        validator = validate_gateway_url_fn or validate_gateway_url
        settings["supportUrl"] = validator(str(body.get("supportUrl") or ""), "客服链接") or public_support_url
    with (connect_fn or _missing_connect)() as conn:
        conn.execute(
            """
            insert into settings (key, value_json, updated_at)
            values (?, ?, ?)
            on conflict(key) do update set
                value_json = excluded.value_json,
                updated_at = excluded.updated_at
            """,
            ("public", json.dumps(settings, ensure_ascii=False, sort_keys=True), utc_now_fn()),
        )
        conn.commit()
    return settings


def validate_gateway_url(value: str, label: str) -> str:
    normalized = str(value or "").strip().rstrip("/")
    if normalized and not normalized.lower().startswith(("http://", "https://")):
        raise ActivationError(f"{label} 必须以 http:// 或 https:// 开头")
    return normalized


def default_account_gateway_settings(account_id: int = 0, *, include_secrets: bool = False) -> dict[str, Any]:
    settings: dict[str, Any] = {
        "accountId": int(account_id or 0),
        "gatewayBaseUrl": "",
        "gatewayImageBaseUrl": "",
        "gatewayVideoBaseUrl": "",
        "gatewayDefaultModel": "",
        "gatewayImageModel": "",
        "gatewayVideoModel": "",
        "gatewayModels": [],
        "gatewayConfigured": False,
        "gatewayImageConfigured": False,
        "gatewayVideoConfigured": False,
        "updatedAt": "",
    }
    if include_secrets:
        settings.update({"gatewayToken": "", "gatewayImageToken": "", "gatewayVideoToken": ""})
    else:
        settings.update({
            "gatewayTokenConfigured": False,
            "gatewayImageTokenConfigured": False,
            "gatewayVideoTokenConfigured": False,
        })
    return settings


def account_gateway_settings_public(
    row: sqlite3.Row | None,
    *,
    account_id: int = 0,
    include_secrets: bool = False,
    default_account_gateway_settings_fn: Callable[..., dict[str, Any]] | None = None,
    load_json_value_fn: Callable[[Any, Any], Any] = load_json_value,
) -> dict[str, Any]:
    if not row:
        return (default_account_gateway_settings_fn or default_account_gateway_settings)(account_id, include_secrets=include_secrets)
    base_url = str(row["gateway_base_url"] or "")
    image_base_url = str(row["gateway_image_base_url"] or "")
    video_base_url = str(row["gateway_video_base_url"] or "")
    token_value = str(row["gateway_token"] or "")
    image_token = str(row["gateway_image_token"] or "")
    video_token = str(row["gateway_video_token"] or "")
    settings: dict[str, Any] = {
        "accountId": int(row["account_id"] or account_id or 0),
        "gatewayBaseUrl": base_url,
        "gatewayImageBaseUrl": image_base_url,
        "gatewayVideoBaseUrl": video_base_url,
        "gatewayDefaultModel": str(row["gateway_default_model"] or ""),
        "gatewayImageModel": str(row["gateway_image_model"] or ""),
        "gatewayVideoModel": str(row["gateway_video_model"] or ""),
        "gatewayModels": load_json_value_fn(row["gateway_models_json"], []),
        "gatewayConfigured": bool(base_url and token_value),
        "gatewayImageConfigured": bool((image_base_url or base_url) and (image_token or token_value)),
        "gatewayVideoConfigured": bool((video_base_url or base_url) and (video_token or token_value)),
        "updatedAt": str(row["updated_at"] or ""),
    }
    if include_secrets:
        settings.update({"gatewayToken": token_value, "gatewayImageToken": image_token, "gatewayVideoToken": video_token})
    else:
        settings.update({
            "gatewayTokenConfigured": bool(token_value),
            "gatewayImageTokenConfigured": bool(image_token),
            "gatewayVideoTokenConfigured": bool(video_token),
        })
    return settings


def get_account_gateway_settings(
    account_id: int,
    *,
    include_secrets: bool = False,
    connect_fn: ConnectFn | None = None,
    account_gateway_settings_public_fn: Callable[..., dict[str, Any]] | None = None,
    default_account_gateway_settings_fn: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    normalized_account_id = int(account_id or 0)
    default_fn = default_account_gateway_settings_fn or default_account_gateway_settings
    if normalized_account_id <= 0:
        return default_fn(normalized_account_id, include_secrets=include_secrets)
    with (connect_fn or _missing_connect)() as conn:
        row = conn.execute("select * from account_gateway_settings where account_id = ?", (normalized_account_id,)).fetchone()
    return (account_gateway_settings_public_fn or account_gateway_settings_public)(
        row,
        account_id=normalized_account_id,
        include_secrets=include_secrets,
    )


def upsert_account_gateway_settings(
    account_id: int,
    body: dict[str, Any],
    *,
    connect_fn: ConnectFn | None = None,
    get_account_by_id_fn: AccountLookupFn | None = None,
    get_account_gateway_settings_fn: GatewaySettingsFn | None = None,
    validate_gateway_url_fn: Callable[[str, str], str] | None = None,
    parse_optional_models_fn: ModelsParserFn | None = None,
    utc_now_fn: UtcNowFn = utc_now,
    account_status_active: str = "active",
) -> dict[str, Any]:
    normalized_account_id = int(account_id or 0)
    if normalized_account_id <= 0:
        raise ActivationError("缺少账号 ID", 400)
    account = (get_account_by_id_fn or _missing_account_lookup)(normalized_account_id)
    if not account or account["status"] != account_status_active:
        raise ActivationError("账号不存在或已停用", 404)
    get_settings = get_account_gateway_settings_fn or _missing_gateway_settings
    existing = get_settings(normalized_account_id, include_secrets=True)
    validator = validate_gateway_url_fn or validate_gateway_url
    gateway_base_url = validator(body.get("gatewayBaseUrl") or existing.get("gatewayBaseUrl") or "", "通用 Base URL")
    gateway_image_base_url = validator(body.get("gatewayImageBaseUrl") or body.get("gateway_image_base_url") or existing.get("gatewayImageBaseUrl") or "", "图片 Base URL")
    gateway_video_base_url = validator(body.get("gatewayVideoBaseUrl") or body.get("gateway_video_base_url") or existing.get("gatewayVideoBaseUrl") or "", "视频 Base URL")
    gateway_token = str(body.get("gatewayToken") or existing.get("gatewayToken") or "").strip()
    gateway_image_token = str(body.get("gatewayImageToken") or body.get("gateway_image_token") or existing.get("gatewayImageToken") or "").strip()
    gateway_video_token = str(body.get("gatewayVideoToken") or body.get("gateway_video_token") or existing.get("gatewayVideoToken") or "").strip()
    gateway_default_model = str(body.get("gatewayDefaultModel") or existing.get("gatewayDefaultModel") or "").strip()
    gateway_image_model = str(body.get("gatewayImageModel") or body.get("gateway_image_model") or existing.get("gatewayImageModel") or "").strip()
    gateway_video_model = str(body.get("gatewayVideoModel") or body.get("gateway_video_model") or existing.get("gatewayVideoModel") or "").strip()
    gateway_models = (parse_optional_models_fn or _missing_models_parser)(body.get("gatewayModels"), existing.get("gatewayModels") or [])
    now = utc_now_fn()
    with (connect_fn or _missing_connect)() as conn:
        row = conn.execute("select created_at from account_gateway_settings where account_id = ?", (normalized_account_id,)).fetchone()
        created_at = str(row["created_at"]) if row else now
        conn.execute(
            """
            insert into account_gateway_settings (
                account_id, gateway_base_url, gateway_image_base_url, gateway_video_base_url,
                gateway_token, gateway_image_token, gateway_video_token,
                gateway_default_model, gateway_image_model, gateway_video_model,
                gateway_models_json, created_at, updated_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(account_id) do update set
                gateway_base_url = excluded.gateway_base_url,
                gateway_image_base_url = excluded.gateway_image_base_url,
                gateway_video_base_url = excluded.gateway_video_base_url,
                gateway_token = excluded.gateway_token,
                gateway_image_token = excluded.gateway_image_token,
                gateway_video_token = excluded.gateway_video_token,
                gateway_default_model = excluded.gateway_default_model,
                gateway_image_model = excluded.gateway_image_model,
                gateway_video_model = excluded.gateway_video_model,
                gateway_models_json = excluded.gateway_models_json,
                updated_at = excluded.updated_at
            """,
            (normalized_account_id, gateway_base_url, gateway_image_base_url, gateway_video_base_url,
             gateway_token, gateway_image_token, gateway_video_token, gateway_default_model,
             gateway_image_model, gateway_video_model, json.dumps(gateway_models, ensure_ascii=False), created_at, now),
        )
        conn.commit()
    return get_settings(normalized_account_id, include_secrets=False)


def has_explicit_gateway_value(body: dict[str, Any], *names: str) -> bool:
    return any(str(body.get(name) or "").strip() for name in names)


def apply_account_gateway_defaults(
    body: dict[str, Any],
    account_id: int,
    *,
    explicit_body: dict[str, Any] | None = None,
    get_account_gateway_settings_fn: GatewaySettingsFn | None = None,
    has_explicit_gateway_value_fn: Callable[..., bool] | None = None,
) -> dict[str, Any]:
    normalized_account_id = int(account_id or 0)
    if normalized_account_id <= 0:
        return body
    settings = (get_account_gateway_settings_fn or _missing_gateway_settings)(normalized_account_id, include_secrets=True)
    field_names = [
        ("gatewayBaseUrl", ("gatewayBaseUrl", "gateway_base_url")),
        ("gatewayImageBaseUrl", ("gatewayImageBaseUrl", "gateway_image_base_url")),
        ("gatewayVideoBaseUrl", ("gatewayVideoBaseUrl", "gateway_video_base_url")),
        ("gatewayToken", ("gatewayToken", "gateway_token")),
        ("gatewayImageToken", ("gatewayImageToken", "gateway_image_token")),
        ("gatewayVideoToken", ("gatewayVideoToken", "gateway_video_token")),
        ("gatewayDefaultModel", ("gatewayDefaultModel", "gateway_default_model")),
        ("gatewayImageModel", ("gatewayImageModel", "gateway_image_model")),
        ("gatewayVideoModel", ("gatewayVideoModel", "gateway_video_model")),
    ]
    if not any(str(settings.get(name) or "").strip() for name, _ in field_names) and not settings.get("gatewayModels"):
        return body
    source = explicit_body or body
    merged = dict(body)
    has_explicit = has_explicit_gateway_value_fn or has_explicit_gateway_value
    for canonical_name, aliases in field_names:
        value = settings.get(canonical_name)
        if value and not has_explicit(source, *aliases):
            merged[canonical_name] = value
    if settings.get("gatewayModels") and not has_explicit(source, "gatewayModels", "gateway_models"):
        merged["gatewayModels"] = ",".join(settings.get("gatewayModels") or [])
    if "memberMode" not in source and (
        settings.get("gatewayConfigured") or settings.get("gatewayImageConfigured") or settings.get("gatewayVideoConfigured")
    ):
        merged["memberMode"] = True
    return merged


def upsert_plan_record(
    body: dict[str, Any],
    *,
    connect_fn: ConnectFn | None = None,
    normalize_plan_key_fn: NormalizerFn = normalize_plan_key,
    parse_features_fn: FeaturesParserFn | None = None,
    parse_models_fn: ModelsParserFn | None = None,
    parse_json_object_fn: JsonObjectParserFn | None = None,
    get_plan_row_fn: PlanRowFn | None = None,
    plan_row_public_fn: PlanRowPublicFn | None = None,
    default_features: list[str] | None = None,
    utc_now_fn: UtcNowFn = utc_now,
) -> dict[str, Any]:
    plan_key = normalize_plan_key_fn(body.get("planKey") or body.get("plan") or body.get("key"))
    display_name = str(body.get("displayName") or body.get("name") or plan_key).strip() or plan_key
    duration_days = max(1, min(int(body.get("durationDays") or 31), 3660))
    features = (parse_features_fn or _missing_features_parser)(str(body.get("features", ",".join(default_features or []))))
    gateway_base_url = str(body.get("gatewayBaseUrl", "")).strip().rstrip("/")
    gateway_image_base_url = str(body.get("gatewayImageBaseUrl") or body.get("gateway_image_base_url") or "").strip().rstrip("/")
    gateway_video_base_url = str(body.get("gatewayVideoBaseUrl") or body.get("gateway_video_base_url") or "").strip().rstrip("/")
    gateway_token = str(body.get("gatewayToken", "")).strip()
    gateway_image_token = str(body.get("gatewayImageToken") or body.get("gateway_image_token") or "").strip()
    gateway_video_token = str(body.get("gatewayVideoToken") or body.get("gateway_video_token") or "").strip()
    gateway_default_model = str(body.get("gatewayDefaultModel", "")).strip()
    gateway_image_model = str(body.get("gatewayImageModel") or body.get("gateway_image_model") or "").strip()
    gateway_video_model = str(body.get("gatewayVideoModel") or body.get("gateway_video_model") or "").strip()
    gateway_models = (parse_models_fn or _missing_models_parser)(body.get("gatewayModels", ""))
    quotas = (parse_json_object_fn or _missing_json_object_parser)(body.get("quotas", ""))
    disabled = 1 if body.get("disabled") else 0
    now = utc_now_fn()
    with (connect_fn or _missing_connect)() as conn:
        existing = conn.execute(
            """select gateway_image_base_url, gateway_video_base_url, gateway_token, gateway_image_token,
               gateway_video_token, gateway_image_model, gateway_video_model, created_at
               from plans where plan_key = ?""",
            (plan_key,),
        ).fetchone()
        if existing and not gateway_image_base_url:
            gateway_image_base_url = str(existing["gateway_image_base_url"] or "")
        if existing and not gateway_video_base_url:
            gateway_video_base_url = str(existing["gateway_video_base_url"] or "")
        if existing and not gateway_token:
            gateway_token = str(existing["gateway_token"] or "")
        if existing and not gateway_image_token:
            gateway_image_token = str(existing["gateway_image_token"] or "")
        if existing and not gateway_video_token:
            gateway_video_token = str(existing["gateway_video_token"] or "")
        if existing and not gateway_image_model:
            gateway_image_model = str(existing["gateway_image_model"] or "")
        if existing and not gateway_video_model:
            gateway_video_model = str(existing["gateway_video_model"] or "")
        created_at = str(existing["created_at"]) if existing else now
        conn.execute(
            """
            insert into plans (
                plan_key, display_name, duration_days, features_json, gateway_base_url,
                gateway_image_base_url, gateway_video_base_url, gateway_token, gateway_image_token,
                gateway_video_token, gateway_default_model, gateway_image_model, gateway_video_model,
                gateway_models_json, quotas_json, disabled, created_at, updated_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(plan_key) do update set
                display_name = excluded.display_name, duration_days = excluded.duration_days,
                features_json = excluded.features_json, gateway_base_url = excluded.gateway_base_url,
                gateway_image_base_url = excluded.gateway_image_base_url,
                gateway_video_base_url = excluded.gateway_video_base_url, gateway_token = excluded.gateway_token,
                gateway_image_token = excluded.gateway_image_token, gateway_video_token = excluded.gateway_video_token,
                gateway_default_model = excluded.gateway_default_model, gateway_image_model = excluded.gateway_image_model,
                gateway_video_model = excluded.gateway_video_model, gateway_models_json = excluded.gateway_models_json,
                quotas_json = excluded.quotas_json, disabled = excluded.disabled, updated_at = excluded.updated_at
            """,
            (plan_key, display_name, duration_days, json.dumps(features, ensure_ascii=False), gateway_base_url,
             gateway_image_base_url, gateway_video_base_url, gateway_token, gateway_image_token, gateway_video_token,
             gateway_default_model, gateway_image_model, gateway_video_model, json.dumps(gateway_models or [], ensure_ascii=False),
             json.dumps(quotas or {}, ensure_ascii=False), disabled, created_at, now),
        )
        conn.commit()
    row = (get_plan_row_fn or _missing_plan_row)(plan_key)
    if not row:
        raise ActivationError("套餐模板不存在")
    return (plan_row_public_fn or _missing_plan_row_public)(row)


def disable_plan_record(
    plan_key: str,
    *,
    connect_fn: ConnectFn | None = None,
    normalize_plan_key_fn: NormalizerFn = normalize_plan_key,
    get_plan_row_fn: PlanRowFn | None = None,
    plan_row_public_fn: PlanRowPublicFn | None = None,
    utc_now_fn: UtcNowFn = utc_now,
) -> dict[str, Any] | None:
    plan_key = normalize_plan_key_fn(plan_key)
    get_row = get_plan_row_fn or _missing_plan_row
    before = get_row(plan_key)
    if not before:
        return None
    with (connect_fn or _missing_connect)() as conn:
        conn.execute("update plans set disabled = 1, updated_at = ? where plan_key = ?", (utc_now_fn(), plan_key))
        conn.commit()
    after = get_row(plan_key)
    return (plan_row_public_fn or _missing_plan_row_public)(after) if after else None


def apply_plan_template(
    body: dict[str, Any],
    *,
    normalize_plan_key_fn: NormalizerFn = normalize_plan_key,
    get_plan_row_fn: PlanRowFn | None = None,
    default_features: list[str] | None = None,
    load_json_value_fn: Callable[[Any, Any], Any] = load_json_value,
    now_fn: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    plan_key_raw = body.get("planTemplate") or body.get("planKey")
    if not str(plan_key_raw or "").strip():
        return body
    plan_key = normalize_plan_key_fn(plan_key_raw)
    row = (get_plan_row_fn or _missing_plan_row)(plan_key)
    if not row or bool(row["disabled"]):
        raise ActivationError("套餐模板不存在或已停用", 404)
    merged = dict(body)

    def blank(name: str) -> bool:
        value = merged.get(name)
        return value is None or str(value).strip() == ""

    if blank("features"):
        merged["features"] = ",".join(load_json_value_fn(row["features_json"], default_features or []))
    if blank("expires"):
        current = (now_fn or (lambda: datetime.now(timezone.utc)))()
        merged["expires"] = (current.date() + timedelta(days=int(row["duration_days"] or 31))).isoformat()
    values = {
        "plan": row["plan_key"],
        "gatewayBaseUrl": row["gateway_base_url"],
        "gatewayImageBaseUrl": row["gateway_image_base_url"],
        "gatewayVideoBaseUrl": row["gateway_video_base_url"],
        "gatewayToken": row["gateway_token"],
        "gatewayImageToken": row["gateway_image_token"],
        "gatewayVideoToken": row["gateway_video_token"],
        "gatewayDefaultModel": row["gateway_default_model"],
        "gatewayImageModel": row["gateway_image_model"],
        "gatewayVideoModel": row["gateway_video_model"],
        "gatewayModels": ",".join(load_json_value_fn(row["gateway_models_json"], [])),
        "quotas": row["quotas_json"] or "{}",
    }
    for name, value in values.items():
        if blank(name):
            merged[name] = value
    merged["memberMode"] = True
    return merged


def _missing_connect() -> sqlite3.Connection:
    raise RuntimeError("connect_fn is required")


def _missing_plan_row_public(_row: sqlite3.Row) -> dict[str, Any]:
    raise RuntimeError("plan_row_public_fn is required")


def _missing_plan_row(_plan_key: str) -> sqlite3.Row | None:
    raise RuntimeError("get_plan_row_fn is required")


def _missing_public_settings() -> dict[str, Any]:
    raise RuntimeError("public_settings_fn is required")


def _missing_gateway_settings(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
    raise RuntimeError("get_account_gateway_settings_fn is required")


def _missing_account_lookup(_account_id: int) -> sqlite3.Row | None:
    raise RuntimeError("get_account_by_id_fn is required")


def _missing_features_parser(_raw: str) -> list[str]:
    raise RuntimeError("parse_features_fn is required")


def _missing_models_parser(*_args: Any, **_kwargs: Any) -> list[str]:
    raise RuntimeError("parse_models_fn is required")


def _missing_json_object_parser(_raw: Any) -> dict[str, Any]:
    raise RuntimeError("parse_json_object_fn is required")
