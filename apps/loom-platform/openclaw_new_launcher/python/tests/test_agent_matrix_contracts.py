from __future__ import annotations

import copy
import hashlib
import json
import os
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from tests.agent_matrix_contract_fixtures import CONTRACT_FIXTURES, REALTIME_EVENT


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WORKSPACE_ROOT = Path(__file__).resolve().parents[5]
SCHEMA_ROOT = Path(__file__).with_name("contract_schemas")
CANONICAL_CONTRACT_ROOT = WORKSPACE_ROOT / "packages" / "contracts"
CANONICAL_SCHEMA_ROOT = CANONICAL_CONTRACT_ROOT / "schemas"
SCHEMA_SNAPSHOT_SHA256 = {
    "agent-approval.v1.schema.json": "ab2b95be8792c5de46d5d1cf573e6dd00b338f92a5cf4153eff97950a604ea51",
    "agent-message.v1.schema.json": "a982a47cbe8e6e8f4e6f55c70d7f3438dd4256c03630007af663982d3b1fe6a9",
    "agent-run.v1.schema.json": "a3fcd80172032bf7389de29112efd7fbeb1440b47009ebcf580f7134074a721c",
    "agent-run.v2.schema.json": "b9918cd1a7fff6b200ca9064c7e3b12ffeb4f139c0e6349b9058ee339cd149d2",
    "agent-session.v1.schema.json": "6aecc3326c1d2369833d1c600e4f908a36c1f173849dee9044bacacf5b05fc4b",
    "device-lease.v1.schema.json": "fefbd7e727276483ef7263b4609662608292b8810c056f7c3fb2873e0a1951e5",
    "matrix-campaign.v2.schema.json": "997d58c26c201a5836012e7fd7316cb90ade54fe6b742c422b6442cd94c9794d",
    "matrix-dispatch.v2.schema.json": "30a4283f2b8be59ea46024f6bbe0b496c53bf926fb2654ef7767a2913ad76fbd",
    "matrix-dispatch.v3.schema.json": "2045281eeafdbcc23cf334489c9e704475651dccf5265f28c229e65fb302dcf7",
    "matrix-screen.v1.schema.json": "b92e497f308b120fd60ec6eb38db152253f81215609fc5db9d9a88d04fc74e49",
    "realtime-event.v1.schema.json": "57d2bc4687637316895bc41148c96479163eed94e9b251bb5df05d6cfb014475",
}


