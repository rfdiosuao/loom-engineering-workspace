"""Sync member gateway model profiles into OpenClaw-compatible config files."""

from __future__ import annotations

import os
import re
from typing import Any
from urllib.parse import urlparse

from core.paths import AppPaths
from core.storage import read_json, write_json


DEFAULT_OPENCLAW_TEXT_MODEL = "glm-5.2-coding"
PHONE_MODEL_IDS = {"agnes-2.0-flash"}
MANAGED_ACCOUNT_SOURCES = {"newapi_account", "heang_account"}


def sync_openclaw_models(paths: AppPaths, gateway_profile: dict[str, Any] | None) -> bool:
    if isinstance(gateway_profile, dict) and gateway_profile:
        return sync_openclaw_models_from_gateway_profile(paths, gateway_profile)
    return sync_openclaw_models_from_auth_profiles(paths)


def sync_openclaw_models_from_gateway_profile(paths: AppPaths, gateway_profile: dict[str, Any]) -> bool:
    base_url = str(gateway_profile.get("baseUrl") or "").strip().rstrip("/")
    api_key = str(gateway_profile.get("apiKey") or "").strip()
    default_model = str(gateway_profile.get("defaultModel") or "").strip()
    model_ids = _text_model_ids(gateway_profile.get("models") or [], default_model)
    if not base_url or not api_key or not model_ids:
        return False

    provider_id = _provider_id_from_base_url(base_url, "member")
    primary_model = default_model or model_ids[0]
    if primary_model not in model_ids:
        primary_model = model_ids[0]
    managed_by = str(gateway_profile.get("source") or gateway_profile.get("managedBy") or "").strip()
    model_ref = f"{provider_id}/{primary_model}"
    provider_config = {
        "baseUrl": base_url,
        "apiKey": api_key,
        "api": "openai-completions",
        "models": [_model_definition(model_id) for model_id in model_ids],
    }
    _write_openclaw_model_files(paths, provider_id, provider_config, model_ref, primary_model)
    profiles = read_json(paths.auth_profiles, {"models": {"providers": {}}})
    if not isinstance(profiles, dict):
        profiles = {"models": {"providers": {}}}
    profiles.setdefault("models", {})
    profiles["models"].setdefault("providers", {})
    profile_key = str(gateway_profile.get("profileKey") or "member_gateway").strip() or "member_gateway"
    provider_name = str(gateway_profile.get("name") or "").strip() or ("Member Gateway" if profile_key == "member_gateway" else "Custom Provider")
    auth_mode = str(gateway_profile.get("authMode") or "").strip() or ("member" if managed_by in MANAGED_ACCOUNT_SOURCES else "custom")
    profiles["models"]["providers"][profile_key] = {
        "id": profile_key,
        "name": provider_name,
        "authMode": auth_mode,
        "mode": auth_mode,
        "providerId": provider_id,
        "baseUrl": base_url,
        "apiKey": api_key,
        "api": "openai-completions",
        "models": model_ids,
        "defaultModel": primary_model,
        "gatewayDefaultModel": primary_model,
        "gatewayImageModel": str(gateway_profile.get("imageModel") or "").strip(),
    }
    if managed_by:
        profiles["models"]["providers"][profile_key]["managedBy"] = managed_by
    profiles["models"]["primary"] = profile_key
    write_json(paths.auth_profiles, profiles)
    return True


def sync_openclaw_models_from_auth_profiles(paths: AppPaths) -> bool:
    profiles = read_json(paths.auth_profiles, {"models": {"providers": {}}})
    profile_models = profiles.get("models") if isinstance(profiles, dict) else {}
    providers = profile_models.get("providers") if isinstance(profile_models, dict) else {}
    if not isinstance(providers, dict) or not providers:
        return False

    primary_key = profile_models.get("primary") if isinstance(profile_models, dict) else None
    provider = providers.get(primary_key) if primary_key else None
    if not isinstance(provider, dict):
        provider = next((item for item in providers.values() if isinstance(item, dict)), None)
    if not provider:
        return False

    api_key = str(provider.get("apiKey") or "").strip()
    base_url = str(provider.get("baseUrl") or provider.get("url") or "").strip().rstrip("/")
    if not api_key or not base_url:
        return False

    raw_models = provider.get("models") if isinstance(provider.get("models"), list) else []
    model_ids = _text_model_ids(raw_models, str(provider.get("defaultModel") or "").strip())
    if not model_ids:
        return False

    provider_id = _provider_id_from_base_url(base_url, str(primary_key or "api"))
    provider_config = {
        "baseUrl": base_url,
        "apiKey": api_key,
        "api": "openai-completions",
        "models": [_model_definition(model_id) for model_id in model_ids],
    }
    _write_openclaw_model_files(paths, provider_id, provider_config, f"{provider_id}/{model_ids[0]}", model_ids[0])
    return True


