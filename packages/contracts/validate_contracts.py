from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError, ValidationError


CONTRACT_ROOT = Path(__file__).resolve().parent
SCHEMA_ROOT = CONTRACT_ROOT / "schemas"
FIXTURE_ROOT = CONTRACT_ROOT / "fixtures"
REPO_ROOT = CONTRACT_ROOT.parents[1]
VENDORED_SCHEMA_ROOT = (
    REPO_ROOT
    / "apps"
    / "loom-platform"
    / "openclaw_new_launcher"
    / "python"
    / "tests"
    / "contract_schemas"
)
COMPATIBILITY_MANIFEST = "consumer-compatibility.v1.json"
MIGRATION_MANIFEST = "migrations.v1.json"
ALLOWED_CONTRACT_ROOT_JSON = frozenset(
    {
        COMPATIBILITY_MANIFEST,
        MIGRATION_MANIFEST,
        "mobile-agent-runtime.schema.json",
        "mobile-linux-runtime.schema.json",
        "reliability-gates.v1.json",
    }
)
ALLOWED_FIXTURE_GROUPS = frozenset({"compat", "migration", "negative"})
REQUIRED_EVOLUTION_FIXTURES = frozenset(
    {
        "fixtures/compat/agent-run.v1.initial.json",
        "fixtures/compat/matrix-dispatch.v2.consumer-gap.json",
        "fixtures/migration/agent-run.v1.public-projection.json",
        "fixtures/negative/agent-run.v1.private-producer.json",
        "fixtures/negative/agent-session.v1.invalid-date-time.json",
    }
)
_LOAD_FAILED = object()

_RFC3339_DATE_TIME = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})[Tt]"
    r"(?P<hour>\d{2}):(?P<minute>\d{2}):(?P<second>\d{2})"
    r"(?:\.\d+)?(?P<offset>[Zz]|[+-]\d{2}:\d{2})$",
    re.ASCII,
)
_HOSTNAME_LABEL = re.compile(
    r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$",
    re.ASCII,
)
_FORMAT_CANARIES = {
    "date-time": "not-a-date",
    "hostname": "bad host",
}


def _is_rfc3339_date_time(instance: object) -> bool:
    if not isinstance(instance, str):
        return True
    match = _RFC3339_DATE_TIME.fullmatch(instance)
    if match is None:
        return False
    try:
        date.fromisoformat(match.group("date"))
    except ValueError:
        return False
    if int(match.group("hour")) > 23 or int(match.group("minute")) > 59:
        return False
    if int(match.group("second")) > 60:
        return False
    offset = match.group("offset")
    if offset not in {"Z", "z"}:
        offset_hour, offset_minute = offset[1:].split(":", 1)
        if int(offset_hour) > 23 or int(offset_minute) > 59:
            return False
    return True


def _is_hostname(instance: object) -> bool:
    if not isinstance(instance, str):
        return True
    hostname = instance[:-1] if instance.endswith(".") else instance
    if not hostname or len(hostname) > 253:
        return False
    return all(
        len(label) <= 63 and _HOSTNAME_LABEL.fullmatch(label) is not None
        for label in hostname.split(".")
    )


def build_format_checker() -> FormatChecker:
    """Build a fail-closed checker even when jsonschema optional extras are absent."""

    checker = FormatChecker()
    if "date-time" not in checker.checkers:
        checker.checks("date-time")(_is_rfc3339_date_time)
    if "hostname" not in checker.checkers:
        checker.checks("hostname")(_is_hostname)
    return checker


def _display_path(path: Path, contract_root: Path) -> str:
    for root in (contract_root, contract_root.parents[1] if len(contract_root.parents) > 1 else None):
        if root is None:
            continue
        try:
            return path.relative_to(root).as_posix()
        except ValueError:
            continue
    return path.as_posix()


