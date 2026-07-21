from __future__ import annotations

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch


PYTHON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)


class SystemInfoContractTests(unittest.TestCase):
    def test_system_info_exposes_bridge_contract_and_capabilities(self) -> None:
        from fastapi import FastAPI
        from fastapi.responses import JSONResponse
        from fastapi.testclient import TestClient

        from api.routes_system import register_system_routes

        app = FastAPI()
        ctx = SimpleNamespace(
            auth_error=lambda _request: None,
            fastapi_json=lambda data, status_code=200: JSONResponse(status_code=status_code, content=data),
            get_updater=lambda: SimpleNamespace(current_version=lambda: "2026.7.16"),
            paths=SimpleNamespace(node_exe="node", base_path="D:/LOOM"),
        )
        register_system_routes(app, ctx)

        with patch.dict(os.environ, {"LOOM_APP_VERSION": "2.1.89"}, clear=False):
            response = TestClient(app).get("/api/system/info")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["api_contract_version"], "loom.bridge.api.v2")
        self.assertEqual(payload["launcher_version"], "2.1.89")
        self.assertIn("phone.config.v2", payload["capabilities"])
        self.assertIn("matrix.dispatch.v2", payload["capabilities"])
        self.assertIn("feishu.reconcile.v1", payload["capabilities"])
        self.assertEqual(payload["bridge"]["apiContractVersion"], "loom.bridge.api.v2")


if __name__ == "__main__":
    unittest.main()