class AgentMatrixContractTests(unittest.TestCase):
    def _source(self, relative_path: str) -> str:
        path = os.path.join(REPO_ROOT, *relative_path.split("/"))
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read()

    def test_contract_fixtures_are_json_serializable_and_versioned(self) -> None:
        schema_ids = {fixture["schema"] for fixture in CONTRACT_FIXTURES}

        self.assertEqual(
            schema_ids,
            {
                "loom.realtime.event.v1",
                "loom.matrix.dispatch.v2",
                "loom.matrix.campaign.v2",
                "loom.matrix.screen.v1",
                "loom.matrix.device_lease.v1",
                "loom.agent.session.v1",
                "loom.agent.message.v1",
                "loom.agent.run.v1",
                "loom.agent.approval.v1",
            },
        )
        for fixture in CONTRACT_FIXTURES:
            json.dumps(fixture, ensure_ascii=False)

    def test_clean_ci_requirements_include_jsonschema(self) -> None:
        requirements = self._source("python/requirements.txt")

        self.assertRegex(requirements, r"(?m)^jsonschema>=4\.23,<5\.0$")
        self.assertRegex(requirements, r"(?m)^rfc3339-validator>=0\.1\.4,<1\.0$")

    def test_contract_fixtures_validate_against_vendored_hub_schemas(self) -> None:
        schemas = {}
        schema_paths = sorted(SCHEMA_ROOT.glob("*.schema.json"))
        self.assertEqual({path.name for path in schema_paths}, set(SCHEMA_SNAPSHOT_SHA256))
        for path in schema_paths:
            snapshot_bytes = path.read_bytes().replace(b"\r\n", b"\n")
            canonical_path = CANONICAL_SCHEMA_ROOT / path.name
            self.assertTrue(canonical_path.is_file())
            self.assertEqual(
                snapshot_bytes,
                canonical_path.read_bytes().replace(b"\r\n", b"\n"),
                msg=f"{path.name} drifted from packages/contracts",
            )
            self.assertEqual(
                hashlib.sha256(snapshot_bytes).hexdigest(),
                SCHEMA_SNAPSHOT_SHA256[path.name],
            )
            schema = json.loads(path.read_text(encoding="utf-8"))
            Draft202012Validator.check_schema(schema)
            schemas[schema["$id"]] = schema

        self.assertEqual(len(schemas), 11)
        for fixture in CONTRACT_FIXTURES:
            schema_id = fixture["schema"]
            self.assertIn(schema_id, schemas)
            validator = Draft202012Validator(schemas[schema_id], format_checker=FormatChecker())
            errors = sorted(validator.iter_errors(fixture), key=lambda error: list(error.path))
            self.assertEqual(errors, [], msg="\n".join(error.message for error in errors))

    def test_agent_run_v1_reads_history_and_keeps_private_producer_state_out(self) -> None:
        schema = json.loads((SCHEMA_ROOT / "agent-run.v1.schema.json").read_text(encoding="utf-8"))
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        historical = json.loads(
            (CANONICAL_CONTRACT_ROOT / "fixtures" / "compat" / "agent-run.v1.initial.json").read_text(
                encoding="utf-8"
            )
        )
        public_projection = json.loads(
            (
                CANONICAL_CONTRACT_ROOT
                / "fixtures"
                / "migration"
                / "agent-run.v1.public-projection.json"
            ).read_text(encoding="utf-8")
        )
        private_producer = json.loads(
            (
                CANONICAL_CONTRACT_ROOT
                / "fixtures"
                / "negative"
                / "agent-run.v1.private-producer.json"
            ).read_text(encoding="utf-8")
        )

        self.assertEqual(list(validator.iter_errors(historical)), [])
        self.assertEqual(list(validator.iter_errors(public_projection)), [])
        producer_errors = list(validator.iter_errors(private_producer))
        self.assertTrue(any(list(error.path) == ["checkpoint"] for error in producer_errors))
        root_messages = "\n".join(error.message for error in producer_errors if not error.path)
        self.assertIn("ownerAccountId", root_messages)
        self.assertIn("request", root_messages)
        self.assertNotIn("modelId", root_messages)
        self.assertNotIn("modelSource", root_messages)

        v2_schema = json.loads((SCHEMA_ROOT / "agent-run.v2.schema.json").read_text(encoding="utf-8"))
        v2_fixture = json.loads(
            (CANONICAL_CONTRACT_ROOT / "fixtures" / "agent-run.v2.json").read_text(encoding="utf-8")
        )
        self.assertIn("executionState", v2_schema["required"])
        self.assertEqual(list(Draft202012Validator(v2_schema).iter_errors(v2_fixture)), [])

    def test_matrix_v2_compatibility_and_v3_consumer_bounds_are_both_explicit(self) -> None:
        v2_schema = json.loads((SCHEMA_ROOT / "matrix-dispatch.v2.schema.json").read_text(encoding="utf-8"))
        v3_schema = json.loads((SCHEMA_ROOT / "matrix-dispatch.v3.schema.json").read_text(encoding="utf-8"))
        v2_fixture = json.loads(
            (
                CANONICAL_CONTRACT_ROOT
                / "fixtures"
                / "compat"
                / "matrix-dispatch.v2.consumer-gap.json"
            ).read_text(encoding="utf-8")
        )
        v3_fixture = json.loads(
            (CANONICAL_CONTRACT_ROOT / "fixtures" / "matrix-dispatch.v3.json").read_text(encoding="utf-8")
        )

        v2_cases = [v2_fixture]
        v2_published_min = copy.deepcopy(v2_fixture)
        v2_published_min["concurrency"] = 1
        v2_published_min["deviceAssignments"][0]["timeoutSec"] = 1
        v2_cases.append(v2_published_min)
        v2_timeout_high = copy.deepcopy(v2_fixture)
        v2_timeout_high["deviceAssignments"][0]["timeoutSec"] = 1201
        v2_cases.append(v2_timeout_high)
        v2_prompt = copy.deepcopy(v2_fixture)
        v2_prompt["deviceAssignments"][0]["prompt"] = "p" * 2001
        v2_cases.append(v2_prompt)
        v2_template = copy.deepcopy(v2_fixture)
        v2_template["deviceAssignments"][0]["templateId"] = "t" * 81
        v2_cases.append(v2_template)
        v2_assignments = copy.deepcopy(v2_fixture)
        v2_assignments["deviceAssignments"] = [
            {
                **copy.deepcopy(v2_fixture["deviceAssignments"][0]),
                "assignmentId": f"assignment-{index}",
                "deviceId": f"device-{index}",
            }
            for index in range(101)
        ]
        v2_cases.append(v2_assignments)
        v2_validator = Draft202012Validator(v2_schema)
        for case in v2_cases:
            self.assertEqual(list(v2_validator.iter_errors(case)), [])
        v3_validator = Draft202012Validator(v3_schema)

        def v3_assignments(count: int) -> list[dict]:
            return [
                {
                    **copy.deepcopy(v3_fixture["deviceAssignments"][0]),
                    "assignmentId": f"assignment-{index}",
                    "deviceId": f"device-{index}",
                }
                for index in range(count)
            ]

        valid_cases = [v3_fixture]
        for value in (1, 8):
            case = copy.deepcopy(v3_fixture)
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
            case = copy.deepcopy(v3_fixture)
            case["deviceAssignments"][0][field] = value
            valid_cases.append(case)
        assignments_max = copy.deepcopy(v3_fixture)
        assignments_max["deviceAssignments"] = v3_assignments(100)
        valid_cases.append(assignments_max)
        nested_input = copy.deepcopy(v3_fixture)
        nested_input["deviceAssignments"][0]["input"] = {
            "scalar": "value",
            "array": [1, True, None, {"nested": [3]}],
            "object": {"child": {"enabled": False}},
        }
        valid_cases.append(nested_input)
        for case in valid_cases:
            self.assertEqual(list(v3_validator.iter_errors(case)), [])

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

        collect_additional_properties(v3_schema)
        self.assertNotEqual(additional_properties_values, [])
        self.assertTrue(all(value is False for value in additional_properties_values))

        invalid_cases = []
        for value in (0, 9):
            case = copy.deepcopy(v3_fixture)
            case["concurrency"] = value
            invalid_cases.append(case)
        for field, value in (
            ("timeoutSec", 29),
            ("timeoutSec", 1201),
            ("prompt", ""),
            ("prompt", "p" * 2001),
            ("templateId", ""),
            ("templateId", "t" * 81),
        ):
            case = copy.deepcopy(v3_fixture)
            case["deviceAssignments"][0][field] = value
            invalid_cases.append(case)
        assignments_empty = copy.deepcopy(v3_fixture)
        assignments_empty["deviceAssignments"] = []
        invalid_cases.append(assignments_empty)
        assignments = copy.deepcopy(v3_fixture)
        assignments["deviceAssignments"] = v3_assignments(101)
        invalid_cases.append(assignments)
        for case in invalid_cases:
            self.assertNotEqual(list(v3_validator.iter_errors(case)), [])

    def test_date_time_format_dependency_rejects_invalid_canary(self) -> None:
        schema = json.loads((SCHEMA_ROOT / "agent-session.v1.schema.json").read_text(encoding="utf-8"))
        invalid = json.loads(
            (
                CANONICAL_CONTRACT_ROOT
                / "fixtures"
                / "negative"
                / "agent-session.v1.invalid-date-time.json"
            ).read_text(encoding="utf-8")
        )

        errors = list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(invalid))

        self.assertTrue(any(list(error.path) == ["createdAt"] for error in errors))

    def test_assignment_event_retains_all_cross_system_identifiers(self) -> None:
        data = REALTIME_EVENT["data"]

        self.assertEqual(REALTIME_EVENT["entityId"], data["deviceTaskId"])
        for field in (
            "campaignId",
            "assignmentId",
            "deviceTaskId",
            "deviceId",
            "jobId",
            "attempt",
            "status",
        ):
            self.assertIn(field, data)

    def test_typescript_contracts_freeze_all_schema_ids(self) -> None:
        sources = "\n".join(
            self._source(path)
            for path in (
                "src/types/realtime.ts",
                "src/types/matrix.ts",
                "src/types/agent.ts",
            )
        )

        for fixture in CONTRACT_FIXTURES:
            self.assertIn(fixture["schema"], sources)

    def test_api_contract_exposes_agent_and_matrix_control_surfaces(self) -> None:
        source = self._source("src/services/api.ts")

        for export_name in ("realtimeApi", "agentApi", "matrixApi"):
            self.assertIn(f"export const {export_name}", source)
        for path in (
            "/api/realtime/tickets",
            "/api/agent/bootstrap",
            "/api/agent/sessions",
            "/api/agent/runs/",
            "/api/agent/approvals/",
            "/api/matrix/cancel",
            "/api/matrix/retry",
            "/screen",
            "/timeline",
            "/lease",
            "/control",
            "/pause",
            "/resume",
            "/api/matrix/emergency-stop",
        ):
            self.assertIn(path, source)

    def test_frontend_contract_never_requests_a_long_lived_bridge_token(self) -> None:
        realtime_source = self._source("src/services/realtimeStream.ts")
        api_source = self._source("src/services/api.ts")

        self.assertNotIn("X-Bridge-Token", realtime_source)
        self.assertNotIn("get_bridge_token", realtime_source)
        self.assertNotIn("get_bridge_token", api_source)
        self.assertIn("ticket", realtime_source)

    def test_loom_client_and_contract_barrel_expose_platform_contracts(self) -> None:
        client_source = self._source("src/services/loomClient.ts")
        contracts_source = self._source("src/services/loomContracts.ts")

        for api_name in ("agentApi", "matrixApi", "realtimeApi"):
            self.assertIn(api_name, client_source)
        for type_module in ("../types/agent", "../types/matrix", "../types/realtime"):
            self.assertIn(type_module, contracts_source)


if __name__ == "__main__":
    unittest.main()
