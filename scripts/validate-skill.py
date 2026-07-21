from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def fail(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(1)


def main() -> None:
    if len(sys.argv) != 2:
        fail("usage: validate-skill.py <skill-directory>")

    skill_dir = Path(sys.argv[1]).resolve()
    skill_file = skill_dir / "SKILL.md"
    if not skill_file.is_file():
        fail(f"SKILL.md is missing: {skill_file}")

    lines = skill_file.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0] != "---":
        fail("SKILL.md must start with YAML frontmatter")
    try:
        closing = lines.index("---", 1)
    except ValueError:
        fail("SKILL.md frontmatter is not closed")

    fields: dict[str, str] = {}
    for line in lines[1:closing]:
        match = re.match(r"^([A-Za-z][A-Za-z0-9_-]*):\s*(.*)$", line)
        if match:
            fields[match.group(1)] = match.group(2).strip()

    name = fields.get("name", "")
    description = fields.get("description", "")
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name):
        fail("Skill name must use lowercase kebab-case")
    if name != skill_dir.name:
        fail(f"Skill name does not match its directory: {name} != {skill_dir.name}")
    if not description:
        fail("Skill description is required")
    if not any(line.strip() for line in lines[closing + 1 :]):
        fail("SKILL.md body is empty")

    print(json.dumps({"schema": "loom.skill_validation.v1", "skill": name, "status": "ok"}))


if __name__ == "__main__":
    main()
