from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError


CONTRACT_NAMES = (
    "agent-approval.v1",
    "agent-message.v1",
    "agent-run.v1",
    "agent-session.v1",
    "device-lease.v1",
    "matrix-campaign.v2",
    "matrix-dispatch.v2",
    "matrix-screen.v1",
    "realtime-event.v1",
)

CONTRACT_ROOT = Path(__file__).resolve().parent
SCHEMA_ROOT = CONTRACT_ROOT / "schemas"
FIXTURE_ROOT = CONTRACT_ROOT / "fixtures"
_LOAD_FAILED = object()


def _display_path(path: Path) -> str:
    return path.relative_to(CONTRACT_ROOT).as_posix()


def _load_json(path: Path, kind: str, errors: list[str]) -> Any:
    if not path.is_file():
        errors.append(f"{_display_path(path)}: missing {kind}")
        return _LOAD_FAILED

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        errors.append(f"{_display_path(path)}: cannot read {kind}: {error}")
        return _LOAD_FAILED


def _instance_path(error: ValidationError) -> str:
    parts = [str(part) for part in error.absolute_path]
    return "/" + "/".join(parts) if parts else "/"


def validate_contracts() -> list[str]:
    errors: list[str] = []

    for name in CONTRACT_NAMES:
        schema_path = SCHEMA_ROOT / f"{name}.schema.json"
        fixture_path = FIXTURE_ROOT / f"{name}.json"
        schema = _load_json(schema_path, "schema", errors)
        fixture = _load_json(fixture_path, "fixture", errors)
        if schema is _LOAD_FAILED or fixture is _LOAD_FAILED:
            continue

        try:
            Draft202012Validator.check_schema(schema)
        except SchemaError as error:
            errors.append(
                f"{_display_path(schema_path)}: invalid Draft 2020-12 schema: "
                f"{error.message}"
            )
            continue

        validator = Draft202012Validator(schema)
        try:
            validation_errors = sorted(
                validator.iter_errors(fixture),
                key=lambda error: tuple(str(part) for part in error.absolute_path),
            )
        except Exception as error:
            errors.append(
                f"{_display_path(schema_path)}: cannot validate "
                f"{_display_path(fixture_path)}: {error}"
            )
            continue
        for error in validation_errors:
            errors.append(
                f"{_display_path(fixture_path)}: does not match "
                f"{_display_path(schema_path)} at {_instance_path(error)}: "
                f"{error.message}"
            )

    return errors


def main() -> int:
    errors = validate_contracts()
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        print(f"Contract validation failed: {len(errors)} error(s).", file=sys.stderr)
        return 1

    count = len(CONTRACT_NAMES)
    print(f"Validated {count} Draft 2020-12 schemas and {count} fixtures.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
