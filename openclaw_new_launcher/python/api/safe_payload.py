"""Public response sanitizers for launcher API routes."""

from __future__ import annotations

import re
from typing import Any


SECRET_TEXT_PATTERNS = (
    re.compile(r"(?i)\b(api[_-]?key|access[_-]?token|session[_-]?cookie|password|secret|token)(\s*[:=]\s*)([^\s,;]+)"),
    re.compile(r"(?i)\b(bearer\s+)([a-z0-9._~+/=-]{8,})"),
    re.compile(r"\b(sk-[A-Za-z0-9._-]+|sess-[A-Za-z0-9._-]+|eyJ[A-Za-z0-9._=-]+)"),
)

SECRET_KEY_NAMES = {
    "apikey",
    "api_key",
    "accesskey",
    "access_key",
    "accesstoken",
    "access_token",
    "authorization",
    "bearer",
    "cookie",
    "gatewayaccesstoken",
    "gateway_access_token",
    "gatewayimageaccesstoken",
    "gateway_image_access_token",
    "gatewayvideoaccesstoken",
    "gateway_video_access_token",
    "gatewaytoken",
    "gateway_token",
    "imageapikey",
    "image_api_key",
    "launchersecret",
    "launcher_secret",
    "launchertoken",
    "launcher_token",
    "membertoken",
    "member_token",
    "password",
    "secret",
    "sessioncookie",
    "session_cookie",
    "token",
    "videoapikey",
    "video_api_key",
}


def mask_secret(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) <= 8:
        return "****"
    return f"{text[:4]}****{text[-4:]}"


def redact_secret_text(value: Any) -> str:
    text = str(value or "")
    for pattern in SECRET_TEXT_PATTERNS:
        if pattern.groups >= 3:
            text = pattern.sub(lambda match: f"{match.group(1)}{match.group(2)}[redacted]", text)
        elif pattern.groups == 2:
            text = pattern.sub(lambda match: f"{match.group(1)}[redacted]", text)
        else:
            text = pattern.sub("[redacted]", text)
    return text


def public_safe_payload(value: Any) -> Any:
    if isinstance(value, dict):
        payload: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if _is_secret_key(key_text):
                masked = mask_secret(item)
                if masked:
                    payload[f"{key_text}Masked"] = masked
                continue
            payload[key_text] = public_safe_payload(item)
        return payload
    if isinstance(value, list):
        return [public_safe_payload(item) for item in value]
    if isinstance(value, str):
        return redact_secret_text(value)
    return value


def _is_secret_key(key: str) -> bool:
    normalized = key.replace("-", "_").lower()
    compact = normalized.replace("_", "")
    if normalized.endswith("masked") or compact.endswith("masked"):
        return False
    if normalized in SECRET_KEY_NAMES or compact in SECRET_KEY_NAMES:
        return True
    return (
        normalized.endswith("_token")
        or compact.endswith("token")
        or normalized.endswith("_secret")
        or compact.endswith("secret")
        or normalized.endswith("_api_key")
        or compact.endswith("apikey")
        or "password" in normalized
        or "session_cookie" in normalized
    )
