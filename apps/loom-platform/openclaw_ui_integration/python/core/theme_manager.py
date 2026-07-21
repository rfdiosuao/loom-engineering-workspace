"""Theme configuration manager with three-level fallback strategy.

Fallback chain:
1. data/theme.json -- cached from activation response (highest priority)
2. data/themes/{merchantId}/theme.json -- local theme package (offline fallback)
3. data/brand_profile.json -- packaged brand profile for unlicensed/default state
4. DEFAULT_THEME -- built-in default (fallback)
"""

from __future__ import annotations

import os
from typing import Any

from core.paths import AppPaths
from core.storage import read_json, write_json

DEFAULT_THEME: dict[str, Any] = {
    "name": "Lumi Graphite Gold",
    "colors": {
        "app_bg": "#05060A",
        "sidebar_bg": "#070912",
        "surface": "#090B12",
        "surface_alt": "#0F1420",
        "surface_deep": "#1C202A",
        "surface_deeper": "#14171E",
        "hover": "#171B28",
        "input": "#0B1020",
        "border": "rgba(215, 181, 109, 0.22)",
        "border_strong": "rgba(215, 181, 109, 0.58)",
        "text": "#F7F1E3",
        "text_muted": "#A9B2C3",
        "text_subtle": "#69758B",
        "accent": "#D7B56D",
        "accent_hover": "#F1D99A",
        "accent_soft": "rgba(215, 181, 109, 0.16)",
        "accent_ink": "#2B1D05",
        "success": "#38D996",
        "warning": "#FFB454",
        "danger": "#FF4D6D",
        "danger_hover": "#FF6E86",
        "terminal_bg": "#05070D",
        "terminal_header": "#0D1320",
        "terminal_text": "#37E6D0",
    },
    "fonts": {
        "display": ["Microsoft YaHei UI", 21, "bold"],
        "title": ["Microsoft YaHei UI", 14, "bold"],
        "section": ["Microsoft YaHei UI", 10, "bold"],
        "body": ["Microsoft YaHei UI", 10, "normal"],
        "small": ["Microsoft YaHei UI", 9, "normal"],
        "mono": ["Cascadia Mono", 10, "normal"],
    },
    "brand": {
        "name": "Lumi",
        "subtitle": "AI Creative Console",
        "app_user_model_id": "Lumi.Launcher",
        "terminal_header": "Lumi Console",
        "logoUrl": "logo.png",
    },
    "navItems": [
        {"key": "terminal", "label": "服务日志", "desc": "查看运行状态", "icon": "LOG", "group": "工作台"},
        {"key": "storyboard", "label": "广告视频", "desc": "分镜/首尾帧/九宫格", "icon": "AD", "group": "工作台", "accent": True},
        {"key": "image", "label": "AI 生图", "desc": "生成/编辑图片", "icon": "IMG", "group": "工作台", "accent": True},
        {"key": "video", "label": "AI 视频", "desc": "多模型视频生成", "icon": "VID", "group": "工作台", "accent": True},
        {"key": "license", "label": "授权码", "desc": "在线激活解锁", "icon": "LIC", "group": "配置"},
        {"key": "api", "label": "API 配置", "desc": "设置模型密钥", "icon": "KEY", "group": "配置"},
        {"key": "feishu", "label": "飞书机器人", "desc": "绑定消息通道", "icon": "BOT", "group": "配置"},
        {"key": "weixin", "label": "微信机器人", "desc": "扫码绑定微信", "icon": "WX", "group": "配置"},
        {"key": "skills", "label": "Skills", "desc": "安装/启用能力模块", "icon": "SK", "group": "扩展"},
        {"key": "web", "label": "网页界面", "desc": "打开本地控制台", "icon": "WEB", "group": "维护"},
        {"key": "diagnostics", "label": "环境诊断", "desc": "检查/修复启动环境", "icon": "FIX", "group": "维护", "accent": True},
        {"key": "update", "label": "检查更新", "desc": "更新 OpenClaw", "icon": "UP", "group": "维护"},
        {"key": "help", "label": "帮助文档", "desc": "查看使用说明", "icon": "DOC", "group": "维护"},
    ],
    "window": {
        "title": "Lumi - AI Creative Console",
        "width": 1200,
        "height": 800,
    },
}


