from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch


PYTHON_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)


from core.agent_capabilities import CapabilityRegistry
from core.agent_policy import AgentPolicyEngine
from core.agent_runtime import RuntimeExecutionError
from core.agent_sessions import AgentSessionRepository
from core.paths import AppPaths


def _registry(operations=None) -> CapabilityRegistry:
    return CapabilityRegistry(
        internal_operations=operations or {},
        skill_provider=lambda: [],
        mcp_provider=lambda: [],
        cli_catalog_provider=lambda: {"domains": []},
    )


def _managed_session(token: str = "sk-native-secret-value", model: str = "glm-managed") -> dict:
    return {
        "source": "newapi_account",
        "gatewayBaseUrl": "https://gateway.example/v1",
        "memberToken": token,
        "gatewayDefaultModel": model,
        "gateway": {
            "baseUrl": "https://gateway.example/v1",
            "accessToken": token,
            "defaultModel": model,
        },
    }


class FakeAccount:
    def __init__(
        self,
        session: dict | None = None,
        *,
        text_models: list[str] | None = None,
        default_model: str = "",
    ) -> None:
        self.session = session
        session_default = str((session or {}).get("gatewayDefaultModel") or "")
        self.text_models = list(text_models) if text_models is not None else ([session_default] if session_default else [])
        self.default_model = default_model or session_default

    def current(self) -> dict | None:
        return self.session

    def ensure_launcher_token(self, *, sync_runtime: bool = False, force_refresh: bool = False) -> dict:
        if self.session is None:
            raise RuntimeError("not_logged_in")
        return self.session

    def public_session(self) -> dict:
        return {
            "models": {"text": list(self.text_models)},
            "selectedModels": {"text": self.default_model},
        }


