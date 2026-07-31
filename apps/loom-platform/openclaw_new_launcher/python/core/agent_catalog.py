"""Load the bundled, validated CLI agent catalog."""

from __future__ import annotations

import json
import os
from collections.abc import Iterable

from core.agent_definition import AgentDefinition, AgentDefinitionError, parse_agent_definition


DEFAULT_DEFINITIONS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), os.pardir, "config", "agent_definitions")
)


class AgentCatalog:
    def __init__(self, definitions_dir: str = DEFAULT_DEFINITIONS_DIR):
        self.definitions_dir = os.path.abspath(definitions_dir)

    def definitions(self) -> tuple[AgentDefinition, ...]:
        definitions: list[AgentDefinition] = []
        seen: set[str] = set()
        if not os.path.isdir(self.definitions_dir):
            raise AgentDefinitionError(f"agent definitions directory is missing: {self.definitions_dir}")
        for filename in sorted(os.listdir(self.definitions_dir)):
            if not filename.lower().endswith(".json"):
                continue
            path = os.path.join(self.definitions_dir, filename)
            try:
                with open(path, "r", encoding="utf-8-sig") as handle:
                    raw = json.load(handle)
            except Exception as exc:
                raise AgentDefinitionError(f"cannot read {filename}: {exc}") from exc
            definition = parse_agent_definition(raw, source=filename)
            if definition.component_id in seen:
                raise AgentDefinitionError(f"duplicate agent id: {definition.component_id}")
            seen.add(definition.component_id)
            definitions.append(definition)
        if not definitions:
            raise AgentDefinitionError("agent definitions directory is empty")
        return tuple(definitions)

    def by_id(self, component_id: str) -> AgentDefinition | None:
        return next((item for item in self.definitions() if item.component_id == component_id), None)

    def components(self) -> tuple:
        return tuple(item.to_release_component() for item in self.definitions())


def merge_agent_components(existing: Iterable, definitions: Iterable[AgentDefinition]) -> tuple:
    result = list(existing)
    seen = {component.component_id for component in result}
    for definition in definitions:
        if definition.component_id not in seen:
            result.append(definition.to_release_component())
            seen.add(definition.component_id)
    return tuple(result)