def _write_openclaw_model_files(
    paths: AppPaths,
    provider_id: str,
    provider_config: dict[str, Any],
    model_ref: str,
    primary_model: str,
) -> None:
    agent_dir = os.path.dirname(paths.auth_profiles)
    models_path = os.path.join(agent_dir, "models.json")
    models_json = read_json(models_path, {"providers": {}})
    if not isinstance(models_json, dict):
        models_json = {"providers": {}}
    models_json.setdefault("providers", {})
    models_json["providers"][provider_id] = provider_config
    write_json(models_path, models_json)

    openclaw_config = read_json(paths.openclaw_config, {})
    if not isinstance(openclaw_config, dict):
        openclaw_config = {}
    openclaw_config.setdefault("models", {})
    openclaw_config["models"]["mode"] = "merge"
    openclaw_config["models"].setdefault("providers", {})
    openclaw_config["models"]["providers"][provider_id] = provider_config

    openclaw_config.setdefault("agents", {})
    openclaw_config["agents"].setdefault("defaults", {})
    defaults = openclaw_config["agents"]["defaults"]
    defaults.setdefault("model", {})
    defaults["model"]["primary"] = model_ref
    defaults.setdefault("models", {})
    for model in provider_config.get("models", []):
        model_id = str(model.get("id") if isinstance(model, dict) else "").strip()
        if model_id:
            defaults["models"][f"{provider_id}/{model_id}"] = {"alias": model_id}
    defaults["models"][model_ref] = {"alias": primary_model}
    write_json(paths.openclaw_config, openclaw_config)


def _provider_id_from_base_url(base_url: str, fallback: str) -> str:
    parsed = urlparse(base_url if "://" in base_url else f"https://{base_url}")
    host = parsed.netloc or parsed.path or fallback
    host = host.split("@")[-1].split(":")[0].lower()
    slug = re.sub(r"[^a-z0-9]+", "-", host).strip("-") or fallback
    return f"custom-{slug}"


def _model_definition(model_id: str) -> dict[str, Any]:
    is_reasoning = model_id.startswith(("claude", "o1", "o3", "o4", "deepseek-reasoner"))
    context_window = 200000 if model_id.startswith("claude") else 128000
    if model_id.startswith("qwen3"):
        context_window = 200000
    context_tokens = 160000 if context_window >= 200000 else 96000
    return {
        "id": model_id,
        "name": f"{model_id} (Custom Provider)",
        "reasoning": is_reasoning,
        "input": ["text"],
        "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
        "contextWindow": context_window,
        "contextTokens": context_tokens,
        "maxTokens": 32000,
        "api": "openai-completions",
    }


def _looks_like_non_text_model(model_id: str) -> bool:
    text = model_id.lower()
    if text in PHONE_MODEL_IDS:
        return True
    markers = (
        "image",
        "dall-e",
        "gpt-image",
        "flux",
        "midjourney",
        "mj-",
        "stable-diffusion",
        "sd-",
        "imagen",
        "seedream",
        "video",
        "veo",
        "sora",
        "seedance",
        "kling",
        "wan",
        "hailuo",
        "runway",
        "pika",
        "luma",
        "happyhorse",
    )
    return any(marker in text for marker in markers)


def _text_model_ids(raw_models: list[Any], default_model: str = "") -> list[str]:
    model_ids: list[str] = []
    for item in raw_models:
        model_id = item.get("id") if isinstance(item, dict) else item
        if isinstance(model_id, str):
            model_id = model_id.strip()
            if model_id and not _looks_like_non_text_model(model_id) and model_id not in model_ids:
                model_ids.append(model_id)
    default_model = default_model.strip()
    if default_model and not _looks_like_non_text_model(default_model):
        model_ids = [default_model] + [model_id for model_id in model_ids if model_id != default_model]
    if model_ids and default_model and not _looks_like_non_text_model(default_model):
        return model_ids
    if DEFAULT_OPENCLAW_TEXT_MODEL in model_ids:
        model_ids = [DEFAULT_OPENCLAW_TEXT_MODEL] + [model_id for model_id in model_ids if model_id != DEFAULT_OPENCLAW_TEXT_MODEL]
    return model_ids