def _normalize_nav_items(items: Any) -> list[dict[str, Any]]:
    default_items = DEFAULT_THEME["navItems"]
    default_by_key = {item["key"]: item for item in default_items}
    source = items if isinstance(items, list) and items else default_items
    normalized: list[dict[str, Any]] = []
    for item in source:
        if not isinstance(item, dict):
            continue
        key = item.get("key")
        if key == "delivery" or key not in default_by_key:
            continue
        merged = dict(default_by_key[key])
        for field in ("label", "desc", "icon", "group"):
            if isinstance(item.get(field), str) and item[field].strip():
                merged[field] = item[field]
        if "accent" in item:
            merged["accent"] = bool(item["accent"])
        normalized.append(merged)
    result = normalized or list(default_items)
    if not any(item.get("key") == "weixin" for item in result):
        weixin_item = default_by_key.get("weixin")
        if weixin_item:
            insert_index = len(result)
            for index, item in enumerate(result):
                if item.get("key") == "feishu":
                    insert_index = index + 1
                    break
            result.insert(insert_index, dict(weixin_item))
    return result


def _is_external_asset(value: str) -> bool:
    lowered = value.lower()
    return lowered.startswith(("data:", "blob:", "http://", "https://", "asset:", "tauri:"))


def _resolve_brand_assets(brand: dict[str, Any], base_dir: str | None) -> None:
    logo_value = brand.get("logoUrl") or brand.get("logo")
    if not isinstance(logo_value, str) or not logo_value.strip():
        return
    logo_value = logo_value.strip()
    if base_dir and not os.path.isabs(logo_value) and not _is_external_asset(logo_value):
        resolved = os.path.abspath(os.path.join(base_dir, logo_value))
        if not os.path.exists(resolved):
            filename = os.path.basename(logo_value)
            fallback_candidates = [
                os.path.join(base_dir, "themes", "lumi", filename),
                os.path.join(base_dir, "themes", "default", filename),
                os.path.join(base_dir, "themes", "yonghao_tech", filename),
            ]
            resolved = next((path for path in fallback_candidates if os.path.exists(path)), resolved)
        logo_value = resolved
    brand["logoUrl"] = logo_value


def _normalize_mode_colors(theme: dict[str, Any], default_colors: dict[str, Any]) -> dict[str, dict[str, Any]]:
    modes: dict[str, dict[str, Any]] = {}
    raw_modes = theme.get("modes")
    if not isinstance(raw_modes, dict):
        return modes
    for mode in ("light", "dark"):
        raw_colors = raw_modes.get(mode)
        if isinstance(raw_colors, dict):
            modes[mode] = {k: v for k, v in raw_colors.items() if k in default_colors}
    return modes