def _load_json(path: Path, kind: str, errors: list[str], contract_root: Path) -> Any:
    if not path.is_file():
        errors.append(f"{_display_path(path, contract_root)}: missing {kind}")
        return _LOAD_FAILED

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        errors.append(
            f"{_display_path(path, contract_root)}: cannot read {kind}: {error}"
        )
        return _LOAD_FAILED


def _instance_path(error: ValidationError) -> str:
    parts = [str(part) for part in error.absolute_path]
    return "/" + "/".join(parts) if parts else "/"


def _schema_paths(contract_root: Path) -> list[Path]:
    return sorted(
        [*contract_root.glob("*.schema.json"), *(contract_root / "schemas").glob("*.schema.json")],
        key=lambda path: path.relative_to(contract_root).as_posix(),
    )


def _validate_inventory_layout(contract_root: Path, errors: list[str]) -> None:
    fixture_root = contract_root / "fixtures"
    unknown_fixture_groups: set[str] = set()
    if fixture_root.is_dir():
        for path in sorted(fixture_root.iterdir()):
            if path.is_dir() and path.name not in ALLOWED_FIXTURE_GROUPS:
                unknown_fixture_groups.add(path.name)
                errors.append(f"fixtures/{path.name}: unknown fixture group")

    for path in sorted(contract_root.rglob("*.json")):
        relative_path = path.relative_to(contract_root)
        parts = relative_path.parts
        display_path = relative_path.as_posix()
        if len(parts) == 1:
            if path.name not in ALLOWED_CONTRACT_ROOT_JSON:
                errors.append(f"{path.name}: unknown contract-root JSON document")
            continue
        if parts[0] == "schemas":
            if len(parts) != 2:
                errors.append(f"{display_path}: nested schema is not allowed")
            elif not path.name.endswith(".schema.json"):
                errors.append(f"{display_path}: unknown schema inventory document")
            continue
        if parts[0] == "fixtures":
            if len(parts) == 2:
                continue
            if len(parts) == 3 and parts[1] in ALLOWED_FIXTURE_GROUPS:
                continue
            if len(parts) >= 2 and parts[1] in unknown_fixture_groups:
                continue
            errors.append(f"{display_path}: unknown nested fixture path")
            continue
        errors.append(f"{display_path}: unknown contract inventory path")


def _collect_formats(value: Any) -> set[str]:
    formats: set[str] = set()
    if isinstance(value, dict):
        format_name = value.get("format")
        if isinstance(format_name, str) and format_name:
            formats.add(format_name)
        for nested in value.values():
            formats.update(_collect_formats(nested))
    elif isinstance(value, list):
        for nested in value:
            formats.update(_collect_formats(nested))
    return formats


def _validate_format_support(
    schemas: list[tuple[Path, dict[str, Any]]],
    checker: FormatChecker,
    errors: list[str],
    contract_root: Path,
) -> None:
    required_formats = set()
    for _path, schema in schemas:
        required_formats.update(_collect_formats(schema))

    for format_name in sorted(required_formats):
        if format_name not in checker.checkers:
            errors.append(f"format checker unavailable for {format_name}")
            continue
        canary = _FORMAT_CANARIES.get(format_name)
        if canary is not None and checker.conforms(canary, format_name):
            errors.append(
                f"format checker accepted invalid {format_name} canary {canary!r}"
            )


