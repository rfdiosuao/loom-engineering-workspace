"""Read and validate immutable OEM runtime identity."""

from __future__ import annotations

import json
import os
import re
from typing import Any
from urllib.parse import urlparse

from core.paths import AppPaths


_BRAND_ID_RE = re.compile(r"^[a-z][a-z0-9-]{2,39}$")
_EXPECTED_KEYS = {
    "schemaVersion",
    "brandId",
    "licenseServer",
    "purchaseFallback",
    "supportFallback",
}


def _https_url(value: Any, field: str) -> str:
    text = str(value or "").strip()
    parsed = urlparse(text)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError(f"OEM runtime {field} must be an absolute HTTPS URL without credentials")
    if len(text) > 2048:
        raise ValueError(f"OEM runtime {field} must not exceed 2048 characters")
    return text


def load_oem_brand_config(paths: AppPaths) -> dict[str, Any] | None:
    """Load only the build-bundled config; writable data must never override identity."""
    path = os.path.join(paths.base_path, "_up_", "data", "oem-brand.json")
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8-sig") as handle:
            value = json.load(handle)
    except (OSError, ValueError) as error:
        raise ValueError(f"OEM runtime config is invalid: {error}") from error
    if not isinstance(value, dict):
        raise ValueError("OEM runtime config root must be an object")
    if set(value) != _EXPECTED_KEYS:
        raise ValueError("OEM runtime config must contain exactly the approved public fields")
    if value.get("schemaVersion") != 1:
        raise ValueError("OEM runtime schemaVersion must be 1")
    brand_id = str(value.get("brandId") or "").strip()
    if not _BRAND_ID_RE.fullmatch(brand_id):
        raise ValueError("OEM runtime brandId must be a lowercase slug")
    return {
        "schemaVersion": 1,
        "brandId": brand_id,
        "licenseServer": _https_url(value.get("licenseServer"), "licenseServer").rstrip("/"),
        "purchaseFallback": _https_url(value.get("purchaseFallback"), "purchaseFallback"),
        "supportFallback": _https_url(value.get("supportFallback"), "supportFallback"),
    }


def bundled_fallback(config: dict[str, Any] | None) -> dict[str, Any]:
    if not config:
        return {}
    return {
        "brandId": config["brandId"],
        "purchaseUrl": config["purchaseFallback"],
        "supportUrl": config["supportFallback"],
        "source": "bundled-fallback",
    }


__all__ = ["bundled_fallback", "load_oem_brand_config"]
