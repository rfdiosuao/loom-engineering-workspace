"""Shared constants for the LOOM launcher.

Theme constants are now sourced from theme_manager.DEFAULT_THEME for
single-source-of-truth.  The module-level COLORS / FONTS / BRAND dicts
remain available for backward compatibility (they are copies of the
default theme).  Use get_theme() to obtain the *current* (possibly
overridden) theme at runtime.
"""

from __future__ import annotations

from typing import Any

from core.theme_manager import DEFAULT_THEME

APP_NAME = "LOOM"
APP_PORT = 18790
HELP_URL = "https://heang.top/docs.html"
FEISHU_APP_URL = "https://open.feishu.cn/app"
LICENSE_SERVER_URL = "https://license.heang.top"

PROVIDERS = {
    "Heang AI": {"url": "https://api.heang.top/v1", "models": ["kimi-k2.5", "gpt-4o", "gpt-4", "gpt-3.5-turbo"]},
    "OpenAI": {"url": "https://api.openai.com/v1", "models": ["gpt-4o", "gpt-4", "gpt-3.5-turbo"]},
    "Claude": {"url": "https://api.anthropic.com/v1", "models": ["claude-3-5-sonnet-20241022", "claude-3-opus-20240229"]},
    "DeepSeek": {"url": "https://api.deepseek.com/v1", "models": ["deepseek-chat", "deepseek-coder"]},
    "智谱AI": {"url": "https://open.bigmodel.cn/api/paas/v4", "models": ["glm-4", "glm-4-flash"]},
    "Moonshot": {"url": "https://api.moonshot.cn/v1", "models": ["moonshot-v1-8k", "moonshot-v1-32k"]},
    "自定义": {"url": "", "models": []},
}

IMAGE_MODEL = "gpt-image-2"
IMAGE_TRIPLE_TEMPLATES = [
    ("主图", "professional product photography, clean studio lighting, hero shot, commercial grade, photorealistic, high quality product image"),
    ("白底图", "pure white background, isolated product on white, e-commerce standard white background product shot, clean minimal product photo, white backdrop studio photography"),
    ("详情图", "detailed close-up macro product photography, showing product features and textures, fine details visible, premium quality product detail shot"),
]
VIDEO_MODEL_T2V = "happyhorse-1.0-t2v"
VIDEO_MODEL_I2V = "happyhorse-1.0-i2v"
DASHSCOPE_VIDEO_URL = "https://dashscope.aliyuncs.com/api/v1/services/aigc/video-generation/video-synthesis"
DASHSCOPE_TASK_URL = "https://dashscope.aliyuncs.com/api/v1/tasks/{task_id}"

_EXTRA_COLORS = {
    "danger_muted": "#FEE2E2",
    "primary_muted": "#DBEAFE",
    "accent_hover_light": "#BFDBFE",
    "terminal_dot_red": "#EF4444",
    "terminal_dot_yellow": "#F59E0B",
    "terminal_dot_green": "#22C55E",
    "terminal_label": "#CBD5E1",
    "terminal_label_muted": "#64748B",
    "terminal_button_bg": "#334155",
    "terminal_button_hover": "#475569",
    "terminal_button_text": "#FFFFFF",
    "terminal_selection": "#1E3A2F",
    "viewer_bg": "#000000",
    "viewer_bar_bg": "#1E293B",
    "code_input_bg": "#FFFFFF",
}

COLORS: dict[str, str] = {**DEFAULT_THEME["colors"], **_EXTRA_COLORS}

_EXTRA_FONTS = {
    "sidebar_caption": ("Microsoft YaHei UI", 8, "bold"),
    "license_code": ("Consolas", 13),
}

FONTS: dict[str, Any] = {**DEFAULT_THEME["fonts"], **_EXTRA_FONTS}

BRAND: dict[str, Any] = dict(DEFAULT_THEME["brand"])

_theme_manager_instance: Any | None = None


def init_theme_manager(manager: Any) -> None:
    global _theme_manager_instance
    _theme_manager_instance = manager


def get_theme() -> dict[str, Any]:
    if _theme_manager_instance is not None:
        return _theme_manager_instance.get_current()
    return dict(DEFAULT_THEME)
