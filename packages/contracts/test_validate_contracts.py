from __future__ import annotations

import copy
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker


CONTRACT_ROOT = Path(__file__).resolve().parent
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

sys.path.insert(0, str(CONTRACT_ROOT))
import validate_contracts as gate  # noqa: E402


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _errors(schema: dict, fixture: dict, *, checker: FormatChecker | None = None):
    validator = Draft202012Validator(schema, format_checker=checker)
    return sorted(validator.iter_errors(fixture), key=lambda error: list(error.path))


class ContractEvolutionTests(unittest.TestCase):
    def test_published_agent_run_v1_without_execution_state_remains_readable(self) -> None:
        schema = _load(CONTRACT_ROOT / "schemas" / "agent-run.v1.schema.json")
        historical = _load(CONTRACT_ROOT / "fixtures" / "compat" / "agent-run.v1.initial.json")

        self.assertEqual(_errors(schema, historical), [])

    def test_agent_run_v2_requires_execution_state(self) -> None:
        schema = _load(CONTRACT_ROOT / "schemas" / "agent-run.v2.schema.json")
        fixture = _load(CONTRACT_ROOT / "fixtures" / "agent-run.v2.json")
        missing_execution_state = dict(fixture)
        missing_execution_state.pop("executionState")

        self.assertIn("executionState", schema["required"])
        self.assertEqual(_errors(schema, fixture), [])
        self.assertTrue(
            any(error.validator == "required" for error in _errors(schema, missing_execution_state))
        )

    def test_canonical_schemas_are_the_only_vendored_source_of_truth(self) -> None:
        canonical_paths = sorted((CONTRACT_ROOT / "schemas").glob("*.schema.json"))
        vendored_paths = sorted(VENDORED_SCHEMA_ROOT.glob("*.schema.json"))

        self.assertEqual([path.name for path in vendored_paths], [path.name for path in canonical_paths])
        for canonical_path, vendored_path in zip(canonical_paths, vendored_paths, strict=True):
            self.assertEqual(
                vendored_path.read_bytes().replace(b"\r\n", b"\n"),
                canonical_path.read_bytes().replace(b"\r\n", b"\n"),
                msg=f"{vendored_path.name} drifted from canonical",
            )

    def test_agent_run_public_projection_accepts_models_but_rejects_private_producer_state(self) -> None:
        schema = _load(CONTRACT_ROOT / "schemas" / "agent-run.v1.schema.json")
        public_projection = _load(
            CONTRACT_ROOT / "fixtures" / "migration" / "agent-run.v1.public-projection.json"
        )
        private_producer = _load(
            CONTRACT_ROOT / "fixtures" / "negative" / "agent-run.v1.private-producer.json"
        )

        self.assertEqual(_errors(schema, public_projection), [])
        private_errors = _errors(schema, private_producer)
        self.assertTrue(any(list(error.path) == ["checkpoint"] for error in private_errors))
        root_messages = "\n".join(error.message for error in private_errors if not error.path)
        self.assertIn("ownerAccountId", root_messages)
        self.assertIn("request", root_messages)
        self.assertNotIn("modelId", root_messages)
        self.assertNotIn("modelSource", root_messages)
        self.assertFalse(any(error.validator == "required" for error in private_errors))

    def test_matrix_v2_schema_accepts_published_inputs_and_tracks_bounded_adapter(self) -> None:
        schema = _load(CONTRACT_ROOT / "schemas" / "matrix-dispatch.v2.schema.json")
        fixture = _load(
            CONTRACT_ROOT / "fixtures" / "compat" / "matrix-dispatch.v2.consumer-gap.json"
        )

        cases = [fixture]
        published_min_case = copy.deepcopy(fixture)
        published_min_case["concurrency"] = 1
        published_min_case["deviceAssignments"][0]["timeoutSec"] = 1
        cases.append(published_min_case)
        assignments_case = copy.deepcopy(fixture)
        assignments_case["deviceAssignments"] = [
            {
                **copy.deepcopy(fixture["deviceAssignments"][0]),
                "assignmentId": f"assignment-{index}",
                "deviceId": f"device-{index}",
            }
            for index in range(101)
        ]
        cases.append(assignments_case)
        prompt_case = copy.deepcopy(fixture)
        prompt_case["deviceAssignments"][0]["prompt"] = "p" * 2001
        cases.append(prompt_case)
        template_case = copy.deepcopy(fixture)
        template_case["deviceAssignments"][0]["templateId"] = "t" * 81
        cases.append(template_case)
        timeout_high_case = copy.deepcopy(fixture)
        timeout_high_case["deviceAssignments"][0]["timeoutSec"] = 1201
        cases.append(timeout_high_case)

        for case in cases:
            self.assertEqual(_errors(schema, case), [])

        compatibility = _load(CONTRACT_ROOT / "consumer-compatibility.v1.json")
        entry = next(
            item
            for item in compatibility["contracts"]
            if item["schemaId"] == "loom.matrix.dispatch.v2"
        )
        self.assertEqual(entry["status"], "supported")
        self.assertEqual(entry["replacementSchemaId"], "loom.matrix.dispatch.v3")
        self.assertEqual(
            entry["limits"],
            {
                "concurrency": {"maximum": 8},
                "deviceAssignments": {"maximumItems": 100},
                "prompt": {"maximumLength": 2000},
                "retryBudget": {"maximum": 10},
                "templateId": {"maximumLength": 80},
                "timeoutSec": {"minimum": 30, "maximum": 1200},
            },
        )

    def test_matrix_v3_matches_current_consumer_boundaries(self) -> None:
        schema = _load(CONTRACT_ROOT / "schemas" / "matrix-dispatch.v3.schema.json")
        fixture = _load(CONTRACT_ROOT / "fixtures" / "matrix-dispatch.v3.json")
        compatibility = _load(CONTRACT_ROOT / "consumer-compatibility.v1.json")
        limits = next(
            item["limits"]
            for item in compatibility["contracts"]
            if item["replacementSchemaId"] == schema["$id"]
        )

        assignment_schema = schema["$defs"]["assignment"]["properties"]
        self.assertEqual(schema["properties"]["concurrency"]["maximum"], limits["concurrency"]["maximum"])
        self.assertEqual(
            schema["properties"]["deviceAssignments"]["maxItems"],
            limits["deviceAssignments"]["maximumItems"],
        )
        self.assertEqual(assignment_schema["prompt"]["maxLength"], limits["prompt"]["maximumLength"])
        self.assertEqual(
            assignment_schema["templateId"]["maxLength"],
            limits["templateId"]["maximumLength"],
        )
        self.assertEqual(assignment_schema["timeoutSec"]["minimum"], limits["timeoutSec"]["minimum"])
        self.assertEqual(assignment_schema["timeoutSec"]["maximum"], limits["timeoutSec"]["maximum"])

        def assignments(count: int) -> list[dict]:
            return [
                {
                    **copy.deepcopy(fixture["deviceAssignments"][0]),
                    "assignmentId": f"assignment-{index}",
                    "deviceId": f"device-{index}",
                }
                for index in range(count)
            ]

        valid_cases = [fixture]
        for value in (1, 8):
            case = copy.deepcopy(fixture)
            case["concurrency"] = value
            valid_cases.append(case)
        for field, value in (
            ("timeoutSec", 30),
            ("timeoutSec", 1200),
            ("prompt", "p"),
            ("prompt", "p" * 2000),
            ("templateId", "t"),
            ("templateId", "t" * 80),
        ):
            case = copy.deepcopy(fixture)
            case["deviceAssignments"][0][field] = value
            valid_cases.append(case)
        assignments_max = copy.deepcopy(fixture)
        assignments_max["deviceAssignments"] = assignments(100)
        valid_cases.append(assignments_max)
        nested_input = copy.deepcopy(fixture)
        nested_input["deviceAssignments"][0]["input"] = {
            "string": "value",
            "number": 1.5,
            "boolean": True,
            "null": None,
            "array": [1, "two", False, None, {"nested": [3]}],
            "object": {"child": {"enabled": True}},
        }
        valid_cases.append(nested_input)
        for case in valid_cases:
            self.assertEqual(_errors(schema, case), [])

        additional_properties_values = []

        def collect_additional_properties(value: object) -> None:
            if isinstance(value, dict):
                if "additionalProperties" in value:
                    additional_properties_values.append(value["additionalProperties"])
                for nested in value.values():
                    collect_additional_properties(nested)
            elif isinstance(value, list):
                for nested in value:
                    collect_additional_properties(nested)

        collect_additional_properties(schema)
        self.assertNotEqual(additional_properties_values, [])
        self.assertTrue(all(value is False for value in additional_properties_values))

        invalid_cases = []
        for field, value in (("concurrency", 0), ("concurrency", 9)):
            case = copy.deepcopy(fixture)
            case[field] = value
            invalid_cases.append(case)
        for field, value in (
            ("timeoutSec", 29),
            ("timeoutSec", 1201),
            ("prompt", ""),
            ("prompt", "p" * 2001),
            ("templateId", ""),
            ("templateId", "t" * 81),
        ):
            case = copy.deepcopy(fixture)
            case["deviceAssignments"][0][field] = value
            invalid_cases.append(case)
        assignments_empty = copy.deepcopy(fixture)
        assignments_empty["deviceAssignments"] = []
        invalid_cases.append(assignments_empty)
        assignments_case = copy.deepcopy(fixture)
        assignments_case["deviceAssignments"] = assignments(101)
        invalid_cases.append(assignments_case)

        for case in invalid_cases:
            self.assertNotEqual(_errors(schema, case), [])

    def test_matrix_v3_locks_ids_retry_and_shared_template_dto(self) -> None:
        schema = _load(CONTRACT_ROOT / "schemas" / "matrix-dispatch.v3.schema.json")
        fixture = _load(CONTRACT_ROOT / "fixtures" / "matrix-dispatch.v3.json")
        assignment_properties = schema["$defs"]["assignment"]["properties"]

        self.assertEqual(assignment_properties["retryBudget"]["maximum"], 10)
        id_schemas = (
            schema["properties"]["campaignId"],
            assignment_properties["assignmentId"],
            assignment_properties["deviceId"],
        )
        for id_schema in id_schemas:
            self.assertEqual(id_schema["maxLength"], 200)
            self.assertIn("pattern", id_schema)
        for text_schema in (
            assignment_properties["prompt"],
            assignment_properties["templateId"],
        ):
            self.assertIn("pattern", text_schema)

        valid_cases = []
        for field, value in (("campaignId", "c"), ("campaignId", "c" * 200)):
            case = copy.deepcopy(fixture)
            case[field] = value
            valid_cases.append(case)
        for field in ("assignmentId", "deviceId"):
            for value in ("i", "i" * 200):
                case = copy.deepcopy(fixture)
                case["deviceAssignments"][0][field] = value
                valid_cases.append(case)
        for value in (0, 10):
            case = copy.deepcopy(fixture)
            case["deviceAssignments"][0]["retryBudget"] = value
            valid_cases.append(case)
        reference = copy.deepcopy(fixture)
        reference["deviceAssignments"][0]["input"] = {
            "sharedTemplate": {"templateId": "beauty-runtime", "version": 1}
        }
        valid_cases.append(reference)
        resolved = copy.deepcopy(fixture)
        resolved["deviceAssignments"][0]["input"] = {
            "sharedTemplate": {
                "templateId": "beauty-runtime",
                "version": 1,
                "name": "Beauty runtime",
                "industry": "beauty",
                "platforms": ["xiaohongshu"],
                "targetCustomer": "local customers",
                "keywords": ["skin care"],
                "leadRules": ["asks price"],
                "replyStyle": "confirm needs first",
                "safetyPolicy": {"outbound": False},
                "feishuMapping": {"table": "leads"},
            }
        }
        valid_cases.append(resolved)
        for case in valid_cases:
            self.assertEqual(_errors(schema, case), [])

        invalid_cases = []
        for target, field in (
            ("root", "campaignId"),
            ("assignment", "assignmentId"),
            ("assignment", "deviceId"),
        ):
            for value in ("", "   ", "bad\x00id", "i" * 201):
                case = copy.deepcopy(fixture)
                if target == "root":
                    case[field] = value
                else:
                    case["deviceAssignments"][0][field] = value
                invalid_cases.append(case)
            missing = copy.deepcopy(fixture)
            if target == "root":
                del missing[field]
            else:
                del missing["deviceAssignments"][0][field]
            invalid_cases.append(missing)
        for field in ("prompt", "templateId"):
            for value in ("   ", "bad\x00text"):
                case = copy.deepcopy(fixture)
                case["deviceAssignments"][0][field] = value
                invalid_cases.append(case)
        for value in (-1, 11):
            case = copy.deepcopy(fixture)
            case["deviceAssignments"][0]["retryBudget"] = value
            invalid_cases.append(case)
        bad_reference = copy.deepcopy(reference)
        bad_reference["deviceAssignments"][0]["input"]["sharedTemplate"]["version"] = 0
        invalid_cases.append(bad_reference)
        incomplete_resolved = copy.deepcopy(resolved)
        del incomplete_resolved["deviceAssignments"][0]["input"]["sharedTemplate"]["replyStyle"]
        invalid_cases.append(incomplete_resolved)
        unknown_shared_field = copy.deepcopy(reference)
        unknown_shared_field["deviceAssignments"][0]["input"]["sharedTemplate"]["unknown"] = True
        invalid_cases.append(unknown_shared_field)
        for case in invalid_cases:
            self.assertNotEqual(_errors(schema, case), [])

    def test_invalid_date_time_is_rejected_without_optional_checker_silence(self) -> None:
        schema = _load(CONTRACT_ROOT / "schemas" / "agent-session.v1.schema.json")
        fixture = _load(
            CONTRACT_ROOT / "fixtures" / "negative" / "agent-session.v1.invalid-date-time.json"
        )

        errors = _errors(schema, fixture, checker=gate.build_format_checker())

        self.assertTrue(any(list(error.path) == ["createdAt"] for error in errors))