def _validate_instance(
    fixture_path: Path,
    fixture: Any,
    schemas_by_id: dict[str, tuple[Path, dict[str, Any]]],
    checker: FormatChecker,
    errors: list[str],
    contract_root: Path,
    *,
    expect_valid: bool,
) -> str | None:
    display_fixture = _display_path(fixture_path, contract_root)
    if not isinstance(fixture, dict):
        errors.append(f"{display_fixture}: fixture must be a JSON object")
        return None
    schema_id = fixture.get("schema")
    if not isinstance(schema_id, str) or not schema_id:
        errors.append(f"{display_fixture}: fixture has no non-empty schema ID")
        return None
    schema_entry = schemas_by_id.get(schema_id)
    if schema_entry is None:
        errors.append(f"{display_fixture}: no canonical schema for {schema_id}")
        return schema_id

    schema_path, schema = schema_entry
    validator = Draft202012Validator(schema, format_checker=checker)
    try:
        validation_errors = sorted(
            validator.iter_errors(fixture),
            key=lambda error: tuple(str(part) for part in error.absolute_path),
        )
    except Exception as error:
        errors.append(
            f"{display_fixture}: cannot validate against "
            f"{_display_path(schema_path, contract_root)}: {error}"
        )
        return schema_id

    if expect_valid:
        for error in validation_errors:
            errors.append(
                f"{display_fixture}: does not match "
                f"{_display_path(schema_path, contract_root)} at {_instance_path(error)}: "
                f"{error.message}"
            )
    elif not validation_errors:
        errors.append(
            f"{display_fixture}: negative fixture unexpectedly validates against "
            f"{_display_path(schema_path, contract_root)}"
        )
    return schema_id


def _validate_fixture_group(
    paths: list[Path],
    kind: str,
    schemas_by_id: dict[str, tuple[Path, dict[str, Any]]],
    checker: FormatChecker,
    errors: list[str],
    contract_root: Path,
    *,
    expect_valid: bool,
) -> set[str]:
    schema_ids: set[str] = set()
    for fixture_path in paths:
        fixture = _load_json(fixture_path, f"{kind} fixture", errors, contract_root)
        if fixture is _LOAD_FAILED:
            continue
        schema_id = _validate_instance(
            fixture_path,
            fixture,
            schemas_by_id,
            checker,
            errors,
            contract_root,
            expect_valid=expect_valid,
        )
        if schema_id is not None:
            schema_ids.add(schema_id)
    return schema_ids


def _normalized_bytes(path: Path) -> bytes:
    return path.read_bytes().replace(b"\r\n", b"\n")


def _validate_vendored_sync(
    canonical_schema_root: Path,
    vendored_schema_root: Path,
    errors: list[str],
    contract_root: Path,
) -> None:
    canonical_paths = {path.name: path for path in canonical_schema_root.glob("*.schema.json")}
    if not vendored_schema_root.is_dir():
        errors.append(
            f"{_display_path(vendored_schema_root, contract_root)}: missing vendored schema directory"
        )
        return
    vendored_paths = {path.name: path for path in vendored_schema_root.glob("*.schema.json")}

    missing = sorted(set(canonical_paths) - set(vendored_paths))
    extra = sorted(set(vendored_paths) - set(canonical_paths))
    if missing:
        errors.append(f"vendored schemas missing canonical files: {', '.join(missing)}")
    if extra:
        errors.append(f"vendored schemas contain orphan files: {', '.join(extra)}")

    vendored_ids: dict[str, Path] = {}
    for name in sorted(set(canonical_paths) & set(vendored_paths)):
        canonical_path = canonical_paths[name]
        vendored_path = vendored_paths[name]
        canonical_bytes = _normalized_bytes(canonical_path)
        vendored_bytes = _normalized_bytes(vendored_path)
        if canonical_bytes != vendored_bytes:
            canonical_hash = hashlib.sha256(canonical_bytes).hexdigest()
            vendored_hash = hashlib.sha256(vendored_bytes).hexdigest()
            errors.append(
                f"{_display_path(vendored_path, contract_root)}: drifted from canonical {name} "
                f"(canonical sha256={canonical_hash}, vendored sha256={vendored_hash})"
            )
        vendored_schema = _load_json(vendored_path, "vendored schema", errors, contract_root)
        if not isinstance(vendored_schema, dict):
            continue
        schema_id = vendored_schema.get("$id")
        if not isinstance(schema_id, str) or not schema_id:
            errors.append(
                f"{_display_path(vendored_path, contract_root)}: missing non-empty $id"
            )
            continue
        previous = vendored_ids.get(schema_id)
        if previous is not None:
            errors.append(
                f"{_display_path(vendored_path, contract_root)}: duplicate $id {schema_id}; "
                f"already declared by {_display_path(previous, contract_root)}"
            )
        else:
            vendored_ids[schema_id] = vendored_path


