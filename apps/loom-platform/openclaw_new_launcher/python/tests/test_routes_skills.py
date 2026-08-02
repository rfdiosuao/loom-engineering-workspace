from __future__ import annotations

import os
import sys
import unittest
from types import SimpleNamespace


PYTHON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)

from api.routes_skills import register_skills_routes
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from services.skills import SkillError


class SkillRoutesTests(unittest.TestCase):
    def test_learn_export_and_invocation_are_wired_to_the_skill_service(self) -> None:
        calls: list[object] = []

        class Service:
            def create_learned_skill(self, body):
                calls.append(("learn", body))
                if body.get("confirmed") is not True:
                    raise SkillError("需要用户明确确认后才能沉淀 Skill")
                return {"skill": {"id": "safe-reuse", "name": "安全复用"}}

            def export_zip(self, skill_id):
                calls.append(("export", skill_id))
                return {"id": skill_id, "filename": "safe-reuse.zip", "data": "UEs="}

            def record_invocation(self, skill_id, **kwargs):
                calls.append(("invocation", skill_id, kwargs))
                return {"skill": {"id": skill_id, "invocationCount": 1}}

        async def body(request):
            payload = await request.json()
            return payload if isinstance(payload, dict) else {}

        def fastapi_json(data, status_code=200):
            return JSONResponse(status_code=status_code, content=data)

        app = FastAPI()
        register_skills_routes(
            app,
            SimpleNamespace(
                auth_error=lambda _request: None,
                body=body,
                fastapi_json=fastapi_json,
                get_skill_svc=lambda: Service(),
            ),
        )
        client = TestClient(app)

        rejected = client.post("/api/skills/learn", json={"name": "不安全"})
        learned = client.post(
            "/api/skills/learn",
            json={"name": "安全复用", "confirmed": True, "verifiedSuccess": True},
        )
        exported = client.post("/api/skills/export", json={"id": "safe-reuse"})
        invoked = client.post(
            "/api/skills/invocation",
            json={
                "id": "safe-reuse",
                "success": True,
                "durationMs": 28,
                "agentId": "lumiagent",
                "templateId": "beauty-local",
            },
        )

        self.assertEqual(rejected.status_code, 400)
        self.assertEqual(learned.status_code, 201)
        self.assertEqual(exported.json()["filename"], "safe-reuse.zip")
        self.assertEqual(invoked.json()["skill"]["invocationCount"], 1)
        self.assertEqual(
            calls[-1],
            (
                "invocation",
                "safe-reuse",
                {
                    "success": True,
                    "duration_ms": 28,
                    "agent_id": "lumiagent",
                    "template_id": "beauty-local",
                },
            ),
        )


if __name__ == "__main__":
    unittest.main()