class ContractInventoryTests(unittest.TestCase):
    def _write_json(self, path: Path, value: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")

    def _minimal_tree(self, root: Path) -> None:
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "loom.test.v1",
            "type": "object",
            "required": ["schema", "timestamp"],
            "properties": {
                "schema": {"const": "loom.test.v1"},
                "timestamp": {"type": "string", "format": "date-time"},
            },
            "additionalProperties": False,
        }
        self._write_json(root / "schemas" / "test.v1.schema.json", schema)
        self._write_json(
            root / "fixtures" / "test.v1.json",
            {"schema": "loom.test.v1", "timestamp": "2026-08-08T10:00:00+08:00"},
        )

    def test_duplicate_schema_ids_and_orphan_fixtures_fail_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._minimal_tree(root)
            duplicate = _load(root / "schemas" / "test.v1.schema.json")
            self._write_json(root / "schemas" / "duplicate.schema.json", duplicate)
            unused = copy.deepcopy(duplicate)
            unused["$id"] = "loom.unused.v1"
            unused["properties"]["schema"]["const"] = "loom.unused.v1"
            self._write_json(root / "schemas" / "unused.schema.json", unused)
            self._write_json(
                root / "fixtures" / "orphan.json",
                {"schema": "loom.orphan.v1", "timestamp": "2026-08-08T10:00:00+08:00"},
            )

            errors = gate.validate_contracts(
                contract_root=root,
                vendored_schema_root=None,
                require_evolution_assets=False,
            )

        messages = "\n".join(errors)
        self.assertIn("duplicate $id loom.test.v1", messages)
        self.assertIn("no canonical schema for loom.orphan.v1", messages)
        self.assertIn("no positive fixture for loom.unused.v1", messages)

    def test_vendored_same_id_content_drift_reports_both_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "contracts"
            vendored_root = Path(directory) / "vendored"
            self._minimal_tree(root)
            vendored = _load(root / "schemas" / "test.v1.schema.json")
            vendored["description"] = "silent same-ID fork"
            self._write_json(vendored_root / "test.v1.schema.json", vendored)

            errors = gate.validate_contracts(
                contract_root=root,
                vendored_schema_root=vendored_root,
                require_evolution_assets=False,
            )

        messages = "\n".join(errors)
        self.assertIn("drifted from canonical test.v1.schema.json", messages)
        self.assertIn("canonical sha256=", messages)
        self.assertIn("vendored sha256=", messages)

    def test_missing_format_checker_cannot_make_negative_fixture_green(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._minimal_tree(root)
            self._write_json(
                root / "fixtures" / "negative" / "invalid-date-time.json",
                {"schema": "loom.test.v1", "timestamp": "not-a-date"},
            )

            errors = gate.validate_contracts(
                contract_root=root,
                vendored_schema_root=None,
                format_checker=FormatChecker(formats=[]),
                require_evolution_assets=False,
            )

        self.assertTrue(any("format checker unavailable for date-time" in error for error in errors))

    def test_default_gate_requires_every_evolution_fixture_group_and_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._minimal_tree(root)

            errors = gate.validate_contracts(
                contract_root=root,
                vendored_schema_root=None,
            )
            self._write_json(
                root / "consumer-compatibility.v1.json",
                {
                    "schema": "loom.contract.consumer-compatibility.v1",
                    "contracts": [],
                },
            )
            invalid_manifest_errors = gate.validate_contracts(
                contract_root=root,
                vendored_schema_root=None,
            )

        messages = "\n".join(errors)
        self.assertIn("fixtures/compat: missing required compatibility fixtures", messages)
        self.assertIn("fixtures/migration: missing required migration fixtures", messages)
        self.assertIn("fixtures/negative: missing required negative fixtures", messages)
        self.assertIn(
            "consumer-compatibility.v1.json: missing required consumer compatibility manifest",
            messages,
        )
        self.assertIn(
            "consumer-compatibility.v1.json: contracts must contain at least one entry",
            "\n".join(invalid_manifest_errors),
        )

    def test_default_gate_requires_each_named_evolution_fixture(self) -> None:
        required_fixtures = (
            "fixtures/compat/agent-run.v1.initial.json",
            "fixtures/compat/matrix-dispatch.v2.consumer-gap.json",
            "fixtures/migration/agent-run.v1.public-projection.json",
            "fixtures/negative/agent-run.v1.private-producer.json",
            "fixtures/negative/agent-session.v1.invalid-date-time.json",
        )

        for missing_fixture in required_fixtures:
            with self.subTest(missing_fixture=missing_fixture), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self._minimal_tree(root)
                v2_schema = _load(root / "schemas" / "test.v1.schema.json")
                v2_schema["$id"] = "loom.test.v2"
                v2_schema["required"].append("newField")
                v2_schema["properties"]["schema"]["const"] = "loom.test.v2"
                v2_schema["properties"]["newField"] = {"type": "string"}
                self._write_json(root / "schemas" / "test.v2.schema.json", v2_schema)
                self._write_json(
                    root / "fixtures" / "test.v2.json",
                    {
                        "schema": "loom.test.v2",
                        "timestamp": "2026-08-08T10:00:00+08:00",
                        "newField": "v2",
                    },
                )
                valid_fixture = {
                    "schema": "loom.test.v1",
                    "timestamp": "2026-08-08T10:00:00+08:00",
                }
                invalid_fixture = {
                    "schema": "loom.test.v1",
                    "timestamp": "not-a-date",
                }
                for fixture_path in required_fixtures:
                    self._write_json(
                        root / fixture_path,
                        invalid_fixture if "/negative/" in fixture_path else valid_fixture,
                    )
                self._write_json(
                    root / "consumer-compatibility.v1.json",
                    {
                        "schema": "loom.contract.consumer-compatibility.v1",
                        "contracts": [
                            {
                                "schemaId": "loom.test.v1",
                                "consumer": "test.consumer",
                                "status": "adapter-required",
                                "replacementSchemaId": "loom.test.v2",
                                "compatibilityFixture": (
                                    "fixtures/compat/matrix-dispatch.v2.consumer-gap.json"
                                ),
                                "limits": {"test": True},
                            }
                        ],
                    },
                )
                (root / missing_fixture).unlink()

                errors = gate.validate_contracts(
                    contract_root=root,
                    vendored_schema_root=None,
                )

                self.assertIn(
                    f"{missing_fixture}: missing required evolution fixture",
                    "\n".join(errors),
                )

    def test_inventory_rejects_unknown_root_json_nested_schema_and_unknown_fixture_group(self) -> None:
        cases = (
            (
                "unknown-root-json",
                "unexpected.json: unknown contract-root JSON document",
            ),
            (
                "nested-schema",
                "schemas/nested/rogue.schema.json: nested schema is not allowed",
            ),
            (
                "unknown-fixture-group",
                "fixtures/archive: unknown fixture group",
            ),
            (
                "nested-fixture",
                "fixtures/compat/archive/rogue.json: unknown nested fixture path",
            ),
            (
                "unknown-nested-json",
                "rogue/nested.json: unknown contract inventory path",
            ),
        )
        for case_name, expected_error in cases:
            with self.subTest(case_name=case_name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self._minimal_tree(root)
                if case_name == "unknown-root-json":
                    self._write_json(root / "unexpected.json", {})
                elif case_name == "nested-schema":
                    self._write_json(
                        root / "schemas" / "nested" / "rogue.schema.json",
                        _load(root / "schemas" / "test.v1.schema.json"),
                    )
                elif case_name == "unknown-fixture-group":
                    self._write_json(
                        root / "fixtures" / "archive" / "rogue.json",
                        {
                            "schema": "loom.test.v1",
                            "timestamp": "2026-08-08T10:00:00+08:00",
                        },
                    )
                elif case_name == "nested-fixture":
                    self._write_json(
                        root / "fixtures" / "compat" / "archive" / "rogue.json",
                        {
                            "schema": "loom.test.v1",
                            "timestamp": "2026-08-08T10:00:00+08:00",
                        },
                    )
                else:
                    self._write_json(root / "rogue" / "nested.json", {})

                errors = gate.validate_contracts(
                    contract_root=root,
                    vendored_schema_root=None,
                    require_evolution_assets=False,
                )

                self.assertIn(expected_error, "\n".join(errors))

    def test_inventory_keeps_additional_root_positive_fixtures_dynamic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._minimal_tree(root)
            extra_schema = _load(root / "schemas" / "test.v1.schema.json")
            extra_schema["$id"] = "loom.extra.v1"
            extra_schema["properties"]["schema"]["const"] = "loom.extra.v1"
            self._write_json(root / "schemas" / "extra.v1.schema.json", extra_schema)
            self._write_json(
                root / "fixtures" / "extra.v1.json",
                {
                    "schema": "loom.extra.v1",
                    "timestamp": "2026-08-08T10:00:00+08:00",
                },
            )

            errors = gate.validate_contracts(
                contract_root=root,
                vendored_schema_root=None,
                require_evolution_assets=False,
            )

        self.assertEqual(errors, [])

    def test_default_gate_requires_executable_migration_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "contracts"
            shutil.copytree(CONTRACT_ROOT, root)
            migration_manifest = root / "migrations.v1.json"
            if migration_manifest.exists():
                migration_manifest.unlink()

            errors = gate.validate_contracts(
                contract_root=root,
                vendored_schema_root=None,
            )

        self.assertIn(
            "migrations.v1.json: missing required migration manifest",
            "\n".join(errors),
        )

    def test_migration_gate_rejects_unknown_transform_and_expected_mismatch(self) -> None:
        base_manifest = {
            "schema": "loom.contract.migrations.v1",
            "migrations": [
                {
                    "id": "agent-run.v1.private-to-public",
                    "sourceSchemaId": "loom.agent.run.v1",
                    "sourceFixture": "fixtures/negative/agent-run.v1.private-producer.json",
                    "transform": "agent-run.v1.public-projection",
                    "expectedFixture": "fixtures/migration/agent-run.v1.public-projection.json",
                }
            ],
        }
        cases = (
            (
                "unknown-transform",
                "unknown migration transform agent-run.v1.missing-transform",
            ),
            (
                "expected-mismatch",
                "transform output does not match expected fixture",
            ),
        )
        for case_name, expected_error in cases:
            with self.subTest(case_name=case_name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory) / "contracts"
                shutil.copytree(CONTRACT_ROOT, root)
                manifest = copy.deepcopy(base_manifest)
                if case_name == "unknown-transform":
                    manifest["migrations"][0]["transform"] = "agent-run.v1.missing-transform"
                else:
                    expected_path = (
                        root / "fixtures" / "migration" / "agent-run.v1.public-projection.json"
                    )
                    expected = _load(expected_path)
                    expected["campaignIds"] = ["unexpected-campaign"]
                    self._write_json(expected_path, expected)
                self._write_json(root / "migrations.v1.json", manifest)

                errors = gate.validate_contracts(
                    contract_root=root,
                    vendored_schema_root=None,
                )

                self.assertIn(expected_error, "\n".join(errors))

    def test_workspace_ci_runs_contract_unit_suite_before_contract_cli(self) -> None:
        workflow = (REPO_ROOT / ".github" / "workflows" / "workspace-ci.yml").read_text(
            encoding="utf-8"
        )
        unit_command = "python -B .\\packages\\contracts\\test_validate_contracts.py"
        cli_command = "python -B .\\packages\\contracts\\validate_contracts.py"
        format_dependency = "rfc3339-validator==0.1.4"

        self.assertIn(format_dependency, workflow)
        self.assertIn(unit_command, workflow)
        self.assertIn(cli_command, workflow)
        self.assertLess(workflow.index(format_dependency), workflow.index(unit_command))
        self.assertLess(workflow.index(unit_command), workflow.index(cli_command))


if __name__ == "__main__":
    unittest.main()
