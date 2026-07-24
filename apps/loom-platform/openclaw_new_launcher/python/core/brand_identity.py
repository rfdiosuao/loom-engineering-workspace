"""Runtime brand identity loaded from the packaged OEM profile."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.storage import read_json


@dataclass(frozen=True)
class BrandIdentity:
    display_name: str = "麓鸣"
    native_agent_name: str = "麓鸣原生智能体"


def load_brand_identity(paths: Any) -> BrandIdentity:
    profile_path = str(getattr(paths, "brand_profile", "") or "").strip()
    payload = read_json(profile_path, {}) if profile_path else {}
    if not isinstance(payload, dict):
        payload = {}
    display_name = str(payload.get("displayName") or "").strip() or "麓鸣"
    native_agent_name = (
        str(payload.get("nativeAgentName") or "").strip()
        or f"{display_name}原生智能体"
    )
    return BrandIdentity(
        display_name=display_name[:120],
        native_agent_name=native_agent_name[:160],
    )
