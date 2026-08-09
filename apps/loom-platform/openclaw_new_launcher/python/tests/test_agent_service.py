from __future__ import annotations

import base64
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch


PYTHON_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)


from core.agent_capabilities import CapabilityRegistry
from core.agent_policy import AgentPolicyEngine
from core.agent_runtime import RuntimeExecutionError
from core.agent_sessions import AgentSessionRepository
from core.job_ownership import account_job_binding
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


def _matrix_account_context(
    root: str,
    account_id: str,
    install_id: str,
) -> SimpleNamespace:
    class Entitlement:
        def current_state(self, _feature=None):
            return {
                "authorized": True,
                "accountId": account_id,
                "lease": {
                    "accountId": account_id,
                    "installId": install_id,
                },
                "limits": {"devices": 1000, "concurrentTasks": 8},
            }

        def authorize_phone_devices(
            self,
            _device_ids,
            _operation,
            *,
            session=None,
        ):
            return {
                "authorized": True,
                "accountId": account_id,
                "limits": {"devices": 1000, "concurrentTasks": 8},
            }

    entitlement = Entitlement()
    return SimpleNamespace(
        paths=AppPaths(root),
        get_entitlement_mgr=lambda: entitlement,
        protected_error=lambda _path: None,
    )


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

    def status(self, campaign_id=None):
        payload = {
            "devices": json.loads(json.dumps(self.devices)),
            "campaigns": [json.loads(json.dumps(self.campaign))],
        }
        if campaign_id:
            payload["campaigns"] = [
                campaign
                for campaign in payload["campaigns"]
                if campaign.get("campaignId") == campaign_id
            ]
        return payload


class GatedStatusMatrix(ProgressMatrix):
    def __init__(self) -> None:
        super().__init__()
        self.status_entered = threading.Event()
        self.release_status = threading.Event()

    def status(self, campaign_id=None):
        self.status_entered.set()
        if not self.release_status.wait(5.0):
            raise RuntimeError("timed out waiting to release matrix status")
        return super().status(campaign_id)


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


class ConfirmationRetryMatrix(ConfirmationMatrix):
    def __init__(self, *, require_confirmation: bool = False) -> None:
        super().__init__(require_confirmation=require_confirmation)
        self.retries: list[dict] = []

    def retry_failed(self, campaign_id, body):
        self.retries.append({"campaignId": campaign_id, **dict(body)})
        if self.require_confirmation and body.get("confirmed") is not True:
            raise ValueError("server confirmation required")
        return {
            "retried": True,
            "retryOf": campaign_id,
            "task": {
                "campaignId": "campaign-retry-progress",
                "status": "queued",
                "missions": [],
            },
            "dispatchBody": dict(body),
        }