def _validate_compatibility_manifest(
    contract_root: Path,
    schemas_by_id: dict[str, tuple[Path, dict[str, Any]]],
    checker: FormatChecker,
    errors: list[str],
    *,
    required: bool,
) -> None:
    manifest_path = contract_root / COMPATIBILITY_MANIFEST
    if not manifest_path.exists():
        if required:
            errors.append(
                f"{COMPATIBILITY_MANIFEST}: missing required consumer compatibility manifest"
            )
        return
    manifest = _load_json(manifest_path, "consumer compatibility manifest", errors, contract_root)
    if not isinstance(manifest, dict):
        return
    if manifest.get("schema") != "loom.contract.consumer-compatibility.v1":
        errors.append(
            f"{_display_path(manifest_path, contract_root)}: invalid manifest schema"
        )
    entries = manifest.get("contracts")
    if not isinstance(entries, list):
        errors.append(
            f"{_display_path(manifest_path, contract_root)}: contracts must be an array"
        )
        return
    if not entries:
        errors.append(
            f"{_display_path(manifest_path, contract_root)}: "
            "contracts must contain at least one entry"
        )
        return

    for index, entry in enumerate(entries):
        prefix = f"{_display_path(manifest_path, contract_root)} /contracts/{index}"
        if not isinstance(entry, dict):
            errors.append(f"{prefix}: entry must be an object")
            continue
        schema_id = entry.get("schemaId")
        replacement_id = entry.get("replacementSchemaId")
        if entry.get("status") != "adapter-required":
            errors.append(f"{prefix}: status must be adapter-required")
        if schema_id not in schemas_by_id:
            errors.append(f"{prefix}: no canonical schema for {schema_id}")
            continue
        if replacement_id not in schemas_by_id:
            errors.append(f"{prefix}: no canonical replacement schema for {replacement_id}")
            continue
        fixture_value = entry.get("compatibilityFixture")
        if not isinstance(fixture_value, str) or not fixture_value:
            errors.append(f"{prefix}: compatibilityFixture must be a path")
            continue
        fixture_path = contract_root / fixture_value
        fixture = _load_json(fixture_path, "compatibility fixture", errors, contract_root)
        if not isinstance(fixture, dict):
            continue
        _validate_instance(
            fixture_path,
            fixture,
            schemas_by_id,
            checker,
            errors,
            contract_root,
            expect_valid=True,
        )
        replacement_fixture = dict(fixture)
        replacement_fixture["schema"] = replacement_id
        replacement_schema = schemas_by_id[replacement_id][1]
        replacement_errors = list(
            Draft202012Validator(
                replacement_schema,
                format_checker=checker,
            ).iter_errors(replacement_fixture)
        )
        if not replacement_errors:
            errors.append(
                f"{prefix}: compatibility fixture no longer demonstrates the declared consumer gap"
            )


def _agent_run_v1_public_projection(
    source: dict[str, Any],
    schemas_by_id: dict[str, tuple[Path, dict[str, Any]]],
) -> dict[str, Any]:
    schema = schemas_by_id["loom.agent.run.v1"][1]
    public_fields = set(schema.get("properties", {}))
    projection = {
        key: value
        for key, value in source.items()
        if key in public_fields
    }
    if projection.get("checkpoint") == "":
        projection.pop("checkpoint")
    return projection


_MIGRATION_TRANSFORMS = {
    "agent-run.v1.public-projection": _agent_run_v1_public_projection,
}


