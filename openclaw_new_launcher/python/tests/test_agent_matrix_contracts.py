from __future__ import annotations

import hashlib
import json
import os
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from tests.agent_matrix_contract_fixtures import CONTRACT_FIXTURES, REALTIME_EVENT


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCHEMA_ROOT = Path(__file__).with_name("contract_schemas")
SCHEMA_SNAPSHOT_SHA256 = {
    "agent-approval.v1.schema.json": "ab2b95be8792c5de46d5d1cf573e6dd00b338f92a5cf4153eff97950a604ea51",
    "agent-message.v1.schema.json": "a982a47cbe8e6e8f4e6f55c70d7f3438dd4256c03630007af663982d3b1fe6a9",
    "agent-run.v1.schema.json": "0b3faa4a3d475f2c55c3acd67748a76d43defb9d3df720a617f97c9321bc6a91",
    "agent-session.v1.schema.json": "6aecc3326c1d2369833d1c600e4f908a36c1f173849dee9044bacacf5b05fc4b",
    "device-lease.v1.schema.json": "fefbd7e727276483ef7263b4609662608292b8810c056f7c3fb2873e0a1951e5",
    "matrix-campaign.v2.schema.json": "997d58c26c201a5836012e7fd7316cb90ade54fe6b742c422b6442cd94c9794d",
    "matrix-dispatch.v2.schema.json": "30a4283f2b8be59ea46024f6bbe0b496c53bf926fb2654ef7767a2913ad76fbd",
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

    def test_contract_fixtures_validate_against_vendored_hub_schemas(self) -> None:
        schemas = {}
        schema_paths = sorted(SCHEMA_ROOT.glob("*.schema.json"))
        self.assertEqual({path.name for path in schema_paths}, set(SCHEMA_SNAPSHOT_SHA256))
        for path in schema_paths:
            snapshot_bytes = path.read_bytes().replace(b"\r\n", b"\n")
            self.assertEqual(
                hashlib.sha256(snapshot_bytes).hexdigest(),
                SCHEMA_SNAPSHOT_SHA256[path.name],
            )
            schema = json.loads(path.read_text(encoding="utf-8"))
            Draft202012Validator.check_schema(schema)
            schemas[schema["$id"]] = schema

        self.assertEqual(len(schemas), 9)
        for fixture in CONTRACT_FIXTURES:
            schema_id = fixture["schema"]
            self.assertIn(schema_id, schemas)
            validator = Draft202012Validator(schemas[schema_id], format_checker=FormatChecker())
            errors = sorted(validator.iter_errors(fixture), key=lambda error: list(error.path))
            self.assertEqual(errors, [], msg="\n".join(error.message for error in errors))

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
