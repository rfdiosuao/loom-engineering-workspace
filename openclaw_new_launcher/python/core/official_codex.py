"""Official ChatGPT desktop app identity used by the Codex UI component."""

from __future__ import annotations

from dataclasses import replace

from core.release_manifest import ReleaseComponent


CODEX_DESKTOP_PACKAGE_NAMES = ("OpenAI.Codex", "OpenAI.ChatGPT")
CODEX_DESKTOP_APP_ID = "App"
CODEX_STORE_PRODUCT_ID = "9PLM9XGG6VKS"
CODEX_STORE_INSTALLER_URL = "https://get.microsoft.com/installer/download/9PLM9XGG6VKS?cid=website_cta_psi"
CODEX_STORE_COMMAND_TIMEOUT_MS = 900000
CODEX_STORE_INSTALLER_FILENAME = "ChatGPT-Store-Installer.exe"


def official_codex_component(component: ReleaseComponent) -> ReleaseComponent:
    if component.component_id != "codex-desktop":
        return component
    return replace(
        component,
        name="ChatGPT Codex 原版",
        version="Microsoft Store",
        archive_type="msstore",
        size=0,
        urls=(CODEX_STORE_INSTALLER_URL,),
        entry=None,
        install_command=(),
        uninstall_command=(),
        external_paths=(),
        official_url="https://openai.com/codex/",
        description="OpenAI 官方 ChatGPT 桌面应用，内含 Codex，由 Microsoft Store 安装和更新",
    )


def is_official_codex_component(component: ReleaseComponent) -> bool:
    return component.component_id == "codex-desktop" and component.archive_type == "msstore"