def _safe_theme_id(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    theme_id = value.strip()
    if not theme_id:
        return None
    if any(ch in theme_id for ch in ("/", "\\", ":", "..")):
        return None
    return theme_id


def _validate_theme(theme: dict[str, Any], base_dir: str | None = None) -> dict[str, Any]:
    default = DEFAULT_THEME
    if not isinstance(theme, dict):
        return dict(default)
    result: dict[str, Any] = {}
    result["name"] = theme.get("name", default["name"])
    result["colors"] = dict(default["colors"])
    if isinstance(theme.get("colors"), dict):
        result["colors"].update(theme["colors"])
    result["modes"] = _normalize_mode_colors(theme, default["colors"])
    result["fonts"] = dict(default["fonts"])
    if isinstance(theme.get("fonts"), dict):
        for k, v in theme["fonts"].items():
            if k in default["fonts"]:
                result["fonts"][k] = v
    result["brand"] = dict(default["brand"])
    if isinstance(theme.get("brand"), dict):
        result["brand"].update(theme["brand"])
    _resolve_brand_assets(result["brand"], base_dir)
    result["navItems"] = _normalize_nav_items(theme.get("navItems"))
    result["window"] = dict(default["window"])
    if isinstance(theme.get("window"), dict):
        result["window"].update(theme["window"])
    return result


class ThemeManager:
    def __init__(self, paths: AppPaths):
        self.paths = paths
        self._current_cache: dict[str, Any] | None = None

    def get_current(self, license_data: dict[str, Any] | None = None) -> dict[str, Any]:
        if self._current_cache is not None:
            return self._current_cache

        theme = self._load_from_cache()
        if theme is not None:
            self._current_cache = theme
            return theme

        if license_data:
            theme = self._load_from_license(license_data)
            if theme is not None:
                self._current_cache = theme
                return theme

            merchant_id = license_data.get("merchantId")
            if merchant_id:
                theme = self._load_from_local_package(merchant_id)
                if theme is not None:
                    self._current_cache = theme
                    return theme

        theme = self._load_from_brand_profile()
        if theme is not None:
            self._current_cache = theme
            return theme

        theme = self._load_from_local_package("default")
        if theme is not None:
            self._current_cache = theme
            return theme

        self._current_cache = _validate_theme(DEFAULT_THEME)
        return self._current_cache

    def get_by_merchant(self, merchant_id: str) -> dict[str, Any] | None:
        if not merchant_id:
            return None
        return self._load_from_local_package(merchant_id)

    def list_themes(self) -> list[dict[str, Any]]:
        themes: list[dict[str, Any]] = []
        themes_dir = self.paths.themes_dir
        if not os.path.isdir(themes_dir):
            return themes
        for entry in sorted(os.listdir(themes_dir)):
            theme_path = os.path.join(themes_dir, entry, "theme.json")
            if os.path.isfile(theme_path):
                theme_data = self._load_from_theme_file(theme_path, entry)
                if isinstance(theme_data, dict):
                    themes.append(theme_data)
        return themes

    def save_theme(self, theme_data: dict[str, Any]) -> None:
        validated = _validate_theme(theme_data, self.paths.data_dir)
        write_json(self.paths.theme_json, validated)
        self._current_cache = validated

    def invalidate_cache(self) -> None:
        self._current_cache = None

    def _load_from_cache(self) -> dict[str, Any] | None:
        theme_data = read_json(self.paths.theme_json, None)
        if self._looks_like_theme(theme_data):
            return _validate_theme(theme_data, self.paths.data_dir)
        return None

    def _load_from_license(self, license_data: dict[str, Any]) -> dict[str, Any] | None:
        brand_config = license_data.get("brandConfig") or license_data.get("theme")
        if self._looks_like_theme(brand_config):
            return _validate_theme(brand_config)
        return None

    def _load_from_local_package(self, merchant_id: str) -> dict[str, Any] | None:
        theme_path = self.paths.theme_file(merchant_id)
        if not os.path.isfile(theme_path):
            return None
        return self._load_from_theme_file(theme_path, merchant_id)

    def _load_from_theme_file(self, theme_path: str, merchant_id: str | None = None) -> dict[str, Any] | None:
        theme_data = read_json(theme_path, None)
        if self._looks_like_theme(theme_data):
            if merchant_id:
                theme_data["merchantId"] = merchant_id
            return _validate_theme(theme_data, os.path.dirname(theme_path))
        return None

    def _load_from_brand_profile(self) -> dict[str, Any] | None:
        profile = read_json(self.paths.brand_profile, None)
        if not isinstance(profile, dict):
            return None
        theme_id = _safe_theme_id(profile.get("themeId") or profile.get("profile"))
        if not theme_id:
            return None
        return self._load_from_local_package(theme_id)

    @staticmethod
    def _looks_like_theme(theme_data: Any) -> bool:
        return (
            isinstance(theme_data, dict)
            and (
                isinstance(theme_data.get("colors"), dict)
                or isinstance(theme_data.get("modes"), dict)
                or isinstance(theme_data.get("brand"), dict)
                or isinstance(theme_data.get("window"), dict)
            )
        )