class MultiPhoneMatrix(ConfirmationMatrix):
    def __init__(self) -> None:
        super().__init__()
        self.devices = [
            {"deviceId": "phone-1", "online": True, "group": "本机手机", "groups": ["本机手机"]},
            {"deviceId": "phone-2", "online": True, "group": "本机手机", "groups": ["本机手机"]},
        ]


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
    def test_image_attachment_is_materialized_without_persisting_inline_base64(self) -> None:
        from services.agent_service import AgentService

        image_bytes = b"\x89PNG\r\n\x1a\nloom"
        data_url = "data:image/png;base64," + base64.b64encode(image_bytes).decode("ascii")
        runtime = ScriptedRuntime([{"final": {"text": "image received"}}])
        with tempfile.TemporaryDirectory() as root:
            service = AgentService(AppPaths(root), runtime=runtime, capabilities=_registry())
            try:
                session = service.create_session({"title": "Image attachment"})
                sent = service.send_message(session["sessionId"], {
                    "clientMessageId": "image-attachment-1",
                    "text": "请分析图片",
                    "attachments": [{
                        "name": "../cover.png",
                        "size": len(image_bytes),
                        "type": "image/png",
                        "kind": "image",
                        "dataUrl": data_url,
                    }],
                })
                _wait_for_status(service, sent["run"]["runId"], "completed")
                attachment = runtime.requests[0]["attachments"][0]
                self.assertNotIn("dataUrl", attachment)
                self.assertEqual(attachment["name"], "cover.png")
                self.assertEqual(attachment["kind"], "image")
                self.assertTrue(os.path.isfile(attachment["path"]))
                with open(attachment["path"], "rb") as handle:
                    self.assertEqual(handle.read(), image_bytes)
                self.assertEqual(
                    os.path.commonpath([
                        os.path.abspath(attachment["path"]),
                        os.path.join(os.path.abspath(root), "data", "agent", "attachments"),
                    ]),
                    os.path.join(os.path.abspath(root), "data", "agent", "attachments"),
                )
            finally:
                service.shutdown()

            persisted = ""
            for directory, _subdirs, files in os.walk(os.path.join(root, "data", "agent")):
                for filename in files:
                    if filename.endswith((".json", ".jsonl")):
                        with open(os.path.join(directory, filename), "r", encoding="utf-8") as handle:
                            persisted += handle.read()
            self.assertNotIn(data_url, persisted)

    def test_unsupported_attachment_is_rejected_before_run_creation(self) -> None:
        from services.agent_service import AgentService

        with tempfile.TemporaryDirectory() as root:
            service = AgentService(AppPaths(root), runtime=UnavailableRuntime(), capabilities=_registry())
            try:
                session = service.create_session({"title": "Unsupported attachment"})
                with self.assertRaisesRegex(ValueError, "AGENT_ATTACHMENT_TYPE_UNSUPPORTED"):
                    service.send_message(session["sessionId"], {
                        "clientMessageId": "unsupported-attachment-1",
                        "text": "",
                        "attachments": [{
                            "name": "brief.pdf",
                            "size": 3,
                            "type": "application/pdf",
                            "kind": "binary",
                            "dataUrl": "data:application/pdf;base64,cGRm",
                        }],
                    })
                self.assertEqual(service.repository.list_runs(session["sessionId"]), [])
            finally:
                service.shutdown()

    def test_attachment_validation_failure_removes_files_created_earlier_in_request(self) -> None:
        from services.agent_service import AgentService

        image_bytes = b"\x89PNG\r\n\x1a\nloom"
        data_url = "data:image/png;base64," + base64.b64encode(image_bytes).decode("ascii")
        with tempfile.TemporaryDirectory() as root:
            service = AgentService(AppPaths(root), runtime=UnavailableRuntime(), capabilities=_registry())
            try:
                session = service.create_session({"title": "Attachment validation rollback"})
                with self.assertRaisesRegex(ValueError, "AGENT_ATTACHMENT_TYPE_UNSUPPORTED"):
                    service.send_message(session["sessionId"], {
                        "clientMessageId": "attachment-validation-rollback-1",
                        "text": "",
                        "attachments": [
                            {
                                "name": "valid.png",
                                "size": len(image_bytes),
                                "type": "image/png",
                                "kind": "image",
                                "dataUrl": data_url,
                            },
                            {
                                "name": "unsupported.pdf",
                                "size": 3,
                                "type": "application/pdf",
                                "kind": "binary",
                                "dataUrl": "data:application/pdf;base64,cGRm",
                            },
                        ],
                    })
                attachment_root = os.path.join(root, "data", "agent", "attachments")
                remaining = [
                    os.path.join(directory, filename)
                    for directory, _subdirs, files in os.walk(attachment_root)
                    for filename in files
                ]
                self.assertEqual(remaining, [])
            finally:
                service.shutdown()

    def test_message_persistence_failure_removes_unreferenced_attachment(self) -> None:
        from services.agent_service import AgentService

        image_bytes = b"\x89PNG\r\n\x1a\nloom"
        data_url = "data:image/png;base64," + base64.b64encode(image_bytes).decode("ascii")
        with tempfile.TemporaryDirectory() as root:
            service = AgentService(AppPaths(root), runtime=UnavailableRuntime(), capabilities=_registry())
            try:
                session = service.create_session({"title": "Attachment persistence rollback"})
                with patch.object(
                    service.repository,
                    "create_message_run",
                    side_effect=OSError("simulated persistence failure"),
                ):
                    with self.assertRaisesRegex(OSError, "simulated persistence failure"):
                        service.send_message(session["sessionId"], {
                            "clientMessageId": "attachment-persistence-rollback-1",
                            "text": "persist this",
                            "attachments": [{
                                "name": "persist.png",
                                "size": len(image_bytes),
                                "type": "image/png",
                                "kind": "image",
                                "dataUrl": data_url,
                            }],
                        })
                attachment_root = os.path.join(root, "data", "agent", "attachments")
                remaining = [
                    os.path.join(directory, filename)
                    for directory, _subdirs, files in os.walk(attachment_root)
                    for filename in files
                ]
                self.assertEqual(remaining, [])
            finally:
                service.shutdown()

    def test_post_commit_failure_keeps_durably_referenced_attachment(self) -> None:
        from services.agent_service import AgentService

        image_bytes = b"\x89PNG\r\n\x1a\nloom"
        data_url = "data:image/png;base64," + base64.b64encode(image_bytes).decode("ascii")
        with tempfile.TemporaryDirectory() as root:
            service = AgentService(AppPaths(root), runtime=UnavailableRuntime(), capabilities=_registry())
            try:
                session = service.create_session({"title": "Attachment committed before response failure"})
                original_create = service.repository.create_message_run

                def persist_then_fail(*args, **kwargs):
                    original_create(*args, **kwargs)
                    raise OSError("response failed after durable commit")

                with patch.object(service.repository, "create_message_run", side_effect=persist_then_fail):
                    with self.assertRaisesRegex(OSError, "response failed after durable commit"):
                        service.send_message(session["sessionId"], {
                            "clientMessageId": "attachment-post-commit-1",
                            "text": "persist this first",
                            "attachments": [{
                                "name": "committed.png",
                                "size": len(image_bytes),
                                "type": "image/png",
                                "kind": "image",
                                "dataUrl": data_url,
                            }],
                        })

                existing = service.repository.find_message_run(
                    session["sessionId"],
                    "attachment-post-commit-1",
                )
                self.assertIsNotNone(existing)
                attachment_root = os.path.join(
                    root,
                    "data",
                    "agent",
                    "attachments",
                    session["sessionId"],
                )
                remaining = [
                    os.path.join(directory, filename)
                    for directory, _subdirs, files in os.walk(attachment_root)
                    for filename in files
                ]
                self.assertEqual(len(remaining), 1)
                with open(remaining[0], "rb") as handle:
                    self.assertEqual(handle.read(), image_bytes)
            finally:
                service.shutdown()

    def test_pending_message_transaction_keeps_attachment_until_recovery(self) -> None:
        from services.agent_service import AgentService

        image_bytes = b"\x89PNG\r\n\x1a\nloom"
        data_url = "data:image/png;base64," + base64.b64encode(image_bytes).decode("ascii")
        with tempfile.TemporaryDirectory() as root:
            service = AgentService(AppPaths(root), runtime=UnavailableRuntime(), capabilities=_registry())
            try:
                session = service.create_session({"title": "Attachment transaction recovery"})
                body = {
                    "clientMessageId": "attachment-transaction-recovery-1",
                    "text": "recover this",
                    "attachments": [{
                        "name": "recover.png",
                        "size": len(image_bytes),
                        "type": "image/png",
                        "kind": "image",
                        "dataUrl": data_url,
                    }],
                }
                with patch.object(
                    service.repository,
                    "_commit_message_transaction_unlocked",
                    side_effect=OSError("commit interrupted after transaction write"),
                ):
                    with self.assertRaisesRegex(OSError, "commit interrupted"):
                        service.send_message(session["sessionId"], body)

                attachment_root = os.path.join(
                    root,
                    "data",
                    "agent",
                    "attachments",
                    session["sessionId"],
                )
                before_recovery = [
                    os.path.join(directory, filename)
                    for directory, _subdirs, files in os.walk(attachment_root)
                    for filename in files
                ]
                self.assertEqual(len(before_recovery), 1)

                recovered = service.send_message(session["sessionId"], body)
                persisted_run = service.repository.get_run(recovered["run"]["runId"])
                self.assertNotIn("request", recovered["run"])
                persisted_path = persisted_run["request"]["attachments"][0]["path"]
                self.assertTrue(os.path.isfile(persisted_path))
                after_recovery = [
                    os.path.join(directory, filename)
                    for directory, _subdirs, files in os.walk(attachment_root)
                    for filename in files
                ]
                self.assertEqual(after_recovery, [persisted_path])
            finally:
                service.shutdown()

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
                persisted = service.repository.get_run(sent["run"]["runId"])
            finally:
                service.shutdown()

        self.assertNotIn("request", completed)
        request = persisted["request"]
        self.assertEqual(request["scopeMode"], "auto")
        self.assertEqual(request["targets"], {"deviceIds": ["phone-progress"]})
        self.assertEqual(request["requestScope"]["status"], "resolved")
        self.assertEqual(runtime.requests[0]["requestScope"], request["requestScope"])

    def test_oem_brand_identity_reaches_bootstrap_and_model_request(self) -> None:
        from services.agent_service import AgentService

        runtime = ScriptedRuntime([{"final": {"text": "done"}}])
        with tempfile.TemporaryDirectory() as root:
            paths = AppPaths(root)
            os.makedirs(os.path.dirname(paths.brand_profile), exist_ok=True)
            with open(paths.brand_profile, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "displayName": "Northstar AI Matrix",
                        "nativeAgentName": "Northstar AI Matrix 原生智能体",
                    },
                    handle,
                    ensure_ascii=False,
                )
            service = AgentService(
                paths,
                runtime=runtime,
                capabilities=_registry(),
                matrix_factory=ProgressMatrix,
            )
            try:
                bootstrap = service.bootstrap()
                session = service.create_session({"title": "OEM identity"})
                sent = service.send_message(session["sessionId"], {
                    "clientMessageId": "oem-identity-1",
                    "text": "你好",
                    "scopeMode": "auto",
                })
                _wait_for_status(service, sent["run"]["runId"], "completed")
            finally:
                service.shutdown()

        self.assertEqual(
            bootstrap["runtimeProfiles"][0]["name"],
            "Northstar AI Matrix 原生智能体",
        )
        self.assertEqual(
            runtime.requests[0]["brandDisplayName"],
            "Northstar AI Matrix",
        )

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
                persisted = service.repository.get_run(sent["run"]["runId"])
            finally:
                service.shutdown()

        self.assertNotIn("request", completed)
        self.assertEqual(persisted["request"]["requestScope"]["status"], "ambiguous")
        self.assertEqual(runtime.requests, [])
        self.assertEqual(matrix.dispatches, [])
        self.assertEqual(trace["approvals"], [])
        self.assertIn("哪台手机", detail["messages"][-1]["blocks"][0]["data"]["text"])

    def test_device_id_reply_resolves_the_next_run_after_multi_phone_clarification(self) -> None:
        from services.agent_service import AgentService

        matrix = MultiPhoneMatrix()
        runtime = ScriptedRuntime([{"final": {"text": "phone-2 已锁定"}}])
        with tempfile.TemporaryDirectory() as root:
            service = AgentService(
                AppPaths(root),
                runtime=runtime,
                capabilities=_registry(),
                matrix_factory=lambda: matrix,
            )
            try:
                session = service.create_session({"title": "Scope clarification"})
                ambiguous = service.send_message(session["sessionId"], {
                    "clientMessageId": "scope-question",
                    "text": "在手机上打开小红书",
                    "scopeMode": "auto",
                })
                first = _wait_for_status(service, ambiguous["run"]["runId"], "completed")
                selected = service.send_message(session["sessionId"], {
                    "clientMessageId": "scope-answer",
                    "text": "phone-2",
                    "scopeMode": "auto",
                })
                second = _wait_for_status(service, selected["run"]["runId"], "completed")
                first_persisted = service.repository.get_run(ambiguous["run"]["runId"])
                second_persisted = service.repository.get_run(selected["run"]["runId"])
            finally:
                service.shutdown()

        self.assertNotIn("request", first)
        self.assertNotIn("request", second)
        self.assertEqual(first_persisted["request"]["requestScope"]["status"], "ambiguous")
        self.assertEqual(second_persisted["request"]["requestScope"]["status"], "resolved")
        self.assertEqual(second_persisted["request"]["targets"], {"deviceIds": ["phone-2"]})
        self.assertEqual(runtime.requests[0]["requestScope"]["targets"], {"deviceIds": ["phone-2"]})

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
        self.assertEqual(bootstrap["policy"]["mode"], "strong")
        self.assertEqual(bootstrap["policy"]["approvalRequired"], ["outbound", "critical"])
        self.assertTrue(bootstrap["permissions"]["outbound"])

    def test_native_capability_catalog_returns_the_live_connected_registry(self) -> None:
        from services.agent_service import AgentService

        with tempfile.TemporaryDirectory() as root:
            service = AgentService(AppPaths(root), runtime=UnavailableRuntime())
            try:
                expected = service.capabilities.list_capabilities(available_only=True)
                catalog = service.capabilities.execute("loom.capabilities.list", {})
            finally:
                service.shutdown()

        self.assertEqual(catalog["schema"], "loom.agent.capability-catalog.v1")
        self.assertEqual(catalog["count"], len(expected))
        self.assertEqual(
            sorted(
                display_name
                for domain in catalog["domains"]
                for display_name in domain["capabilities"]
            ),
            sorted(item["displayName"] for item in expected),
        )
        self.assertEqual(sum(domain["count"] for domain in catalog["domains"]), catalog["count"])
        self.assertLess(
            len(json.dumps(catalog, ensure_ascii=False, separators=(",", ":")).encode("utf-8")),
            10_000,
        )

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
                persisted = service.repository.get_run(sent["run"]["runId"])

                self.assertEqual(sent["run"]["modelId"], "qwen3.7-plus")
                self.assertEqual(sent["run"]["modelSource"], "session")
                self.assertNotIn("request", sent["run"])
                self.assertEqual(persisted["request"]["modelId"], "qwen3.7-plus")
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

    def test_session_active_run_check_is_atomic_across_service_instances(self) -> None:
        from services.agent_service import AgentService

        with tempfile.TemporaryDirectory() as root:
            first_runtime = BlockingRuntime()
            second_runtime = BlockingRuntime()
            first_service = AgentService(AppPaths(root), runtime=first_runtime, capabilities=_registry())
            second_service = AgentService(AppPaths(root), runtime=second_runtime, capabilities=_registry())
            release_first_check = threading.Event()
            first_check_completed = threading.Event()
            second_submission_completed = threading.Event()
            outcomes: dict[str, object] = {}
            threads: list[threading.Thread] = []
            try:
                session = first_service.create_session({"title": "Cross-service single run"})
                original_commit = first_service.repository._commit_message_transaction_unlocked

                def pause_before_first_commit(index: dict, transaction: dict) -> dict:
                    first_check_completed.set()
                    if not release_first_check.wait(5.0):
                        raise RuntimeError("timed out waiting to continue first submission")
                    return original_commit(index, transaction)

                first_service.repository._commit_message_transaction_unlocked = (  # type: ignore[method-assign]
                    pause_before_first_commit
                )

                def submit(label: str, service: AgentService) -> None:
                    try:
                        outcomes[label] = service.send_message(
                            session["sessionId"],
                            {
                                "clientMessageId": f"cross-service-{label}",
                                "text": label,
                            },
                        )
                    except Exception as exc:
                        outcomes[label] = exc
                    finally:
                        if label == "second":
                            second_submission_completed.set()

                first_thread = threading.Thread(target=submit, args=("first", first_service))
                second_thread = threading.Thread(target=submit, args=("second", second_service))
                threads = [first_thread, second_thread]
                first_thread.start()
                self.assertTrue(first_check_completed.wait(2.0))
                second_thread.start()

                crossed_check_create_window = second_submission_completed.wait(2.0)
                release_first_check.set()
                for thread in threads:
                    thread.join(5.0)

                self.assertFalse(crossed_check_create_window)
                self.assertTrue(all(not thread.is_alive() for thread in threads))
                successes = [value for value in outcomes.values() if isinstance(value, dict)]
                failures = [value for value in outcomes.values() if isinstance(value, Exception)]
                self.assertEqual(len(successes), 1)
                self.assertEqual(len(failures), 1)
                self.assertRegex(str(failures[0]), "already active")
                self.assertEqual(len(first_service.repository.list_runs(session["sessionId"])), 1)
            finally:
                release_first_check.set()
                first_runtime.release.set()
                second_runtime.release.set()
                for thread in threads:
                    if thread.ident is not None:
                        thread.join(1.0)
                first_service.shutdown()
                second_service.shutdown()

    def test_accepted_follow_up_snapshots_history_after_previous_run_commits(self) -> None:
        from services.agent_service import AgentService

        with tempfile.TemporaryDirectory() as root:
            first_runtime = BlockingRuntime()
            second_runtime = ScriptedRuntime([{"final": {"text": "second answer"}}])
            gated_matrix = GatedStatusMatrix()
            first_service = AgentService(
                AppPaths(root),
                runtime=first_runtime,
                capabilities=_registry(),
                matrix_factory=ProgressMatrix,
            )
            second_service = AgentService(
                AppPaths(root),
                runtime=second_runtime,
                capabilities=_registry(),
                matrix_factory=lambda: gated_matrix,
            )
            outcome: dict[str, object] = {}
            follow_up_thread: threading.Thread | None = None
            try:
                session = first_service.create_session({"title": "Committed history boundary"})
                first = first_service.send_message(
                    session["sessionId"],
                    {"clientMessageId": "history-race-1", "text": "first question"},
                )
                self.assertTrue(first_runtime.started.wait(1.0))

                def send_follow_up() -> None:
                    try:
                        outcome["result"] = second_service.send_message(
                            session["sessionId"],
                            {"clientMessageId": "history-race-2", "text": "follow up"},
                        )
                    except Exception as error:
                        outcome["error"] = error

                follow_up_thread = threading.Thread(target=send_follow_up)
                follow_up_thread.start()
                self.assertTrue(gated_matrix.status_entered.wait(1.0))

                first_runtime.release.set()
                _wait_for_status(first_service, first["run"]["runId"], "completed")
                gated_matrix.release_status.set()
                follow_up_thread.join(5.0)

                self.assertFalse(follow_up_thread.is_alive())
                self.assertNotIn("error", outcome)
                second = outcome.get("result")
                self.assertIsInstance(second, dict)
                _wait_for_status(second_service, second["run"]["runId"], "completed")
            finally:
                first_runtime.release.set()
                gated_matrix.release_status.set()
                if follow_up_thread is not None:
                    follow_up_thread.join(1.0)
                first_service.shutdown()
                second_service.shutdown()

        history = second_runtime.requests[0].get("history")
        self.assertIsInstance(history, list)
        serialized = json.dumps(history, ensure_ascii=False)
        self.assertIn("first question", serialized)
        self.assertIn("done", serialized)

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
                self.assertEqual(paused["status"], "running")
                self.assertNotIn("controlState", paused)
                self.assertEqual(
                    service.repository.get_run(sent["run"]["runId"])["controlState"],
                    "pause_requested",
                )
                self.assertTrue(runtime.cancel_seen.wait(1.0))
                queued_resume = service.resume_run(sent["run"]["runId"])
                self.assertEqual(queued_resume["status"], "running")

                self.assertFalse(runtime.resumed.wait(0.1))
                runtime.allow_stop.set()
                self.assertTrue(runtime.resumed.wait(5.0))
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

    def test_new_media_or_phone_query_does_not_inherit_an_unrelated_previous_phone_scope(self) -> None:
        from services.agent_service import AgentService

        runtime = ScriptedRuntime([
            {"final": {"text": "published"}},
            {"final": {"text": "generated"}},
            {"final": {"text": "listed"}},
        ])
        with tempfile.TemporaryDirectory() as root:
            service = AgentService(
                AppPaths(root),
                runtime=runtime,
                capabilities=_registry(),
                matrix_factory=ProgressMatrix,
            )
            try:
                session = service.create_session({"title": "No accidental scope inheritance"})
                first = service.send_message(session["sessionId"], {
                    "clientMessageId": "no-scope-leak-1",
                    "text": "发布到小红书",
                    "scopeMode": "auto",
                })
                _wait_for_status(service, first["run"]["runId"], "completed")
                second = service.send_message(session["sessionId"], {
                    "clientMessageId": "no-scope-leak-2",
                    "text": "生成一张图片",
                    "scopeMode": "auto",
                })
                _wait_for_status(service, second["run"]["runId"], "completed")
                third = service.send_message(session["sessionId"], {
                    "clientMessageId": "no-scope-leak-3",
                    "text": "现在有哪些手机",
                    "scopeMode": "auto",
                })
                _wait_for_status(service, third["run"]["runId"], "completed")
            finally:
                service.shutdown()

        self.assertEqual(runtime.requests[0]["targets"], {"deviceIds": ["phone-progress"]})
        self.assertEqual(runtime.requests[1]["targets"], {})
        self.assertEqual(runtime.requests[2]["targets"], {})

    def test_negated_or_independent_continuation_does_not_reuse_previous_phone_scope(self) -> None:
        from services.agent_service import AgentService

        runtime = ScriptedRuntime([
            {"final": {"text": "published"}},
            {"final": {"text": "generated"}},
            {"final": {"text": "explained"}},
        ])
        with tempfile.TemporaryDirectory() as root:
            service = AgentService(
                AppPaths(root),
                runtime=runtime,
                capabilities=_registry(),
                matrix_factory=ProgressMatrix,
            )
            try:
                session = service.create_session({"title": "Scope continuation boundaries"})
                first = service.send_message(session["sessionId"], {
                    "clientMessageId": "scope-boundary-1",
                    "text": "发布到小红书",
                    "scopeMode": "auto",
                })
                _wait_for_status(service, first["run"]["runId"], "completed")
                second = service.send_message(session["sessionId"], {
                    "clientMessageId": "scope-boundary-2",
                    "text": "继续生成一张图片",
                    "scopeMode": "auto",
                })
                _wait_for_status(service, second["run"]["runId"], "completed")
                third = service.send_message(session["sessionId"], {
                    "clientMessageId": "scope-boundary-3",
                    "text": "不要继续刚才的手机任务，只说明风险",
                    "scopeMode": "auto",
                })
                _wait_for_status(service, third["run"]["runId"], "completed")
            finally:
                service.shutdown()

        self.assertEqual(runtime.requests[0]["targets"], {"deviceIds": ["phone-progress"]})
        self.assertEqual(runtime.requests[1]["targets"], {})
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

    def test_restart_recovery_terminalizes_uncertain_run_and_starts_safe_queued_run(self) -> None:
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
                uncertain_persisted = service.repository.get_run("run-uncertain")
                self.assertEqual(uncertain["status"], "failed")
                self.assertEqual(uncertain["error"]["code"], "agent_restart_inflight_unknown")
                self.assertFalse(uncertain["error"]["recoverable"])
                self.assertNotIn("outcomeIndeterminate", uncertain["error"])
                self.assertNotIn("executionMayContinue", uncertain["error"])
                self.assertTrue(uncertain_persisted["error"]["outcomeIndeterminate"])
                self.assertTrue(uncertain_persisted["error"]["executionMayContinue"])
                self.assertEqual(_wait_for_status(service, "run-queued", "completed")["status"], "completed")
                self.assertEqual(len(runtime.requests), 1)
                self.assertEqual(runtime.requests[0]["runtimeProfileId"], "loom-native")
            finally:
                service.shutdown()

    def test_restart_recovery_allows_safe_pre_tool_run_to_resume(self) -> None:
        from services.agent_service import AgentService

        with tempfile.TemporaryDirectory() as root:
            paths = AppPaths(root)
            repository = AgentSessionRepository(paths)
            repository.create_session("Safe paused run", session_id="session-safe-paused")
            repository.create_run({
                "schema": "loom.agent.run.v1",
                "runId": "run-safe-paused",
                "sessionId": "session-safe-paused",
                "status": "running",
                "campaignIds": [],
                "checkpoint": json.dumps({
                    "version": 1,
                    "completedToolCallIds": [],
                    "toolResults": [],
                    "inFlightToolCall": None,
                }),
                "request": {"prompt": "continue after restart", "runtimeProfileId": "loom-native"},
            })

            runtime = ScriptedRuntime([{"final": {"text": "resumed safely"}}])
            service = AgentService(paths, runtime=runtime, capabilities=_registry())
            try:
                recovered = service.get_run("run-safe-paused")
                self.assertEqual(recovered["status"], "paused")
                self.assertEqual(recovered["error"]["code"], "agent_restart_recovery")
                self.assertTrue(recovered["error"]["recoverable"])

                service.resume_run("run-safe-paused")
                completed = _wait_for_status(service, "run-safe-paused", "completed")

                self.assertEqual(completed["status"], "completed")
                self.assertNotIn("error", completed)
                self.assertEqual(len(runtime.requests), 1)
                self.assertEqual(runtime.requests[0]["prompt"], "continue after restart")
            finally:
                service.shutdown()

    def test_worker_crash_with_inflight_tool_is_indeterminate_and_not_retryable(self) -> None:
        from services.agent_service import AgentService

        with tempfile.TemporaryDirectory() as root:
            service = AgentService(
                AppPaths(root),
                runtime=UnavailableRuntime(),
                capabilities=_registry(),
            )
            try:
                session = service.create_session({"title": "Worker crash"})

                def crash_with_inflight_tool(session_id, run_id, request=None):
                    run = service.repository.get_run(run_id, session_id=session_id)
                    checkpoint = json.loads(str(run.get("checkpoint") or "{}"))
                    checkpoint["inFlightToolCall"] = {
                        "toolCallId": "tool-crashed",
                        "name": "loom.phone.task",
                        "input": {"deviceId": "phone-1", "task": "发布内容"},
                    }
                    service.repository.update_run(
                        run_id,
                        {
                            "status": "running",
                            "checkpoint": json.dumps(checkpoint, ensure_ascii=False),
                        },
                        session_id=session_id,
                    )
                    raise RuntimeError("simulated service worker crash")

                service.orchestrator.execute_run = crash_with_inflight_tool
                sent = service.send_message(
                    session["sessionId"],
                    {"clientMessageId": "worker-crash-client", "text": "执行手机任务"},
                )
                failed = _wait_for_status(service, sent["run"]["runId"], "failed")
                failed_persisted = service.repository.get_run(sent["run"]["runId"])

                self.assertEqual(failed["error"]["code"], "agent_service_inflight_unknown")
                self.assertFalse(failed["error"]["recoverable"])
                self.assertNotIn("outcomeIndeterminate", failed["error"])
                self.assertNotIn("executionMayContinue", failed["error"])
                self.assertTrue(failed_persisted["error"]["outcomeIndeterminate"])
                self.assertTrue(failed_persisted["error"]["executionMayContinue"])
                checkpoint = json.loads(failed["checkpoint"])
                self.assertIsNone(checkpoint["inFlightToolCall"])
                self.assertEqual(checkpoint["completedToolCallIds"], ["tool-crashed"])
                self.assertEqual(checkpoint["toolResults"][-1]["status"], "failed")
            finally:
                service.shutdown()

    def test_worker_crash_discards_queued_continuation_after_terminal_failure(self) -> None:
        from services.agent_service import AgentService

        started = threading.Event()
        release = threading.Event()
        continuation_released = threading.Event()
        invocations: list[dict] = []
        with tempfile.TemporaryDirectory() as root:
            service = AgentService(
                AppPaths(root),
                runtime=UnavailableRuntime(),
                capabilities=_registry(),
            )
            try:
                session = service.create_session({"title": "Queued crash continuation"})

                def crash_with_inflight_tool(session_id, run_id, request=None):
                    invocations.append(dict(request or {}))
                    run = service.repository.get_run(run_id, session_id=session_id)
                    checkpoint = json.loads(str(run.get("checkpoint") or "{}"))
                    checkpoint["inFlightToolCall"] = {
                        "toolCallId": "tool-before-queued-crash",
                        "name": "loom.phone.publish",
                        "input": {"target": {"deviceIds": ["phone-1"]}, "text": "publish once"},
                    }
                    service.repository.update_run(
                        run_id,
                        {
                            "status": "running",
                            "checkpoint": json.dumps(checkpoint, ensure_ascii=False),
                        },
                        session_id=session_id,
                    )
                    started.set()
                    release.wait(3)
                    raise RuntimeError("simulated crash after queuing a continuation")

                service.orchestrator.execute_run = crash_with_inflight_tool
                sent = service.send_message(
                    session["sessionId"],
                    {"clientMessageId": "queued-crash-client", "text": "publish once"},
                )
                self.assertTrue(started.wait(1))
                queued = service._submit_run(
                    session["sessionId"],
                    sent["run"]["runId"],
                    {"prompt": "queued approval continuation"},
                    emit_runtime_requested=False,
                    on_complete=continuation_released.set,
                    queue_if_busy=True,
                )
                self.assertTrue(queued)

                release.set()
                failed = _wait_for_status(service, sent["run"]["runId"], "failed")

                self.assertEqual(failed["error"]["code"], "agent_service_inflight_unknown")
                self.assertTrue(continuation_released.wait(1))
                time.sleep(0.05)
                self.assertEqual(len(invocations), 1)
                self.assertNotIn(sent["run"]["runId"], service._pending_continuations)
            finally:
                release.set()
                service.shutdown()

    def test_worker_crash_before_tool_execution_remains_retryable(self) -> None:
        from services.agent_service import AgentService

        with tempfile.TemporaryDirectory() as root:
            service = AgentService(
                AppPaths(root),
                runtime=UnavailableRuntime(),
                capabilities=_registry(),
            )
            try:
                session = service.create_session({"title": "Pre-tool worker crash"})

                def crash_before_tool(session_id, run_id, request=None):
                    raise RuntimeError("simulated pre-tool service crash")

                service.orchestrator.execute_run = crash_before_tool
                sent = service.send_message(
                    session["sessionId"],
                    {"clientMessageId": "pre-tool-crash-client", "text": "分析任务"},
                )
                failed = _wait_for_status(service, sent["run"]["runId"], "failed")

                self.assertEqual(failed["error"]["code"], "agent_service_failed")
                self.assertTrue(failed["error"]["recoverable"])
                self.assertNotIn("outcomeIndeterminate", failed["error"])
                checkpoint = json.loads(failed["checkpoint"])
                self.assertIsNone(checkpoint["inFlightToolCall"])
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
                persisted = service.repository.get_run(sent["run"]["runId"])
            finally:
                service.shutdown()

        requested = next(event for event in events if event["type"] == "runtime.requested")
        self.assertEqual(session["runtimeProfileId"], "loom-native")
        self.assertEqual(updated["runtimeProfileId"], "loom-native")
        self.assertNotIn("request", sent["run"])
        self.assertEqual(persisted["request"]["runtimeProfileId"], "loom-native")
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
            {"final": {"text": "Matrix campaign completed."}},
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
                self.assertEqual(resolved["run"]["status"], "paused")

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
                resumed = _wait_for_status(service, sent["run"]["runId"], "completed")
                self.assertEqual(resumed["status"], "completed")
            finally:
                service.shutdown()

    def test_matrix_terminal_intent_survives_waiting_approval_and_reconciles_after_approval(self) -> None:
        from services.agent_service import AgentService

        matrix = ProgressMatrix()
        registry = _registry({
            "loom.matrix.status": {
                "executor": lambda payload: matrix.status(payload.get("campaignId")),
                "permission": "read",
                "risk": "read",
                "idempotent": True,
            },
            "loom.matrix.dispatch": {
                "executor": lambda payload: matrix.dispatch(payload),
                "permission": "control",
                "risk": "control_safe",
                "targetScope": "matrix-write",
            },
            "loom.outbound.publish": {
                "executor": lambda _payload: {"status": "completed", "receiptId": "publish-1"},
                "permission": "control",
                "risk": "outbound",
                "targetScope": "none",
            },
        })
        runtime = ScriptedRuntime([
            {
                "toolCalls": [{
                    "toolCallId": "dispatch-before-approval-window",
                    "name": "loom.matrix.dispatch",
                    "input": {"prompt": "inspect the selected phone"},
                }]
            },
            {
                "toolCalls": [{
                    "toolCallId": "publish-during-approval-window",
                    "name": "loom.outbound.publish",
                    "input": {"text": "publish after matrix completion"},
                }]
            },
            {"final": {"text": "matrix and publish both completed"}},
        ])

        with tempfile.TemporaryDirectory() as root:
            service = AgentService(
                AppPaths(root),
                runtime=runtime,
                capabilities=registry,
                matrix_factory=lambda: matrix,
                policy=AgentPolicyEngine(approval_mode="strong"),
            )
            try:
                session = service.create_session({"title": "Terminal during approval"})
                sent = service.send_message(session["sessionId"], {
                    "clientMessageId": "terminal-during-approval",
                    "text": "inspect then publish",
                    "targets": {"deviceIds": ["phone-progress"]},
                })
                first_waiting = _wait_for_status(service, sent["run"]["runId"], "waiting_approval")
                first_approval = service.get_trace(first_waiting["runId"])["approvals"][0]
                second_waiting = service.resolve_approval(
                    first_approval["approvalId"],
                    {"decision": "approved"},
                )["run"]
                self.assertEqual(second_waiting["status"], "waiting_approval")

                matrix.campaign["status"] = "succeeded"
                matrix.campaign["missions"][0]["status"] = "succeeded"
                matrix.campaign["missions"][0]["deviceTasks"][0]["status"] = "succeeded"
                service._reconcile_matrix_campaign_snapshot(matrix.status())

                persisted = service.get_run(sent["run"]["runId"])
                self.assertEqual(persisted["status"], "waiting_approval")
                persisted_private = service.repository.get_run(sent["run"]["runId"])
                self.assertNotIn("matrixTerminalIntents", persisted)
                self.assertEqual(
                    [item["campaignId"] for item in persisted_private["matrixTerminalIntents"]],
                    ["campaign-progress"],
                )
                second_approval = service.get_trace(persisted["runId"])["approvals"][-1]
                completed = service.resolve_approval(
                    second_approval["approvalId"],
                    {"decision": "approved"},
                )["run"]
                completed_private = service.repository.get_run(sent["run"]["runId"])

                self.assertEqual(completed["status"], "completed")
                checkpoint = json.loads(completed_private["checkpoint"])
                matrix_result = next(
                    item
                    for item in checkpoint["toolResults"]
                    if item["toolCallId"] == "dispatch-before-approval-window"
                )
                self.assertEqual(matrix_result["status"], "completed")
                self.assertNotIn("matrixTerminalIntents", completed)
                self.assertEqual(completed_private.get("matrixTerminalIntents"), [])
            finally:
                service.shutdown()

    def test_matrix_link_survives_many_missing_snapshots_then_resumes_on_terminal_return(self) -> None:
        from services.agent_service import AgentService

        matrix = ProgressMatrix()
        registry = _registry({
            "loom.matrix.status": {
                "executor": lambda payload: matrix.status(payload.get("campaignId")),
                "permission": "read",
                "risk": "read",
                "idempotent": True,
            },
            "loom.matrix.dispatch": {
                "executor": lambda payload: matrix.dispatch(payload),
                "permission": "control",
                "risk": "control_safe",
                "targetScope": "matrix-write",
            },
        })
        runtime = ScriptedRuntime([
            {
                "toolCalls": [{
                    "toolCallId": "dispatch-before-missing-window",
                    "name": "loom.matrix.dispatch",
                    "input": {"prompt": "inspect the selected phone"},
                }]
            },
            {"final": {"text": "campaign accepted"}},
            {"final": {"text": "campaign reached a real terminal state"}},
        ])

        with tempfile.TemporaryDirectory() as root:
            service = AgentService(
                AppPaths(root),
                runtime=runtime,
                capabilities=registry,
                matrix_factory=lambda: matrix,
                policy=AgentPolicyEngine(approval_mode="weak"),
            )
            try:
                session = service.create_session({"title": "Transient missing campaign"})
                sent = service.send_message(session["sessionId"], {
                    "clientMessageId": "missing-then-terminal",
                    "text": "inspect the selected phone",
                    "targets": {"deviceIds": ["phone-progress"]},
                })
                paused = _wait_for_status(service, sent["run"]["runId"], "paused")
                self.assertEqual(paused["error"]["code"], "agent_child_operation_pending")

                for _ in range(25):
                    service._reconcile_matrix_campaign_snapshot({"campaigns": []})
                self.assertIn("campaign-progress", service._campaign_links)
                self.assertGreaterEqual(
                    service._campaign_links["campaign-progress"]["missingPolls"],
                    25,
                )

                matrix.campaign["status"] = "succeeded"
                matrix.campaign["missions"][0]["status"] = "succeeded"
                matrix.campaign["missions"][0]["deviceTasks"][0]["status"] = "succeeded"
                service._reconcile_matrix_campaign_snapshot(matrix.status())
                completed = _wait_for_status(service, sent["run"]["runId"], "completed")

                self.assertEqual(completed["status"], "completed")
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
            service = AgentService(
                AppPaths(root),
                runtime=runtime,
                matrix_factory=lambda: matrix,
                policy=AgentPolicyEngine(approval_mode="weak"),
            )
            try:
                session = service.create_session({"title": "Weak dispatch"})
                sent = service.send_message(session["sessionId"], {
                    "clientMessageId": "weak-dispatch-client",
                    "text": "contact the selected account",
                    "targets": {"deviceIds": ["phone-progress"]},
                })
                paused = _wait_for_status(service, sent["run"]["runId"], "paused")
                trace = service.get_trace(paused["runId"])
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

                self.assertEqual(outcome["run"]["status"], "paused")
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
                waiting = _wait_for_status(
                    service,
                    sent["run"]["runId"],
                    "waiting_approval",
                    timeout=10.0,
                )
                approval = service.get_trace(waiting["runId"])["approvals"][0]

                outcome = service.queue_approval_resolution(
                    approval["approvalId"],
                    {"decision": "approved"},
                )
                paused = _wait_for_status(service, waiting["runId"], "paused")

                self.assertEqual(outcome["approval"]["status"], "approved")
                self.assertEqual(paused["status"], "paused")
                self.assertEqual(len(matrix.dispatches), 1)
                self.assertIs(matrix.dispatches[0].get("confirmed"), True)
                events = service.events_after(session_id=session["sessionId"], after_seq=0)
                self.assertEqual([event["type"] for event in events].count("runtime.requested"), 1)
            finally:
                service.shutdown()

    def test_approved_matrix_retry_receives_one_server_confirmation(self) -> None:
        from services.agent_service import AgentService

        runtime = ScriptedRuntime([
            {
                "toolCalls": [{
                    "toolCallId": "dispatch-before-retry",
                    "name": "loom.matrix.dispatch",
                    "input": {
                        "prompt": "prepare the selected device",
                        "target": {"deviceIds": ["phone-progress"]},
                    },
                }]
            },
            {
                "toolCalls": [{
                    "toolCallId": "retry-confirmed",
                    "name": "loom.matrix.retry",
                    "input": {"campaignId": "campaign-progress"},
                }]
            },
            {"final": {"text": "approved retry complete"}},
        ])
        with tempfile.TemporaryDirectory() as root:
            matrix = ConfirmationRetryMatrix(require_confirmation=True)
            service = AgentService(
                AppPaths(root),
                runtime=runtime,
                matrix_factory=lambda: matrix,
                policy=AgentPolicyEngine(approval_mode="strong"),
            )
            try:
                session = service.create_session({"title": "Confirmed retry"})
                sent = service.send_message(session["sessionId"], {
                    "clientMessageId": "confirmed-retry-client",
                    "text": "dispatch and then retry the selected device",
                    "targets": {"deviceIds": ["phone-progress"]},
                })
                first_waiting = _wait_for_status(service, sent["run"]["runId"], "waiting_approval")
                self.assertEqual(matrix.retries, [])
                first_approval = service.get_trace(first_waiting["runId"])["approvals"][0]

                first_outcome = service.resolve_approval(
                    first_approval["approvalId"],
                    {"decision": "approved"},
                )
                self.assertEqual(first_outcome["run"]["status"], "waiting_approval")
                self.assertEqual(len(matrix.dispatches), 1)
                self.assertEqual(matrix.retries, [])
                approvals = service.get_trace(first_waiting["runId"])["approvals"]
                self.assertEqual(len(approvals), 2)

                outcome = service.resolve_approval(
                    approvals[-1]["approvalId"],
                    {"decision": "approved"},
                )
                self.assertEqual(outcome["run"]["status"], "paused")
                self.assertEqual(len(matrix.retries), 1)
                self.assertIs(matrix.retries[0].get("confirmed"), True)
            finally:
                service.shutdown()

    def test_weak_policy_auto_confirms_matrix_retry_without_approval(self) -> None:
        from services.agent_service import AgentService

        runtime = ScriptedRuntime([
            {
                "toolCalls": [{
                    "toolCallId": "dispatch-before-weak-retry",
                    "name": "loom.matrix.dispatch",
                    "input": {
                        "prompt": "prepare the selected device",
                        "target": {"deviceIds": ["phone-progress"]},
                    },
                }]
            },
            {
                "toolCalls": [{
                    "toolCallId": "retry-weak",
                    "name": "loom.matrix.retry",
                    "input": {"campaignId": "campaign-progress"},
                }]
            },
            {"final": {"text": "retry complete"}},
        ])
        with tempfile.TemporaryDirectory() as root:
            matrix = ConfirmationRetryMatrix(require_confirmation=True)
            service = AgentService(
                AppPaths(root),
                runtime=runtime,
                matrix_factory=lambda: matrix,
                policy=AgentPolicyEngine(approval_mode="weak"),
            )
            try:
                session = service.create_session({"title": "Weak retry"})
                sent = service.send_message(session["sessionId"], {
                    "clientMessageId": "weak-retry-client",
                    "text": "dispatch and then retry the selected device",
                    "targets": {"deviceIds": ["phone-progress"]},
                })
                paused = _wait_for_status(service, sent["run"]["runId"], "paused")
                trace = service.get_trace(paused["runId"])
            finally:
                service.shutdown()

        self.assertEqual(trace["approvals"], [])
        self.assertEqual(len(matrix.retries), 1)
        self.assertIs(matrix.retries[0].get("confirmed"), True)

    def test_cancel_run_cascades_to_linked_matrix_campaigns_and_jobs(self) -> None:
        from services.agent_service import AgentService

        with tempfile.TemporaryDirectory() as root:
            matrix = CancellableMatrix()
            jobs = RecordingJobManager()
            jobs.jobs[0]["kind"] = "matrix.dispatch"
            jobs.jobs[0]["progress"].update({
                "ownerAccountBinding": account_job_binding(
                    "account-a",
                    "install-a",
                ),
                "matrixDeviceIds": ["phone-progress"],
                "matrixDeviceTaskIds": ["task-progress"],
            })
            context = _matrix_account_context(root, "account-a", "install-a")
            service = AgentService(
                AppPaths(root),
                runtime=UnavailableRuntime(),
                capabilities=_registry(),
                matrix_factory=lambda: matrix,
                job_manager=jobs,
                context_factory=lambda: context,
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

    def test_central_agent_matrix_job_has_owner_binding_and_device_scope(self) -> None:
        from services.agent_service import AgentService

        class CapturingJobManager:
            def __init__(self) -> None:
                self.initial_progress: dict = {}

            def submit_progress(
                self,
                kind,
                title,
                target,
                initial_progress=None,
            ):
                del title, target
                self.initial_progress = dict(initial_progress or {})
                return {
                    "id": "job-agent-matrix",
                    "kind": kind,
                    "progress": dict(self.initial_progress),
                }

        with tempfile.TemporaryDirectory() as root:
            jobs = CapturingJobManager()
            context = _matrix_account_context(root, "account-a", "install-a")
            service = object.__new__(AgentService)
            service.job_manager = jobs
            service.context_factory = lambda: context
            task = {
                "campaignId": "campaign-agent",
                "missions": [{
                    "deviceTasks": [
                        {
                            "deviceTaskId": "task-phone-b",
                            "deviceId": "phone-b",
                        },
                        {
                            "deviceTaskId": "task-phone-a",
                            "deviceId": "phone-a",
                        },
                    ],
                }],
            }

            job = service._start_matrix_job(
                "matrix.dispatch",
                "Agent Matrix dispatch",
                ProgressMatrix(),
                task,
                {"prompt": "check"},
            )

        self.assertEqual(job["id"], "job-agent-matrix")
        self.assertEqual(
            jobs.initial_progress["ownerAccountBinding"],
            account_job_binding("account-a", "install-a"),
        )
        self.assertNotIn("ownerAccountId", jobs.initial_progress)
        self.assertEqual(
            jobs.initial_progress["matrixDeviceIds"],
            ["phone-a", "phone-b"],
        )
        self.assertEqual(
            jobs.initial_progress["matrixDeviceTaskIds"],
            ["task-phone-a", "task-phone-b"],
        )
        self.assertEqual(
            jobs.initial_progress["phoneDeviceIds"],
            ["phone-a", "phone-b"],
        )

    def test_agent_linked_matrix_cancel_preserves_other_and_unknown_owner_jobs(self) -> None:
        from services.agent_service import AgentService

        binding_a = account_job_binding("account-a", "install-a")
        binding_b = account_job_binding("account-b", "install-a")
        jobs = RecordingJobManager()
        jobs.jobs = [
            {
                "id": "job-account-a",
                "kind": "matrix.dispatch",
                "status": "running",
                "progress": {
                    "campaignId": "campaign-progress",
                    "ownerAccountBinding": binding_a,
                    "matrixDeviceIds": ["phone-a"],
                },
            },
            {
                "id": "job-account-b",
                "kind": "matrix.dispatch",
                "status": "running",
                "progress": {
                    "campaignId": "campaign-progress",
                    "ownerAccountBinding": binding_b,
                    "matrixDeviceIds": ["phone-b"],
                },
            },
            {
                "id": "job-owner-unknown",
                "kind": "matrix.dispatch",
                "status": "running",
                "progress": {
                    "campaignId": "campaign-progress",
                    "matrixDeviceIds": ["phone-unknown"],
                },
            },
        ]
        with tempfile.TemporaryDirectory() as root:
            context = _matrix_account_context(root, "account-a", "install-a")
            matrix = CancellableMatrix()
            service = object.__new__(AgentService)
            service.job_manager = jobs
            service.context_factory = lambda: context
            service._matrix_factory = lambda: matrix
            service._lock = threading.RLock()
            service._campaign_links = {
                "campaign-progress": {
                    "sessionId": "session-a",
                    "runId": "run-a",
                },
            }

            incomplete = service._cancel_linked_matrix_campaigns(
                ["campaign-progress"],
            )

        self.assertEqual(incomplete, [])
        self.assertEqual(jobs.cancelled_job_ids, ["job-account-a"])
        self.assertEqual(jobs.jobs[0]["status"], "cancelled")
        self.assertEqual(jobs.jobs[1]["status"], "running")
        self.assertEqual(jobs.jobs[2]["status"], "running")

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
                persisted = service.repository.get_run("run-incomplete-cancel")

                self.assertNotEqual(outcome["status"], "cancelled")
                self.assertEqual(outcome["error"]["code"], "agent_matrix_cancel_incomplete")
                self.assertFalse(outcome["error"]["recoverable"])
                self.assertNotIn("outcomeIndeterminate", outcome["error"])
                self.assertNotIn("executionMayContinue", outcome["error"])
                self.assertTrue(persisted["error"]["outcomeIndeterminate"])
                self.assertTrue(persisted["error"]["executionMayContinue"])
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
            from core.acquisition_templates import AcquisitionTemplateLibrary

            with patch.dict(os.environ, {"LOOM_TEMPLATE_DISABLE_DEFAULT_CLOUD": "1"}, clear=False):
                template = AcquisitionTemplateLibrary(paths).save_from_acquisition(
                    {
                        "templateId": "resume-template",
                        "name": "候选人筛选模板",
                        "industry": "招聘",
                        "platforms": ["manual"],
                        "targetCustomer": "候选人",
                    }
                )["template"]

            service = AgentService(paths, runtime=UnavailableRuntime())
            try:
                service._skill_service.set_template_binding(
                    "resume-screening", "resume-template", template["version"], linked=True
                )
                capability = service.capabilities.get("loom.skill.resume-screening")
                result = service.capabilities.execute("loom.skill.resume-screening", {"role": "recruiter"})
            finally:
                service.shutdown()

        self.assertEqual(capability.permission, "admin")
        self.assertEqual(capability.risk, "critical")
        self.assertIn("Read candidate summaries", result["instructions"])
        self.assertEqual(result["requestedContext"], {"role": "recruiter"})
        self.assertEqual(result["sharedTemplates"][0]["templateId"], "resume-template")
        self.assertEqual(result["sharedTemplates"][0]["version"], 1)

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

    def test_shutdown_rejects_new_messages_without_persisting_an_orphan_run(self) -> None:
        from services.agent_service import AgentService

        with tempfile.TemporaryDirectory() as root:
            service = AgentService(AppPaths(root), runtime=UnavailableRuntime(), capabilities=_registry())
            session = service.create_session({"title": "Closed service"})

            service.shutdown()

            with self.assertRaisesRegex(RuntimeError, "agent service is closed"):
                service.send_message(
                    session["sessionId"],
                    {"clientMessageId": "after-shutdown", "text": "must not persist"},
                )

            detail = service.session_detail(session["sessionId"])
            self.assertEqual(detail["messages"], [])
            self.assertEqual(detail["runs"], [])

    def test_shutdown_waits_for_an_inflight_run_to_stop(self) -> None:
        from services.agent_service import AgentService

        with tempfile.TemporaryDirectory() as root:
            runtime = SlowStoppingRuntime()
            service = AgentService(AppPaths(root), runtime=runtime, capabilities=_registry())
            session = service.create_session({"title": "Controlled shutdown"})
            sent = service.send_message(
                session["sessionId"],
                {"clientMessageId": "shutdown-active", "text": "keep running"},
            )
            self.assertTrue(runtime.started.wait(1.0))

            shutdown_thread = threading.Thread(target=service.shutdown)
            shutdown_thread.start()
            try:
                self.assertTrue(runtime.cancel_seen.wait(1.0))
                self.assertTrue(shutdown_thread.is_alive())

                runtime.allow_stop.set()
                shutdown_thread.join(2.0)

                self.assertFalse(shutdown_thread.is_alive())
                self.assertEqual(service.get_run(sent["run"]["runId"])["status"], "paused")
            finally:
                runtime.allow_stop.set()
                shutdown_thread.join(2.0)
                service.shutdown()

    def test_shutdown_returns_after_grace_window_for_non_cooperative_runtime(self) -> None:
        from services.agent_service import AgentService

        with tempfile.TemporaryDirectory() as root:
            runtime = SlowStoppingRuntime()
            service = AgentService(AppPaths(root), runtime=runtime, capabilities=_registry())
            session = service.create_session({"title": "Bounded shutdown"})
            sent = service.send_message(
                session["sessionId"],
                {"clientMessageId": "shutdown-bounded", "text": "keep running"},
            )
            self.assertTrue(runtime.started.wait(1.0))

            started_at = time.monotonic()
            try:
                incomplete = service.shutdown(grace_seconds=0.05)
                elapsed = time.monotonic() - started_at

                self.assertLess(elapsed, 0.5)
                self.assertTrue(runtime.cancel_seen.wait(0.5))
                run = service.get_run(sent["run"]["runId"])
                self.assertEqual(run["status"], "running")
                self.assertNotIn("controlState", run)
                self.assertEqual(
                    service.repository.get_run(sent["run"]["runId"])["controlState"],
                    "pause_requested",
                )
                self.assertFalse(incomplete["drained"])
                self.assertEqual(incomplete["unfinishedRuns"], 1)
                self.assertTrue(incomplete["executionMayContinue"])
            finally:
                runtime.allow_stop.set()
                service.shutdown(grace_seconds=1)

    def test_shutdown_reports_unfinished_capability_worker_until_it_really_drains(self) -> None:
        from services.agent_service import AgentService

        started = threading.Event()
        release = threading.Event()

        def non_cooperative_side_effect(_payload):
            started.set()
            release.wait(2)
            return {"campaignId": "campaign-shutdown", "status": "running"}

        registry = _registry({
            "loom.matrix.dispatch": {
                "executor": non_cooperative_side_effect,
                "permission": "control",
                "risk": "control_safe",
                "targetScope": "matrix-write",
                "timeoutSec": 2,
            },
        })
        runtime = ScriptedRuntime([
            {
                "toolCalls": [{
                    "toolCallId": "shutdown-capability-worker",
                    "name": "loom.matrix.dispatch",
                    "input": {"prompt": "perform one external action"},
                }]
            },
        ])

        with tempfile.TemporaryDirectory() as root:
            matrix = ProgressMatrix()
            service = AgentService(
                AppPaths(root),
                runtime=runtime,
                capabilities=registry,
                matrix_factory=lambda: matrix,
                policy=AgentPolicyEngine(approval_mode="weak"),
            )
            session = service.create_session({"title": "Capability worker shutdown"})
            sent = service.send_message(session["sessionId"], {
                "clientMessageId": "shutdown-capability-worker",
                "text": "perform one external action",
                "targets": {"deviceIds": ["phone-progress"]},
            })
            self.assertTrue(started.wait(1))

            try:
                incomplete = service.shutdown(grace_seconds=0.01)

                self.assertFalse(incomplete["drained"])
                self.assertGreaterEqual(incomplete["unfinishedWorkers"], 1)
                self.assertTrue(incomplete["executionMayContinue"])
                self.assertEqual(incomplete["code"], "agent_shutdown_incomplete")
                self.assertIn(
                    service.get_run(sent["run"]["runId"])["status"],
                    {"running", "failed"},
                )
            finally:
                release.set()

            drained = service.shutdown(grace_seconds=1)
            self.assertTrue(drained["drained"])
            self.assertEqual(drained["unfinishedRuns"], 0)
            self.assertEqual(drained["unfinishedWorkers"], 0)
            self.assertFalse(drained["executionMayContinue"])

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

    def test_bridge_shutdown_closes_only_the_existing_agent_service_once(self) -> None:
        import bridge

        class FakeService:
            def __init__(self) -> None:
                self.shutdown_calls = 0

            def shutdown(self) -> None:
                self.shutdown_calls += 1

        service = FakeService()
        with patch.object(bridge, "_agent_service", service):
            first = bridge._shutdown_agent_service()
            second = bridge._shutdown_agent_service()

        self.assertTrue(first["stopped"])
        self.assertFalse(second["stopped"])
        self.assertEqual(service.shutdown_calls, 1)

    def test_bridge_account_logout_cleanup_stops_every_account_runtime(self) -> None:
        import bridge

        cancelled: list[str] = []

        class FakeMatrix:
            def __init__(self, _paths, **_kwargs) -> None:
                pass

            def emergency_stop(self, *, all_tasks: bool = False):
                self.assert_all = all_tasks
                return {"cancelled": True, "affectedTaskCount": 2}

        class FakeJobs:
            def cancel_matching(self, predicate, *, wait_for_workers=True):
                self.wait_for_workers = wait_for_workers
                candidates = [
                    {"id": "job-phone", "kind": "phone.task"},
                    {"id": "job-image", "kind": "image"},
                    {"id": "job-update", "kind": "component.update"},
                ]
                cancelled.extend(
                    item["id"] for item in candidates if predicate(item)
                )
                return list(cancelled)

            def list(self, limit=30):
                del limit
                return []

        jobs = FakeJobs()
        with (
            patch.object(bridge, "_shutdown_agent_service", return_value={
                "drained": True,
                "executionMayContinue": False,
            }),
            patch.object(bridge, "_get_job_mgr", return_value=jobs),
            patch.object(
                bridge,
                "_get_entitlement_mgr",
                return_value=SimpleNamespace(
                    current_state=lambda _feature: {
                        "accountId": "account-a",
                    },
                ),
            ),
            patch("core.phone_matrix.MatrixControlPlane", FakeMatrix),
            patch("api.routes_phone.stop_phone_event_syncs_for_account", return_value={
                "ok": True,
                "executionMayContinue": False,
            }),
            patch("api.routes_phone.stop_phone_daemon", return_value={
                "ok": True,
                "running": False,
            }),
            patch(
                "api.routes_phone.cleanup_phone_usb_for_account",
                return_value={
                    "cleanedDeviceIds": ["phone-a"],
                    "failedDeviceIds": [],
                    "executionMayContinue": False,
                },
            ) as cleanup_usb,
        ):
            result = bridge._account_logout_cleanup()

        self.assertTrue(result["ok"])
        self.assertFalse(result["executionMayContinue"])
        self.assertEqual(result["cancelledJobIds"], ["job-image", "job-phone"])
        self.assertTrue(jobs.wait_for_workers)
        self.assertNotIn("job-update", cancelled)
        self.assertEqual(result["usb"]["cleanedDeviceIds"], ["phone-a"])
        cleanup_usb.assert_called_once()
        self.assertEqual(cleanup_usb.call_args.args[1], "account-a")

    def test_bridge_account_cleanup_reports_cancelling_jobs_and_usb_failure(self) -> None:
        import bridge

        class FakeJobs:
            def cancel_matching(self, _predicate, *, wait_for_workers=True):
                self.wait_for_workers = wait_for_workers
                return ["job-still-running"]

            def list(self, limit=30):
                del limit
                return [{
                    "id": "job-still-running",
                    "kind": "phone.task",
                    "status": "cancelling",
                }]

        with (
            patch.object(bridge, "_shutdown_agent_service", return_value={
                "drained": True,
                "executionMayContinue": False,
            }),
            patch.object(bridge, "_get_job_mgr", return_value=FakeJobs()),
            patch.object(
                bridge,
                "_get_entitlement_mgr",
                return_value=SimpleNamespace(
                    current_state=lambda _feature: {
                        "accountId": "account-a",
                    },
                ),
            ),
            patch(
                "core.phone_matrix.MatrixControlPlane.emergency_stop",
                return_value={"cancelled": True, "affectedTaskCount": 0},
            ),
            patch(
                "api.routes_phone.stop_phone_event_syncs_for_account",
                return_value={
                    "ok": True,
                    "executionMayContinue": False,
                },
            ),
            patch(
                "api.routes_phone.stop_phone_daemon",
                return_value={"ok": True, "running": False},
            ),
            patch(
                "api.routes_phone.cleanup_phone_usb_for_account",
                return_value={
                    "cleanedDeviceIds": [],
                    "failedDeviceIds": ["phone-a"],
                    "executionMayContinue": True,
                },
            ),
        ):
            result = bridge._account_logout_cleanup()

        self.assertFalse(result["ok"])
        self.assertTrue(result["executionMayContinue"])
        self.assertEqual(result["unfinishedJobIds"], ["job-still-running"])
        self.assertEqual(result["usb"]["failedDeviceIds"], ["phone-a"])

    def test_bridge_context_exposes_account_logout_cleanup(self) -> None:
        import bridge

        self.assertIs(
            bridge._build_fastapi_context().account_logout_cleanup,
            bridge._account_logout_cleanup,
        )

    def test_bridge_keeps_global_service_until_shutdown_is_truly_drained(self) -> None:
        import bridge

        class FakeService:
            def __init__(self) -> None:
                self.shutdown_calls = 0

            def shutdown(self):
                self.shutdown_calls += 1
                if self.shutdown_calls == 1:
                    return {
                        "stopped": False,
                        "drained": False,
                        "unfinishedRuns": 0,
                        "unfinishedWorkers": 1,
                        "executionMayContinue": True,
                    }
                return {
                    "stopped": True,
                    "drained": True,
                    "unfinishedRuns": 0,
                    "unfinishedWorkers": 0,
                    "executionMayContinue": False,
                }

        service = FakeService()
        with patch.object(bridge, "_agent_service", service):
            incomplete = bridge._shutdown_agent_service()
            self.assertIs(bridge._agent_service, service)

            drained = bridge._shutdown_agent_service()
            self.assertIsNone(bridge._agent_service)

        self.assertFalse(incomplete["drained"])
        self.assertTrue(incomplete["executionMayContinue"])
        self.assertTrue(drained["drained"])
        self.assertEqual(service.shutdown_calls, 2)

    def test_bridge_exit_removes_only_its_own_session_file(self) -> None:
        import bridge

        with tempfile.TemporaryDirectory() as session_dir:
            session_path = os.path.join(session_dir, "bridge-session.json")
            with patch.dict(os.environ, {"LOOM_BRIDGE_SESSION_FILE": session_path}):
                bridge._write_bridge_session(18888, "owned-token", "fastapi")
                with open(session_path, "r", encoding="utf-8") as handle:
                    replacement = json.load(handle)
                replacement["instanceId"] = "replacement-instance"
                with open(session_path, "w", encoding="utf-8") as handle:
                    json.dump(replacement, handle)

                self.assertFalse(bridge._remove_bridge_session_if_owned())
                self.assertTrue(os.path.exists(session_path))

                bridge._write_bridge_session(18888, "owned-token", "fastapi")
                self.assertTrue(bridge._remove_bridge_session_if_owned())
                self.assertFalse(os.path.exists(session_path))


if __name__ == "__main__":
    unittest.main()
