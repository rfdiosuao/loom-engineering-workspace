"""New API account login and launcher model sync support."""

from __future__ import annotations

import http.cookiejar
import copy
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any

from core.license_manager import LicenseManager
from core.openclaw_model_sync import sync_openclaw_models
from core.paths import AppPaths
from core.secret_store import protect_secret, unprotect_secret
from core.storage import read_json, write_json
from core.wire_config import WireService, clear_agent_user_env_keys


class NewApiAccountError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


DEFAULT_BASE_URL = "https://api.heang.top"
DEFAULT_API_BASE = "https://api.heang.top/v1"
LEGACY_BASE_URL = "https://api.heang.top"
LEGACY_API_BASE = "https://api.heang.top/v1"
DEFAULT_ACCOUNT_CENTER_PATH = "/wallet"
ACCOUNT_SOURCE = "newapi_account"
LEGACY_ACCOUNT_SOURCE = "heang_account"
SESSION_GRACE_DAYS = 14
DEFAULT_TEXT_MODEL = "glm-5.2-coding"
DEFAULT_PHONE_MODEL = "qwen3.7-plus"
LAUNCHER_TOKEN_NAME_PREFIX = "LOOM Launcher"
TEXT_MODEL_PRIORITY = (
    "glm-5.2-coding",
    "qwen3.7-plus",
    "qwen3.6-plus",
    "qwen3.5-plus",
    "glm-4-flash",
    "kimi-k2.5",
    "MiniMax-M2.5",
)
PHONE_MODEL_IDS = {"agnes-2.0-flash"}
MANAGED_ACCOUNT_SOURCES = {ACCOUNT_SOURCE, LEGACY_ACCOUNT_SOURCE}
NEWAPI_EMAIL_CODE_SEND_PATH = "/api/verification"
OPENCLAW_EMAIL_CODE_SEND_PATHS = (
    "/api/openclaw/auth/email-code/send",
    "/api/openclaw/email-code/send",
)
OPENCLAW_EMAIL_CODE_LOGIN_PATHS = (
    "/api/openclaw/auth/email-code/login",
    "/api/openclaw/email-code/login",
)
OPENCLAW_EMAIL_CODE_REGISTER_PATHS = (
    "/api/openclaw/auth/email-code/register",
    "/api/openclaw/email-code/register",
    "/api/user/register",
)
OPENCLAW_SUBSCRIPTION_PATHS = (
    "/api/user/subscription",
    "/api/user/self",
    "/api/openclaw/account/subscription",
    "/api/openclaw/subscription",
)
SESSION_SECRET_PATHS = (
    ("memberToken",),
    ("gatewayImageAccessToken",),
    ("gatewayVideoAccessToken",),
    ("gateway", "accessToken"),
    ("gateway", "imageAccessToken"),
    ("gateway", "videoAccessToken"),
    ("newApi", "sessionCookie"),
    ("newApi", "launcherToken"),
    ("phoneAgent", "apiKey"),
)
DEFAULT_RUNTIME_SYNC_TARGETS = ("openclaw", "opencode", "claude", "image", "desktop", "phone")
FAST_PASSWORD_BRIDGE_TIMEOUT_SECONDS = 5
NATIVE_PASSWORD_LOGIN_TIMEOUT_SECONDS = 10
AUTH_CAPABILITIES_CACHE_SECONDS = 300


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _pick_text(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text and text.lower() != "none":
            return text
    return ""


def _looks_like_email(value: Any) -> bool:
    text = str(value or "").strip()
    return "@" in text and "." in text.rsplit("@", 1)[-1]


def _url_origin(value: str) -> tuple[str, str, int] | None:
    try:
        parsed = urllib.parse.urlsplit(str(value or "").strip())
        scheme = parsed.scheme.lower()
        hostname = (parsed.hostname or "").lower()
        if scheme not in {"http", "https"} or not hostname:
            return None
        port = parsed.port or (443 if scheme == "https" else 80)
        return scheme, hostname, port
    except (TypeError, ValueError):
        return None


MANAGED_HEANG_HOSTS = {"api-cn.heang.top", "api.heang.top"}
TRANSIENT_HTTP_STATUS_CODES = {408, 500, 502, 503, 504, 520, 521, 522, 523, 524}
LEGACY_FALLBACK_POST_PATHS = {
    "/api/user/login",
    "/api/openclaw/auth/email-code/login",
}
MIGRATABLE_SESSION_URL_KEYS = {
    "baseUrl",
    "gatewayBaseUrl",
    "gatewayImageBaseUrl",
    "gatewayVideoBaseUrl",
    "imageBaseUrl",
    "videoBaseUrl",
    "purchaseUrl",
    "webViewUrl",
}
MANAGED_GATEWAY_MIGRATION_VERSION = 1


def _replace_managed_heang_origin(value: Any, target_base_url: str) -> str:
    text = str(value or "").strip()
    try:
        parsed = urllib.parse.urlsplit(text)
        target = urllib.parse.urlsplit(target_base_url)
    except (TypeError, ValueError):
        return text
    if parsed.scheme != "https" or (parsed.hostname or "").lower() not in MANAGED_HEANG_HOSTS:
        return text
    if target.scheme != "https" or (target.hostname or "").lower() not in MANAGED_HEANG_HOSTS:
        return text
    return urllib.parse.urlunsplit((target.scheme, target.netloc, parsed.path, parsed.query, parsed.fragment))


def _migrate_managed_session_urls(session: dict[str, Any]) -> bool:
    changed = False

    def walk(value: Any) -> None:
        nonlocal changed
        if isinstance(value, dict):
            for key, nested in value.items():
                if key in MIGRATABLE_SESSION_URL_KEYS and isinstance(nested, str):
                    migrated = _replace_managed_heang_origin(nested, DEFAULT_BASE_URL)
                    if migrated != nested:
                        value[key] = migrated
                        changed = True
                else:
                    walk(nested)
        elif isinstance(value, list):
            for nested in value:
                walk(nested)

    walk(session)
    return changed


def _trusted_managed_api_base(candidate: Any, account_base_url: str) -> str:
    account_base_url = str(account_base_url or "").strip().rstrip("/")
    fallback = f"{account_base_url}/v1"
    api_base_url = _pick_text(candidate, fallback).rstrip("/")
    account_origin = _url_origin(account_base_url)
    api_origin = _url_origin(api_base_url)
    if (
        account_origin
        and api_origin
        and account_origin[0] == "https"
        and api_origin[0] == "https"
        and account_origin[1] in MANAGED_HEANG_HOSTS
        and api_origin[1] in MANAGED_HEANG_HOSTS
    ):
        api_base_url = _replace_managed_heang_origin(api_base_url, account_base_url)
    if _url_origin(api_base_url) != _url_origin(account_base_url):
        raise NewApiAccountError("模型服务返回的 API 域名与登录域名不一致，已拒绝写入凭据")
    return api_base_url


def _should_retry_email_login(error: Exception) -> bool:
    text = str(error or "").lower()
    return any(
        marker in text
        for marker in (
            "invalid parameter",
            "invalid parameters",
            "missing",
            "required",
        )
    )


def _should_try_openclaw_email_fallback(error: Exception) -> bool:
    text = str(error or "").lower()
    return any(
        marker in text
        for marker in (
            "http_404",
            "http_405",
            "http_501",
            "not found",
            "invalid url",
            "endpoint_unavailable",
            "newapi_network_error",
            "urlopen error",
        )
    )


def _mask_secret(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) <= 8:
        return "****"
    return f"{text[:4]}****{text[-4:]}"


SECRET_TEXT_PATTERNS = (
    re.compile(r"(?i)\b(api[_-]?key|access[_-]?token|session[_-]?cookie|password|secret|token)(\s*[:=]\s*)([^\s,;]+)"),
    re.compile(r"(?i)\b(bearer\s+)([a-z0-9._~+/=-]{8,})"),
    re.compile(r"\b(sk-[A-Za-z0-9._-]+|sess-[A-Za-z0-9._-]+|eyJ[A-Za-z0-9._=-]+)"),
)


def _redact_secret_text(value: Any) -> str:
    text = str(value or "")
    for pattern in SECRET_TEXT_PATTERNS:
        if pattern.groups >= 3:
            text = pattern.sub(lambda match: f"{match.group(1)}{match.group(2)}[redacted]", text)
        elif pattern.groups == 2:
            text = pattern.sub(lambda match: f"{match.group(1)}[redacted]", text)
        else:
            text = pattern.sub("[redacted]", text)
    return text


def _unwrap(payload: Any) -> Any:
    if isinstance(payload, dict) and isinstance(payload.get("data"), (dict, list)):
        return payload["data"]
    return payload


def _candidate_items(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    for key in ("data", "items", "tokens", "rows", "list"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            nested = _candidate_items(value)
            if nested:
                return nested
    return []


def _extract_user_id(*payloads: Any) -> str:
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        candidates = [payload]
        for key in ("user", "account", "data"):
            if isinstance(payload.get(key), dict):
                candidates.append(payload[key])
        for item in candidates:
            user_id = _pick_text(item.get("id"), item.get("user_id"), item.get("userId"))
            if user_id:
                return user_id
    return ""


def _extract_account_name(*payloads: Any) -> str:
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        candidates = [payload]
        for key in ("user", "account", "data"):
            if isinstance(payload.get(key), dict):
                candidates.append(payload[key])
        for item in candidates:
            text = _pick_text(item.get("email"), item.get("username"), item.get("display_name"), item.get("name"))
            if text:
                return text
    return ""


def _extract_api_key(payload: Any) -> str:
    if isinstance(payload, str):
        text = payload.strip()
        if text.startswith("sk-"):
            return text
        return ""
    if isinstance(payload, list):
        for item in payload:
            token = _extract_api_key(item)
            if token:
                return token
        return ""
    if not isinstance(payload, dict):
        return ""
    for key in ("key", "value", "api_key", "apiKey"):
        value = payload.get(key)
        if isinstance(value, str):
            text = value.strip()
            if len(text) >= 8 and "*" not in text:
                return text
    for key in ("token", "access_token"):
        value = payload.get(key)
        if isinstance(value, str):
            text = value.strip()
            if text.startswith("sk-") or (len(text) >= 8 and "*" not in text and isinstance(payload.get("name"), str)):
                return text
    for key in ("data", "token", "result", "items", "tokens", "rows", "list"):
        token = _extract_api_key(payload.get(key))
        if token:
            return token
    return ""


def _token_quota_value(item: dict[str, Any]) -> int:
    try:
        return int(item.get("remain_quota") or item.get("remainQuota") or item.get("quota") or 0)
    except (TypeError, ValueError):
        return 0


def _token_is_usable(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    token = _extract_api_key(item)
    if not token:
        return False
    status = str(item.get("status") or "1")
    if status not in ("1", "true", "active"):
        return False
    return item.get("unlimited_quota") is True or item.get("unlimitedQuota") is True or _token_quota_value(item) > 0


def _extract_best_api_key(payload: Any, preferred_name: str = "") -> str:
    items = _candidate_items(payload)
    if not items:
        return _extract_api_key(payload)

    preferred = []
    usable = []
    fallback = []
    for item in items:
        token = _extract_api_key(item)
        if not token:
            continue
        if preferred_name and isinstance(item, dict) and str(item.get("name") or "") == preferred_name:
            preferred.append(item)
        if _token_is_usable(item):
            usable.append(item)
        fallback.append(item)

    for group in (preferred, usable, fallback):
        for item in group:
            token = _extract_api_key(item)
            if token:
                return token
    return ""


def _token_name(item: Any) -> str:
    if not isinstance(item, dict):
        return ""
    return _pick_text(item.get("name"), item.get("tokenName"), item.get("token_name"))


def _is_launcher_token_item(item: Any) -> bool:
    name = _token_name(item).lower()
    return name.startswith(LAUNCHER_TOKEN_NAME_PREFIX.lower())


def _extract_launcher_api_key(payload: Any) -> str:
    launcher_items = [item for item in _candidate_items(payload) if _is_launcher_token_item(item)]
    if not launcher_items:
        return ""
    for item in launcher_items:
        if not _token_is_usable(item):
            continue
        token = _extract_api_key(item)
        if token:
            return token
    return ""


def _extract_models(payload: Any) -> list[str]:
    models: list[str] = []
    for item in _iter_model_items(payload):
        model_id = _model_id_from_item(item)
        if model_id and model_id not in models:
            models.append(model_id)
    return models


def _model_ids_from_group(value: Any) -> list[str]:
    result: list[str] = []
    for item in _iter_model_items(value):
        model_id = _model_id_from_item(item)
        if model_id and model_id not in result:
            result.append(model_id)
    return result


MODEL_CONTAINER_KEYS = {
    "data",
    "items",
    "tokens",
    "rows",
    "list",
    "models",
    "model",
    "text",
    "chat",
    "llm",
    "image",
    "images",
    "video",
    "videos",
    "phone",
    "phone_models",
    "modelClasses",
    "classifiedModels",
}

MODEL_METADATA_KEYS = {
    "success",
    "message",
    "error",
    "code",
    "quota",
    "usage",
    "subscription",
    "account",
    "api",
    "defaults",
}

MODEL_ID_PREFIXES = (
    "gpt",
    "o1",
    "o3",
    "o4",
    "qwen",
    "claude",
    "gemini",
    "glm",
    "kimi",
    "moonshot",
    "deepseek",
    "doubao",
    "agnes",
    "seedream",
    "seedance",
    "sora",
    "veo",
    "kling",
    "wan",
    "hailuo",
    "runway",
    "pika",
    "luma",
    "flux",
    "imagen",
    "dall-e",
    "text-",
    "chat-",
)


def _iter_model_items(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, (str, int, float)):
        return [value]
    if not isinstance(value, dict):
        return []

    direct = _candidate_items(value)
    if direct:
        return direct

    result: list[Any] = []
    for key in (
        "models",
        "model",
        "data",
        "items",
        "tokens",
        "rows",
        "list",
        "text",
        "chat",
        "llm",
        "image",
        "images",
        "video",
        "videos",
        "phone",
        "phone_models",
        "modelClasses",
        "classifiedModels",
    ):
        nested = value.get(key)
        for item in _iter_model_items(nested):
            if item not in result:
                result.append(item)

    for key, nested in value.items():
        if not _looks_like_model_map_entry(key, nested):
            continue
        if key not in result:
            result.append(key)
        for item in _iter_model_items(nested):
            if item not in result:
                result.append(item)
    return result


def _model_id_from_item(item: Any) -> str:
    if isinstance(item, dict):
        return _pick_text(
            item.get("id"),
            item.get("model"),
            item.get("model_id"),
            item.get("modelId"),
            item.get("name"),
        )
    return _pick_text(item)


def _looks_like_model_map_entry(key: Any, value: Any) -> bool:
    text = str(key or "").strip()
    if not text:
        return False
    if text in MODEL_CONTAINER_KEYS or text in MODEL_METADATA_KEYS:
        return False
    if isinstance(value, dict) and _model_id_from_item(value):
        return True
    lowered = text.lower()
    if lowered.startswith(MODEL_ID_PREFIXES):
        return True
    return any(char.isdigit() for char in lowered) and any(char in lowered for char in ("-", ".", "/", "_"))


def _merge_model_ids(*groups: list[str]) -> list[str]:
    result: list[str] = []
    for group in groups:
        for model_id in group:
            if model_id and model_id not in result:
                result.append(model_id)
    return result


def _classified_models_from_catalog(catalog: Any) -> dict[str, list[str]]:
    if not isinstance(catalog, dict):
        return _classify_models(_model_ids_from_group(catalog))
    text = _merge_model_ids(
        _model_ids_from_group(catalog.get("text")),
        _model_ids_from_group(catalog.get("chat")),
        _model_ids_from_group(catalog.get("llm")),
    )
    image = _merge_model_ids(
        _model_ids_from_group(catalog.get("image")),
        _model_ids_from_group(catalog.get("images")),
    )
    video = _merge_model_ids(
        _model_ids_from_group(catalog.get("video")),
        _model_ids_from_group(catalog.get("videos")),
    )
    inferred = _classify_models(_extract_models(catalog))
    return {
        "text": _merge_model_ids(text, inferred["text"]),
        "image": _merge_model_ids(image, inferred["image"]),
        "video": _merge_model_ids(video, inferred["video"]),
    }


def _flatten_model_catalog(catalog: Any) -> list[str]:
    classes = _classified_models_from_catalog(catalog)
    phone = _phone_model_ids_from_catalog(catalog)
    return _merge_model_ids(classes["text"], classes["image"], classes["video"], phone)


def _phone_model_ids_from_catalog(catalog: Any) -> list[str]:
    if not isinstance(catalog, dict):
        return []
    result = _merge_model_ids(
        _model_ids_from_group(catalog.get("phone")),
        _model_ids_from_group(catalog.get("phone_models")),
    )
    for nested in catalog.values():
        if isinstance(nested, dict):
            result = _merge_model_ids(result, _phone_model_ids_from_catalog(nested))
    return result


def _looks_like_image_model(model_id: str) -> bool:
    text = model_id.lower()
    markers = ("image", "dall-e", "gpt-image", "flux", "midjourney", "mj-", "stable-diffusion", "sd-", "imagen", "seedream")
    return any(marker in text for marker in markers)


def _looks_like_video_model(model_id: str) -> bool:
    text = model_id.lower()
    markers = ("video", "veo", "sora", "seedance", "kling", "wan", "hailuo", "runway", "pika", "luma", "happyhorse")
    return any(marker in text for marker in markers)


def _classify_models(models: list[str]) -> dict[str, list[str]]:
    classified = {"text": [], "image": [], "video": []}
    for model in models:
        if _looks_like_video_model(model):
            classified["video"].append(model)
        elif _looks_like_image_model(model):
            classified["image"].append(model)
        elif _looks_like_phone_model(model):
            continue
        else:
            classified["text"].append(model)
    return classified


def _models_have_text(models: list[str]) -> bool:
    return bool(_classify_models(models)["text"])


def _launcher_permission_contract_satisfied(lease: dict[str, Any]) -> bool:
    token_group = _pick_text(lease.get("tokenGroup"))
    account_group = _pick_text(lease.get("accountGroup"), lease.get("group"))
    group_matches_account = not token_group or bool(account_group and token_group == account_group)
    return bool(
        lease.get("tokenKind") == "launcher"
        and lease.get("permissionMode") == "default"
        and lease.get("modelLimitsEnabled") is False
        and lease.get("unlimitedQuota") is True
        and group_matches_account
    )


def _text_models_with_default(classes: dict[str, Any], *, selected: str = "") -> list[str]:
    values = classes.get("text") if isinstance(classes.get("text"), list) else []
    text_models = [model for model in values if isinstance(model, str) and not _looks_like_non_text_model(model)]
    selected_model = _choose_model(text_models, _pick_text(selected), [])
    if selected_model and selected_model not in text_models:
        text_models = [selected_model, *text_models]
    return text_models


def _looks_like_non_text_model(model_id: str) -> bool:
    return _looks_like_phone_model(model_id) or _looks_like_image_model(model_id) or _looks_like_video_model(model_id)


def _choose_model(candidates: list[str], preferred: str, fallback: list[str] | None = None) -> str:
    candidates = [model for model in candidates if not _looks_like_non_text_model(model)]
    fallback = [model for model in (fallback or []) if not _looks_like_non_text_model(model)]
    if preferred in candidates:
        return preferred
    for model in TEXT_MODEL_PRIORITY:
        if model in candidates:
            return model
    if candidates:
        return candidates[0]
    if preferred in fallback:
        return preferred
    for model in TEXT_MODEL_PRIORITY:
        if model in fallback:
            return model
    return fallback[0] if fallback else ""


def _looks_like_phone_model(model_id: str) -> bool:
    text = str(model_id or "").strip().lower()
    return bool(text) and text in PHONE_MODEL_IDS


def _extract_subscription_snapshot(payload: Any, *, base_url: str, fallback: dict[str, Any] | None = None) -> dict[str, Any]:
    fallback = fallback if isinstance(fallback, dict) else {}
    data = _unwrap(payload)
    if not isinstance(data, dict):
        data = {}
    account = data.get("account") if isinstance(data.get("account"), dict) else {}
    subscription = data.get("subscription") if isinstance(data.get("subscription"), dict) else {}
    quota = data.get("quota") if isinstance(data.get("quota"), dict) else {}
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    fallback_usage = fallback.get("usage") if isinstance(fallback.get("usage"), dict) else {}
    plan = _pick_text(
        subscription.get("plan"),
        subscription.get("name"),
        account.get("plan"),
        account.get("group"),
        data.get("plan"),
        fallback.get("plan"),
        "default",
    )
    balance = _pick_text(
        subscription.get("balance"),
        subscription.get("remaining"),
        quota.get("remaining"),
        data.get("balance"),
        fallback_usage.get("quota"),
    )
    used = _pick_text(
        subscription.get("used"),
        usage.get("used"),
        usage.get("usedQuota"),
        usage.get("used_quota"),
        quota.get("used"),
        data.get("used_quota"),
        data.get("usedQuota"),
        fallback_usage.get("usedQuota"),
    )
    expires_at = _pick_text(
        subscription.get("expiresAt"),
        subscription.get("expiredAt"),
        subscription.get("expireAt"),
        subscription.get("expired_time"),
        data.get("expiresAt"),
        fallback.get("expiresAt"),
        fallback.get("leaseExpiresAt"),
    )
    purchase_url = _safe_purchase_url(
        _pick_text(
            subscription.get("purchaseUrl"),
            subscription.get("checkoutUrl"),
            subscription.get("url"),
            data.get("purchaseUrl"),
            _default_purchase_url(base_url),
        ),
        base_url=base_url,
    )
    return {
        "mode": "native",
        "plan": plan,
        "balance": balance,
        "expiresAt": expires_at,
        "usage": {
            "usedQuota": used,
            "requestCount": _pick_text(
                usage.get("requestCount"),
                usage.get("request_count"),
                data.get("request_count"),
                data.get("requestCount"),
                fallback_usage.get("requestCount"),
            ),
        },
        "purchaseUrl": purchase_url,
        "updatedAt": _iso(_utc_now()),
    }


def _default_purchase_url(base_url: str) -> str:
    base = str(base_url or DEFAULT_BASE_URL).strip().rstrip("/") or DEFAULT_BASE_URL
    return f"{base}{DEFAULT_ACCOUNT_CENTER_PATH}"


def _safe_purchase_url(value: Any, *, base_url: str) -> str:
    text = _pick_text(value)
    if not text:
        return _default_purchase_url(base_url)
    try:
        parsed = urllib.parse.urlparse(urllib.parse.urljoin(base_url, text))
    except Exception:
        return _default_purchase_url(base_url)
    if parsed.scheme not in {"http", "https"}:
        return _default_purchase_url(base_url)
    if parsed.hostname in MANAGED_HEANG_HOSTS and parsed.path.rstrip("/") == "/topup":
        return _default_purchase_url(base_url)
    if parsed.hostname in MANAGED_HEANG_HOSTS:
        return _replace_managed_heang_origin(urllib.parse.urlunparse(parsed), base_url)
    return urllib.parse.urlunparse(parsed)


def _legacy_fallback_url(url: str) -> str:
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        return ""
    if (parsed.hostname or "").lower() != "api-cn.heang.top":
        return ""
    legacy = urllib.parse.urlparse(LEGACY_BASE_URL)
    return urllib.parse.urlunparse(parsed._replace(scheme=legacy.scheme, netloc=legacy.netloc))


def _allows_legacy_fallback(url: str, method: str) -> bool:
    normalized_method = str(method or "GET").strip().upper()
    if normalized_method in {"GET", "HEAD", "OPTIONS"}:
        return True
    if normalized_method != "POST":
        return False
    try:
        path = urllib.parse.urlparse(url).path.rstrip("/") or "/"
    except Exception:
        return False
    return path in LEGACY_FALLBACK_POST_PATHS


class NewApiAccountManager:
    def __init__(self, paths: AppPaths, append_log=None):
        self.paths = paths
        self.license_mgr = LicenseManager(paths)
        self.append_log = append_log or (lambda _text: None)
        self._auth_capabilities_cache: tuple[float, str, dict[str, Any]] | None = None

    @property
    def session_path(self) -> str:
        return self.paths.member_session_file

    @staticmethod
    def normalize_base_url(value: Any) -> str:
        text = str(value or "").strip().rstrip("/")
        if not text:
            return DEFAULT_BASE_URL
        if not text.startswith(("http://", "https://")):
            text = f"https://{text}"
        return text.rstrip("/")

    def _request_json(
        self,
        opener: urllib.request.OpenerDirector,
        url: str,
        *,
        method: str = "GET",
        body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: int = 20,
    ) -> dict[str, Any]:
        data = json.dumps(body or {}, ensure_ascii=False).encode("utf-8") if body is not None else None
        fallback_url = _legacy_fallback_url(url) if _allows_legacy_fallback(url, method) else ""
        candidates = [url, fallback_url] if fallback_url else [url]
        payload: Any = {}
        for index, candidate_url in enumerate(candidates):
            request = urllib.request.Request(
                candidate_url,
                data=data,
                method=method,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "User-Agent": "LOOM-Launcher/2.1",
                    **(headers or {}),
                },
            )
            try:
                with opener.open(request, timeout=timeout) as response:
                    raw = response.read().decode("utf-8", errors="replace")
                    payload = json.loads(raw) if raw.strip() else {}
                break
            except urllib.error.HTTPError as error:
                if index + 1 < len(candidates) and error.code in TRANSIENT_HTTP_STATUS_CODES:
                    self.append_log("NewAPI 国内加速线路暂不可用，正在切换兼容线路。")
                    continue
                try:
                    raw = error.read().decode("utf-8", errors="replace")
                    payload = json.loads(raw) if raw.strip() else {}
                    message = _pick_text(
                        payload.get("message") if isinstance(payload, dict) else "",
                        payload.get("error") if isinstance(payload, dict) else "",
                    )
                except Exception:
                    message = ""
                raise NewApiAccountError(message or f"http_{error.code}", status_code=error.code) from error
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as error:
                if index + 1 < len(candidates):
                    self.append_log("NewAPI 国内加速线路连接失败，正在切换兼容线路。")
                    continue
                raise NewApiAccountError(f"newapi_network_error:{error}") from error
            except Exception as error:
                raise NewApiAccountError(f"newapi_network_error:{error}") from error

        if isinstance(payload, dict) and payload.get("success") is False:
            raise NewApiAccountError(_pick_text(payload.get("message"), payload.get("error"), "newapi_request_failed"))
        return payload if isinstance(payload, dict) else {"data": payload}

    def _auth_headers(self, access_token: str = "", user_id: str = "") -> dict[str, str]:
        headers: dict[str, str] = {}
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"
        if user_id:
            headers["New-Api-User"] = user_id
        return headers

    def _request_launcher_token_bridge(
        self,
        opener: urllib.request.OpenerDirector,
        base_url: str,
        username: str,
        password: str,
    ) -> tuple[str, dict[str, Any]]:
        payload = self._login_request(
            opener,
            f"{base_url}/api/openclaw/launcher-token",
            username,
            password,
            timeout=FAST_PASSWORD_BRIDGE_TIMEOUT_SECONDS,
        )
        data = _unwrap(payload)
        token = _extract_best_api_key(payload)
        if not token:
            raise NewApiAccountError("launcher_token_bridge_no_key")
        models = []
        if isinstance(data, dict) and isinstance(data.get("models"), list):
            models = [str(item).strip() for item in data.get("models") or [] if str(item).strip()]
        api = data.get("api") if isinstance(data, dict) and isinstance(data.get("api"), dict) else {}
        token_meta = {
            "source": _pick_text(data.get("source") if isinstance(data, dict) else "", "bridge"),
            "tokenId": data.get("tokenId") if isinstance(data, dict) else None,
            "tokenName": data.get("tokenName") if isinstance(data, dict) else "",
            "tokenKind": data.get("tokenKind") if isinstance(data, dict) else "",
            "permissionMode": data.get("permissionMode") if isinstance(data, dict) else "",
            "modelLimitsEnabled": data.get("modelLimitsEnabled") if isinstance(data, dict) else None,
            "unlimitedQuota": data.get("unlimitedQuota") if isinstance(data, dict) else None,
            "tokenGroup": data.get("tokenGroup") if isinstance(data, dict) else "",
            "models": models,
            "userId": _pick_text(data.get("userId") if isinstance(data, dict) else "", data.get("user_id") if isinstance(data, dict) else ""),
            "account": _pick_text(data.get("account") if isinstance(data, dict) else "", data.get("username") if isinstance(data, dict) else ""),
            "group": _pick_text(data.get("group") if isinstance(data, dict) else "", "default"),
            "remainQuota": data.get("remainQuota") if isinstance(data, dict) else None,
            "sessionCookie": _pick_text(data.get("sessionCookie") if isinstance(data, dict) else ""),
            "apiBaseUrl": _pick_text(api.get("baseUrl")),
        }
        legacy_contract_missing = bool(
            token_meta.get("tokenKind") == "launcher"
            and isinstance(data, dict)
            and all(
                key not in data
                for key in ("permissionMode", "modelLimitsEnabled", "unlimitedQuota", "tokenGroup")
            )
        )
        if legacy_contract_missing:
            token_meta.update({
                "permissionMode": "default",
                "modelLimitsEnabled": False,
                "unlimitedQuota": True,
                "tokenGroup": "",
                "legacyPasswordBridge": True,
            })
        if not _launcher_permission_contract_satisfied(token_meta):
            raise NewApiAccountError("launcher_token_permission_contract_invalid")
        return token, token_meta

    def _request_launcher_token_ensure_bridge(
        self,
        opener: urllib.request.OpenerDirector,
        base_url: str,
        api_token: str,
    ) -> tuple[str, dict[str, Any]]:
        payload = self._request_json(
            opener,
            f"{base_url}/api/openclaw/launcher-token/ensure",
            method="POST",
            body={},
            headers={"Authorization": f"Bearer {api_token}"},
            timeout=FAST_PASSWORD_BRIDGE_TIMEOUT_SECONDS,
        )
        data = _unwrap(payload)
        token = _extract_best_api_key(payload)
        if not token:
            raise NewApiAccountError("launcher_token_ensure_no_key")
        models = []
        if isinstance(data, dict) and isinstance(data.get("models"), list):
            models = [str(item).strip() for item in data.get("models") or [] if str(item).strip()]
        if not _models_have_text(models):
            raise NewApiAccountError("launcher_token_ensure_no_text_models")
        api = data.get("api") if isinstance(data, dict) and isinstance(data.get("api"), dict) else {}
        token_meta = {
            "source": _pick_text(data.get("source") if isinstance(data, dict) else "", "bridge_ensure"),
            "tokenId": data.get("tokenId") if isinstance(data, dict) else None,
            "tokenName": data.get("tokenName") if isinstance(data, dict) else "",
            "tokenKind": _pick_text(data.get("tokenKind") if isinstance(data, dict) else "", "launcher"),
            "permissionMode": data.get("permissionMode") if isinstance(data, dict) else "",
            "modelLimitsEnabled": data.get("modelLimitsEnabled") if isinstance(data, dict) else None,
            "unlimitedQuota": data.get("unlimitedQuota") if isinstance(data, dict) else None,
            "tokenGroup": data.get("tokenGroup") if isinstance(data, dict) else "",
            "models": models,
            "userId": _pick_text(data.get("userId") if isinstance(data, dict) else ""),
            "account": _pick_text(data.get("account") if isinstance(data, dict) else ""),
            "group": _pick_text(data.get("group") if isinstance(data, dict) else "", "default"),
            "apiBaseUrl": _pick_text(api.get("baseUrl")),
        }
        if not _launcher_permission_contract_satisfied(token_meta):
            raise NewApiAccountError("launcher_token_permission_contract_invalid")
        return token, token_meta

    def _login_request(
        self,
        opener: urllib.request.OpenerDirector,
        url: str,
        username: str,
        password: str,
        *,
        timeout: int = 20,
    ) -> dict[str, Any]:
        try:
            return self._request_json(
                opener,
                url,
                method="POST",
                body={"username": username, "password": password},
                timeout=timeout,
            )
        except NewApiAccountError as error:
            if not (_looks_like_email(username) and _should_retry_email_login(error)):
                raise
            self.append_log("[Account] username login payload rejected; retrying email payload\n")
            return self._request_json(
                opener,
                url,
                method="POST",
                body={"email": username, "password": password},
                timeout=timeout,
            )

    def _claim_bind_ticket(
        self,
        opener: urllib.request.OpenerDirector,
        base_url: str,
        ticket: str,
    ) -> dict[str, Any]:
        payload = self._request_json(
            opener,
            f"{base_url}/api/openclaw/bind/claim",
            method="POST",
            body={"ticket": ticket},
            timeout=35,
        )
        data = _unwrap(payload)
        token = _extract_best_api_key(payload)
        if not token:
            raise NewApiAccountError("bind_ticket_no_key")
        models = []
        if isinstance(data, dict) and isinstance(data.get("models"), list):
            models = [str(item).strip() for item in data.get("models") or [] if str(item).strip()]
        return {
            "raw": payload,
            "data": data if isinstance(data, dict) else {},
            "token": token,
            "models": models,
        }

    def _request_openclaw_auth_endpoint(
        self,
        opener: urllib.request.OpenerDirector,
        base_url: str,
        paths: tuple[str, ...],
        body: dict[str, Any],
        *,
        timeout: int = 35,
    ) -> dict[str, Any]:
        errors: list[str] = []
        for path in paths:
            try:
                return self._request_json(
                    opener,
                    f"{base_url}{path}",
                    method="POST",
                    body=body,
                    timeout=timeout,
                )
            except NewApiAccountError as error:
                errors.append(_redact_secret_text(error))
                status_code = getattr(error, "status_code", None)
                message = str(error).strip().lower()
                if status_code is not None:
                    endpoint_missing = status_code in {404, 405, 501}
                else:
                    endpoint_missing = message in {
                        "http_404",
                        "http_405",
                        "http_501",
                        "not found",
                        "endpoint not found",
                        "endpoint unavailable",
                    }
                if not endpoint_missing:
                    raise
        raise NewApiAccountError("; ".join(errors[-2:]) or "openclaw_auth_endpoint_unavailable")

    def send_email_code(self, email: str, *, base_url: str = "", purpose: str = "register") -> dict[str, Any]:
        email = email.strip()
        if not _looks_like_email(email):
            raise NewApiAccountError("请输入有效的模型账号邮箱")

        base_url = self.normalize_base_url(base_url)
        opener = urllib.request.build_opener()
        normalized_purpose = str(purpose or "").strip().lower()
        normalized_purpose = "login" if normalized_purpose in {"login", "email", "signin", "sign_in"} else "register"
        if normalized_purpose == "login":
            try:
                payload = self._request_openclaw_auth_endpoint(
                    opener,
                    base_url,
                    OPENCLAW_EMAIL_CODE_SEND_PATHS,
                    {
                        "email": email,
                        "purpose": "login",
                        "scene": "login",
                        "type": "login",
                        "mode": "login",
                        "action": "login",
                        "authType": "email_code_login",
                        "product": "LOOM",
                        "app": "LOOM",
                    },
                )
            except NewApiAccountError as error:
                if "not found" in str(error).lower() or "openclaw_auth_endpoint_unavailable" in str(error).lower():
                    raise NewApiAccountError("当前模型服务暂未开放验证码登录，请使用密码登录，或切到邮箱注册创建新账号。") from error
                raise
            data = _unwrap(payload)
            data = data if isinstance(data, dict) else {}
            result = {
                "sent": bool(data.get("sent", payload.get("success", True))),
                "email": email,
                "maskedEmail": _pick_text(data.get("maskedEmail"), data.get("masked_email")),
                "retryAfter": data.get("retryAfter") or data.get("retry_after"),
                "expiresIn": data.get("expiresIn") or data.get("expires_in"),
                "message": _pick_text(data.get("message"), payload.get("message")),
            }
            return {key: value for key, value in result.items() if value not in ("", None)}

        try:
            payload = self._request_json(
                opener,
                f"{base_url}{NEWAPI_EMAIL_CODE_SEND_PATH}?{urllib.parse.urlencode({'email': email})}",
                method="GET",
                timeout=20,
            )
        except NewApiAccountError as first_error:
            if not _should_try_openclaw_email_fallback(first_error):
                raise
            self.append_log(f"[Account] New API verification endpoint unavailable: {_redact_secret_text(first_error)}\n")
            payload = self._request_openclaw_auth_endpoint(
                opener,
                base_url,
                OPENCLAW_EMAIL_CODE_SEND_PATHS,
                {
                    "email": email,
                    "purpose": "register",
                    "scene": "register",
                    "type": "register",
                    "mode": "register",
                    "action": "register",
                    "product": "LOOM",
                    "app": "LOOM",
                },
            )
        data = _unwrap(payload)
        data = data if isinstance(data, dict) else {}
        result = {
            "sent": bool(data.get("sent", payload.get("success", True))),
            "email": email,
            "maskedEmail": _pick_text(data.get("maskedEmail"), data.get("masked_email")),
            "retryAfter": data.get("retryAfter") or data.get("retry_after"),
            "expiresIn": data.get("expiresIn") or data.get("expires_in"),
            "message": _pick_text(data.get("message"), payload.get("message")),
        }
        return {key: value for key, value in result.items() if value not in ("", None)}

    def auth_capabilities(self, *, base_url: str = "") -> dict[str, Any]:
        base_url = self.normalize_base_url(base_url)
        now = time.monotonic()
        cached = self._auth_capabilities_cache
        if cached and cached[1] == base_url and now - cached[0] < AUTH_CAPABILITIES_CACHE_SECONDS:
            return dict(cached[2])

        capabilities: dict[str, Any] = {
            "passwordLogin": True,
            "inlineEmailCode": False,
            "inlineRegistration": False,
            "webRegistrationRequired": True,
            "registrationUrl": f"{base_url}/register",
            "emailReason": "正在检测模型账号邮箱能力；密码登录可直接使用。",
        }
        try:
            bridge_payload = self._request_json(
                urllib.request.build_opener(),
                f"{base_url}/api/openclaw/auth/capabilities",
                timeout=4,
            )
            bridge_data = _unwrap(bridge_payload)
            if isinstance(bridge_data, dict) and "passwordLogin" in bridge_data:
                capabilities.update({
                    "passwordLogin": bridge_data.get("passwordLogin") is not False,
                    "inlineEmailCode": bridge_data.get("inlineEmailCode") is True,
                    "inlineRegistration": bridge_data.get("inlineRegistration") is True,
                    "webRegistrationRequired": bridge_data.get("webRegistrationRequired") is True,
                    "emailConfigured": bridge_data.get("emailConfigured") is True,
                    "emailReason": _pick_text(bridge_data.get("emailReason"), capabilities["emailReason"]),
                })
                self._auth_capabilities_cache = (now, base_url, dict(capabilities))
                return capabilities
        except NewApiAccountError:
            pass

        try:
            payload = self._request_json(
                urllib.request.build_opener(),
                f"{base_url}/api/status",
                timeout=6,
            )
            data = _unwrap(payload)
            data = data if isinstance(data, dict) else {}
            email_enabled = data.get("email_verification") is True
            turnstile_required = data.get("turnstile_check") is True
            inline_email = bool(email_enabled and not turnstile_required)
            capabilities.update({
                "inlineEmailCode": inline_email,
                "inlineRegistration": False,
                "webRegistrationRequired": bool(turnstile_required or not inline_email),
                "emailVerificationEnabled": email_enabled,
                "turnstileRequired": turnstile_required,
                "emailReason": (
                    "当前模型服务启用了网页人机验证，请在网页完成邮箱注册或验证码登录。"
                    if turnstile_required
                    else "当前模型服务未开放桌面端邮箱验证码，请使用密码登录或网页注册。"
                    if not email_enabled
                    else "桌面端邮箱验证码可用。"
                ),
            })
        except NewApiAccountError as error:
            self.append_log(f"[Account] auth capability probe unavailable: {_redact_secret_text(error)}\n")
            capabilities["emailReason"] = "邮箱能力暂时无法确认，请使用密码登录或网页注册。"

        self._auth_capabilities_cache = (now, base_url, dict(capabilities))
        return capabilities

    def _build_email_code_session(
        self,
        base_url: str,
        email: str,
        payload: dict[str, Any],
        cookie_jar: http.cookiejar.CookieJar,
    ) -> dict[str, Any]:
        data = _unwrap(payload)
        if not isinstance(data, dict):
            data = {}
        account = data.get("account") if isinstance(data.get("account"), dict) else {}
        quota = data.get("quota") if isinstance(data.get("quota"), dict) else {}
        api = data.get("api") if isinstance(data.get("api"), dict) else {}
        defaults = data.get("defaults") if isinstance(data.get("defaults"), dict) else {}
        models_catalog = data.get("models")

        api_token = _pick_text(
            api.get("token"),
            api.get("apiKey"),
            api.get("api_key"),
            api.get("key"),
            data.get("scopedModelToken"),
            data.get("modelToken"),
            data.get("apiToken"),
            data.get("apiKey"),
        )
        if not api_token:
            api_token = _extract_best_api_key({"data": api}) or _extract_best_api_key(data)
        if not api_token:
            raise NewApiAccountError("邮箱验证码登录成功，但服务端未返回托管模型 Token")

        api_base_url = _trusted_managed_api_base(
            _pick_text(api.get("baseUrl"), api.get("baseURL"), data.get("baseUrl")),
            base_url,
        )
        session_base_url = self.normalize_base_url(base_url)
        username = _pick_text(account.get("email"), account.get("username"), account.get("name"), email)
        user_id = _pick_text(account.get("id"), account.get("userId"), account.get("user_id"), username)
        plan = _pick_text(account.get("plan"), account.get("group"), data.get("plan"), "default")
        launcher_token = _pick_text(data.get("launcherToken"), data.get("launcher_token"), data.get("sessionToken"))
        flat_models = _flatten_model_catalog(models_catalog)
        if not flat_models:
            flat_models = _extract_models(payload)
        classified = _classified_models_from_catalog(models_catalog)
        if not any(classified.values()):
            classified = _classify_models(flat_models)
        phone_models = _model_ids_from_group(models_catalog.get("phone") if isinstance(models_catalog, dict) else None)

        login_payload = {
            "success": True,
            "data": {
                "id": user_id,
                "username": username,
                "email": username,
                "name": _pick_text(account.get("name"), username),
                "group": plan,
                "launcherToken": launcher_token,
            },
        }
        self_payload = {
            "success": True,
            "data": {
                "id": user_id,
                "username": username,
                "email": username,
                "name": _pick_text(account.get("name"), username),
                "group": plan,
                "quota": quota.get("remaining") if quota else account.get("quota"),
                "usedQuota": quota.get("used") if quota else account.get("usedQuota"),
                "requestCount": quota.get("requestCount") if quota else account.get("requestCount"),
            },
        }
        token_meta = {
            "source": "openclaw_email_code",
            "launcherToken": launcher_token,
            "tokenId": data.get("tokenId"),
            "tokenName": data.get("tokenName") or "",
            "tokenKind": data.get("tokenKind") or "",
            "models": flat_models,
        }
        session = self._build_session(
            session_base_url,
            username,
            api_token,
            login_payload,
            self_payload,
            token_meta,
            flat_models,
            cookie_jar,
        )
        text_model = _choose_model(classified["text"], DEFAULT_TEXT_MODEL, flat_models)
        image_model = _pick_text(defaults.get("imageModel"), session.get("gatewayImageModel"))
        video_model = _pick_text(defaults.get("videoDraftModel"), defaults.get("videoModel"), session.get("gatewayVideoDraftModel"))
        phone_model = _pick_text(defaults.get("phoneModel"), DEFAULT_PHONE_MODEL, phone_models[0] if phone_models else "")
        session.update({
            "gatewayBaseUrl": api_base_url,
            "gatewayImageBaseUrl": api_base_url,
            "gatewayDefaultModel": text_model,
            "gatewayImageModel": image_model,
            "gatewayVideoDraftModel": video_model,
            "gatewayModels": flat_models,
            "usage": quota,
        })
        gateway = session.get("gateway") if isinstance(session.get("gateway"), dict) else {}
        gateway.update({
            "baseUrl": api_base_url,
            "imageBaseUrl": api_base_url,
            "defaultModel": text_model,
            "imageModel": image_model,
            "videoDraftModel": video_model,
            "models": flat_models,
            "classifiedModels": classified,
        })
        gateway.pop("videoModel", None)
        session["gateway"] = gateway
        newapi = session.get("newApi") if isinstance(session.get("newApi"), dict) else {}
        newapi.update({
            "baseUrl": session_base_url,
            "launcherToken": launcher_token,
            "authMethod": "email_code",
            "modelClasses": classified,
        })
        session_cookie = _pick_text(data.get("sessionCookie"), data.get("session_cookie"))
        if session_cookie:
            newapi["sessionCookie"] = session_cookie
        session["newApi"] = newapi
        phone_agent = session.get("phoneAgent") if isinstance(session.get("phoneAgent"), dict) else {}
        phone_agent.update({
            "baseUrl": api_base_url,
            "apiKey": api_token,
            "model": phone_model,
        })
        session["phoneAgent"] = phone_agent
        return session

    def login_with_email_code(
        self,
        email: str,
        code: str,
        *,
        base_url: str = "",
        sync_runtime: bool = True,
    ) -> dict[str, Any]:
        email = email.strip()
        code = code.strip()
        if not _looks_like_email(email):
            raise NewApiAccountError("请输入有效的模型账号邮箱")
        if not code:
            raise NewApiAccountError("请输入邮箱验证码")

        base_url = self.normalize_base_url(base_url)
        cookie_jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))
        try:
            payload = self._request_openclaw_auth_endpoint(
                opener,
                base_url,
                OPENCLAW_EMAIL_CODE_LOGIN_PATHS,
                {
                    "email": email,
                    "code": code,
                    "purpose": "login",
                    "scene": "login",
                    "type": "login",
                    "mode": "login",
                    "action": "login",
                    "authType": "email_code_login",
                    "product": "LOOM",
                    "app": "LOOM",
                },
            )
        except NewApiAccountError as error:
            if "not found" in str(error).lower() or "openclaw_auth_endpoint_unavailable" in str(error).lower():
                raise NewApiAccountError("当前模型服务暂未开放验证码登录，请使用密码登录") from error
            raise
        # The managed NewAPI deployment exposes email verification for
        # registration but not passwordless login. Keep this route for future
        # launcher-specific support and translate missing endpoints in routes.
        session = self._build_email_code_session(base_url, email, payload, cookie_jar)
        return self._persist_authenticated_session(session, sync_runtime=sync_runtime)

    def register_with_email_code(
        self,
        email: str,
        password: str,
        code: str,
        *,
        base_url: str = "",
        sync_runtime: bool = True,
    ) -> dict[str, Any]:
        email = email.strip()
        password = password.strip()
        code = code.strip()
        if not _looks_like_email(email):
            raise NewApiAccountError("请输入有效的模型账号邮箱")
        if len(password) < 6:
            raise NewApiAccountError("密码至少需要 6 位")
        if not code:
            raise NewApiAccountError("请输入邮箱验证码")

        base_url = self.normalize_base_url(base_url)
        cookie_jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))
        payload = self._request_openclaw_auth_endpoint(
            opener,
            base_url,
            OPENCLAW_EMAIL_CODE_REGISTER_PATHS,
            {
                "email": email,
                "username": email,
                "password": password,
                "code": code,
                "verification_code": code,
                "product": "LOOM",
                "app": "LOOM",
            },
        )
        try:
            session = self._build_email_code_session(base_url, email, payload, cookie_jar)
        except NewApiAccountError:
            data = _unwrap(payload)
            api = data.get("api") if isinstance(data, dict) and isinstance(data.get("api"), dict) else {}
            managed_token = _pick_text(
                api.get("token"),
                api.get("apiKey"),
                api.get("api_key"),
                data.get("apiToken") if isinstance(data, dict) else "",
                data.get("apiKey") if isinstance(data, dict) else "",
            )
            if managed_token:
                raise
            session = self.login(email, password, base_url=base_url, sync_runtime=sync_runtime)
            return session
        return self._persist_authenticated_session(session, sync_runtime=sync_runtime)

    def subscription_snapshot(self) -> dict[str, Any]:
        session = self.current()
        if not session:
            return {
                "mode": "native",
                "loggedIn": False,
                "plan": "",
                "balance": "",
                "expiresAt": "",
                "usage": {},
                "purchaseUrl": _default_purchase_url(DEFAULT_BASE_URL),
                "webViewUrl": _default_purchase_url(DEFAULT_BASE_URL),
            }
        newapi = session.get("newApi") if isinstance(session.get("newApi"), dict) else {}
        base_url = self.normalize_base_url(newapi.get("baseUrl") or DEFAULT_BASE_URL)
        opener = urllib.request.build_opener()
        headers = self._session_headers(session)
        fallback = {
            "plan": session.get("plan"),
            "expiresAt": session.get("expiresAt") or session.get("leaseExpiresAt"),
            "usage": session.get("usage") if isinstance(session.get("usage"), dict) else {},
            "leaseExpiresAt": session.get("leaseExpiresAt"),
        }
        errors: list[str] = []
        for path in OPENCLAW_SUBSCRIPTION_PATHS:
            try:
                payload = self._request_json(opener, f"{base_url}{path}", headers=headers, timeout=20)
                snapshot = _extract_subscription_snapshot(payload, base_url=base_url, fallback=fallback)
                snapshot["loggedIn"] = True
                snapshot["offline"] = False
                return snapshot
            except NewApiAccountError as error:
                errors.append(_redact_secret_text(error))
        snapshot = _extract_subscription_snapshot({}, base_url=base_url, fallback=fallback)
        snapshot.update({
            "loggedIn": True,
            "offline": True,
            "stale": True,
            "webViewUrl": snapshot.get("purchaseUrl") or _default_purchase_url(base_url),
            "message": "暂时无法连接模型服务，订阅信息稍后刷新",
        })
        if errors:
            snapshot["diagnostic"] = "; ".join(errors[-2:])
        return snapshot

    def _create_launcher_token(
        self,
        opener: urllib.request.OpenerDirector,
        base_url: str,
        headers: dict[str, str],
    ) -> str:
        token_name = f"{LAUNCHER_TOKEN_NAME_PREFIX} {int(time.time())}"
        attempts = [
            {
                "name": token_name,
                "remain_quota": 0,
                "expired_time": -1,
                "unlimited_quota": True,
                "model_limits_enabled": False,
                "model_limits": "",
                "allow_ips": "",
                "group": "",
                "cross_group_retry": False,
            },
            {
                "name": token_name,
                "remain_quota": 0,
                "expired_time": -1,
                "unlimited_quota": True,
                "model_limits_enabled": False,
                "model_limits": "",
                "group": "",
            },
        ]
        errors: list[str] = []
        for body in attempts:
            try:
                payload = self._request_json(opener, f"{base_url}/api/token/", method="POST", body=body, headers=headers)
                token = _extract_best_api_key(payload, token_name)
                if token:
                    return token
                created = _unwrap(payload)
                if isinstance(created, dict) and created.get("success") is False:
                    errors.append(_pick_text(created.get("message"), "token_create_failed"))
                    continue
                list_payload = self._request_json(opener, f"{base_url}/api/token/?p=0&page_size=100", headers=headers)
                token = _extract_best_api_key(list_payload, token_name)
                if token:
                    return token
                self._delete_created_tokens_by_name(opener, base_url, headers, token_name, list_payload)
                raise NewApiAccountError("模型服务已创建 Token，但接口只返回脱敏 key；请手动填入 API Token，或在服务端开放创建后返回完整 key")
            except NewApiAccountError as error:
                message = _redact_secret_text(error)
                errors.append(message)
                if "脱敏 key" in message:
                    break
        raise NewApiAccountError("无法自动创建 API Token：" + "; ".join(errors[-3:]))

    def _delete_created_tokens_by_name(
        self,
        opener: urllib.request.OpenerDirector,
        base_url: str,
        headers: dict[str, str],
        token_name: str,
        payload: dict[str, Any],
    ) -> None:
        for item in _candidate_items(payload):
            if not isinstance(item, dict) or str(item.get("name") or "") != token_name:
                continue
            token_id = _pick_text(item.get("id"))
            if not token_id:
                continue
            try:
                self._request_json(opener, f"{base_url}/api/token/{token_id}", method="DELETE", headers=headers, timeout=10)
            except NewApiAccountError:
                pass

    def _read_or_create_api_token(
        self,
        opener: urllib.request.OpenerDirector,
        base_url: str,
        headers: dict[str, str],
        username: str,
        password: str,
        supplied_api_token: str,
        *,
        try_bridge: bool = True,
    ) -> tuple[str, dict[str, Any]]:
        supplied_api_token = supplied_api_token.strip()
        if supplied_api_token:
            return supplied_api_token, {"source": "supplied"}

        if try_bridge:
            try:
                return self._request_launcher_token_bridge(opener, base_url, username, password)
            except NewApiAccountError as error:
                self.append_log(f"[Account] launcher token bridge unavailable: {_redact_secret_text(error)}\n")

        list_payload: dict[str, Any] | None = None
        try:
            list_payload = self._request_json(opener, f"{base_url}/api/token/?p=0&page_size=100", headers=headers)
            token = _extract_launcher_api_key(list_payload)
            if token:
                return token, {"source": "existing_launcher", "raw": _candidate_items(list_payload)}
        except NewApiAccountError as error:
            self.append_log(f"[Account] token list unavailable: {_redact_secret_text(error)}\n")

        create_error: NewApiAccountError | None = None
        try:
            token = self._create_launcher_token(opener, base_url, headers)
            return token, {"source": "created_launcher"}
        except NewApiAccountError as error:
            create_error = error
            self.append_log(f"[Account] launcher token create unavailable: {_redact_secret_text(error)}\n")

        if create_error:
            raise create_error
        raise NewApiAccountError("无法读取或创建模型服务 API Token")

    def _fetch_models(self, opener: urllib.request.OpenerDirector, base_url: str, api_token: str, headers: dict[str, str]) -> list[str]:
        model_ids: list[str] = []
        for url, request_headers in (
            (f"{base_url}/api/user/models", headers),
            (f"{base_url}/v1/models", {"Authorization": f"Bearer {api_token}"}),
        ):
            try:
                payload = self._request_json(opener, url, headers=request_headers, timeout=25)
                for model in _extract_models(payload):
                    if model not in model_ids:
                        model_ids.append(model)
                if _models_have_text(model_ids):
                    return model_ids
            except NewApiAccountError:
                continue
        return model_ids

    def _session_headers(self, session: dict[str, Any]) -> dict[str, str]:
        newapi = session.get("newApi") if isinstance(session.get("newApi"), dict) else {}
        headers = self._auth_headers("", _pick_text(newapi.get("userId")))
        cookie = _pick_text(newapi.get("sessionCookie"))
        if cookie:
            headers["Cookie"] = cookie
        return headers

    def _build_session(
        self,
        base_url: str,
        username: str,
        api_token: str,
        login_payload: dict[str, Any],
        self_payload: dict[str, Any],
        token_meta: dict[str, Any],
        models: list[str],
        cookie_jar: http.cookiejar.CookieJar,
    ) -> dict[str, Any]:
        login_data = _unwrap(login_payload)
        self_data = _unwrap(self_payload)
        account_name = _extract_account_name(self_data, login_data) or username
        user_id = _extract_user_id(self_data, login_data) or account_name
        classified = _classify_models(models)
        text_model = _choose_model(classified["text"], DEFAULT_TEXT_MODEL, models)
        image_model = classified["image"][0] if classified["image"] else ""
        video_model = classified["video"][0] if classified["video"] else ""
        now = _utc_now()
        cookies = "; ".join(f"{cookie.name}={cookie.value}" for cookie in cookie_jar)
        usage = {}
        if isinstance(self_data, dict):
            usage = {
                "quota": self_data.get("quota"),
                "usedQuota": self_data.get("used_quota") or self_data.get("usedQuota"),
                "requestCount": self_data.get("request_count") or self_data.get("requestCount"),
            }
        return {
            "source": ACCOUNT_SOURCE,
            "memberId": f"newapi:{user_id}",
            "memberName": account_name,
            "plan": _pick_text((self_data or {}).get("group") if isinstance(self_data, dict) else "", "default"),
            "status": "active",
            "expiresAt": None,
            "leaseExpiresAt": _iso(now + timedelta(days=SESSION_GRACE_DAYS)),
            "gatewayBaseUrl": f"{base_url}/v1",
            "gatewayImageBaseUrl": f"{base_url}/v1",
            "gatewayVideoBaseUrl": "",
            "gatewayDefaultModel": text_model,
            "gatewayImageModel": image_model,
            "gatewayVideoDraftModel": video_model,
            "gatewayModels": models,
            "lastGoodModels": {
                "models": models,
                "classified": classified,
                "updatedAt": _iso(now),
            },
            "memberToken": api_token,
            "gatewayImageAccessToken": api_token,
            "gatewayVideoAccessToken": "",
            "features": ["llm", "image"] + (["video"] if video_model else []),
            "usage": usage,
            "lease": {
                "source": ACCOUNT_SOURCE,
                "quota": usage,
                "tokenSource": token_meta.get("source"),
                "tokenId": token_meta.get("tokenId"),
                "tokenName": token_meta.get("tokenName") or "",
                "tokenKind": token_meta.get("tokenKind") or "",
                "permissionMode": token_meta.get("permissionMode") or "",
                "modelLimitsEnabled": token_meta.get("modelLimitsEnabled"),
                "unlimitedQuota": token_meta.get("unlimitedQuota"),
                "tokenGroup": token_meta.get("tokenGroup") or "",
                "accountGroup": token_meta.get("group") or "",
            },
            "gateway": {
                "baseUrl": f"{base_url}/v1",
                "imageBaseUrl": f"{base_url}/v1",
                "videoBaseUrl": "",
                "accessToken": api_token,
                "imageAccessToken": api_token,
                "videoAccessToken": "",
                "defaultModel": text_model,
                "imageModel": image_model,
                "videoDraftModel": video_model,
                "models": models,
                "classifiedModels": classified,
            },
            "newApi": {
                "baseUrl": base_url,
                "userId": user_id,
                "account": account_name,
                "sessionCookie": cookies,
                "lastOnlineAt": _iso(now),
                "graceExpiresAt": _iso(now + timedelta(days=SESSION_GRACE_DAYS)),
                "modelClasses": classified,
            },
            "phoneAgent": {
                "managedBy": ACCOUNT_SOURCE,
                "baseUrl": f"{base_url}/v1",
                "apiKey": api_token,
                "model": DEFAULT_PHONE_MODEL,
            },
            "updatedAt": _iso(now),
            "managedBy": ACCOUNT_SOURCE,
        }

    @staticmethod
    def _bridge_can_use_legacy_fallback(error: NewApiAccountError) -> bool:
        status_code = getattr(error, "status_code", None)
        if status_code is not None:
            return status_code in {404, 405, 408, 429, 500, 501, 502, 503, 504, 520, 521, 522, 523, 524}
        message = str(error).strip().lower()
        return any(
            marker in message
            for marker in (
                "http_404",
                "http_405",
                "http_408",
                "http_429",
                "http_500",
                "http_501",
                "http_502",
                "http_503",
                "http_504",
                "not found",
                "endpoint not found",
                "newapi_network_error",
                "timed out",
                "timeout",
                "additional configuration",
                "not configured",
                "requires configuration",
                "需要额外配置",
                "未配置",
            )
        )

    def _build_bridge_session(
        self,
        base_url: str,
        username: str,
        api_token: str,
        token_meta: dict[str, Any],
        cookie_jar: http.cookiejar.CookieJar,
    ) -> dict[str, Any]:
        account = _pick_text(token_meta.get("account"), username)
        user_id = _pick_text(token_meta.get("userId"), account)
        group = _pick_text(token_meta.get("group"), "default")
        user_data = {
            "id": user_id,
            "username": account,
            "email": account if _looks_like_email(account) else "",
            "group": group,
            "quota": token_meta.get("remainQuota"),
        }
        payload = {"success": True, "data": user_data}
        models = token_meta.get("models") if isinstance(token_meta.get("models"), list) else []
        session = self._build_session(
            base_url,
            username,
            api_token,
            payload,
            payload,
            token_meta,
            models,
            cookie_jar,
        )
        api_base_url = _trusted_managed_api_base(token_meta.get("apiBaseUrl"), base_url)
        session["gatewayBaseUrl"] = api_base_url
        session["gatewayImageBaseUrl"] = api_base_url
        gateway = session.get("gateway") if isinstance(session.get("gateway"), dict) else {}
        gateway["baseUrl"] = api_base_url
        gateway["imageBaseUrl"] = api_base_url
        session["gateway"] = gateway
        phone_agent = session.get("phoneAgent") if isinstance(session.get("phoneAgent"), dict) else {}
        phone_agent["baseUrl"] = api_base_url
        session["phoneAgent"] = phone_agent
        newapi = session.get("newApi") if isinstance(session.get("newApi"), dict) else {}
        newapi["authMethod"] = "password_bridge"
        session_cookie = _pick_text(token_meta.get("sessionCookie"))
        if session_cookie:
            newapi["sessionCookie"] = session_cookie
        session["newApi"] = newapi
        return session

    def login(
        self,
        username: str,
        password: str,
        *,
        base_url: str = "",
        api_token: str = "",
        sync_runtime: bool = True,
    ) -> dict[str, Any]:
        username = username.strip()
        password = str(password or "")
        if not username or not password:
            raise NewApiAccountError("请输入模型账号用户名或邮箱和密码")

        base_url = self.normalize_base_url(base_url)
        cookie_jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))
        bridge_attempted = False
        if not api_token.strip():
            bridge_attempted = True
            try:
                bridge_token, bridge_meta = self._request_launcher_token_bridge(opener, base_url, username, password)
            except NewApiAccountError as error:
                if (urllib.parse.urlparse(base_url).hostname or "").lower() in MANAGED_HEANG_HOSTS:
                    raise
                if not self._bridge_can_use_legacy_fallback(error):
                    raise
                self.append_log(f"[Account] fast login bridge unavailable, using compatibility path: {_redact_secret_text(error)}\n")
            else:
                bridge_models = bridge_meta.get("models") if isinstance(bridge_meta.get("models"), list) else []
                if not _models_have_text(bridge_models):
                    raise NewApiAccountError("模型账号服务未返回可用文本模型，请稍后重试")
                session = self._build_bridge_session(base_url, username, bridge_token, bridge_meta, cookie_jar)
                return self._persist_authenticated_session(session, sync_runtime=sync_runtime)

        login_payload = self._login_request(
            opener,
            f"{base_url}/api/user/login",
            username,
            password,
            timeout=NATIVE_PASSWORD_LOGIN_TIMEOUT_SECONDS,
        )
        login_data = _unwrap(login_payload)
        access_token = _pick_text(
            login_payload.get("access_token"),
            login_payload.get("accessToken"),
            login_payload.get("token"),
            login_data.get("access_token") if isinstance(login_data, dict) else "",
            login_data.get("accessToken") if isinstance(login_data, dict) else "",
            login_data.get("token") if isinstance(login_data, dict) else "",
        )
        user_id = _extract_user_id(login_payload, login_data)
        headers = self._auth_headers(access_token, user_id)

        try:
            self_payload = self._request_json(opener, f"{base_url}/api/user/self", headers=headers)
        except NewApiAccountError:
            self_payload = login_payload
        if not user_id:
            user_id = _extract_user_id(self_payload, login_payload)
            headers = self._auth_headers(access_token, user_id)

        api_token_value, token_meta = self._read_or_create_api_token(
            opener,
            base_url,
            headers,
            username,
            password,
            api_token,
            try_bridge=not bridge_attempted,
        )
        models = token_meta.get("models") if isinstance(token_meta.get("models"), list) else []
        if not models:
            models = self._fetch_models(opener, base_url, api_token_value, headers)
        if (
            not api_token.strip()
            and not _models_have_text(models)
            and token_meta.get("source") not in {"supplied", "created_launcher", "created_launcher_after_model_check"}
        ):
            try:
                fresh_token = self._create_launcher_token(opener, base_url, headers)
                fresh_models = self._fetch_models(opener, base_url, fresh_token, headers)
                if _models_have_text(fresh_models):
                    api_token_value = fresh_token
                    token_meta = {"source": "created_launcher_after_model_check"}
                    models = fresh_models
            except NewApiAccountError as error:
                self.append_log(f"[Account] launcher token model check failed: {_redact_secret_text(error)}\n")
        session = self._build_session(base_url, username, api_token_value, login_payload, self_payload, token_meta, models, cookie_jar)
        return self._persist_authenticated_session(session, sync_runtime=sync_runtime)

    def _persist_authenticated_session(self, session: dict[str, Any], *, sync_runtime: bool) -> dict[str, Any]:
        session["managedGatewayMigrationVersion"] = MANAGED_GATEWAY_MIGRATION_VERSION
        self._write_session(session)
        if sync_runtime:
            self.sync_targets(session, targets=DEFAULT_RUNTIME_SYNC_TARGETS)
        return session

    def bind_ticket(self, ticket: str, *, base_url: str = "") -> dict[str, Any]:
        ticket = ticket.strip()
        if not ticket:
            raise NewApiAccountError("bind ticket is required")

        base_url = self.normalize_base_url(base_url)
        cookie_jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))
        claimed = self._claim_bind_ticket(opener, base_url, ticket)
        data = claimed["data"] if isinstance(claimed.get("data"), dict) else {}
        api_token_value = _pick_text(claimed.get("token"))
        username = _pick_text(data.get("account"), data.get("username"), "NewAPI Account")
        user_id = _pick_text(data.get("userId"), data.get("user_id"), data.get("id"), username)
        login_payload = {
            "success": True,
            "data": {
                "id": user_id,
                "username": username,
                "email": username,
                "group": _pick_text(data.get("group"), data.get("plan"), "default"),
            },
        }
        self_payload = login_payload
        headers = self._auth_headers("", user_id)
        models = claimed["models"] if isinstance(claimed.get("models"), list) else []
        if not models:
            models = self._fetch_models(opener, base_url, api_token_value, headers)
        token_meta = {
            "source": _pick_text(data.get("source"), "website_bind"),
            "tokenId": data.get("tokenId"),
            "tokenName": data.get("tokenName") or "",
            "tokenKind": data.get("tokenKind") or "",
            "models": models,
        }
        session = self._build_session(base_url, username, api_token_value, login_payload, self_payload, token_meta, models, cookie_jar)
        self._write_session(session)
        self.sync_targets(session, targets=DEFAULT_RUNTIME_SYNC_TARGETS)
        return session

    def ensure_launcher_token(
        self,
        *,
        sync_runtime: bool = True,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        session = self.current()
        if not session or session.get("source") != ACCOUNT_SOURCE:
            raise NewApiAccountError("not_logged_in")
        current_token = _pick_text(session.get("memberToken"))
        if not current_token:
            raise NewApiAccountError("managed_session_missing_api_token")
        lease = session.get("lease") if isinstance(session.get("lease"), dict) else {}
        current_models = session.get("gatewayModels") if isinstance(session.get("gatewayModels"), list) else []
        if not force_refresh and _launcher_permission_contract_satisfied(lease) and _models_have_text(current_models):
            return session

        newapi = session.get("newApi") if isinstance(session.get("newApi"), dict) else {}
        base_url = self.normalize_base_url(newapi.get("baseUrl") or DEFAULT_BASE_URL)
        opener = urllib.request.build_opener()
        api_token, token_meta = self._request_launcher_token_ensure_bridge(
            opener,
            base_url,
            current_token,
        )
        models = token_meta["models"]
        classified = _classify_models(models)
        now = _utc_now()
        api_base_url = _trusted_managed_api_base(token_meta.get("apiBaseUrl"), base_url)

        session["memberToken"] = api_token
        session["gatewayImageAccessToken"] = api_token
        session["gatewayVideoAccessToken"] = ""
        session["gatewayBaseUrl"] = api_base_url
        session["gatewayImageBaseUrl"] = api_base_url
        session["gatewayModels"] = models
        session["gatewayDefaultModel"] = _choose_model(
            classified["text"],
            _pick_text(session.get("gatewayDefaultModel"), DEFAULT_TEXT_MODEL),
            models,
        )
        session["gatewayImageModel"] = (
            session.get("gatewayImageModel")
            if session.get("gatewayImageModel") in classified["image"]
            else (classified["image"][0] if classified["image"] else "")
        )
        session["gatewayVideoDraftModel"] = (
            session.get("gatewayVideoDraftModel")
            if session.get("gatewayVideoDraftModel") in classified["video"]
            else (classified["video"][0] if classified["video"] else "")
        )
        session["lastGoodModels"] = {
            "models": models,
            "classified": classified,
            "updatedAt": _iso(now),
        }

        gateway = session.get("gateway") if isinstance(session.get("gateway"), dict) else {}
        gateway.update({
            "baseUrl": api_base_url,
            "imageBaseUrl": api_base_url,
            "accessToken": api_token,
            "imageAccessToken": api_token,
            "videoAccessToken": "",
            "defaultModel": session["gatewayDefaultModel"],
            "imageModel": session["gatewayImageModel"],
            "videoDraftModel": session["gatewayVideoDraftModel"],
            "models": models,
            "classifiedModels": classified,
        })
        session["gateway"] = gateway

        phone_agent = session.get("phoneAgent") if isinstance(session.get("phoneAgent"), dict) else {}
        phone_agent.update({"baseUrl": api_base_url, "apiKey": api_token})
        session["phoneAgent"] = phone_agent

        lease.update({
            "tokenSource": token_meta.get("source"),
            "tokenId": token_meta.get("tokenId"),
            "tokenName": token_meta.get("tokenName") or "",
            "tokenKind": "launcher",
            "permissionMode": token_meta.get("permissionMode") or "",
            "modelLimitsEnabled": token_meta.get("modelLimitsEnabled"),
            "unlimitedQuota": token_meta.get("unlimitedQuota"),
            "tokenGroup": token_meta.get("tokenGroup") or "",
            "accountGroup": token_meta.get("group") or lease.get("accountGroup") or "",
            "tokenVerifiedAt": _iso(now),
        })
        session["lease"] = lease
        newapi.update({
            "baseUrl": base_url,
            "modelClasses": classified,
            "lastOnlineAt": _iso(now),
            "offline": False,
            "stale": False,
        })
        session["newApi"] = newapi
        session["updatedAt"] = _iso(now)
        self._write_session(session)
        if sync_runtime:
            self.sync_targets(session, targets=DEFAULT_RUNTIME_SYNC_TARGETS)
        return session

    def refresh_current(self) -> dict[str, Any]:
        session = self.current()
        if not session:
            raise NewApiAccountError("尚未登录模型账号")
        newapi = session.get("newApi") if isinstance(session.get("newApi"), dict) else {}
        base_url = self.normalize_base_url(newapi.get("baseUrl") or DEFAULT_BASE_URL)
        api_token = _pick_text(session.get("memberToken"))
        if not api_token:
            raise NewApiAccountError("本机会话缺少 API Token，请重新登录")

        opener = urllib.request.build_opener()
        headers = self._session_headers(session)
        try:
            self_payload = self._request_json(opener, f"{base_url}/api/user/self", headers=headers)
        except NewApiAccountError:
            self_payload = {}
        online = False
        try:
            models = self._fetch_models(opener, base_url, api_token, headers)
            online = bool(models)
        except NewApiAccountError:
            models = []
        if not models and isinstance(session.get("gatewayModels"), list):
            models = list(session.get("gatewayModels") or [])
        if not models:
            last_good = session.get("lastGoodModels") if isinstance(session.get("lastGoodModels"), dict) else {}
            if isinstance(last_good.get("models"), list):
                models = list(last_good.get("models") or [])
        lease = session.get("lease") if isinstance(session.get("lease"), dict) else {}
        if not _models_have_text(models) and lease.get("tokenSource") != "supplied":
            try:
                fresh_token = self._create_launcher_token(opener, base_url, headers)
                fresh_models = self._fetch_models(opener, base_url, fresh_token, headers)
                if _models_have_text(fresh_models):
                    api_token = fresh_token
                    models = fresh_models
                    online = True
                    session["memberToken"] = fresh_token
                    session["gatewayImageAccessToken"] = fresh_token
                    session["gatewayVideoAccessToken"] = ""
                    gateway_for_token = session.get("gateway") if isinstance(session.get("gateway"), dict) else {}
                    gateway_for_token["accessToken"] = fresh_token
                    gateway_for_token["imageAccessToken"] = fresh_token
                    gateway_for_token["videoAccessToken"] = ""
                    session["gateway"] = gateway_for_token
                    phone_agent_for_token = session.get("phoneAgent") if isinstance(session.get("phoneAgent"), dict) else {}
                    phone_agent_for_token["apiKey"] = fresh_token
                    session["phoneAgent"] = phone_agent_for_token
                    lease["tokenSource"] = "created_launcher_after_refresh_model_check"
                    session["lease"] = lease
            except NewApiAccountError as error:
                self.append_log(f"[Account] refresh launcher token model check failed: {_redact_secret_text(error)}\n")
        classified = _classify_models(models)
        now = _utc_now()
        session["gatewayModels"] = models
        session["gatewayDefaultModel"] = _choose_model(classified["text"], DEFAULT_TEXT_MODEL, models or [_pick_text(session.get("gatewayDefaultModel"))])
        session["gatewayImageModel"] = classified["image"][0] if classified["image"] else _pick_text(session.get("gatewayImageModel"))
        session["gatewayVideoDraftModel"] = classified["video"][0] if classified["video"] else _pick_text(
            session.get("gatewayVideoDraftModel"),
            session.get("gatewayVideoModel"),
        )
        session.pop("gatewayVideoModel", None)
        gateway = session.get("gateway") if isinstance(session.get("gateway"), dict) else {}
        gateway.update({
            "models": models,
            "classifiedModels": classified,
            "defaultModel": session["gatewayDefaultModel"],
            "imageModel": session["gatewayImageModel"],
            "videoDraftModel": session["gatewayVideoDraftModel"],
        })
        gateway.pop("videoModel", None)
        session["gateway"] = gateway
        if isinstance(self_payload, dict) and self_payload:
            self_data = _unwrap(self_payload)
            if isinstance(self_data, dict):
                session["usage"] = {
                    "quota": self_data.get("quota"),
                    "usedQuota": self_data.get("used_quota") or self_data.get("usedQuota"),
                    "requestCount": self_data.get("request_count") or self_data.get("requestCount"),
                }
                online = True
        if online:
            newapi.update({
                "lastOnlineAt": _iso(now),
                "graceExpiresAt": _iso(now + timedelta(days=SESSION_GRACE_DAYS)),
            })
            session["lastGoodModels"] = {
                "models": models,
                "classified": classified,
                "updatedAt": _iso(now),
            }
        else:
            newapi.update({
                "offline": True,
                "stale": True,
            })
        newapi.update({
            "baseUrl": base_url,
            "modelClasses": classified,
        })
        session["newApi"] = newapi
        session["updatedAt"] = _iso(now)
        self._write_session(session)
        self.sync_targets(session, targets=DEFAULT_RUNTIME_SYNC_TARGETS)
        return session

    def _write_session(self, session: dict[str, Any]) -> None:
        os.makedirs(os.path.dirname(self.session_path), exist_ok=True)
        write_json(self.session_path, self._protected_session(session))

    def current(self) -> dict[str, Any] | None:
        session = read_json(self.session_path, None)
        if isinstance(session, dict) and session.get("source") == ACCOUNT_SOURCE:
            current = self._unprotected_session(session)
            urls_migrated = _migrate_managed_session_urls(current)
            migration_version = int(current.get("managedGatewayMigrationVersion") or 0)
            if urls_migrated or migration_version < MANAGED_GATEWAY_MIGRATION_VERSION:
                try:
                    results = self.sync_targets(current, targets=DEFAULT_RUNTIME_SYNC_TARGETS)
                    if all(not isinstance(item, dict) or item.get("ok") is not False for item in results):
                        current["managedGatewayMigrationVersion"] = MANAGED_GATEWAY_MIGRATION_VERSION
                    else:
                        self.append_log("[Account] accelerated gateway migration has pending local targets.\n")
                except Exception as error:
                    self.append_log(f"[Account] accelerated gateway migration sync failed: {_redact_secret_text(error)}\n")
                self._write_session(current)
            return current
        return None

    def _protected_session(self, session: dict[str, Any]) -> dict[str, Any]:
        return self._transform_session_secrets(session, protect_secret)

    def _unprotected_session(self, session: dict[str, Any]) -> dict[str, Any]:
        return self._transform_session_secrets(session, unprotect_secret)

    @staticmethod
    def _transform_session_secrets(session: dict[str, Any], transform) -> dict[str, Any]:
        result = copy.deepcopy(session)
        for path in SESSION_SECRET_PATHS:
            current: Any = result
            for key in path[:-1]:
                if not isinstance(current, dict):
                    current = None
                    break
                current = current.get(key)
            if not isinstance(current, dict):
                continue
            leaf = path[-1]
            if leaf in current and current.get(leaf):
                current[leaf] = transform(current.get(leaf))
        return result

    def public_session(self) -> dict[str, Any]:
        session = self.current()
        if not session:
            return {
                "loggedIn": False,
                "source": "",
                "account": "",
                "tokenMasked": "",
                "models": {"text": [], "image": [], "video": []},
                "selectedModels": {"text": "", "image": "", "videoDraft": ""},
                "usage": {},
                "lastSyncResults": [],
            }
        newapi = session.get("newApi") if isinstance(session.get("newApi"), dict) else {}
        gateway = session.get("gateway") if isinstance(session.get("gateway"), dict) else {}
        classes = gateway.get("classifiedModels") if isinstance(gateway.get("classifiedModels"), dict) else newapi.get("modelClasses")
        if not isinstance(classes, dict):
            classes = _classify_models(session.get("gatewayModels") if isinstance(session.get("gatewayModels"), list) else [])
        text_models = _text_models_with_default(
            classes,
            selected=_pick_text(session.get("gatewayDefaultModel"), gateway.get("defaultModel")),
        )
        selected_text_model = _choose_model(text_models, _pick_text(session.get("gatewayDefaultModel"), gateway.get("defaultModel")), [])
        subscription = _extract_subscription_snapshot(
            {},
            base_url=_pick_text(newapi.get("baseUrl"), DEFAULT_BASE_URL),
            fallback={
                "plan": session.get("plan"),
                "expiresAt": session.get("expiresAt") or session.get("leaseExpiresAt"),
                "usage": session.get("usage") if isinstance(session.get("usage"), dict) else {},
                "leaseExpiresAt": session.get("leaseExpiresAt"),
            },
        )
        return {
            "loggedIn": True,
            "source": ACCOUNT_SOURCE,
            "account": _pick_text(newapi.get("account"), session.get("memberName")),
            "memberId": _pick_text(session.get("memberId")),
            "plan": _pick_text(session.get("plan"), "default"),
            "status": _pick_text(session.get("status"), "active"),
            "baseUrl": _pick_text(newapi.get("baseUrl"), DEFAULT_BASE_URL),
            "gatewayBaseUrl": _pick_text(session.get("gatewayBaseUrl")),
            "tokenMasked": _mask_secret(session.get("memberToken")),
            "models": {
                "text": text_models,
                "phone": classes.get("phone") if isinstance(classes.get("phone"), list) else [],
                "image": classes.get("image") if isinstance(classes.get("image"), list) else [],
                "video": classes.get("video") if isinstance(classes.get("video"), list) else [],
            },
            "selectedModels": {
                "text": selected_text_model,
                "phone": _pick_text(
                    (session.get("phoneAgent") or {}).get("model")
                    if isinstance(session.get("phoneAgent"), dict)
                    else "",
                    DEFAULT_PHONE_MODEL,
                ),
                "image": _pick_text(session.get("gatewayImageModel"), gateway.get("imageModel")),
                "videoDraft": _pick_text(
                    session.get("gatewayVideoDraftModel"),
                    gateway.get("videoDraftModel"),
                    session.get("gatewayVideoModel"),
                    gateway.get("videoModel"),
                ),
            },
            "usage": session.get("usage") if isinstance(session.get("usage"), dict) else {},
            "subscription": subscription,
            "purchaseUrl": subscription.get("purchaseUrl"),
            "lastOnlineAt": _pick_text(newapi.get("lastOnlineAt")),
            "graceExpiresAt": _pick_text(newapi.get("graceExpiresAt"), session.get("leaseExpiresAt")),
            "offline": bool(newapi.get("offline")),
            "stale": bool(newapi.get("stale")),
            "lastSyncResults": session.get("lastSyncResults") if isinstance(session.get("lastSyncResults"), list) else [],
        }

    def select_models(
        self,
        *,
        text_model: str = "",
        phone_model: str = "",
        image_model: str = "",
        video_model: str = "",
    ) -> dict[str, Any]:
        session = self.current()
        if not session:
            raise NewApiAccountError("尚未登录模型账号")
        classes = self._session_model_classes(session)
        text_model = text_model.strip()
        phone_model = phone_model.strip()
        image_model = image_model.strip()
        video_model = video_model.strip()
        if text_model:
            self._ensure_model_choice(text_model, classes.get("text", []), "文本模型")
            session["gatewayDefaultModel"] = text_model
        if image_model:
            self._ensure_model_choice(image_model, classes.get("image", []), "图像模型")
            session["gatewayImageModel"] = image_model
        if video_model:
            self._ensure_model_choice(video_model, classes.get("video", []), "视频模型")
            session["gatewayVideoDraftModel"] = video_model
        if phone_model:
            self._ensure_model_choice(phone_model, classes.get("phone", []), "手机模型")
            phone_agent = session.get("phoneAgent") if isinstance(session.get("phoneAgent"), dict) else {}
            phone_agent["model"] = phone_model
            session["phoneAgent"] = phone_agent
        gateway = session.get("gateway") if isinstance(session.get("gateway"), dict) else {}
        if text_model:
            gateway["defaultModel"] = text_model
        if image_model:
            gateway["imageModel"] = image_model
        if video_model:
            gateway["videoDraftModel"] = video_model
        session.pop("gatewayVideoModel", None)
        gateway.pop("videoModel", None)
        session["gateway"] = gateway
        session["updatedAt"] = _iso(_utc_now())
        self._write_session(session)
        self.sync_targets(session, targets=DEFAULT_RUNTIME_SYNC_TARGETS)
        return self.public_session()

    @staticmethod
    def _ensure_model_choice(model: str, candidates: list[str], label: str) -> None:
        if model not in candidates:
            raise NewApiAccountError(f"{label}不在当前账号可用列表中")

    def _session_model_classes(self, session: dict[str, Any]) -> dict[str, list[str]]:
        newapi = session.get("newApi") if isinstance(session.get("newApi"), dict) else {}
        gateway = session.get("gateway") if isinstance(session.get("gateway"), dict) else {}
        classes = gateway.get("classifiedModels") if isinstance(gateway.get("classifiedModels"), dict) else newapi.get("modelClasses")
        if not isinstance(classes, dict):
            classes = _classify_models(session.get("gatewayModels") if isinstance(session.get("gatewayModels"), list) else [])
        text_models = _text_models_with_default(
            classes,
            selected=_pick_text(session.get("gatewayDefaultModel"), gateway.get("defaultModel")),
        )
        return {
            "text": text_models,
            "phone": classes.get("phone") if isinstance(classes.get("phone"), list) else [],
            "image": classes.get("image") if isinstance(classes.get("image"), list) else [],
            "video": classes.get("video") if isinstance(classes.get("video"), list) else [],
        }

    def _sync_image_config(self, session: dict[str, Any]) -> None:
        image_model = _pick_text(session.get("gatewayImageModel"))
        if not image_model:
            return
        current = read_json(self.paths.image_config, {})
        if not isinstance(current, dict):
            current = {}
        if current.get("lockedByUser") is True:
            return
        current.update({
            "gatewayMode": "member",
            "managedBy": ACCOUNT_SOURCE,
            "baseUrl": session.get("gatewayImageBaseUrl") or session.get("gatewayBaseUrl"),
            "apiKey": session.get("gatewayImageAccessToken") or session.get("memberToken"),
            "model": image_model,
        })
        write_json(self.paths.image_config, current)

    def _sync_video_config(self, session: dict[str, Any]) -> None:
        self._clear_managed_video_config()

    def _clear_managed_video_config(self) -> None:
        for path in (self.paths.video_config, self.paths.videoapi_config):
            current = read_json(path, {})
            if not isinstance(current, dict) or current.get("lockedByUser") is True:
                continue
            if current.get("managedBy") in MANAGED_ACCOUNT_SOURCES or current.get("gatewayMode") == "member":
                write_json(path, {})

    def _sync_openclaw_models(self) -> None:
        sync_openclaw_models(self.paths, self.license_mgr.current_gateway_profile())

    def _sync_desktop_agent_config(self, session: dict[str, Any]) -> None:
        model = _pick_text(session.get("gatewayDefaultModel"))
        base_url = _pick_text(session.get("gatewayBaseUrl"), DEFAULT_API_BASE)
        api_key = _pick_text(session.get("memberToken"))
        path = os.path.join(self.paths.launcher_dir, "desktop-agent.json")
        current = read_json(path, {})
        if not isinstance(current, dict):
            current = {}
        provider = {
            "managedBy": ACCOUNT_SOURCE,
            "apiKey": api_key,
            "baseUrl": base_url,
            "baseURL": base_url,
            "model": model,
        }
        current.setdefault("provider", {})
        current.setdefault("llm", {})
        current.setdefault("chatProvider", {})
        current["chatProvider"].setdefault("config", {})
        current["provider"].update(provider)
        current["llm"].update(provider)
        current["chatProvider"]["config"].update(provider)
        write_json(path, current)

    def _sync_phone_agent_config(self, session: dict[str, Any]) -> None:
        phone_agent = session.get("phoneAgent") if isinstance(session.get("phoneAgent"), dict) else {}
        base_url = _pick_text(phone_agent.get("baseUrl"), session.get("gatewayBaseUrl"), DEFAULT_API_BASE)
        api_key = _pick_text(phone_agent.get("apiKey"), session.get("memberToken"))
        model = _pick_text(phone_agent.get("model"), DEFAULT_PHONE_MODEL)
        path = os.path.join(self.paths.launcher_dir, "phone-agent.json")
        current = read_json(path, {})
        if not isinstance(current, dict):
            current = {}
        current.setdefault("llm", {})
        current["llm"].update({
            "managedBy": ACCOUNT_SOURCE,
            "baseUrl": base_url,
            "apiKey": api_key,
            "model": model,
        })
        write_json(path, current)

    def sync_targets(self, session: dict[str, Any] | None = None, *, targets: tuple[str, ...] = DEFAULT_RUNTIME_SYNC_TARGETS) -> list[dict[str, Any]]:
        session = session or self.current()
        if not session:
            raise NewApiAccountError("not_logged_in")
        result = WireService(self.paths, self.append_log).sync_from_session(session, targets=targets)
        results = result["syncResults"] if isinstance(result.get("syncResults"), list) else []
        session["lastSyncResults"] = results
        if isinstance(session, dict) and session.get("source") == ACCOUNT_SOURCE:
            self._write_session(session)
        return results

    def logout(self) -> bool:
        session = self.current()
        if not session:
            return False
        try:
            os.remove(self.session_path)
        except FileNotFoundError:
            pass
        self._clear_synced_configs()
        return True

    def _clear_synced_configs(self) -> None:
        profiles = read_json(self.paths.auth_profiles, {"models": {"providers": {}}})
        if isinstance(profiles, dict):
            models = profiles.get("models") if isinstance(profiles.get("models"), dict) else {}
            providers = models.get("providers") if isinstance(models.get("providers"), dict) else {}
            if isinstance(providers, dict):
                for provider_id, provider in list(providers.items()):
                    if isinstance(provider, dict) and provider.get("managedBy") in MANAGED_ACCOUNT_SOURCES:
                        providers.pop(provider_id, None)
                if models.get("primary") not in providers:
                    models["primary"] = next(iter(providers), "")
                    write_json(self.paths.auth_profiles, profiles)

        for path in (self.paths.image_config, self.paths.video_config, os.path.join(self.paths.base_path, "videoapi_config.json")):
            data = read_json(path, {})
            if isinstance(data, dict) and data.get("managedBy") in MANAGED_ACCOUNT_SOURCES:
                write_json(path, {})

        wire = read_json(self.paths.wire_current, {})
        if isinstance(wire, dict) and wire.get("managedBy") in MANAGED_ACCOUNT_SOURCES:
            write_json(self.paths.wire_current, {})
            clear_agent_user_env_keys(self.paths)

        self._clear_managed_launcher_config(os.path.join(self.paths.launcher_dir, "phone-agent.json"))
        self._clear_managed_launcher_config(os.path.join(self.paths.launcher_dir, "desktop-agent.json"))

    def _clear_managed_launcher_config(self, path: str) -> None:
        data = read_json(path, {})
        if not isinstance(data, dict):
            return

        changed = False
        for key in ("provider", "llm", "chatProvider"):
            value = data.get(key)
            if not isinstance(value, dict):
                continue
            if key == "chatProvider":
                config = value.get("config") if isinstance(value.get("config"), dict) else {}
                if config.get("managedBy") in MANAGED_ACCOUNT_SOURCES:
                    value["config"] = {}
                    changed = True
            elif value.get("managedBy") in MANAGED_ACCOUNT_SOURCES:
                data[key] = {}
                changed = True

        if data.get("managedBy") in MANAGED_ACCOUNT_SOURCES:
            data = {}
            changed = True

        if changed:
            write_json(path, data)
