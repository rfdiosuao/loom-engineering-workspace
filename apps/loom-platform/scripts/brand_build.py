"""Compile a LOOM OEM brand pack into deterministic build inputs.

This module deliberately does not invoke compilers or read signing material.
It validates public brand metadata and emits the inputs consumed by the
PowerShell build orchestrator.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


PLATFORM_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER_ROOT = PLATFORM_ROOT / "openclaw_new_launcher"
DEFAULT_THEME_PATH = LAUNCHER_ROOT / "data" / "themes" / "default" / "theme.json"

VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)
SLUG_RE = re.compile(r"^[a-z][a-z0-9-]{2,63}$")
BRAND_ID_RE = re.compile(r"^[a-z][a-z0-9-]{2,39}$")
REVERSE_DNS_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*(?:\.[A-Za-z][A-Za-z0-9_-]*)+$")
BINARY_RE = re.compile(r'^[^\\/:*?"<>|]+\.exe$', re.IGNORECASE)
SECRET_KEY_RE = re.compile(
    r"(?:^|[_-])(?:api[_-]?key|private[_-]?key|secret|token|password|credential|"
    r"certificate|keystore|signing[_-]?key)(?:$|[_-])",
    re.IGNORECASE,
)
PLACEHOLDER_HOST_MARKERS = (
    ".invalid",
    ".example",
    ".test",
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "::1",
)
REQUIRED_TOP_LEVEL = {
    "schemaVersion",
    "brandId",
    "status",
    "product",
    "positioning",
    "desktop",
    "phone",
    "urls",
    "release",
    "assets",
}
REQUIRED_COPY = {"homeTitle", "taskPlaceholder", "supportLabel"}
REQUIRED_MODULES = {"enabled", "locked", "hidden"}


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError(f"required JSON file is missing: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as error:
        raise ValueError(f"invalid JSON file {path}: {error}") from error
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _require_string(container: dict[str, Any], key: str, context: str) -> str:
    value = container.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context}.{key} must be a non-empty string")
    return value.strip()


def _require_string_list(container: dict[str, Any], key: str, context: str) -> list[str]:
    value = container.get(key)
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"{context}.{key} must be a string array")
    normalized = [item.strip() for item in value]
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{context}.{key} contains duplicate values")
    return normalized


def _reject_secret_fields(value: Any, path: str = "brand") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            normalized = re.sub(r"(?<!^)(?=[A-Z])", "_", key_text).lower()
            if SECRET_KEY_RE.search(normalized):
                raise ValueError(f"sensitive or secret field is forbidden in a brand pack: {path}.{key_text}")
            _reject_secret_fields(child, f"{path}.{key_text}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_secret_fields(child, f"{path}[{index}]")


def _safe_asset_path(brand_root: Path, value: str, name: str) -> Path:
    candidate = Path(value)
    if candidate.is_absolute() or candidate.drive:
        raise ValueError(f"asset path must be relative: assets.{name}")
    resolved = (brand_root / candidate).resolve()
    try:
        resolved.relative_to(brand_root)
    except ValueError as error:
        raise ValueError(f"asset path escapes the brand directory: assets.{name}") from error
    if not resolved.is_file():
        raise ValueError(f"asset file does not exist: assets.{name} -> {value}")
    return resolved


def _validate_https_url(value: str, context: str, release_ready: bool) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError(f"{context} must use an absolute HTTPS URL")
    host = parsed.hostname.lower()
    if release_ready and any(marker in host for marker in PLACEHOLDER_HOST_MARKERS):
        raise ValueError(f"{context} uses a placeholder or local domain: {host}")
    return value


def _validate_brand(
    brand_root: Path,
    brand: dict[str, Any],
    copy: dict[str, Any],
    modules: dict[str, Any],
    *,
    release_ready: bool,
) -> dict[str, Path]:
    _reject_secret_fields(brand)
    missing = sorted(REQUIRED_TOP_LEVEL - set(brand))
    if missing:
        raise ValueError(f"brand.json is missing required fields: {', '.join(missing)}")
    if brand.get("schemaVersion") != 1:
        raise ValueError("brand.schemaVersion must be 1")

    brand_id = _require_string(brand, "brandId", "brand")
    if not BRAND_ID_RE.fullmatch(brand_id):
        raise ValueError("brand.brandId must be a lowercase slug")
    status = _require_string(brand, "status", "brand")
    if status not in {"demo", "active", "suspended"}:
        raise ValueError("brand.status must be demo, active, or suspended")
    if release_ready and status != "active":
        raise ValueError("release builds require brand.status=active")

    for section, required in {
        "product": ("displayName", "shortName", "publisher"),
        "positioning": ("category", "promise"),
        "desktop": ("productName", "binaryName", "identifier", "windowTitle"),
        "phone": ("appName", "applicationId"),
        "urls": ("website", "apiBase", "docs", "support", "manifest"),
        "release": ("channel", "filePrefix", "updateChannelId"),
    }.items():
        value = brand.get(section)
        if not isinstance(value, dict):
            raise ValueError(f"brand.{section} must be an object")
        for key in required:
            _require_string(value, key, f"brand.{section}")

    desktop = brand["desktop"]
    if not BINARY_RE.fullmatch(desktop["binaryName"]):
        raise ValueError("brand.desktop.binaryName must be a safe .exe filename")
    if not REVERSE_DNS_RE.fullmatch(desktop["identifier"]):
        raise ValueError("brand.desktop.identifier must use reverse-DNS notation")
    phone = brand["phone"]
    if not REVERSE_DNS_RE.fullmatch(phone["applicationId"]):
        raise ValueError("brand.phone.applicationId must use reverse-DNS notation")

    release = brand["release"]
    if release["channel"] not in {"stable", "rc", "internal"}:
        raise ValueError("brand.release.channel must be stable, rc, or internal")
    for key in ("filePrefix", "updateChannelId"):
        if not SLUG_RE.fullmatch(release[key]):
            raise ValueError(f"brand.release.{key} must be a lowercase release slug")

    urls = brand["urls"]
    for key, value in urls.items():
        _validate_https_url(str(value), f"brand.urls.{key}", release_ready)

    missing_copy = sorted(REQUIRED_COPY - set(copy))
    if missing_copy:
        raise ValueError(f"copy.json is missing required fields: {', '.join(missing_copy)}")
    for key in REQUIRED_COPY:
        _require_string(copy, key, "copy")

    missing_modules = sorted(REQUIRED_MODULES - set(modules))
    if missing_modules:
        raise ValueError(f"modules.json is missing required fields: {', '.join(missing_modules)}")
    enabled = _require_string_list(modules, "enabled", "modules")
    locked = _require_string_list(modules, "locked", "modules")
    hidden = _require_string_list(modules, "hidden", "modules")
    conflicts = (set(enabled) & set(hidden)) | (set(enabled) & set(locked)) | (set(locked) & set(hidden))
    if conflicts:
        raise ValueError(f"modules contain conflicting assignments: {', '.join(sorted(conflicts))}")

    assets = brand["assets"]
    if not isinstance(assets, dict) or not assets:
        raise ValueError("brand.assets must be a non-empty object")
    if "logo" not in assets:
        raise ValueError("brand.assets.logo is required")
    resolved_assets: dict[str, Path] = {}
    for name, relative in assets.items():
        if not isinstance(relative, str) or not relative.strip():
            raise ValueError(f"brand.assets.{name} must be a non-empty relative path")
        resolved_assets[str(name)] = _safe_asset_path(brand_root, relative.strip(), str(name))
    return resolved_assets


def _filtered_nav_items(theme: dict[str, Any], hidden_modules: list[str]) -> list[dict[str, Any]]:
    hidden = set(hidden_modules)
    aliases = {
        "agent-orchestration": {"agent", "agents", "agentAccess"},
        "phone-matrix": {"phone", "workbench", "acquisition"},
        "media-creation": {"creative"},
        "model-accounts": {"license"},
        "diagnostics": {"diagnostics", "terminal"},
    }
    hidden_features = set(hidden)
    for module_id in hidden:
        hidden_features.update(aliases.get(module_id, set()))
    items = theme.get("navItems")
    if not isinstance(items, list):
        return []
    return [
        item
        for item in items
        if isinstance(item, dict) and str(item.get("key") or "") not in hidden_features
    ]


def compile_brand_pack(
    *,
    brand_path: str,
    output_path: str,
    version: str,
    core_commit: str,
    factory_commit: str,
    release_ready: bool = True,
) -> dict[str, Any]:
    brand_root = Path(brand_path).resolve()
    output_root = Path(output_path).resolve()
    if not brand_root.is_dir():
        raise ValueError(f"brand directory does not exist: {brand_root}")
    if not VERSION_RE.fullmatch(str(version).strip()):
        raise ValueError(f"version must use MAJOR.MINOR.PATCH format: {version}")
    if not COMMIT_RE.fullmatch(str(core_commit).strip()):
        raise ValueError("core_commit must be a full 40-character Git SHA")
    if not COMMIT_RE.fullmatch(str(factory_commit).strip()):
        raise ValueError("factory_commit must be a full 40-character Git SHA")
    if output_root == brand_root or brand_root in output_root.parents:
        raise ValueError("compiled output must not be inside the brand pack")
    if output_root.exists() and any(output_root.iterdir()):
        raise ValueError(f"compiled output directory must be empty: {output_root}")
    output_root.mkdir(parents=True, exist_ok=True)

    brand = _read_json(brand_root / "brand.json")
    copy = _read_json(brand_root / "copy.json")
    modules = _read_json(brand_root / "modules.json")
    assets = _validate_brand(
        brand_root,
        brand,
        copy,
        modules,
        release_ready=release_ready,
    )

    brand_id = brand["brandId"]
    display_name = brand["product"]["displayName"]
    short_name = brand["product"]["shortName"]
    binary_name = brand["desktop"]["binaryName"]
    main_binary_name = Path(binary_name).stem
    logo_source = assets["logo"]
    if logo_source.suffix.lower() not in {".svg", ".png", ".jpg", ".jpeg", ".webp"}:
        raise ValueError(f"brand logo uses an unsupported image format: {logo_source}")
    logo_name = "logo" + logo_source.suffix.lower()
    runtime_root = output_root / "runtime"
    theme_root = runtime_root / "themes" / brand_id
    theme_root.mkdir(parents=True, exist_ok=True)
    shutil.copy2(logo_source, theme_root / logo_name)

    base_theme = _read_json(DEFAULT_THEME_PATH)
    base_theme["name"] = f"{display_name} OEM"
    base_theme["brand"] = {
        **(base_theme.get("brand") if isinstance(base_theme.get("brand"), dict) else {}),
        "name": display_name,
        "subtitle": brand["positioning"]["promise"],
        "app_user_model_id": f"{brand_id}.Agent",
        "terminal_header": f"{short_name} 运行时",
        "logoUrl": logo_name,
    }
    base_theme["window"] = {
        **(base_theme.get("window") if isinstance(base_theme.get("window"), dict) else {}),
        "title": brand["desktop"]["windowTitle"],
    }
    base_theme["navItems"] = _filtered_nav_items(base_theme, modules["hidden"])
    _write_json(theme_root / "theme.json", base_theme)

    brand_profile = {
        "schemaVersion": 1,
        "profile": brand_id,
        "themeId": brand_id,
        "edition": "oem",
        "brandId": brand_id,
        "displayName": display_name,
        "nativeAgentName": f"{display_name} 原生智能体",
        "copy": copy,
        "modules": modules,
    }
    _write_json(runtime_root / "brand_profile.json", brand_profile)

    update_config = {
        "schemaVersion": 1,
        "brandId": brand_id,
        "displayName": display_name,
        "product": brand_id,
        "channel": brand["release"]["channel"],
        "channelId": brand["release"]["updateChannelId"],
        "filePrefix": brand["release"]["filePrefix"],
        "manifestUrl": brand["urls"]["manifest"],
        "cacheKey": f"{brand_id}-{brand['release']['updateChannelId']}",
    }
    _write_json(runtime_root / "desktop-update-brand.json", update_config)

    icons_root = output_root / "icons"
    installer_root = output_root / "installer"
    android_res_root = output_root / "android-res"
    icons_root.mkdir(parents=True, exist_ok=True)
    installer_root.mkdir(parents=True, exist_ok=True)
    android_res_root.mkdir(parents=True, exist_ok=True)

    resources = {
        str((runtime_root / "brand_profile.json").resolve()): "_up_/data/brand_profile.json",
        str((runtime_root / "desktop-update-brand.json").resolve()): "_up_/data/desktop-update-brand.json",
        str(theme_root.resolve()): f"_up_/data/themes/{brand_id}/",
    }
    tauri_config = {
        "productName": brand["desktop"]["productName"],
        "mainBinaryName": main_binary_name,
        "identifier": brand["desktop"]["identifier"],
        "app": {
            "windows": [
                {
                    "title": brand["desktop"]["windowTitle"],
                    "width": 1200,
                    "height": 800,
                    "minWidth": 960,
                    "minHeight": 640,
                    "resizable": True,
                    "zoomHotkeysEnabled": False,
                    "decorations": False,
                    "center": True,
                    "fullscreen": False,
                }
            ]
        },
        "bundle": {
            "resources": resources,
            "icon": [
                str((icons_root / "32x32.png").resolve()),
                str((icons_root / "128x128.png").resolve()),
                str((icons_root / "128x128@2x.png").resolve()),
                str((icons_root / "icon.icns").resolve()),
                str((icons_root / "icon.ico").resolve()),
            ],
            "windows": {
                "nsis": {
                    "installerIcon": str((icons_root / "icon.ico").resolve()),
                    "uninstallerIcon": str((icons_root / "icon.ico").resolve()),
                    "headerImage": str((installer_root / "nsis-header.bmp").resolve()),
                    "sidebarImage": str((installer_root / "nsis-sidebar.bmp").resolve()),
                    "uninstallerHeaderImage": str((installer_root / "nsis-header.bmp").resolve()),
                }
            },
        },
    }
    _write_json(output_root / "tauri.brand.conf.json", tauri_config)

    bundled_logo_relative = f"oem-brand/brand-logo{logo_source.suffix.lower()}"
    frontend_public_root = output_root / "frontend-public"
    shutil.copytree(LAUNCHER_ROOT / "public", frontend_public_root, dirs_exist_ok=True)
    bundled_logo_path = frontend_public_root / Path(bundled_logo_relative)
    bundled_logo_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(logo_source, bundled_logo_path)

    environment = {
        "VITE_LOOM_BRAND_DISPLAY_NAME": display_name,
        "VITE_LOOM_BRAND_SUBTITLE": brand["positioning"]["promise"],
        "VITE_LOOM_BRAND_LOGO_URL": f"/{bundled_logo_relative}",
        "VITE_LOOM_BRAND_HOME_TITLE": copy["homeTitle"],
        "VITE_LOOM_BRAND_TASK_PLACEHOLDER": copy["taskPlaceholder"],
        "VITE_LOOM_BRAND_SUPPORT_LABEL": copy["supportLabel"],
        "VITE_LOOM_BRAND_HIDDEN_MODULES": ",".join(modules["hidden"]),
        "LOOM_BRAND_VITE_PUBLIC_DIR": str(frontend_public_root),
        "LOOM_BRAND_ID": brand_id,
        "LOOM_BRAND_DISPLAY_NAME": display_name,
        "LOOM_BRAND_BINARY_NAME": binary_name,
        "LOOM_BRAND_UPDATE_CACHE_KEY": update_config["cacheKey"],
        "LOOM_BRAND_UPDATE_FILE_PREFIX": brand["release"]["filePrefix"],
    }
    _write_json(output_root / "environment.json", environment)

    plan: dict[str, Any] = {
        "schemaVersion": 1,
        "brandId": brand_id,
        "version": version,
        "coreCommit": core_commit.lower(),
        "factoryCommit": factory_commit.lower(),
        "brandPath": str(brand_root),
        "outputPath": str(output_root),
        "desktop": {
            "productName": brand["desktop"]["productName"],
            "binaryName": binary_name,
            "mainBinaryName": main_binary_name,
            "identifier": brand["desktop"]["identifier"],
            "windowTitle": brand["desktop"]["windowTitle"],
            "filePrefix": brand["release"]["filePrefix"],
        },
        "android": {
            "enabled": "phone-matrix" in modules["enabled"] and "phone-matrix" not in modules["hidden"],
            "appName": brand["phone"]["appName"],
            "applicationId": brand["phone"]["applicationId"],
            "filePrefix": f"{brand['release']['filePrefix']}-phone",
            "resDir": str(android_res_root),
        },
        "update": {
            "product": brand_id,
            "channel": brand["release"]["channel"],
            "channelId": brand["release"]["updateChannelId"],
            "filePrefix": brand["release"]["filePrefix"],
            "manifestUrl": brand["urls"]["manifest"],
        },
        "frontend": {
            "displayName": display_name,
            "subtitle": brand["positioning"]["promise"],
            "logoAsset": str(logo_source),
            "bundledLogoRelativePath": bundled_logo_relative,
            "copy": copy,
            "modules": modules,
        },
        "assets": {name: str(path) for name, path in assets.items()},
        "paths": {
            "tauriConfig": str(output_root / "tauri.brand.conf.json"),
            "environment": str(output_root / "environment.json"),
            "icons": str(icons_root),
            "installer": str(installer_root),
            "androidRes": str(android_res_root),
            "frontendPublic": str(frontend_public_root),
            "runtime": str(runtime_root),
        },
    }
    _write_json(output_root / "brand-build-plan.json", plan)
    return plan


def main() -> int:
    parser = argparse.ArgumentParser(description="Compile a LOOM OEM brand pack")
    parser.add_argument("--brand-path", required=True)
    parser.add_argument("--output-path", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--core-commit", required=True)
    parser.add_argument("--factory-commit", required=True)
    parser.add_argument("--allow-demo", action="store_true")
    args = parser.parse_args()

    plan = compile_brand_pack(
        brand_path=args.brand_path,
        output_path=args.output_path,
        version=args.version,
        core_commit=args.core_commit,
        factory_commit=args.factory_commit,
        release_ready=not args.allow_demo,
    )
    print(json.dumps({"ok": True, "plan": str(Path(args.output_path) / "brand-build-plan.json"), "brandId": plan["brandId"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