def _validate_migration_manifest(
    contract_root: Path,
    schemas_by_id: dict[str, tuple[Path, dict[str, Any]]],
    errors: list[str],
    *,
    required: bool,
) -> None:
    manifest_path = contract_root / MIGRATION_MANIFEST
    if not manifest_path.exists():
        if required:
            errors.append(f"{MIGRATION_MANIFEST}: missing required migration manifest")
        return
    manifest = _load_json(manifest_path, "migration manifest", errors, contract_root)
    if not isinstance(manifest, dict):
        return
    if manifest.get("schema") != "loom.contract.migrations.v1":
        errors.append(f"{MIGRATION_MANIFEST}: invalid migration manifest schema")
    migrations = manifest.get("migrations")
    if not isinstance(migrations, list) or not migrations:
        errors.append(f"{MIGRATION_MANIFEST}: migrations must contain at least one entry")
        return

    migration_ids: set[str] = set()
    for index, migration in enumerate(migrations):
        prefix = f"{MIGRATION_MANIFEST} /migrations/{index}"
        if not isinstance(migration, dict):
            errors.append(f"{prefix}: migration must be an object")
            continue
        migration_id = migration.get("id")
        if not isinstance(migration_id, str) or not migration_id:
            errors.append(f"{prefix}: id must be a non-empty string")
        elif migration_id in migration_ids:
            errors.append(f"{prefix}: duplicate migration id {migration_id}")
        else:
            migration_ids.add(migration_id)

        source_schema_id = migration.get("sourceSchemaId")
        if source_schema_id not in schemas_by_id:
            errors.append(f"{prefix}: no canonical source schema for {source_schema_id}")
            continue
        transform_name = migration.get("transform")
        transform = _MIGRATION_TRANSFORMS.get(transform_name)
        if transform is None:
            errors.append(f"{prefix}: unknown migration transform {transform_name}")
            continue

        fixture_paths: dict[str, Path] = {}
        invalid_path = False
        for field in ("sourceFixture", "expectedFixture"):
            path_value = migration.get(field)
            if not isinstance(path_value, str) or not path_value:
                errors.append(f"{prefix}: {field} must be a relative path")
                invalid_path = True
                continue
            resolved_path = (contract_root / path_value).resolve()
            try:
                resolved_path.relative_to(contract_root)
            except ValueError:
                errors.append(f"{prefix}: {field} escapes the contract root")
                invalid_path = True
                continue
            fixture_paths[field] = resolved_path
        if invalid_path:
            continue

        source = _load_json(
            fixture_paths["sourceFixture"],
            "migration source fixture",
            errors,
            contract_root,
        )
        expected = _load_json(
            fixture_paths["expectedFixture"],
            "migration expected fixture",
            errors,
            contract_root,
        )
        if not isinstance(source, dict) or not isinstance(expected, dict):
            continue
        if source.get("schema") != source_schema_id:
            errors.append(
                f"{prefix}: source fixture schema does not match {source_schema_id}"
            )
            continue
        actual = transform(source, schemas_by_id)
        if actual != expected:
            errors.append(
                f"{prefix}: transform output does not match expected fixture "
                f"{migration.get('expectedFixture')}"
            )