def _wait_for_status(service, run_id: str, *statuses: str, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        run = service.get_run(run_id)
        if run["status"] in statuses:
            return run
        time.sleep(0.01)
    raise AssertionError(f"run {run_id} did not reach {statuses}: {service.get_run(run_id)}")


class BlockingRuntime:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls = 0
        self.requests: list[dict] = []

    def status(self, profile_id=None):
        return {"available": True, "profileId": profile_id or "default", "runtime": "test"}

    def start(self, request, emit, cancel, *, timeout_sec=None):
        self.calls += 1
        self.requests.append(dict(request))
        self.started.set()
        while not self.release.wait(0.01):
            if cancel.is_set():
                raise RuntimeExecutionError("agent_runtime_cancelled", "Runtime cancelled.")
        return {"final": {"text": "done"}}


class SlowStoppingRuntime:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.cancel_seen = threading.Event()
        self.allow_stop = threading.Event()
        self.resumed = threading.Event()
        self.calls = 0

    def status(self, profile_id=None):
        return {"available": True, "profileId": profile_id or "default", "runtime": "test"}

    def start(self, request, emit, cancel, *, timeout_sec=None):
        self.calls += 1
        if self.calls == 1:
            self.started.set()
            while not cancel.wait(0.01):
                pass
            self.cancel_seen.set()
            self.allow_stop.wait(2.0)
            raise RuntimeExecutionError("agent_runtime_cancelled", "Runtime cancelled.")
        self.resumed.set()
        return {"final": {"text": "continued"}}


class ScriptedRuntime:
    def __init__(self, responses: list[dict]) -> None:
        self.responses = list(responses)
        self.requests: list[dict] = []

    def status(self, profile_id=None):
        return {"available": True, "profileId": profile_id or "default", "runtime": "test"}

    def start(self, request, emit, cancel, *, timeout_sec=None):
        self.requests.append(dict(request))
        return self.responses.pop(0)


class UnavailableRuntime:
    def status(self, profile_id=None):
        return {
            "available": False,
            "profileId": profile_id or "default",
            "error": {
                "code": "agent_runtime_unavailable",
                "message": "No compatible local runtime is configured.",
                "recoverable": True,
            },
        }

    def start(self, request, emit, cancel, *, timeout_sec=None):
        raise RuntimeExecutionError(
            "agent_runtime_unavailable",
            "No compatible local runtime is configured.",
        )


class ProgressMatrix:
    def __init__(self) -> None:
        self.devices = [{
            "deviceId": "phone-progress",
            "online": True,
            "group": "招聘一组",
            "groups": ["招聘一组"],
        }]
        device_task = {
            "assignmentId": "assignment-progress",
            "deviceTaskId": "task-progress",
            "deviceId": "phone-progress",
            "jobId": None,
            "status": "running",
            "attempt": 1,
        }
        self.campaign = {
            "schema": "loom.matrix.campaign.v2",
            "campaignId": "campaign-progress",
            "status": "running",
            "concurrency": 1,
            "missions": [{"missionId": "mission-progress", "status": "running", "deviceTasks": [device_task]}],
        }

    def dispatch(self, _body):
        return {
            "campaignId": "campaign-progress",
            "status": "running",
            "missions": [{"deviceTasks": [dict(self.campaign["missions"][0]["deviceTasks"][0])]}],
        }

    def status(self):
        return {
            "devices": json.loads(json.dumps(self.devices)),
            "campaigns": [json.loads(json.dumps(self.campaign))],
        }


class ConfirmationMatrix(ProgressMatrix):
    def __init__(self, *, require_confirmation: bool = False) -> None:
        super().__init__()
        self.require_confirmation = require_confirmation
        self.dispatches: list[dict] = []

    def dispatch(self, body):
        self.dispatches.append(dict(body))
        if self.require_confirmation and body.get("confirmed") is not True:
            raise ValueError("server confirmation required")
        return super().dispatch(body)


class CancellableMatrix(ProgressMatrix):
    def __init__(self, *, completes_cancel: bool = True) -> None:
        super().__init__()
        self.completes_cancel = completes_cancel
        self.cancelled_campaign_ids: list[str] = []

    def cancel(self, campaign_id: str):
        self.cancelled_campaign_ids.append(campaign_id)
        if self.completes_cancel:
            self.campaign["status"] = "cancelled"
            self.campaign["missions"][0]["status"] = "cancelled"
            self.campaign["missions"][0]["deviceTasks"][0]["status"] = "cancelled"
        return {"campaignId": campaign_id, "cancelled": self.completes_cancel}


class RecordingJobManager:
    def __init__(self) -> None:
        self.jobs = [{
            "id": "job-progress",
            "status": "running",
            "progress": {"campaignId": "campaign-progress"},
        }]
        self.cancelled_job_ids: list[str] = []

    def cancel_matching(self, predicate):
        matched = [job for job in self.jobs if job["status"] == "running" and predicate(dict(job))]
        for job in matched:
            job["status"] = "cancelled"
            self.cancelled_job_ids.append(job["id"])
        return [job["id"] for job in matched]


class AgentServiceTests(unittest.TestCase):
    def test_session_detail_returns_newest_message_page_and_cursor_loads_older_messages(self) -> None:
        from services.agent_service import AgentService

        with tempfile.TemporaryDirectory() as root:
            service = AgentService(
                AppPaths(root),
                runtime=UnavailableRuntime(),
                capabilities=_registry(),
                matrix_factory=ProgressMatrix,
            )
            try:
                session = service.create_session({"title": "Long conversation"})
                session_id = session["sessionId"]
                for index in range(205):
                    service.repository.append_message(
                        session_id,
                        {
                            "schema": "loom.agent.message.v1",
                            "messageId": f"message_{index:03d}",
                            "sessionId": session_id,
                            "role": "assistant",
                            "status": "completed",
                            "blocks": [{"type": "text", "data": {"text": f"Reply {index}"}}],
                            "createdAt": "2026-07-18T00:00:00+00:00",
                            "completedAt": "2026-07-18T00:00:00+00:00",
                        },
                    )

                newest = service.session_detail(session_id, limit=200)
                service.repository.append_message(
                    session_id,
                    {
                        "schema": "loom.agent.message.v1",
                        "messageId": "message_205",
                        "sessionId": session_id,
                        "role": "assistant",
                        "status": "completed",
                        "blocks": [{"type": "text", "data": {"text": "Reply 205"}}],
                        "createdAt": "2026-07-18T00:00:00+00:00",
                        "completedAt": "2026-07-18T00:00:00+00:00",
                    },
                )
                older = service.session_detail(
                    session_id,
                    cursor=newest["nextCursor"],
                    limit=200,
                )
            finally:
                service.shutdown()

        self.assertEqual(
            [message["messageId"] for message in newest["messages"]],
            [f"message_{index:03d}" for index in range(5, 205)],
        )
        self.assertEqual(
            [message["messageId"] for message in older["messages"]],
            [f"message_{index:03d}" for index in range(5)],
        )
        self.assertNotIn("nextCursor", older)

    def test_auto_scope_is_resolved_and_frozen_before_runtime_start(self) -> None:
        from services.agent_service import AgentService

        matrix = ProgressMatrix()
        runtime = ScriptedRuntime([{"final": {"text": "done"}}])
        with tempfile.TemporaryDirectory() as root:
            service = AgentService(
                AppPaths(root),
                runtime=runtime,
                capabilities=_registry(),
                matrix_factory=lambda: matrix,
            )
            try:
                session = service.create_session({"title": "Auto scope"})
                sent = service.send_message(session["sessionId"], {
                    "clientMessageId": "auto-scope-1",
                    "text": "让 phone-progress 读取屏幕",
                    "scopeMode": "auto",
                })
                completed = _wait_for_status(service, sent["run"]["runId"], "completed")
            finally:
                service.shutdown()

        request = completed["request"]
        self.assertEqual(request["scopeMode"], "auto")
        self.assertEqual(request["targets"], {"deviceIds": ["phone-progress"]})
        self.assertEqual(request["requestScope"]["status"], "resolved")
        self.assertEqual(runtime.requests[0]["requestScope"], request["requestScope"])

    def test_ambiguous_phone_scope_returns_clarification_without_runtime_or_dispatch(self) -> None:
        from services.agent_service import AgentService

        matrix = ConfirmationMatrix()
        runtime = ScriptedRuntime([{"final": {"text": "should not run"}}])
        with tempfile.TemporaryDirectory() as root:
            service = AgentService(AppPaths(root), runtime=runtime, matrix_factory=lambda: matrix)
            try:
                session = service.create_session({"title": "Ambiguous scope"})
                sent = service.send_message(session["sessionId"], {
                    "clientMessageId": "ambiguous-scope-1",
                    "text": "让那几台手机继续",
                    "scopeMode": "auto",
                })
                completed = _wait_for_status(service, sent["run"]["runId"], "completed")
                detail = service.session_detail(session["sessionId"])
                trace = service.get_trace(sent["run"]["runId"])
            finally:
                service.shutdown()

        self.assertEqual(completed["request"]["requestScope"]["status"], "ambiguous")
        self.assertEqual(runtime.requests, [])
        self.assertEqual(matrix.dispatches, [])
        self.assertEqual(trace["approvals"], [])
        self.assertIn("哪台手机", detail["messages"][-1]["blocks"][0]["data"]["text"])

    def test_invalid_manual_scope_is_rejected_before_run_creation(self) -> None:
        from services.agent_service import AgentService

        with tempfile.TemporaryDirectory() as root:
            service = AgentService(
                AppPaths(root),
                runtime=ScriptedRuntime([]),
                capabilities=_registry(),
                matrix_factory=ProgressMatrix,
            )
            try:
                session = service.create_session({"title": "Manual scope"})
                with self.assertRaisesRegex(ValueError, "AGENT_SCOPE_INVALID"):
                    service.send_message(session["sessionId"], {
                        "clientMessageId": "invalid-manual-scope-1",
                        "text": "执行任务",
                        "scopeMode": "manual",
                        "scope": {"deviceIds": ["removed-phone"]},
                    })
                self.assertEqual(service.session_detail(session["sessionId"])["runs"], [])
            finally:
                service.shutdown()

    def test_bootstrap_lists_current_account_text_models_and_default(self) -> None:
        from services.agent_service import AgentService

        account = FakeAccount(
            _managed_session(model="glm-5"),
            text_models=["glm-5", "qwen3.7-plus"],
        )
        with tempfile.TemporaryDirectory() as root:
            service = AgentService(
                AppPaths(root),
                runtime=UnavailableRuntime(),
                account_manager=account,
                capabilities=_registry(),
            )
            try:
                bootstrap = service.bootstrap()
            finally:
                service.shutdown()

        self.assertEqual(bootstrap["defaultModelId"], "glm-5")
        self.assertEqual(bootstrap["models"], [
            {"modelId": "glm-5", "name": "glm-5", "available": True},
            {"modelId": "qwen3.7-plus", "name": "qwen3.7-plus", "available": True},
        ])
        self.assertEqual(bootstrap["policy"]["mode"], "weak")
        self.assertEqual(bootstrap["policy"]["approvalRequired"], ["critical"])
        self.assertTrue(bootstrap["permissions"]["outbound"])

    def test_session_model_is_snapshotted_into_run_and_survives_later_switch(self) -> None:
        from services.agent_service import AgentService

        account = FakeAccount(
            _managed_session(model="glm-5"),
            text_models=["glm-5", "qwen3.7-plus"],
        )
        runtime = BlockingRuntime()
        with tempfile.TemporaryDirectory() as root:
            service = AgentService(
                AppPaths(root),
                runtime=runtime,
                account_manager=account,
                capabilities=_registry(),
            )
            try:
                session = service.create_session({"title": "Recruiting", "modelId": "qwen3.7-plus"})
                sent = service.send_message(
                    session["sessionId"],
                    {"clientMessageId": "model-snapshot-1", "text": "check status"},
                )
                self.assertTrue(runtime.started.wait(1.0))
                service.update_session(session["sessionId"], {"modelId": "glm-5"})

                self.assertEqual(sent["run"]["modelId"], "qwen3.7-plus")
                self.assertEqual(sent["run"]["modelSource"], "session")
                self.assertEqual(sent["run"]["request"]["modelId"], "qwen3.7-plus")
                self.assertEqual(runtime.requests[0]["modelId"], "qwen3.7-plus")
            finally:
                runtime.release.set()
                service.shutdown()

    def test_account_default_model_is_snapshotted_when_session_has_no_override(self) -> None:
        from services.agent_service import AgentService

        account = FakeAccount(_managed_session(model="glm-5"), text_models=["glm-5"])
        runtime = BlockingRuntime()
        with tempfile.TemporaryDirectory() as root:
            service = AgentService(
                AppPaths(root),
                runtime=runtime,
                account_manager=account,
                capabilities=_registry(),
            )
            try:
                session = service.create_session({"title": "Default model"})
                sent = service.send_message(
                    session["sessionId"],
                    {"clientMessageId": "model-default-1", "text": "check status"},
                )
                self.assertEqual(sent["run"]["modelId"], "glm-5")
                self.assertEqual(sent["run"]["modelSource"], "account-default")
            finally:
                runtime.release.set()
                service.shutdown()

    def test_rejects_model_not_in_current_account_text_models(self) -> None:
        from services.agent_service import AgentService

        account = FakeAccount(
            _managed_session(model="glm-5"),
            text_models=["glm-5", "qwen3.7-plus"],
        )
        with tempfile.TemporaryDirectory() as root:
            service = AgentService(
                AppPaths(root),
                runtime=UnavailableRuntime(),
                account_manager=account,
                capabilities=_registry(),
            )
            try:
                with self.assertRaisesRegex(ValueError, "AGENT_MODEL_NOT_AVAILABLE"):
                    service.create_session({"title": "Invalid", "modelId": "removed-model"})

                session = service.create_session({"title": "Valid", "modelId": "qwen3.7-plus"})
                account.text_models = ["glm-5"]
                with self.assertRaisesRegex(ValueError, "AGENT_MODEL_NOT_AVAILABLE"):
                    service.update_session(session["sessionId"], {"modelId": "qwen3.7-plus"})
                with self.assertRaisesRegex(ValueError, "AGENT_MODEL_NOT_AVAILABLE"):
                    service.send_message(
                        session["sessionId"],
                        {"clientMessageId": "removed-model-1", "text": "check status"},
                    )
            finally:
                service.shutdown()

    def test_send_message_returns_immediately_and_persists_under_data_agent(self) -> None:
        from services.agent_service import AgentService

        with tempfile.TemporaryDirectory() as root:
            runtime = BlockingRuntime()
            service = AgentService(AppPaths(root), runtime=runtime, capabilities=_registry())
            try:
                session = service.create_session({"title": "Async"})
                started = time.monotonic()
                response = service.send_message(
                    session["sessionId"],
                    {"clientMessageId": "client-1", "text": "run this", "runtimeProfileId": "default"},
                )
                elapsed = time.monotonic() - started

                self.assertLess(elapsed, 2.0)
                self.assertEqual(response["run"]["status"], "queued")
                self.assertTrue(runtime.started.wait(5.0))
                self.assertTrue(os.path.isfile(os.path.join(root, "data", "agent", "sessions-index.json")))
                self.assertTrue(os.path.isfile(os.path.join(
                    root,
                    "data",
                    "agent",
                    "sessions",
                    session["sessionId"],
                    "messages.jsonl",
                )))
                runtime.release.set()
                self.assertEqual(_wait_for_status(service, response["run"]["runId"], "completed")["status"], "completed")
            finally:
                runtime.release.set()
                service.shutdown()

    def test_client_message_id_is_idempotent_and_does_not_launch_twice(self) -> None:
        from services.agent_service import AgentService

        with tempfile.TemporaryDirectory() as root:
            runtime = BlockingRuntime()
            service = AgentService(AppPaths(root), runtime=runtime, capabilities=_registry())
            try:
                session = service.create_session({"title": "Idempotent"})
                body = {"clientMessageId": "same-client-id", "text": "only once"}
                first = service.send_message(session["sessionId"], body)
                self.assertTrue(runtime.started.wait(1.0))
                second = service.send_message(session["sessionId"], body)

                self.assertEqual(second["message"]["messageId"], first["message"]["messageId"])
                self.assertEqual(second["run"]["runId"], first["run"]["runId"])
                self.assertEqual(runtime.calls, 1)
            finally:
                runtime.release.set()
                service.shutdown()

    def test_session_rejects_a_second_run_while_the_first_is_active(self) -> None:
        from services.agent_service import AgentService

        with tempfile.TemporaryDirectory() as root:
            runtime = BlockingRuntime()
            service = AgentService(AppPaths(root), runtime=runtime, capabilities=_registry())
            try:
                session = service.create_session({"title": "One run at a time"})
                first = service.send_message(
                    session["sessionId"],
                    {"clientMessageId": "active-client-1", "text": "first"},
                )
                self.assertTrue(runtime.started.wait(1.0))

                with self.assertRaisesRegex(ValueError, "already active"):
                    service.send_message(
                        session["sessionId"],
                        {"clientMessageId": "active-client-2", "text": "second"},
                    )

                detail = service.session_detail(session["sessionId"], limit=50)
                self.assertEqual([item["messageId"] for item in detail["messages"]], [first["message"]["messageId"]])
                self.assertEqual(len(detail["runs"]), 1)
            finally:
                runtime.release.set()
                service.shutdown()

    def test_quick_pause_then_resume_chains_continuation_after_worker_wind_down(self) -> None:
        from services.agent_service import AgentService

        with tempfile.TemporaryDirectory() as root:
            runtime = SlowStoppingRuntime()
            service = AgentService(AppPaths(root), runtime=runtime, capabilities=_registry(), max_workers=2)
            try:
                session = service.create_session({"title": "Pause and resume"})
                sent = service.send_message(
                    session["sessionId"],
                    {"clientMessageId": "pause-resume-client", "text": "keep going"},
                )
                self.assertTrue(runtime.started.wait(1.0))

                paused = service.pause_run(sent["run"]["runId"])
                self.assertEqual(paused["status"], "paused")
                self.assertTrue(runtime.cancel_seen.wait(1.0))
                service.resume_run(sent["run"]["runId"])

                self.assertFalse(runtime.resumed.wait(0.1))
                runtime.allow_stop.set()
                self.assertTrue(runtime.resumed.wait(1.0))
                completed = _wait_for_status(service, sent["run"]["runId"], "completed")
                self.assertEqual(completed["status"], "completed")
                self.assertEqual(runtime.calls, 2)
            finally:
                runtime.allow_stop.set()
                service.shutdown()

    def test_follow_up_runtime_request_includes_prior_conversation_history(self) -> None:
        from services.agent_service import AgentService

        runtime = ScriptedRuntime([
            {"final": {"text": "first answer"}},
            {"final": {"text": "second answer"}},
        ])
        with tempfile.TemporaryDirectory() as root:
            service = AgentService(AppPaths(root), runtime=runtime, capabilities=_registry())
            try:
                session = service.create_session({"title": "History"})
                first = service.send_message(
                    session["sessionId"],
                    {"clientMessageId": "history-1", "text": "first question"},
                )
                _wait_for_status(service, first["run"]["runId"], "completed")
                second = service.send_message(
                    session["sessionId"],
                    {"clientMessageId": "history-2", "text": "follow up"},
                )
                _wait_for_status(service, second["run"]["runId"], "completed")
            finally:
                service.shutdown()

        history = runtime.requests[1].get("history")
        self.assertIsInstance(history, list)
        serialized = json.dumps(history, ensure_ascii=False)
        self.assertIn("first question", serialized)
        self.assertIn("first answer", serialized)

    def test_follow_up_runtime_request_includes_reusable_generated_artifacts(self) -> None:
        from services.agent_service import AgentService

        runtime = ScriptedRuntime([{"final": {"text": "reuse it"}}])
        with tempfile.TemporaryDirectory() as root:
            artifact_path = os.path.join(root, "wukong.png")
            with open(artifact_path, "wb") as handle:
                handle.write(b"image")
            service = AgentService(AppPaths(root), runtime=runtime, capabilities=_registry())
            try:
                session = service.create_session({"title": "Artifact history"})
                service.event_bus.publish(
                    session["sessionId"],
                    "tool.completed",
                    topic="agent.run",
                    entity_id="run_previous",
                    data={
                        "runId": "run_previous",
                        "toolCallId": "tool_image_previous",
                        "capability": "loom.media.image.generate",
                        "attachments": [{
                            "name": "wukong.png",
                            "path": artifact_path,
                            "mime": "image/png",
                            "kind": "image",
                        }],
                    },
                )
                sent = service.send_message(
                    session["sessionId"],
                    {"clientMessageId": "reuse-artifact-1", "text": "use the image already generated"},
                )
                _wait_for_status(service, sent["run"]["runId"], "completed")
            finally:
                service.shutdown()

        self.assertEqual(runtime.requests[0]["sessionArtifacts"], [{
            "name": "wukong.png",
            "path": artifact_path,
            "mime": "image/png",
            "kind": "image",
        }])

    def test_explicit_follow_up_inherits_the_recent_resolved_phone_scope_only(self) -> None:
        from services.agent_service import AgentService

        runtime = ScriptedRuntime([
            {"final": {"text": "first"}},
            {"final": {"text": "continued"}},
            {"final": {"text": "ordinary"}},
        ])
        with tempfile.TemporaryDirectory() as root:
            service = AgentService(
                AppPaths(root),
                runtime=runtime,
                capabilities=_registry(),
                matrix_factory=ProgressMatrix,
            )
            try:
                session = service.create_session({"title": "Scope continuation"})
                first = service.send_message(session["sessionId"], {
                    "clientMessageId": "scope-continuation-1",
                    "text": "\u53d1\u5e03\u5230\u5c0f\u7ea2\u4e66",
                    "scopeMode": "auto",
                })
                _wait_for_status(service, first["run"]["runId"], "completed")
                second = service.send_message(session["sessionId"], {
                    "clientMessageId": "scope-continuation-2",
                    "text": "\u6211\u5df2\u7ecf\u767b\u5f55\u597d\u4e86\uff0c\u7ee7\u7eed",
                    "scopeMode": "auto",
                })
                _wait_for_status(service, second["run"]["runId"], "completed")
                third = service.send_message(session["sessionId"], {
                    "clientMessageId": "scope-continuation-3",
                    "text": "summarize the conversation",
                    "scopeMode": "auto",
                })
                _wait_for_status(service, third["run"]["runId"], "completed")
            finally:
                service.shutdown()

        self.assertEqual(runtime.requests[1]["targets"], {"deviceIds": ["phone-progress"]})
        self.assertEqual(runtime.requests[2]["targets"], {})

    def test_explicit_capability_id_is_added_to_runtime_hints(self) -> None:
        from services.agent_service import AgentService

        runtime = ScriptedRuntime([{"final": {"text": "ready"}}])
        registry = _registry({
            "loom.phone.publish": {
                "executor": lambda _payload: {"ok": True},
                "permission": "control",
                "risk": "outbound",
            }
        })
        with tempfile.TemporaryDirectory() as root:
            service = AgentService(AppPaths(root), runtime=runtime, capabilities=registry)
            try:
                session = service.create_session({"title": "Explicit capability"})
                sent = service.send_message(
                    session["sessionId"],
                    {
                        "clientMessageId": "explicit-capability-1",
                        "text": "Please use loom.phone.publish to save this draft.",
                    },
                )
                _wait_for_status(service, sent["run"]["runId"], "completed")
            finally:
                service.shutdown()

        self.assertEqual(runtime.requests[0]["capabilityHints"], ["loom.phone.publish"])

    def test_approval_is_persisted_resolved_and_executes_tool_once(self) -> None:
        from services.agent_service import AgentService

        calls: list[dict] = []
        runtime = ScriptedRuntime([
            {
                "toolCalls": [{
                    "toolCallId": "publish-1",
                    "name": "loom.phone.publish",
                    "input": {"target": {"deviceIds": ["phone-1"]}, "text": "approved"},
                }]
            },
            {"final": {"text": "published"}},
        ])
        registry = _registry({
            "loom.phone.publish": {
                "executor": lambda payload: calls.append(payload) or {"ok": True},
                "permission": "control",
                "risk": "outbound",
                "timeoutSec": 2,
            }
        })
        with tempfile.TemporaryDirectory() as root:
            service = AgentService(
                AppPaths(root),
                runtime=runtime,
                capabilities=registry,
                policy=AgentPolicyEngine(approval_mode="strong"),
            )
            try:
                session = service.create_session({"title": "Approval"})
                sent = service.send_message(
                    session["sessionId"],
                    {"clientMessageId": "approval-client", "text": "publish"},
                )
                waiting = _wait_for_status(service, sent["run"]["runId"], "waiting_approval")
                trace = service.get_trace(waiting["runId"])
                approval = trace["approvals"][0]

                outcome = service.resolve_approval(
                    approval["approvalId"],
                    {"decision": "approved", "operator": "local-user"},
                )

                self.assertEqual(outcome["run"]["status"], "completed")
                self.assertEqual(outcome["approval"]["status"], "consumed")
                self.assertEqual(len(calls), 1)
                completed_trace = service.get_trace(waiting["runId"])["trace"]
                self.assertTrue(any(node["kind"] == "policy" for node in completed_trace))
                tool_nodes = [
                    node
                    for node in completed_trace
                    if node["kind"] == "tool" and node["inputSummary"].get("toolCallId") == "publish-1"
                ]
                self.assertEqual(len(tool_nodes), 1)
                self.assertEqual(tool_nodes[0]["status"], "completed")
                self.assertEqual(tool_nodes[0]["name"], "tool.completed")
            finally:
                service.shutdown()

    def test_queued_approval_returns_before_slow_tool_finishes(self) -> None:
        from services.agent_service import AgentService

        started = threading.Event()
        release = threading.Event()
        calls: list[dict] = []

        def slow_publish(payload):
            calls.append(payload)
            started.set()
            release.wait(3)
            return {"ok": True}

        runtime = ScriptedRuntime([
            {
                "toolCalls": [{
                    "toolCallId": "publish-slow",
                    "name": "loom.phone.publish",
                    "input": {"target": {"deviceIds": ["phone-1"]}, "text": "approved"},
                }]
            },
            {"final": {"text": "published"}},
        ])
        registry = _registry({
            "loom.phone.publish": {
                "executor": slow_publish,
                "permission": "control",
                "risk": "outbound",
                "timeoutSec": 5,
            }
        })
        with tempfile.TemporaryDirectory() as root:
            service = AgentService(
                AppPaths(root),
                runtime=runtime,
                capabilities=registry,
                policy=AgentPolicyEngine(approval_mode="strong"),
            )
            try:
                session = service.create_session({"title": "Queued approval"})
                sent = service.send_message(
                    session["sessionId"],
                    {"clientMessageId": "queued-approval-client", "text": "publish"},
                )
                waiting = _wait_for_status(service, sent["run"]["runId"], "waiting_approval")
                approval = service.get_trace(waiting["runId"])["approvals"][0]

                before = time.monotonic()
                outcome = service.queue_approval_resolution(
                    approval["approvalId"],
                    {"decision": "approved", "operator": "local-user"},
                )
                elapsed = time.monotonic() - before

                self.assertLess(elapsed, 0.5)
                self.assertEqual(outcome["approval"]["status"], "approved")
                self.assertTrue(started.wait(1))
                self.assertEqual(len(calls), 1)
                release.set()
                completed = _wait_for_status(service, waiting["runId"], "completed")
                self.assertEqual(completed["status"], "completed")
                self.assertEqual(
                    service.get_trace(waiting["runId"])["approvals"][0]["status"],
                    "consumed",
                )
                events = service.events_after(session_id=session["sessionId"], after_seq=0)
                self.assertEqual([event["type"] for event in events].count("runtime.requested"), 1)
            finally:
                release.set()
                service.shutdown()

    def test_restart_recovery_pauses_uncertain_run_and_starts_safe_queued_run(self) -> None:
        from services.agent_service import AgentService

        with tempfile.TemporaryDirectory() as root:
            paths = AppPaths(root)
            repository = AgentSessionRepository(paths)
            repository.create_session("Uncertain", session_id="session-uncertain")
            repository.create_run({
                "schema": "loom.agent.run.v1",
                "runId": "run-uncertain",
                "sessionId": "session-uncertain",
                "status": "running",
                "campaignIds": [],
                "checkpoint": json.dumps({
                    "version": 1,
                    "completedToolCallIds": [],
                    "toolResults": [],
                    "inFlightToolCall": {"toolCallId": "unknown", "name": "loom.matrix.dispatch", "input": {}},
                }),
            })
            repository.create_session("Queued", session_id="session-queued")
            repository.create_run({
                "schema": "loom.agent.run.v1",
                "runId": "run-queued",
                "sessionId": "session-queued",
                "status": "queued",
                "campaignIds": [],
                "checkpoint": "",
                "request": {"prompt": "resume safely", "runtimeProfileId": "default"},
            })

            runtime = ScriptedRuntime([{"final": {"text": "recovered"}}])
            service = AgentService(paths, runtime=runtime, capabilities=_registry())
            try:
                uncertain = service.get_run("run-uncertain")
                self.assertEqual(uncertain["status"], "paused")
                self.assertEqual(uncertain["error"]["code"], "agent_restart_inflight_unknown")
                self.assertTrue(uncertain["error"]["recoverable"])
                self.assertEqual(_wait_for_status(service, "run-queued", "completed")["status"], "completed")
                self.assertEqual(len(runtime.requests), 1)
                self.assertEqual(runtime.requests[0]["runtimeProfileId"], "loom-native")
            finally:
                service.shutdown()

    def test_restart_restores_matrix_links_with_bounded_session_pagination(self) -> None:
        from services.agent_service import AgentService

        with tempfile.TemporaryDirectory() as root:
            paths = AppPaths(root)
            repository = AgentSessionRepository(paths)
            for index in range(201):
                session_id = f"session-{index:03d}"
                repository.create_session(f"Session {index}", session_id=session_id)
            repository.create_run({
                "schema": "loom.agent.run.v1",
                "runId": "run-page-two",
                "sessionId": "session-000",
                "status": "completed",
                "campaignIds": ["campaign-page-two"],
                "checkpoint": "",
            })

            original_list_sessions = AgentSessionRepository.list_sessions
            calls: list[dict] = []

            def tracked_list_sessions(instance, *args, **kwargs):
                calls.append(dict(kwargs))
                return original_list_sessions(instance, *args, **kwargs)

            with patch.object(AgentSessionRepository, "list_sessions", new=tracked_list_sessions):
                service = AgentService(
                    paths,
                    runtime=UnavailableRuntime(),
                    capabilities=_registry(),
                    matrix_factory=lambda: ProgressMatrix(),
                )
                try:
                    self.assertIn("campaign-page-two", service._campaign_links)
                finally:
                    service.shutdown()

        self.assertGreaterEqual(len(calls), 2)
        self.assertTrue(all(int(call.get("limit", 50)) <= 200 for call in calls))
        self.assertTrue(any(call.get("cursor") for call in calls))

    def test_bootstrap_reports_unavailable_runtime_and_only_allowlisted_capabilities(self) -> None:
        from services.agent_service import AgentService

        catalog = {
            "domains": [{
                "commands": [
                    {"name": "status", "permission": "read"},
                    {"name": "shell", "permission": "admin"},
                ]
            }]
        }
        registry = CapabilityRegistry(
            skill_provider=lambda: [],
            mcp_provider=lambda: [],
            cli_catalog_provider=lambda: catalog,
        )
        with tempfile.TemporaryDirectory() as root:
            service = AgentService(AppPaths(root), runtime=UnavailableRuntime(), capabilities=registry)
            try:
                with patch.object(
                    registry,
                    "get",
                    side_effect=AssertionError("bootstrap must consume the registry catalog directly"),
                ):
                    bootstrap = service.bootstrap()
            finally:
                service.shutdown()

        self.assertFalse(bootstrap["runtime"]["available"])
        self.assertEqual(bootstrap["runtime"]["error"]["code"], "agent_runtime_unavailable")
        self.assertTrue(bootstrap["runtime"]["error"]["recoverable"])
        self.assertFalse(bootstrap["runtimeProfiles"][0]["available"])
        self.assertTrue(bootstrap["errors"])
        capabilities = {item["name"]: item for item in bootstrap["capabilities"]}
        self.assertIn("loom.cli.status", capabilities)
        self.assertTrue(capabilities["loom.cli.status"]["available"])
        self.assertNotIn("loom.cli.shell", capabilities)
        self.assertIn("loom.media.image.generate", capabilities)
        self.assertFalse(capabilities["loom.media.image.generate"]["available"])
        self.assertIn("policy", bootstrap)
        self.assertIn("limits", bootstrap)

    def test_default_bootstrap_exposes_only_loom_native_profile(self) -> None:
        from services.agent_service import AgentService

        with tempfile.TemporaryDirectory() as root:
            account = FakeAccount(_managed_session())
            with patch("services.agent_service.shutil.which") as discover:
                service = AgentService(AppPaths(root), account_manager=account, capabilities=_registry())
                try:
                    bootstrap = service.bootstrap()
                finally:
                    service.shutdown()

        discover.assert_not_called()
        self.assertEqual(bootstrap["defaultRuntimeProfileId"], "loom-native")
        self.assertEqual(bootstrap["runtimeProfiles"], [{
            "runtimeProfileId": "loom-native",
            "name": "麓鸣原生智能体",
            "available": True,
            "isDefault": True,
        }])

    def test_runtime_profile_ids_are_normalized_for_sessions_requests_and_snapshots(self) -> None:
        from services.agent_service import AgentService

        runtime = ScriptedRuntime([{"final": {"text": "done"}}])
        with tempfile.TemporaryDirectory() as root:
            service = AgentService(AppPaths(root), runtime=runtime, capabilities=_registry())
            try:
                session = service.create_session({"title": "Native", "runtimeProfileId": "codex"})
                updated = service.update_session(session["sessionId"], {"runtimeProfileId": "claude"})
                sent = service.send_message(session["sessionId"], {
                    "clientMessageId": "native-profile-client",
                    "text": "normalize this",
                    "runtimeProfileId": "claude",
                })
                _wait_for_status(service, sent["run"]["runId"], "completed")
                events = service.events_after(session_id=session["sessionId"], after_seq=0)
            finally:
                service.shutdown()

        requested = next(event for event in events if event["type"] == "runtime.requested")
        self.assertEqual(session["runtimeProfileId"], "loom-native")
        self.assertEqual(updated["runtimeProfileId"], "loom-native")
        self.assertEqual(sent["run"]["request"]["runtimeProfileId"], "loom-native")
        self.assertEqual(runtime.requests[0]["runtimeProfileId"], "loom-native")
        self.assertEqual(requested["data"]["promptSnapshot"]["runtimeProfileId"], "loom-native")

    def test_default_bootstrap_reports_login_required_for_logged_out_account(self) -> None:
        from services.agent_service import AgentService

        with tempfile.TemporaryDirectory() as root:
            service = AgentService(AppPaths(root), account_manager=FakeAccount(), capabilities=_registry())
            try:
                bootstrap = service.bootstrap()
            finally:
                service.shutdown()

        self.assertEqual(bootstrap["runtimeProfiles"], [{
            "runtimeProfileId": "loom-native",
            "name": "麓鸣原生智能体",
            "available": False,
            "isDefault": True,
            "error": {
                "code": "AGENT_ACCOUNT_LOGIN_REQUIRED",
                "message": "Managed model login is required.",
            },
        }])
        self.assertEqual(bootstrap["errors"][0]["code"], "AGENT_ACCOUNT_LOGIN_REQUIRED")

    def test_matrix_campaign_progress_is_written_back_to_the_linked_agent_event_ledger(self) -> None:
        from services.agent_service import AgentService

        runtime = ScriptedRuntime([
            {
                "toolCalls": [{
                    "toolCallId": "dispatch-progress",
                    "name": "loom.matrix.dispatch",
                    "input": {"prompt": "check", "target": {"deviceIds": ["phone-progress"]}},
                }]
            },
            {"final": {"text": "Matrix campaign started."}},
        ])
        matrix = ProgressMatrix()
        with tempfile.TemporaryDirectory() as root:
            service = AgentService(
                AppPaths(root),
                runtime=runtime,
                matrix_factory=lambda: matrix,
                policy=AgentPolicyEngine(approval_mode="strong"),
            )
            try:
                session = service.create_session({"title": "Progress"})
                sent = service.send_message(
                    session["sessionId"],
                    {
                        "clientMessageId": "progress-client",
                        "text": "dispatch",
                        "targets": {"deviceIds": ["phone-progress"]},
                    },
                )
                waiting = _wait_for_status(service, sent["run"]["runId"], "waiting_approval")
                approval = service.get_trace(waiting["runId"])["approvals"][0]
                resolved = service.resolve_approval(approval["approvalId"], {"decision": "approved"})
                self.assertEqual(resolved["run"]["status"], "completed")

                deadline = time.monotonic() + 2
                events = []
                while time.monotonic() < deadline:
                    events = service.events_after(session_id=session["sessionId"], after_seq=0)
                    if any(event["type"] == "matrix.progress" for event in events):
                        break
                    time.sleep(0.05)
                self.assertTrue(any(event["type"] == "matrix.attached" for event in events))
                progress = next(event for event in events if event["type"] == "matrix.progress")
                self.assertEqual(progress["data"]["runId"], sent["run"]["runId"])
                self.assertEqual(progress["data"]["deviceIds"], ["phone-progress"])
                self.assertEqual(progress["data"]["counts"]["running"], 1)
                self.assertEqual(progress["data"]["total"], 1)

                matrix.campaign["status"] = "succeeded"
                matrix.campaign["missions"][0]["status"] = "succeeded"
                matrix.campaign["missions"][0]["deviceTasks"][0]["status"] = "succeeded"
                deadline = time.monotonic() + 2
                while time.monotonic() < deadline:
                    events = service.events_after(session_id=session["sessionId"], after_seq=0)
                    if any(event["type"] == "matrix.succeeded" for event in events):
                        break
                    time.sleep(0.05)
                completed = next(event for event in events if event["type"] == "matrix.succeeded")
                self.assertEqual(completed["data"]["completed"], 1)
                self.assertEqual(completed["data"]["messageId"], "matrix:campaign-progress")
                self.assertNotIn("campaign-progress", service._campaign_links)
            finally:
                service.shutdown()

    def test_model_supplied_matrix_confirmation_is_ignored(self) -> None:
        from services.agent_service import AgentService

        with tempfile.TemporaryDirectory() as root:
            matrix = ConfirmationMatrix()
            service = AgentService(
                AppPaths(root),
                runtime=UnavailableRuntime(),
                capabilities=_registry(),
                matrix_factory=lambda: matrix,
                policy=AgentPolicyEngine(approval_mode="strong"),
            )
            try:
                service._matrix_dispatch({
                    "prompt": "inspect",
                    "targets": {"deviceIds": ["phone-progress"]},
                    "confirmed": True,
                })
            finally:
                service.shutdown()

        self.assertNotIn("confirmed", matrix.dispatches[0])

    def test_weak_policy_auto_confirms_explicit_matrix_outreach_without_an_approval_card(self) -> None:
        from services.agent_service import AgentService

        runtime = ScriptedRuntime([
            {
                "toolCalls": [{
                    "toolCallId": "dispatch-weak",
                    "name": "loom.matrix.dispatch",
                    "input": {
                        "prompt": "send_dm to the selected account",
                        "targets": {"deviceIds": ["phone-progress"]},
                    },
                }]
            },
            {"final": {"text": "dispatch complete"}},
        ])
        with tempfile.TemporaryDirectory() as root:
            matrix = ConfirmationMatrix(require_confirmation=True)
            service = AgentService(AppPaths(root), runtime=runtime, matrix_factory=lambda: matrix)
            try:
                session = service.create_session({"title": "Weak dispatch"})
                sent = service.send_message(session["sessionId"], {
                    "clientMessageId": "weak-dispatch-client",
                    "text": "contact the selected account",
                    "targets": {"deviceIds": ["phone-progress"]},
                })
                completed = _wait_for_status(service, sent["run"]["runId"], "completed")
                trace = service.get_trace(completed["runId"])
            finally:
                service.shutdown()

        self.assertEqual(trace["approvals"], [])
        self.assertEqual(len(matrix.dispatches), 1)
        self.assertIs(matrix.dispatches[0].get("confirmed"), True)

    def test_approved_matrix_tool_call_receives_one_server_confirmation(self) -> None:
        from services.agent_service import AgentService

        runtime = ScriptedRuntime([
            {
                "toolCalls": [{
                    "toolCallId": "dispatch-confirmed",
                    "name": "loom.matrix.dispatch",
                    "input": {
                        "prompt": "send_dm to the selected account",
                        "targets": {"deviceIds": ["phone-progress"]},
                    },
                }]
            },
            {"final": {"text": "approved dispatch complete"}},
        ])
        with tempfile.TemporaryDirectory() as root:
            matrix = ConfirmationMatrix(require_confirmation=True)
            service = AgentService(
                AppPaths(root),
                runtime=runtime,
                matrix_factory=lambda: matrix,
                policy=AgentPolicyEngine(approval_mode="strong"),
            )
            try:
                session = service.create_session({"title": "Confirmed dispatch"})
                sent = service.send_message(session["sessionId"], {
                    "clientMessageId": "confirmed-dispatch-client",
                    "text": "contact the selected account",
                    "targets": {"deviceIds": ["phone-progress"]},
                })
                waiting = _wait_for_status(service, sent["run"]["runId"], "waiting_approval")
                self.assertEqual(matrix.dispatches, [])
                approval = service.get_trace(waiting["runId"])["approvals"][0]

                outcome = service.resolve_approval(approval["approvalId"], {"decision": "approved"})

                self.assertEqual(outcome["run"]["status"], "completed")
                self.assertEqual(len(matrix.dispatches), 1)
                self.assertIs(matrix.dispatches[0].get("confirmed"), True)
            finally:
                service.shutdown()

    def test_queued_approved_matrix_tool_call_keeps_server_confirmation(self) -> None:
        from services.agent_service import AgentService

        runtime = ScriptedRuntime([
            {
                "toolCalls": [{
                    "toolCallId": "dispatch-confirmed-queued",
                    "name": "loom.matrix.dispatch",
                    "input": {
                        "prompt": "send_dm to the selected account",
                        "targets": {"deviceIds": ["phone-progress"]},
                    },
                }]
            },
            {"final": {"text": "approved dispatch complete"}},
        ])
        with tempfile.TemporaryDirectory() as root:
            matrix = ConfirmationMatrix(require_confirmation=True)
            service = AgentService(
                AppPaths(root),
                runtime=runtime,
                matrix_factory=lambda: matrix,
                policy=AgentPolicyEngine(approval_mode="strong"),
            )
            try:
                session = service.create_session({"title": "Queued confirmed dispatch"})
                sent = service.send_message(session["sessionId"], {
                    "clientMessageId": "queued-confirmed-dispatch-client",
                    "text": "contact the selected account",
                    "targets": {"deviceIds": ["phone-progress"]},
                })
                waiting = _wait_for_status(service, sent["run"]["runId"], "waiting_approval")
                approval = service.get_trace(waiting["runId"])["approvals"][0]

                outcome = service.queue_approval_resolution(
                    approval["approvalId"],
                    {"decision": "approved"},
                )
                completed = _wait_for_status(service, waiting["runId"], "completed")

                self.assertEqual(outcome["approval"]["status"], "approved")
                self.assertEqual(completed["status"], "completed")
                self.assertEqual(len(matrix.dispatches), 1)
                self.assertIs(matrix.dispatches[0].get("confirmed"), True)
                events = service.events_after(session_id=session["sessionId"], after_seq=0)
                self.assertEqual([event["type"] for event in events].count("runtime.requested"), 1)
            finally:
                service.shutdown()

    def test_cancel_run_cascades_to_linked_matrix_campaigns_and_jobs(self) -> None:
        from services.agent_service import AgentService

        with tempfile.TemporaryDirectory() as root:
            matrix = CancellableMatrix()
            jobs = RecordingJobManager()
            service = AgentService(
                AppPaths(root),
                runtime=UnavailableRuntime(),
                capabilities=_registry(),
                matrix_factory=lambda: matrix,
                job_manager=jobs,
            )
            try:
                session = service.create_session({"title": "Cascade cancel"})
                service.repository.create_run({
                    "schema": "loom.agent.run.v1",
                    "runId": "run-cascade-cancel",
                    "sessionId": session["sessionId"],
                    "status": "running",
                    "campaignIds": ["campaign-progress"],
                    "checkpoint": "",
                })
                service._register_matrix_campaign(
                    session["sessionId"], "run-cascade-cancel", "campaign-progress", {}
                )

                cancelled = service.cancel_run("run-cascade-cancel")

                self.assertEqual(cancelled["status"], "cancelled")
                self.assertEqual(matrix.cancelled_campaign_ids, ["campaign-progress"])
                self.assertEqual(jobs.cancelled_job_ids, ["job-progress"])
                self.assertNotIn("campaign-progress", service._campaign_links)
            finally:
                service.shutdown()

    def test_cancel_run_stays_nonterminal_while_linked_campaign_is_still_running(self) -> None:
        from services.agent_service import AgentService

        with tempfile.TemporaryDirectory() as root:
            matrix = CancellableMatrix(completes_cancel=False)
            service = AgentService(
                AppPaths(root),
                runtime=UnavailableRuntime(),
                capabilities=_registry(),
                matrix_factory=lambda: matrix,
            )
            try:
                session = service.create_session({"title": "Incomplete cancel"})
                service.repository.create_run({
                    "schema": "loom.agent.run.v1",
                    "runId": "run-incomplete-cancel",
                    "sessionId": session["sessionId"],
                    "status": "running",
                    "campaignIds": ["campaign-progress"],
                    "checkpoint": "",
                })
                service._register_matrix_campaign(
                    session["sessionId"], "run-incomplete-cancel", "campaign-progress", {}
                )

                outcome = service.cancel_run("run-incomplete-cancel")

                self.assertNotEqual(outcome["status"], "cancelled")
                self.assertEqual(outcome["error"]["code"], "agent_matrix_cancel_incomplete")
                self.assertTrue(outcome["error"]["recoverable"])
                self.assertIn("campaign-progress", service._campaign_links)
            finally:
                service.shutdown()

    def test_installed_skill_is_loaded_as_instructions_without_executing_package_scripts(self) -> None:
        from services.agent_service import AgentService

        with tempfile.TemporaryDirectory() as root:
            paths = AppPaths(root)
            skill_dir = os.path.join(paths.skills_dir, "resume-screening")
            os.makedirs(skill_dir, exist_ok=True)
            with open(os.path.join(skill_dir, "SKILL.md"), "w", encoding="utf-8") as handle:
                handle.write("# Resume Screening\nRead candidate summaries before ranking.\n")
            with open(os.path.join(skill_dir, "dangerous.py"), "w", encoding="utf-8") as handle:
                handle.write("raise RuntimeError('must never execute')\n")

            service = AgentService(paths, runtime=UnavailableRuntime())
            try:
                capability = service.capabilities.get("loom.skill.resume-screening")
                result = service.capabilities.execute("loom.skill.resume-screening", {"role": "recruiter"})
            finally:
                service.shutdown()

        self.assertEqual(capability.permission, "admin")
        self.assertEqual(capability.risk, "critical")
        self.assertIn("Read candidate summaries", result["instructions"])
        self.assertEqual(result["requestedContext"], {"role": "recruiter"})

    def test_service_redacts_secrets_from_persisted_request_and_events(self) -> None:
        from services.agent_service import AgentService

        with tempfile.TemporaryDirectory() as root:
            runtime = ScriptedRuntime([{"final": {"text": "done"}}])
            service = AgentService(AppPaths(root), runtime=runtime, capabilities=_registry())
            try:
                session = service.create_session({"title": "Secrets"})
                sent = service.send_message(session["sessionId"], {
                    "clientMessageId": "secret-client",
                    "text": "Authorization: Bearer secret.value",
                    "attachments": [{"name": "safe.txt", "apiKey": "sk-super-secret-value"}],
                })
                _wait_for_status(service, sent["run"]["runId"], "completed")
            finally:
                service.shutdown()

            persisted = ""
            for directory, _subdirs, files in os.walk(os.path.join(root, "data", "agent")):
                for filename in files:
                    with open(os.path.join(directory, filename), "r", encoding="utf-8") as handle:
                        persisted += handle.read()
        self.assertNotIn("secret.value", persisted)
        self.assertNotIn("sk-super-secret-value", persisted)

    def test_bridge_context_exposes_one_lazy_agent_service(self) -> None:
        import bridge

        with tempfile.TemporaryDirectory() as root:
            with (
                patch.object(bridge, "paths", AppPaths(root)),
                patch.object(bridge, "_agent_service", None),
                patch.object(bridge, "_newapi_account_mgr", None),
            ):
                context = bridge._build_fastapi_context()
                first = context.get_agent_service()
                second = context.get_agent_service()
                try:
                    self.assertIs(first, second)
                    self.assertEqual(first.repository.root, os.path.join(root, "data", "agent"))
                    self.assertIs(first.account_manager, bridge._get_newapi_account_mgr())
                finally:
                    first.shutdown()


if __name__ == "__main__":
    unittest.main()
