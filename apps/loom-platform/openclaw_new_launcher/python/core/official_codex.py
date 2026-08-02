"""Codex Desktop and Codex CLI product identities.

The signed release manifest historically used ``codex-desktop`` for the npm
Codex CLI package.  Keep the signed bytes untouched and derive the three UI
products at runtime so package identity, executable name, and CLI shims cannot
be confused with one another.  The Store entry executable may still be named
``ChatGPT.exe``; the authoritative product identity remains ``OpenAI.Codex``.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from core.release_manifest import ReleaseComponent


CODEX_DESKTOP_COMPONENT_ID = "codex-desktop"
CODEX_CLI_COMPONENT_ID = "codex-cli"

CODEX_DESKTOP_PACKAGE_NAME = "OpenAI.Codex"
CODEX_DESKTOP_APP_ID = "App"

CODEX_STORE_PRODUCT_ID = "9PLM9XGG6VKS"
CODEX_STORE_INSTALLER_URL = "https://get.microsoft.com/installer/download/9PLM9XGG6VKS?cid=website_cta_psi"
CODEX_STORE_COMMAND_TIMEOUT_MS = 900000


@dataclass(frozen=True)
class OpenAIDesktopIdentity:
    component_id: str
    name: str
    package_name: str
    product_id: str
    installer_url: str
    installer_filename: str
    official_url: str
    description: str
    entry_names: tuple[str, ...]


OPENAI_DESKTOP_IDENTITIES = {
    CODEX_DESKTOP_COMPONENT_ID: OpenAIDesktopIdentity(
        component_id=CODEX_DESKTOP_COMPONENT_ID,
        name="Codex Desktop",
        package_name=CODEX_DESKTOP_PACKAGE_NAME,
        product_id=CODEX_STORE_PRODUCT_ID,
        installer_url=CODEX_STORE_INSTALLER_URL,
        installer_filename="Codex-Store-Installer.exe",
        official_url="https://openai.com/codex/",
        description="OpenAI 官方 Codex 桌面应用，由 Microsoft Store 安装和更新",
        # The signed Store package currently declares app/ChatGPT.exe as its
        # primary executable and also ships app/Codex.exe. Package identity is
        # therefore authoritative; the filename alone is not a product ID.
        entry_names=("app/ChatGPT.exe", "app/Codex.exe", "ChatGPT.exe", "Codex.exe"),
    ),
}

# Backward-compatible names used by older tests/import sites. The tuple is now
# deliberately exact and must never include the ChatGPT package.
CODEX_DESKTOP_PACKAGE_NAMES = (CODEX_DESKTOP_PACKAGE_NAME,)
CODEX_STORE_INSTALLER_FILENAME = OPENAI_DESKTOP_IDENTITIES[CODEX_DESKTOP_COMPONENT_ID].installer_filename


def openai_desktop_identity(component_or_id: ReleaseComponent | str) -> OpenAIDesktopIdentity | None:
    component_id = component_or_id if isinstance(component_or_id, str) else component_or_id.component_id
    return OPENAI_DESKTOP_IDENTITIES.get(component_id)


def official_desktop_component(component: ReleaseComponent, component_id: str) -> ReleaseComponent:
    identity = openai_desktop_identity(component_id)
    if identity is None:
        return component
    return replace(
        component,
        component_id=identity.component_id,
        name=identity.name,
        version="Microsoft Store",
        archive_type="msstore",
        size=0,
        urls=(identity.installer_url,),
        install_path=f"agents/{identity.component_id}",
        entry=None,
        install_command=(),
        uninstall_command=(),
        external_paths=(),
        official_url=identity.official_url,
        description=identity.description,
    )


def official_codex_component(component: ReleaseComponent) -> ReleaseComponent:
    """Compatibility wrapper for the Codex Desktop virtual component."""

    if component.component_id != CODEX_DESKTOP_COMPONENT_ID:
        return component
    return official_desktop_component(component, CODEX_DESKTOP_COMPONENT_ID)


def official_codex_cli_component(component: ReleaseComponent) -> ReleaseComponent:
    """Restore the original manifest record as the independent Codex CLI."""

    return replace(
        component,
        component_id=CODEX_CLI_COMPONENT_ID,
        name="Codex CLI",
        install_path="agents/codex-cli",
        category="agent",
        official_url="https://developers.openai.com/codex/cli/",
        description="OpenAI 官方 Codex 命令行智能体；与桌面应用独立检测和安装",
    )


def expand_openai_components(components: tuple[ReleaseComponent, ...]) -> tuple[ReleaseComponent, ...]:
    expanded: list[ReleaseComponent] = []
    for component in components:
        if component.component_id != CODEX_DESKTOP_COMPONENT_ID:
            expanded.append(component)
            continue
        expanded.extend(
            (
                official_codex_component(component),
                official_codex_cli_component(component),
            )
        )
    return tuple(expanded)


def virtual_openai_component(component: ReleaseComponent, component_id: str) -> ReleaseComponent | None:
    if component.component_id != CODEX_DESKTOP_COMPONENT_ID:
        return component if component.component_id == component_id else None
    if component_id == CODEX_DESKTOP_COMPONENT_ID:
        return official_codex_component(component)
    if component_id == CODEX_CLI_COMPONENT_ID:
        return official_codex_cli_component(component)
    return None


def is_official_codex_component(component: ReleaseComponent) -> bool:
    """Return true only for the official Codex Store desktop product."""

    return component.component_id in OPENAI_DESKTOP_IDENTITIES and component.archive_type == "msstore"


def is_openai_desktop_component(component: ReleaseComponent) -> bool:
    return is_official_codex_component(component)
