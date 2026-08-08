"""Validated declarative definitions for third-party command-line agents.

Definitions are shipped with the launcher and are deliberately more restrictive
than the signed binary release manifest.  They may describe a fixed npm install
or a detect-only official installer, but never arbitrary shell snippets or
credentials.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.parse import urlparse

from core.release_manifest import ReleaseComponent


class AgentDefinitionError(ValueError):
    """Raised when a bundled agent definition is unsafe or malformed."""


SUPPORTED_INSTALL_MODES = {"managed_npm", "official_manual", "detect_only"}
SUPPORTED_PROVIDER_CONFIG_MODES = {"verified_schema", "probe_required", "official_only", "unsupported"}
TRUSTED_OFFICIAL_HOSTS = {
    "docs.x.ai",
    "x.ai",
    "github.com",
    "pi.dev",
    "block.github.io",
    "google-gemini.github.io",
}
TRUSTED_URL_PREFIXES = (
    "https://docs.x.ai/build/",
    "https://github.com/xai-org/grok-build",
    "https://pi.dev/docs/",
    "https://github.com/earendil-works/pi",
    "https://block.github.io/goose/",
    "https://github.com/block/goose",
    "https://github.com/aaif-goose/goose",
    "https://google-gemini.github.io/gemini-cli/",
    "https://github.com/google-gemini/gemini-cli",
)
TRUSTED_NPM_PACKAGES = {
    "@earendil-works/pi-coding-agent": "pi",
    "@google/gemini-cli": "gemini",
}
_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_COMMAND_TOKEN_RE = re.compile(r"^[A-Za-z0-9@._/+:-]+$")
_SECRET_MARKERS = re.compile(r"(?:xai-|sk-|api[_-]?key|token|secret|password)", re.IGNORECASE)
_SHELL_META = re.compile(r"[|;&`$<>\r\n]")


@dataclass(frozen=True)
class AgentDefinition:
    component_id: str
    name: str
    description: str
    official_url: str
    source_url: str
    install_mode: str
    provider_config_mode: str
    install_command: tuple[str, ...]
    uninstall_command: tuple[str, ...]
    command_names: tuple[str, ...]
    compatibility: str
    sandbox: bool
    priority: str

    @property
    def install_locked(self) -> bool:
        return self.install_mode != "managed_npm"

    def to_release_component(self) -> ReleaseComponent:
        return ReleaseComponent(
            component_id=self.component_id,
            name=self.name,
            version="latest",
            platform="windows",
            arch="x64",
            archive_type="external",
            size=0,
            sha256="0" * 64,
            urls=(),
            install_path=f"agents/{self.component_id}",
            entry=None,
            category="agent",
            official_url=self.official_url,
            description=self.description,
            external_paths=self.command_names,
            install_command=self.install_command,
            uninstall_command=self.uninstall_command,
        )

    def payload(self) -> dict[str, Any]:
        return {
            "installMode": self.install_mode,
            "installLocked": self.install_locked,
            "providerConfigMode": self.provider_config_mode,
            "compatibility": self.compatibility,
            "sandbox": self.sandbox,
            "priority": self.priority,
            "sourceUrl": self.source_url,
        }


def parse_agent_definition(data: Mapping[str, Any], *, source: str = "definition") -> AgentDefinition:
    if not isinstance(data, Mapping):
        raise AgentDefinitionError(f"{source} must be a JSON object")
    if data.get("schemaVersion") != 1:
        raise AgentDefinitionError(f"{source}.schemaVersion must be 1")

    component_id = _required_text(data, "id", source)
    if not _ID_RE.fullmatch(component_id):
        raise AgentDefinitionError(f"{source}.id is invalid")
    name = _required_text(data, "name", source)
    description = _required_text(data, "description", source)
    official_url = _official_url(_required_text(data, "officialUrl", source), f"{source}.officialUrl")
    source_url = _official_url(_required_text(data, "sourceUrl", source), f"{source}.sourceUrl")
    install_mode = _required_text(data, "installMode", source)
    if install_mode not in SUPPORTED_INSTALL_MODES:
        raise AgentDefinitionError(f"{source}.installMode is unsupported")
    provider_config_mode = _required_text(data, "providerConfigMode", source)
    if provider_config_mode not in SUPPORTED_PROVIDER_CONFIG_MODES:
        raise AgentDefinitionError(f"{source}.providerConfigMode is unsupported")

    install_command = _command(data.get("installCommand"), f"{source}.installCommand")
    uninstall_command = _command(data.get("uninstallCommand"), f"{source}.uninstallCommand")
    command_names = _text_tuple(data.get("commandNames"), f"{source}.commandNames", required=True)
    for command_name in command_names:
        if not re.fullmatch(r"[A-Za-z0-9._-]+", command_name):
            raise AgentDefinitionError(f"{source}.commandNames contains an unsafe name")

    if install_mode == "managed_npm":
        _validate_managed_npm_pair(install_command, uninstall_command, command_names, source)
    elif install_command or uninstall_command:
        raise AgentDefinitionError(f"{source} detect/manual definitions cannot execute commands")

    sandbox_value = data.get("sandbox")
    if not isinstance(sandbox_value, bool):
        raise AgentDefinitionError(f"{source}.sandbox must be boolean")
    return AgentDefinition(
        component_id=component_id,
        name=name,
        description=description,
        official_url=official_url,
        source_url=source_url,
        install_mode=install_mode,
        provider_config_mode=provider_config_mode,
        install_command=install_command,
        uninstall_command=uninstall_command,
        command_names=command_names,
        compatibility=_required_text(data, "compatibility", source),
        sandbox=sandbox_value,
        priority=_required_text(data, "priority", source),
    )


def _required_text(data: Mapping[str, Any], key: str, source: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise AgentDefinitionError(f"{source}.{key} must be a non-empty string")
    return value.strip()


def _text_tuple(value: Any, label: str, *, required: bool = False) -> tuple[str, ...]:
    if value is None and not required:
        return ()
    if not isinstance(value, list) or (required and not value):
        raise AgentDefinitionError(f"{label} must be a non-empty array")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise AgentDefinitionError(f"{label} contains an invalid value")
        result.append(item.strip())
    return tuple(result)


def _official_url(value: str, label: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" or (parsed.hostname or "").lower() not in TRUSTED_OFFICIAL_HOSTS:
        raise AgentDefinitionError(f"{label} must use a trusted official HTTPS host")
    if parsed.username or parsed.password:
        raise AgentDefinitionError(f"{label} cannot contain credentials")
    if not any(value.startswith(prefix) for prefix in TRUSTED_URL_PREFIXES):
        raise AgentDefinitionError(f"{label} is not an allowlisted official project URL")
    return value


def _command(value: Any, label: str) -> tuple[str, ...]:
    command = _text_tuple(value, label)
    for token in command:
        if _SHELL_META.search(token) or _SECRET_MARKERS.search(token) or not _COMMAND_TOKEN_RE.fullmatch(token):
            raise AgentDefinitionError(f"{label} contains an unsafe token")
    return command


def _validate_managed_npm_pair(
    install_command: tuple[str, ...],
    uninstall_command: tuple[str, ...],
    command_names: tuple[str, ...],
    source: str,
) -> None:
    if len(install_command) < 4 or install_command[:3] not in {
        ("npm", "install", "-g"),
        ("npm", "install", "--global"),
    }:
        raise AgentDefinitionError(f"{source}.installCommand must be a fixed global npm install")
    package = install_command[-1]
    expected_command = TRUSTED_NPM_PACKAGES.get(package)
    allowed_options = {"--ignore-scripts"}
    middle = set(install_command[3:-1])
    if not expected_command or not middle.issubset(allowed_options):
        raise AgentDefinitionError(f"{source}.installCommand package/options are not trusted")
    if uninstall_command not in {
        ("npm", "uninstall", "-g", package),
        ("npm", "uninstall", "--global", package),
    }:
        raise AgentDefinitionError(f"{source}.uninstallCommand must match the install package")
    if expected_command not in command_names:
        raise AgentDefinitionError(f"{source}.commandNames does not expose the trusted package entry")