def validate_contracts(
    *,
    contract_root: Path = CONTRACT_ROOT,
    vendored_schema_root: Path | None = VENDORED_SCHEMA_ROOT,
    format_checker: FormatChecker | None = None,
    require_evolution_assets: bool = True,
) -> list[str]:
    contract_root = Path(contract_root).resolve()
    if vendored_schema_root is not None:
        vendored_schema_root = Path(vendored_schema_root).resolve()
    checker = format_checker if format_checker is not None else build_format_checker()
    errors: list[str] = []
    _validate_inventory_layout(contract_root, errors)

    schema_entries: list[tuple[Path, dict[str, Any]]] = []
    schemas_by_id: dict[str, tuple[Path, dict[str, Any]]] = {}
    for schema_path in _schema_paths(contract_root):
        schema = _load_json(schema_path, "schema", errors, contract_root)
        if schema is _LOAD_FAILED:
            continue
        if not isinstance(schema, dict):
            errors.append(
                f"{_display_path(schema_path, contract_root)}: schema must be a JSON object"
            )
            continue
        try:
            Draft202012Validator.check_schema(schema)
        except SchemaError as error:
            errors.append(
                f"{_display_path(schema_path, contract_root)}: invalid Draft 2020-12 schema: "
                f"{error.message}"
            )
            continue
        schema_id = schema.get("$id")
        if not isinstance(schema_id, str) or not schema_id:
            errors.append(
                f"{_display_path(schema_path, contract_root)}: missing non-empty $id"
            )
            continue
        schema_entries.append((schema_path, schema))
        previous = schemas_by_id.get(schema_id)
        if previous is not None:
            errors.append(
                f"{_display_path(schema_path, contract_root)}: duplicate $id {schema_id}; "
                f"already declared by {_display_path(previous[0], contract_root)}"
            )
        else:
            schemas_by_id[schema_id] = (schema_path, schema)

    if not schema_entries:
        errors.append("no canonical schemas discovered")
        return errors

    _validate_format_support(schema_entries, checker, errors, contract_root)

    fixture_root = contract_root / "fixtures"
    if require_evolution_assets:
        discovered_fixture_paths = {
            path.relative_to(contract_root).as_posix()
            for path in fixture_root.rglob("*.json")
        }
        missing_evolution_fixtures = sorted(
            REQUIRED_EVOLUTION_FIXTURES - discovered_fixture_paths
        )
        for relative_path in missing_evolution_fixtures:
            errors.append(f"{relative_path}: missing required evolution fixture")
    positive_paths = sorted(fixture_root.glob("*.json"))
    positive_ids = _validate_fixture_group(
        positive_paths,
        "positive",
        schemas_by_id,
        checker,
        errors,
        contract_root,
        expect_valid=True,
    )
    for schema_id, (schema_path, _schema) in sorted(schemas_by_id.items()):
        if schema_id not in positive_ids:
            errors.append(
                f"{_display_path(schema_path, contract_root)}: no positive fixture for {schema_id}"
            )

    fixture_groups = (
        ("compat", "compatibility"),
        ("migration", "migration"),
    )
    for group, label in fixture_groups:
        group_paths = sorted((fixture_root / group).glob("*.json"))
        if require_evolution_assets and not group_paths:
            errors.append(f"fixtures/{group}: missing required {label} fixtures")
        _validate_fixture_group(
            group_paths,
            group,
            schemas_by_id,
            checker,
            errors,
            contract_root,
            expect_valid=True,
        )
    negative_paths = sorted((fixture_root / "negative").glob("*.json"))
    if require_evolution_assets and not negative_paths:
        errors.append("fixtures/negative: missing required negative fixtures")
    _validate_fixture_group(
        negative_paths,
        "negative",
        schemas_by_id,
        checker,
        errors,
        contract_root,
        expect_valid=False,
    )

    _validate_compatibility_manifest(
        contract_root,
        schemas_by_id,
        checker,
        errors,
        required=require_evolution_assets,
    )
    _validate_migration_manifest(
        contract_root,
        schemas_by_id,
        errors,
        required=require_evolution_assets,
    )
    if vendored_schema_root is not None:
        _validate_vendored_sync(
            contract_root / "schemas",
            vendored_schema_root,
            errors,
            contract_root,
        )
    return errors


def main() -> int:
    errors = validate_contracts()
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        print(f"Contract validation failed: {len(errors)} error(s).", file=sys.stderr)
        return 1

    positive_count = len(list(FIXTURE_ROOT.glob("*.json")))
    compatibility_count = sum(
        len(list((FIXTURE_ROOT / group).glob("*.json")))
        for group in ("compat", "migration")
    )
    negative_count = len(list((FIXTURE_ROOT / "negative").glob("*.json")))
    schema_count = len(_schema_paths(CONTRACT_ROOT))
    vendored_count = len(list(VENDORED_SCHEMA_ROOT.glob("*.schema.json")))
    print(
        f"Validated {schema_count} canonical Draft 2020-12 schemas, "
        f"{positive_count} positive fixtures, {compatibility_count} compatibility/migration "
        f"fixtures, {negative_count} negative fixtures, and {vendored_count} vendored sync copies."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
