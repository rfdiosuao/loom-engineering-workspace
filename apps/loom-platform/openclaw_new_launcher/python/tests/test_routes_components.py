from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from types import SimpleNamespace


PYTHON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)


from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from api.routes_components import (
    SIMULATION_COMPONENTS,
    _model_config_error_text,
    _resolve_component_for_action,
    register_component_routes,
)
from core.component_installer import ComponentInstallError
from core.component_state import ComponentState
from core.component_state import ComponentStateStore
from core.component_catalog import default_component_state_path
from api.routes_jobs import register_job_routes
from core.newapi_account_manager import ACCOUNT_SOURCE, NewApiAccountError
from core.wire_config import WireConfigError
from services.jobs import JobManager


class ComponentRouteResolutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._env_patch = patch.dict(os.environ, {"LOOM_RELEASE_MANIFEST_DISABLE_DEFAULTS": "1"})
        self._env_patch.start()

    def tearDown(self) -> None:
        self._env_patch.stop()

    def test_tool_call_probe_failure_has_actionable_message(self) -> None:
        message = _model_config_error_text(
            WireConfigError("remote_responses_probe_failed: responses_tool_call_missing")
        )

        self.assertIn("工具调用", message)
        self.assertIn("没有写入", message)

    def test_session_preservation_failure_has_actionable_chinese_message(self) -> None:
        message = _model_config_error_text(
            WireConfigError(
                "codex_session_preservation_failed: "
                "agent_session_count_decreased: before=8; after=7"
            )
        )

        self.assertIn("原有会话", message)
        self.assertIn("已自动回滚", message)

    def test_dry_run_can_use_fallback_component_when_manifest_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            component, error = _resolve_component_for_action(
                os.path.join(temp_dir, "release-manifest.json"),
                "codex-desktop",
                allow_fallback=True,
            )

            self.assertIsNotNone(component)
            self.assertEqual(component.component_id, "codex-desktop")
            self.assertEqual(component.name, "ChatGPT Codex 原版")
            self.assertEqual(component.archive_type, "msstore")
            self.assertEqual(component.install_command, ())
            self.assertIsNotNone(error)
            self.assertIn("release-manifest.json", error or "")

    def test_real_action_resolution_requires_formal_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            component, error = _resolve_component_for_action(
                os.path.join(temp_dir, "release-manifest.json"),
                "codex-desktop",
                allow_fallback=False,
            )

            self.assertIsNone(component)
            self.assertIsNotNone(error)
            self.assertIn("release-manifest.json", error or "")

    def test_model_config_apply_ensures_managed_launcher_token_before_writing(self) -> None:
        calls: list[str] = []

        class FakeAccountManager:
            def current(self):
                return {"source": ACCOUNT_SOURCE, "memberToken": "old-token"}

            def ensure_launcher_token(self):
                calls.append("ensure")
                return {"source": ACCOUNT_SOURCE, "memberToken": "dedicated-token"}

        class FakeWireService:
            def sync_agent_model_config(self, component_id, *, model="", validate_remote=False):
                self.validate_remote = validate_remote
                calls.append(f"write:{validate_remote}")
                return {
                    "componentId": component_id,
                    "model": model,
                    "configured": True,
                    "transactionId": "tx-test",
                    "transactionState": "committed",
                }

        async def body(request):
            return await request.json()

        def fastapi_json(data: dict, status_code: int = 200):
            return JSONResponse(status_code=status_code, content=data)

        ctx = SimpleNamespace(
            auth_error=lambda _request: None,
            body=body,
            fastapi_json=fastapi_json,
            get_newapi_account_mgr=lambda: FakeAccountManager(),
            get_wire_svc=lambda: FakeWireService(),
        )
        app = FastAPI()
        register_component_routes(app, ctx)
        client = TestClient(app)

        with patch(
            "api.routes_components._model_config_status",
            return_value={"installed": True, "componentStatus": "ready"},
        ):
            response = client.post(
                "/api/components/model-config/apply",
                json={"componentId": "codex-desktop", "model": "glm-5.2-coding", "confirmed": True},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(calls, ["ensure", "write:True"])
        self.assertEqual(response.json()["status"]["transactionId"], "tx-test")

    def test_model_config_apply_does_not_write_when_launcher_token_prepare_fails(self) -> None:
        calls: list[str] = []

        class FakeAccountManager:
            def current(self):
                return {"source": ACCOUNT_SOURCE, "memberToken": "bad-token"}

            def ensure_launcher_token(self):
                calls.append("ensure")
                raise NewApiAccountError("launcher_token_ensure_no_text_models")

        class FakeWireService:
            def sync_agent_model_config(self, _component_id, *, model="", validate_remote=False):
                calls.append("write")
                return {"model": model}

        async def body(request):
            return await request.json()

        ctx = SimpleNamespace(
            auth_error=lambda _request: None,
            body=body,
            fastapi_json=lambda data, status_code=200: JSONResponse(status_code=status_code, content=data),
            get_newapi_account_mgr=lambda: FakeAccountManager(),
            get_wire_svc=lambda: FakeWireService(),
        )
        app = FastAPI()
        register_component_routes(app, ctx)
        client = TestClient(app)

        with patch(
            "api.routes_components._model_config_status",
            return_value={"installed": True, "componentStatus": "ready"},
        ):
            response = client.post(
                "/api/components/model-config/apply",
                json={"componentId": "codex-desktop", "confirmed": True},
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(calls, ["ensure"])
        self.assertIn("自动创建", response.json()["error"])

    def test_model_config_apply_requests_relogin_for_legacy_account_session(self) -> None:
        class FakeAccountManager:
            def current(self):
                return {"source": ACCOUNT_SOURCE, "memberToken": "legacy-token"}

            def ensure_launcher_token(self):
                raise NewApiAccountError("launcher token upgrade requires re-login", status_code=403)

        class FakeWireService:
            def sync_agent_model_config(self, *_args, **_kwargs):
                raise AssertionError("model config must not be written before account repair")

        async def body(request):
            return await request.json()

        ctx = SimpleNamespace(
            auth_error=lambda _request: None,
            body=body,
            fastapi_json=lambda data, status_code=200: JSONResponse(status_code=status_code, content=data),
            get_newapi_account_mgr=lambda: FakeAccountManager(),
            get_wire_svc=lambda: FakeWireService(),
        )
        app = FastAPI()
        register_component_routes(app, ctx)
        client = TestClient(app)

        with patch(
            "api.routes_components._model_config_status",
            return_value={"installed": True, "componentStatus": "ready"},
        ):
            response = client.post(
                "/api/components/model-config/apply",
                json={"componentId": "codex-desktop", "model": "glm-5.2-coding", "confirmed": True},
            )

        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertEqual(payload["code"], "account_relogin_required")
        self.assertEqual(payload["action"], "open_model_account")
        self.assertIn("配置未写入", payload["error"])

    def test_model_config_apply_explains_remote_probe_failure_without_claiming_success(self) -> None:
        class FakeWireService:
            def sync_agent_model_config(self, _component_id, *, model="", validate_remote=False):
                self.model = model
                self.validate_remote = validate_remote
                raise WireConfigError("remote_responses_probe_failed: http_401")

        async def body(request):
            return await request.json()

        ctx = SimpleNamespace(
            auth_error=lambda _request: None,
            body=body,
            fastapi_json=lambda data, status_code=200: JSONResponse(status_code=status_code, content=data),
            get_newapi_account_mgr=lambda: SimpleNamespace(current=lambda: None),
            get_wire_svc=lambda: FakeWireService(),
        )
        app = FastAPI()
        register_component_routes(app, ctx)
        client = TestClient(app)

        with patch(
            "api.routes_components._model_config_status",
            return_value={"installed": True, "componentStatus": "ready"},
        ):
            response = client.post(
                "/api/components/model-config/apply",
                json={"componentId": "codex-desktop", "model": "glm-5.2-coding", "confirmed": True},
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("模型连接验证失败", response.json()["error"])
        self.assertIn("没有写入", response.json()["error"])
        self.assertEqual(response.json()["status"]["status"], "failed")

    def test_model_config_disable_requires_confirmation(self) -> None:
        calls: list[str] = []

        class FakeWireService:
            def disable_agent_model_config(self, component_id):
                calls.append(component_id)
                return {"componentId": component_id, "status": "official"}

        async def body(request):
            return await request.json()

        ctx = SimpleNamespace(
            auth_error=lambda _request: None,
            body=body,
            fastapi_json=lambda data, status_code=200: JSONResponse(status_code=status_code, content=data),
            get_wire_svc=lambda: FakeWireService(),
        )
        app = FastAPI()
        register_component_routes(app, ctx)
        client = TestClient(app)

        response = client.post(
            "/api/components/model-config/disable",
            json={"componentId": "codex-desktop"},
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(calls, [])
        self.assertIn("确认", response.json()["error"])

    def test_model_config_disable_restores_official_channel(self) -> None:
        calls: list[str] = []

        class FakeWireService:
            def disable_agent_model_config(self, component_id):
                calls.append(component_id)
                return {
                    "componentId": component_id,
                    "configured": False,
                    "status": "official",
                    "channelMode": "official",
                    "managedBy": "",
                }

        async def body(request):
            return await request.json()

        ctx = SimpleNamespace(
            auth_error=lambda _request: None,
            body=body,
            fastapi_json=lambda data, status_code=200: JSONResponse(status_code=status_code, content=data),
            get_wire_svc=lambda: FakeWireService(),
        )
        app = FastAPI()
        register_component_routes(app, ctx)
        client = TestClient(app)

        with patch(
            "api.routes_components._model_config_status",
            return_value={"installed": True, "componentStatus": "started"},
        ):
            response = client.post(
                "/api/components/model-config/disable",
                json={"componentId": "codex-desktop", "confirmed": True},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(calls, ["codex-desktop"])
        self.assertEqual(response.json()["status"]["channelMode"], "official")
        self.assertEqual(response.json()["status"]["componentStatus"], "started")

    def test_custom_model_config_route_applies_wire_and_agent_as_one_operation(self) -> None:
        calls: list[dict] = []

        class FakeWireService:
            def sync_custom_agent_model_config(self, component_id, **kwargs):
                calls.append({"componentId": component_id, **kwargs})
                return {
                    "componentId": component_id,
                    "configured": True,
                    "status": "configured",
                    "channelMode": "custom",
                    "remoteVerified": True,
                    "transactionState": "committed",
                }

        async def body(request):
            return await request.json()

        ctx = SimpleNamespace(
            auth_error=lambda _request: None,
            body=body,
            fastapi_json=lambda data, status_code=200: JSONResponse(status_code=status_code, content=data),
            get_wire_svc=lambda: FakeWireService(),
        )
        app = FastAPI()
        register_component_routes(app, ctx)
        client = TestClient(app)

        with patch(
            "api.routes_components._model_config_status",
            return_value={"installed": True, "componentStatus": "started"},
        ):
            response = client.post(
                "/api/components/model-config/apply-custom",
                json={
                    "componentId": "codex-desktop",
                    "provider": "Custom",
                    "baseUrl": "https://custom.example.invalid/v1",
                    "apiKey": "sk-custom-not-real",
                    "model": "custom-text-model",
                    "confirmed": True,
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["model"], "custom-text-model")
        self.assertEqual(response.json()["status"]["componentStatus"], "started")

    def test_dry_run_install_route_returns_persistent_job_progress_for_page_switch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            logs: list[str] = []
            job_mgr = JobManager(logs.append)
            app = FastAPI()
            ctx = _test_context(temp_dir, job_mgr, logs)
            register_component_routes(app, ctx)
            register_job_routes(app, ctx)
            client = TestClient(app)

            response = client.post(
                "/api/components/install",
                json={"componentId": "codex-desktop", "mode": "simulate", "dryRun": True},
            )

            self.assertEqual(response.status_code, 202)
            submitted = response.json()
            self.assertTrue(submitted["jobId"].startswith("job_"))
            self.assertEqual(submitted["state"]["status"], "resolving_manifest")

            job = _wait_for_job(client, submitted["jobId"])

            self.assertEqual(job["status"], "succeeded")
            self.assertEqual(job["kind"], "component.install.simulate")
            self.assertEqual(job["result"]["state"]["status"], "simulation_ready")
            self.assertEqual(job["result"]["catalog"]["components"][0]["status"], "simulation_ready")
            self.assertEqual(job["progress"]["componentId"], "codex-desktop")
            self.assertGreaterEqual(len(job["progress"]["history"]), 6)
            self.assertIn("codex-desktop", "".join(logs))

            listed = client.get("/api/jobs/list?limit=5").json()["jobs"]
            listed_job = next(item for item in listed if item["id"] == submitted["jobId"])
            self.assertEqual(listed_job["status"], "succeeded")
            self.assertEqual(listed_job["result"]["state"]["status"], "simulation_ready")

    def test_real_install_route_requires_confirmation_before_manifest_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            logs: list[str] = []
            job_mgr = JobManager(logs.append)
            app = FastAPI()
            ctx = _test_context(temp_dir, job_mgr, logs)
            register_component_routes(app, ctx)
            client = TestClient(app)

            response = client.post("/api/components/install", json={"componentId": "codex-desktop"})

            self.assertEqual(response.status_code, 403)
            self.assertIn("安装组件需要确认", response.json()["error"])

    def test_detect_route_passes_force_to_external_probe_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            logs: list[str] = []
            job_mgr = JobManager(logs.append)
            app = FastAPI()
            ctx = _test_context(temp_dir, job_mgr, logs)
            register_component_routes(app, ctx)
            register_job_routes(app, ctx)
            client = TestClient(app)
            force_values: list[bool] = []

            class FakeInstaller:
                def detect(self, component, *, job_id=None, on_progress=None, force_external_probe=False):
                    force_values.append(force_external_probe)
                    return ComponentState(component.component_id, "ready", version=component.version, job_id=job_id)

            with (
                patch(
                    "api.routes_components._resolve_component_for_action",
                    return_value=(
                        SIMULATION_COMPONENTS["codex-desktop"],
                        None,
                    ),
                ),
                patch("api.routes_components._component_installer", return_value=FakeInstaller()),
            ):
                response = client.post("/api/components/detect", json={"componentId": "codex-desktop", "force": True})
                self.assertEqual(response.status_code, 202)
                job = _wait_for_job(client, response.json()["jobId"])

            self.assertEqual(job["status"], "succeeded")
            self.assertEqual(force_values, [True])

    def test_start_route_reuses_active_component_job(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            logs: list[str] = []
            job_mgr = JobManager(logs.append)
            release = threading.Event()
            active_job = job_mgr.submit_progress("component.start", "Start Codex", lambda _job_id: release.wait(1))
            state_store = ComponentStateStore(default_component_state_path(temp_dir))
            state_store.mark("codex-desktop", "starting", job_id=active_job["id"])
            app = FastAPI()
            ctx = _test_context(temp_dir, job_mgr, logs)
            register_component_routes(app, ctx)
            register_job_routes(app, ctx)
            client = TestClient(app)

            try:
                response = client.post(
                    "/api/components/start",
                    json={"componentId": "codex-desktop", "confirmed": True},
                )
            finally:
                release.set()

            self.assertEqual(response.status_code, 202)
            self.assertEqual(response.json()["jobId"], active_job["id"])

    def test_component_status_recovers_orphaned_starting_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            logs: list[str] = []
            job_mgr = JobManager(logs.append)
            state_store = ComponentStateStore(default_component_state_path(temp_dir))
            state_store.mark(
                "codex-desktop",
                "starting",
                version="0.142.3",
                job_id="job_missing_after_restart",
            )
            app = FastAPI()
            ctx = _test_context(temp_dir, job_mgr, logs)
            register_component_routes(app, ctx)
            client = TestClient(app)

            response = client.get("/api/components/status")

            self.assertEqual(response.status_code, 200)
            codex = next(item for item in response.json()["components"] if item["id"] == "codex-desktop")
            self.assertEqual(codex["status"], "start_failed")
            self.assertEqual(codex["errorCode"], "start_interrupted")
            self.assertIn("重新", codex["errorMessage"])

    def test_component_status_recovers_orphaned_install_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            logs: list[str] = []
            job_mgr = JobManager(logs.append)
            state_store = ComponentStateStore(default_component_state_path(temp_dir))
            state_store.mark(
                "claude-code",
                "downloading",
                version="2.1.195",
                job_id="job_missing_after_restart",
            )
            app = FastAPI()
            ctx = _test_context(temp_dir, job_mgr, logs)
            register_component_routes(app, ctx)
            client = TestClient(app)

            response = client.get("/api/components/status")

            self.assertEqual(response.status_code, 200)
            claude = next(item for item in response.json()["components"] if item["id"] == "claude-code")
            self.assertEqual(claude["status"], "download_failed")
            self.assertEqual(claude["errorCode"], "install_interrupted")
            self.assertIn("重新", claude["errorMessage"])

    def test_component_status_keeps_starting_state_for_live_job(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            logs: list[str] = []
            job_mgr = JobManager(logs.append)
            release = threading.Event()
            active_job = job_mgr.submit_progress("component.start", "Start Codex", lambda _job_id: release.wait(1))
            state_store = ComponentStateStore(default_component_state_path(temp_dir))
            state_store.mark("codex-desktop", "starting", version="0.142.3", job_id=active_job["id"])
            app = FastAPI()
            ctx = _test_context(temp_dir, job_mgr, logs)
            register_component_routes(app, ctx)
            client = TestClient(app)

            try:
                response = client.get("/api/components/status")
            finally:
                release.set()

            self.assertEqual(response.status_code, 200)
            codex = next(item for item in response.json()["components"] if item["id"] == "codex-desktop")
            self.assertEqual(codex["status"], "starting")

    def test_start_route_registers_job_before_accepting_second_start(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            logs: list[str] = []
            job_mgr = JobManager(logs.append)
            release = threading.Event()

            class FakeInstaller:
                def launch(self, component, *, job_id=None):
                    release.wait(1)
                    return {"success": True, "pid": 42, "componentId": component.component_id}

            app = FastAPI()
            ctx = _test_context(temp_dir, job_mgr, logs)
            register_component_routes(app, ctx)
            register_job_routes(app, ctx)
            client = TestClient(app)

            with (
                patch(
                    "api.routes_components._resolve_component_for_action",
                    return_value=(SIMULATION_COMPONENTS["codex-desktop"], None),
                ),
                patch("api.routes_components._component_installer", return_value=FakeInstaller()),
            ):
                first = client.post(
                    "/api/components/start",
                    json={"componentId": "codex-desktop", "confirmed": True},
                )
                second = client.post(
                    "/api/components/start",
                    json={"componentId": "codex-desktop", "confirmed": True},
                )
                release.set()

            self.assertEqual(first.status_code, 202)
            self.assertEqual(second.status_code, 202)
            self.assertEqual(second.json()["jobId"], first.json()["jobId"])
            persisted = ComponentStateStore(default_component_state_path(temp_dir)).load()["codex-desktop"]
            self.assertEqual(persisted.job_id, first.json()["jobId"])

    def test_start_route_keeps_ready_state_until_launcher_takes_ownership(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            logs: list[str] = []
            job_mgr = JobManager(logs.append)
            state_store = ComponentStateStore(default_component_state_path(temp_dir))
            state_store.mark("codex-desktop", "ready", version="0.142.3")

            class StateAwareInstaller:
                def launch(self, component, *, job_id=None):
                    current = state_store.load()[component.component_id]
                    if current.status != "ready":
                        raise ComponentInstallError(f"unexpected pre-launch state: {current.status}")
                    state_store.mark(component.component_id, "started", version=current.version, job_id=job_id)
                    return {"success": True, "pid": 42, "componentId": component.component_id}

            app = FastAPI()
            ctx = _test_context(temp_dir, job_mgr, logs)
            register_component_routes(app, ctx)
            register_job_routes(app, ctx)
            client = TestClient(app)

            with (
                patch(
                    "api.routes_components._resolve_component_for_action",
                    return_value=(SIMULATION_COMPONENTS["codex-desktop"], None),
                ),
                patch("api.routes_components._component_installer", return_value=StateAwareInstaller()),
            ):
                submitted = client.post(
                    "/api/components/start",
                    json={"componentId": "codex-desktop", "confirmed": True},
                )
                job = _wait_for_job(client, submitted.json()["jobId"])

            self.assertEqual(job["status"], "succeeded")
            self.assertTrue(job["result"]["success"])
            self.assertEqual(state_store.load()["codex-desktop"].status, "started")

    def test_restart_route_restarts_official_codex_as_persistent_job(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            logs: list[str] = []
            job_mgr = JobManager(logs.append)

            class FakeInstaller:
                def restart(self, component, *, job_id=None):
                    return {"success": True, "componentId": component.component_id, "jobId": job_id}

            ComponentStateStore(default_component_state_path(temp_dir)).mark(
                "codex-desktop",
                "started",
                version="Microsoft Store",
            )
            app = FastAPI()
            ctx = _test_context(temp_dir, job_mgr, logs)
            register_component_routes(app, ctx)
            register_job_routes(app, ctx)
            client = TestClient(app)

            with (
                patch(
                    "api.routes_components._resolve_component_for_action",
                    return_value=(SIMULATION_COMPONENTS["codex-desktop"], None),
                ),
                patch("api.routes_components._component_installer", return_value=FakeInstaller()),
            ):
                submitted = client.post(
                    "/api/components/restart",
                    json={"componentId": "codex-desktop", "confirmed": True},
                )
                job = _wait_for_job(client, submitted.json()["jobId"])

            self.assertEqual(submitted.status_code, 202)
            self.assertEqual(job["status"], "succeeded")
            self.assertTrue(job["result"]["success"])

    def test_restart_route_requires_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            logs: list[str] = []
            app = FastAPI()
            ctx = _test_context(temp_dir, JobManager(logs.append), logs)
            register_component_routes(app, ctx)
            client = TestClient(app)

            response = client.post("/api/components/restart", json={"componentId": "codex-desktop"})

            self.assertEqual(response.status_code, 403)
            self.assertIn("确认", response.json()["error"])

    def test_restart_route_marks_job_failed_when_official_app_restart_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            logs: list[str] = []
            job_mgr = JobManager(logs.append)

            class FakeInstaller:
                def restart(self, _component, *, job_id=None):
                    raise ComponentInstallError(f"simulated restart failure {job_id}")

            ComponentStateStore(default_component_state_path(temp_dir)).mark(
                "codex-desktop",
                "started",
                version="Microsoft Store",
            )
            app = FastAPI()
            ctx = _test_context(temp_dir, job_mgr, logs)
            register_component_routes(app, ctx)
            register_job_routes(app, ctx)
            client = TestClient(app)

            with (
                patch(
                    "api.routes_components._resolve_component_for_action",
                    return_value=(SIMULATION_COMPONENTS["codex-desktop"], None),
                ),
                patch("api.routes_components._component_installer", return_value=FakeInstaller()),
            ):
                submitted = client.post(
                    "/api/components/restart",
                    json={"componentId": "codex-desktop", "confirmed": True},
                )
                job = _wait_for_job(client, submitted.json()["jobId"])

            self.assertEqual(job["status"], "failed")
            self.assertIn("simulated restart failure", job["error"])

    def test_restart_route_reuses_single_active_restart_job(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            logs: list[str] = []
            job_mgr = JobManager(logs.append)
            release = threading.Event()
            calls: list[str] = []

            class FakeInstaller:
                def restart(self, component, *, job_id=None):
                    calls.append(component.component_id)
                    release.wait(1)
                    return {"success": True, "jobId": job_id}

            ComponentStateStore(default_component_state_path(temp_dir)).mark(
                "codex-desktop",
                "started",
                version="Microsoft Store",
            )
            app = FastAPI()
            ctx = _test_context(temp_dir, job_mgr, logs)
            register_component_routes(app, ctx)
            register_job_routes(app, ctx)
            client = TestClient(app)

            with (
                patch(
                    "api.routes_components._resolve_component_for_action",
                    return_value=(SIMULATION_COMPONENTS["codex-desktop"], None),
                ),
                patch("api.routes_components._component_installer", return_value=FakeInstaller()),
            ):
                first = client.post(
                    "/api/components/restart",
                    json={"componentId": "codex-desktop", "confirmed": True},
                )
                second = client.post(
                    "/api/components/restart",
                    json={"componentId": "codex-desktop", "confirmed": True},
                )
                release.set()
                _wait_for_job(client, first.json()["jobId"], timeout=5.0)

            self.assertEqual(first.status_code, 202)
            self.assertEqual(second.status_code, 202)
            self.assertEqual(second.json()["jobId"], first.json()["jobId"])
            self.assertEqual(calls, ["codex-desktop"])

    def test_restart_route_does_not_stop_app_when_job_registration_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            logs: list[str] = []
            job_mgr = JobManager(logs.append)
            restarted = threading.Event()

            class FailingStore:
                def load(self):
                    return {"codex-desktop": ComponentState("codex-desktop", "started", version="Microsoft Store")}

                def mark(self, *_args, **_kwargs):
                    raise OSError("simulated restart registration failure")

            class FakeInstaller:
                def restart(self, _component, *, job_id=None):
                    restarted.set()
                    return {"success": True, "jobId": job_id}

            app = FastAPI()
            ctx = _test_context(temp_dir, job_mgr, logs)
            register_component_routes(app, ctx)
            client = TestClient(app, raise_server_exceptions=False)

            with (
                patch(
                    "api.routes_components._resolve_component_for_action",
                    return_value=(SIMULATION_COMPONENTS["codex-desktop"], None),
                ),
                patch("api.routes_components._component_state_store", return_value=FailingStore()),
                patch("api.routes_components._component_installer", return_value=FakeInstaller()),
            ):
                response = client.post(
                    "/api/components/restart",
                    json={"componentId": "codex-desktop", "confirmed": True},
                )
                time.sleep(0.2)

            self.assertEqual(response.status_code, 500)
            self.assertFalse(restarted.is_set())

    def test_start_route_does_not_launch_when_registration_state_cannot_be_saved(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            logs: list[str] = []
            job_mgr = JobManager(logs.append)
            launched = threading.Event()

            class FailingStore:
                def load(self):
                    return {"codex-desktop": ComponentState("codex-desktop", "ready", version="0.142.3")}

                def mark(self, *_args, **_kwargs):
                    raise OSError("simulated component state write denial")

            class RecordingInstaller:
                def launch(self, component, *, job_id=None):
                    launched.set()
                    return {"success": True, "pid": 42, "componentId": component.component_id}

            app = FastAPI()
            ctx = _test_context(temp_dir, job_mgr, logs)
            register_component_routes(app, ctx)
            register_job_routes(app, ctx)
            client = TestClient(app, raise_server_exceptions=False)

            with (
                patch(
                    "api.routes_components._resolve_component_for_action",
                    return_value=(SIMULATION_COMPONENTS["codex-desktop"], None),
                ),
                patch("api.routes_components._component_state_store", return_value=FailingStore()),
                patch("api.routes_components._component_installer", return_value=RecordingInstaller()),
            ):
                response = client.post(
                    "/api/components/start",
                    json={"componentId": "codex-desktop", "confirmed": True},
                )
                time.sleep(2.2)

            self.assertEqual(response.status_code, 500)
            self.assertFalse(launched.is_set())
            failed_jobs = [job for job in job_mgr.list() if job.get("kind") == "component.start"]
            self.assertEqual(len(failed_jobs), 1)
            self.assertEqual(failed_jobs[0]["status"], "failed")

    def test_start_route_surfaces_launcher_failure_as_failed_job(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            logs: list[str] = []
            job_mgr = JobManager(logs.append)

            class FailingInstaller:
                def launch(self, _component, *, job_id=None):
                    raise ComponentInstallError("Codex 启动入口损坏")

            app = FastAPI()
            ctx = _test_context(temp_dir, job_mgr, logs)
            register_component_routes(app, ctx)
            register_job_routes(app, ctx)
            client = TestClient(app)

            with (
                patch(
                    "api.routes_components._resolve_component_for_action",
                    return_value=(SIMULATION_COMPONENTS["codex-desktop"], None),
                ),
                patch("api.routes_components._component_installer", return_value=FailingInstaller()),
            ):
                submitted = client.post(
                    "/api/components/start",
                    json={"componentId": "codex-desktop", "confirmed": True},
                )
                job = _wait_for_job(client, submitted.json()["jobId"])

            self.assertEqual(submitted.status_code, 202)
            self.assertEqual(job["status"], "failed")
            self.assertIn("启动入口损坏", job["error"])

    def test_rollback_route_runs_through_job_manager(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            rollback_dir = os.path.join(temp_dir, "data", ".installer", "rollback", "codex-desktop")
            os.makedirs(rollback_dir, exist_ok=True)
            with open(os.path.join(rollback_dir, "restored.txt"), "w", encoding="utf-8") as handle:
                handle.write("previous")

            logs: list[str] = []
            job_mgr = JobManager(logs.append)
            app = FastAPI()
            ctx = _test_context(temp_dir, job_mgr, logs)
            register_component_routes(app, ctx)
            register_job_routes(app, ctx)
            client = TestClient(app)

            response = client.post(
                "/api/components/rollback",
                json={"componentId": "codex-desktop", "confirmed": True},
            )

            self.assertEqual(response.status_code, 202)
            submitted = response.json()
            self.assertTrue(submitted["jobId"].startswith("job_"))
            self.assertEqual(submitted["job"]["kind"], "component.rollback")
            self.assertEqual(submitted["state"]["status"], "rolling_back")

            job = _wait_for_job(client, submitted["jobId"])

            self.assertEqual(job["status"], "succeeded")
            self.assertEqual(job["result"]["state"]["status"], "ready")
            self.assertTrue(os.path.isfile(os.path.join(temp_dir, "agents", "codex-desktop", "restored.txt")))
            self.assertEqual(job["progress"]["phase"], "rollback")

    def test_rollback_route_requires_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            logs: list[str] = []
            job_mgr = JobManager(logs.append)
            app = FastAPI()
            ctx = _test_context(temp_dir, job_mgr, logs)
            register_component_routes(app, ctx)
            register_job_routes(app, ctx)
            client = TestClient(app)

            response = client.post("/api/components/rollback", json={"componentId": "codex-desktop"})

            self.assertEqual(response.status_code, 403)
            self.assertIn("确认", response.json()["error"])


def _test_context(base_path: str, job_mgr: JobManager, logs: list[str]) -> SimpleNamespace:
    async def body(request):
        payload = await request.json()
        return payload if isinstance(payload, dict) else {}

    def fastapi_json(data: dict, status_code: int = 200):
        payload = dict(data)
        payload["_meta"] = {"ok": 200 <= status_code < 400 and "error" not in payload, "status": status_code}
        return JSONResponse(status_code=status_code, content=payload)

    return SimpleNamespace(
        append_log=logs.append,
        auth_error=lambda _request: None,
        body=body,
        fastapi_json=fastapi_json,
        get_job_mgr=lambda: job_mgr,
        paths=SimpleNamespace(base_path=base_path),
    )


def _wait_for_job(client: TestClient, job_id: str, timeout: float = 2.0) -> dict:
    deadline = time.time() + timeout
    last_job = None
    while time.time() < deadline:
        response = client.get(f"/api/jobs/{job_id}")
        if response.status_code == 200:
            job = response.json()["job"]
            last_job = job
            if job.get("status") in {"succeeded", "failed"}:
                return job
        time.sleep(0.02)
    raise AssertionError(f"job did not finish: {job_id}; last={last_job}")


if __name__ == "__main__":
    unittest.main()
