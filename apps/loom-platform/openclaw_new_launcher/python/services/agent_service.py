"""Production service facade for the local LOOM central agent."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import shutil
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor, wait
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from core.agent_capabilities import CapabilityExecutionError, CapabilityRegistry
from core.agent_events import AgentEventBus
from core.agent_language import has_positive_term
from core.agent_orchestrator import AgentOrchestrator
from core.agent_policy import AgentPolicyEngine
from core.agent_runtime import redact_sensitive
from core.agent_scope import resolve_request_scope
from core.agent_sessions import AgentSessionRepository, sanitize_for_storage
from core.brand_identity import load_brand_identity
from core.loom_model_client import LoomModelClient, extract_explicit_capability_hints
from core.native_agent_runtime import LoomNativeRuntimeAdapter
from core.newapi_account_manager import NewApiAccountManager
from core.phone_matrix import MatrixControlPlane
from core.job_ownership import current_account_job_identity, job_visible_to_account
from services.agent_builtin_capabilities import AgentBuiltinCapabilityProvider
from services.skills import SkillService


Json = dict[str, Any]
RunContinuation = tuple[str, Json, bool, bool, Callable[[], None] | None]
TERMINAL_RUN_STATUSES = {"completed", "failed", "cancelled"}
TERMINAL_MATRIX_STATUSES = {"succeeded", "completed", "failed", "cancelled"}
NATIVE_RUNTIME_PROFILE_ID = "loom-native"
MATRIX_CONFIRMATION_CAPABILITIES = frozenset({
    "loom.matrix.dispatch",
    "loom.matrix.retry",
})
_SCOPE_CONTINUATION_TERMS = (
    "\u7ee7\u7eed",
    "\u91cd\u8bd5",
    "\u518d\u8bd5",
    "\u5df2\u7ecf",
    "\u597d\u4e86",
    "\u53ef\u4ee5\u4e86",
    "\u521a\u624d",
    "\u4e0a\u9762",
    "\u4e4b\u524d",
)
_SCOPE_INDEPENDENT_MEDIA_TERMS = (
    "生成图片",
    "生成一张图片",
    "生成海报",
    "制作图片",
    "画一张",
    "画图",
    "生图",
    "生成视频",
    "制作视频",
    "做视频",
    "生视频",
)
_MAX_USER_ATTACHMENTS = 8
_MAX_USER_ATTACHMENT_TOTAL_BYTES = 16 * 1024 * 1024
_MAX_USER_IMAGE_BYTES = 8 * 1024 * 1024
_MAX_USER_TEXT_CHARS = 32_768
_USER_IMAGE_MIME_EXTENSIONS = {
    "image/gif": ".gif",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}
_USER_TEXT_EXTENSIONS = {
    ".csv",
    ".json",
    ".jsonl",
    ".log",
    ".markdown",
    ".md",
    ".tsv",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}


def _native_runtime_profile_id(_value: Any = None) -> str:
    return NATIVE_RUNTIME_PROFILE_ID


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _tool_input_hash(value: Mapping[str, Any]) -> str:
    canonical = json.dumps(dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


def _history_message_text(item: Any) -> str:
    if not isinstance(item, Mapping) or str(item.get("role") or "") != "user":
        return ""
    blocks = item.get("blocks") if isinstance(item.get("blocks"), list) else []
    parts: list[str] = []
    for block in blocks:
        if not isinstance(block, Mapping) or str(block.get("type") or "") != "text":
            continue
        data = block.get("data") if isinstance(block.get("data"), Mapping) else {}
        value = str(data.get("text") or "").strip()
        if value:
            parts.append(value)
    return "\n".join(parts)


def _is_scope_continuation(text: str) -> bool:
    folded = str(text or "").casefold()
    continuation = has_positive_term(
        folded,
        tuple(term.casefold() for term in _SCOPE_CONTINUATION_TERMS),
    )
    independent_media = has_positive_term(
        folded,
        tuple(term.casefold() for term in _SCOPE_INDEPENDENT_MEDIA_TERMS),
    )
    return continuation and not independent_media


def _account_id_from_session(session: Any) -> str:
    if not isinstance(session, Mapping) or session.get("loggedIn") is not True:
        return ""
    entitlement = (
        session.get("accountEntitlement")
        if isinstance(session.get("accountEntitlement"), Mapping)
        else {}
    )
    account_id = str(
        entitlement.get("accountId")
        or session.get("accountId")
        or ""
    ).strip()
    if account_id:
        return account_id
    member_id = str(session.get("memberId") or "").strip()
    return member_id.partition(":")[2].strip() if member_id.startswith("newapi:") else ""


def _safe_attachment_name(value: Any) -> str:
    name = os.path.basename(str(value or "").replace("\\", "/")).replace("\x00", "").strip()
    if not name:
        raise ValueError("AGENT_ATTACHMENT_INVALID: attachment name is required")
    return name[:160]


def _image_signature_matches(mime: str, payload: bytes) -> bool:
    if mime == "image/png":
        return payload.startswith(b"\x89PNG\r\n\x1a\n")
    if mime == "image/jpeg":
        return payload.startswith(b"\xff\xd8\xff")
    if mime == "image/gif":
        return payload.startswith((b"GIF87a", b"GIF89a"))
    if mime == "image/webp":
        return len(payload) >= 12 and payload.startswith(b"RIFF") and payload[8:12] == b"WEBP"
    return False


class AgentService:
    """Join persistence, runtime execution, policy, tools, and API envelopes."""

    def __init__(
        self,
        paths: Any,
        *,
        runtime: Any | None = None,
        account_manager: Any | None = None,
        model_client: LoomModelClient | None = None,
        capabilities: CapabilityRegistry | None = None,
        policy: AgentPolicyEngine | None = None,
        context_factory: Callable[[], Any] | None = None,
        job_manager: Any | None = None,
        matrix_factory: Callable[[], Any] | None = None,
        max_workers: int = 4,
    ) -> None:
        self.paths = paths
        self.brand_identity = load_brand_identity(paths)
        self.native_runtime_name = self.brand_identity.native_agent_name
        self.context_factory = context_factory
        self.job_manager = job_manager
        self._matrix_factory = matrix_factory or self._default_matrix_factory
        self._campaign_links: dict[str, Json] = {}
        self._matrix_monitor_stop = threading.Event()
        self.account_manager = account_manager
        self.model_client = model_client
        if runtime is None:
            self.account_manager = account_manager or NewApiAccountManager(paths, lambda _text: None)
            self.model_client = model_client or LoomModelClient(self.account_manager)
        public_session: Mapping[str, Any] = {}
        public_session_reader = getattr(self.account_manager, "public_session", None)
        if callable(public_session_reader):
            try:
                candidate = public_session_reader()
                if isinstance(candidate, Mapping):
                    public_session = candidate
            except Exception:
                public_session = {}
        self._account_scoped = bool(
            isinstance(self.account_manager, NewApiAccountManager)
            or (
                self.account_manager is not None
                and "loggedIn" in public_session
            )
        )
        self.owner_account_id = _account_id_from_session(public_session)
        self.repository = AgentSessionRepository(
            paths,
            owner_account_id=self.owner_account_id if self._account_scoped else None,
        )
        self.event_bus = AgentEventBus(self.repository)
        if runtime is None:
            self.runtime = LoomNativeRuntimeAdapter(
                self.model_client,
                runtime_name=self.native_runtime_name,
            )
        else:
            self.runtime = runtime
        self._skill_service = SkillService(paths)
        self._builtin_capabilities = AgentBuiltinCapabilityProvider(
            context_factory=self.context_factory,
            job_manager=self.job_manager,
            matrix_factory=self._matrix_factory,
        )
        self.capabilities = capabilities or CapabilityRegistry(
            internal_operations={
                **self._internal_operations(),
                **self._builtin_capabilities.operations(),
            },
            skill_provider=self._skill_service.list_skills,
            skill_executor=self._load_skill_instructions,
        )
        self.policy = policy if policy is not None else AgentPolicyEngine(approval_mode="strong")
        self.orchestrator = AgentOrchestrator(
            self.repository,
            self.event_bus,
            self.runtime,
            self.capabilities,
            self.policy,
            matrix_attachment_listener=self._register_matrix_campaign,
        )
        self._executor = ThreadPoolExecutor(
            max_workers=max(1, min(int(max_workers), 16)),
            thread_name_prefix="loom-agent-run",
        )

        self._futures: dict[str, Future[Any]] = {}
        self._pending_continuations: dict[str, RunContinuation] = {}
        self._resume_requests: set[str] = set()
        self._matrix_confirmation_tokens: dict[str, list[str]] = {}
        self._lock = threading.RLock()
        self._closed = False
        self._executor_shutdown = False

        execution_permitted = self._execution_permitted()
        recovered = (
            self.orchestrator.recover_unfinished_runs()
            if execution_permitted
            else []
        )
        for run in recovered:
            if run.get("status") == "queued":
                self._submit_run(
                    str(run["sessionId"]),
                    str(run["runId"]),
                    self._request_from_run(run),
                )
        if execution_permitted:
            self._restore_matrix_campaign_links()
        self._matrix_monitor_thread = threading.Thread(
            target=self._monitor_matrix_campaigns,
            name="loom-agent-matrix-monitor",
            daemon=True,
        )
        self._matrix_monitor_thread.start()

    def _default_matrix_factory(self) -> MatrixControlPlane:
        ctx = self.context_factory() if callable(self.context_factory) else None
        owner_account_id, owner_binding = (
            current_account_job_identity(ctx) if ctx is not None else ("", "")
        )
        return MatrixControlPlane(
            self.paths,
            phone_authorizer=self._authorize_matrix_phone_devices,
            owner_account_id=owner_account_id,
            owner_account_binding=owner_binding,
        )

    def _authorize_matrix_phone_devices(
        self,
        device_ids: list[str],
        operation: str,
    ) -> dict | None:
        if not callable(self.context_factory):
            return None
        from api.routes_phone import _authorize_phone_entitlement

        return _authorize_phone_entitlement(
            self.context_factory(),
            device_ids,
            operation,
        )

    def bootstrap(self) -> Json:
        self._require_current_account()
        runtime_status = redact_sensitive(self.runtime.status(NATIVE_RUNTIME_PROFILE_ID))
        if not isinstance(runtime_status, Mapping):
            runtime_status = {}
        runtime_status = {**runtime_status, "profileId": NATIVE_RUNTIME_PROFILE_ID}
        profile: Json = {
            "runtimeProfileId": NATIVE_RUNTIME_PROFILE_ID,
            "name": self.native_runtime_name,
            "available": bool(runtime_status.get("available")),
            "isDefault": True,
        }
        errors: list[Json] = []
        if isinstance(runtime_status.get("error"), Mapping):
            profile["error"] = redact_sensitive(runtime_status["error"])
            errors.append(redact_sensitive(runtime_status["error"]))

        capabilities = self.capabilities.list_capabilities()
        models, default_model_id = self._model_catalog()
        return {
            "runtime": runtime_status,
            "runtimeProfiles": [profile],
            "defaultRuntimeProfileId": NATIVE_RUNTIME_PROFILE_ID,
            "models": models,
            "defaultModelId": default_model_id,
            "capabilities": capabilities,
            "permissions": {"read": True, "control": True, "outbound": True, "critical": False},
            "policy": {
                "mode": self.policy.approval_mode,
                "approvalRequired": ["critical"] if self.policy.approval_mode == "weak" else ["outbound", "critical"],
                "approvalTtlSec": self.policy.approval_ttl_sec,
            },
            "limits": {"maxConcurrentRuns": self._executor._max_workers, "maxToolRounds": self.orchestrator.max_tool_rounds},
            "errors": errors,
        }

    def list_sessions(self, *, query: str | None = None, cursor: str | None = None, limit: int = 50) -> Json:
        self._require_current_account()
        return self.repository.list_sessions(query=query, cursor=cursor, limit=limit)

    def create_session(self, body: Mapping[str, Any] | None = None) -> Json:
        self._require_execution_access()
        data = dict(body or {})
        model_id = str(data.get("modelId") or "").strip()
        if model_id:
            self._ensure_model_available(model_id)
        return self.repository.create_session(
            title=str(data.get("title") or "New conversation"),
            runtime_profile_id=_native_runtime_profile_id(data.get("runtimeProfileId")),
            model_id=model_id,
        )

    def update_session(self, session_id: str, body: Mapping[str, Any] | None = None) -> Json:
        self._require_execution_access()
        data = dict(body or {})
        if "modelId" in data:
            model_id = str(data.get("modelId") or "").strip()
            if model_id:
                self._ensure_model_available(model_id)
            data["modelId"] = model_id
        data["runtimeProfileId"] = NATIVE_RUNTIME_PROFILE_ID
        return self.repository.update_session(session_id, data)

    def session_detail(self, session_id: str, *, cursor: str | None = None, limit: int = 100) -> Json:
        self._require_current_account()
        page = self.repository.page_messages(session_id, cursor=cursor, limit=limit)
        return {
            "session": self.repository.get_session(session_id),
            "messages": page.get("messages", []),
            "runs": self.repository.list_runs(session_id),
            **({"nextCursor": page["nextCursor"]} if page.get("nextCursor") else {}),
        }

    def send_message(self, session_id: str, body: Mapping[str, Any]) -> Json:
        self._require_execution_access()
        with self._lock:
            if self._closed:
                raise RuntimeError("agent service is closed")
        request = dict(body)
        client_message_id = str(request.get("clientMessageId") or "").strip()
        if not client_message_id:
            raise ValueError("clientMessageId is required")
        text = str(request.get("text") or "").strip()
        raw_attachments = request.get("attachments") if isinstance(request.get("attachments"), list) else []
        if not text and not raw_attachments:
            raise ValueError("message text or attachment is required")
        session = self.repository.get_session(session_id)
        existing = self.repository.find_message_run(session_id, client_message_id)
        if existing is not None:
            return {"message": existing["message"], "run": existing["run"]}
        model_id, model_source = self._resolve_run_model(session)
        supplied_scope = request.get("scope") if isinstance(request.get("scope"), Mapping) else None
        legacy_targets = request.get("targets") if isinstance(request.get("targets"), Mapping) else {}
        scope_values = dict(supplied_scope if supplied_scope is not None else legacy_targets)
        requested_mode = str(request.get("scopeMode") or scope_values.get("mode") or "").strip().lower()
        if requested_mode not in {"auto", "manual"}:
            requested_mode = "manual" if any(
                scope_values.get(key) for key in ("deviceIds", "groups", "allOnline")
            ) else "auto"
        scope_values["mode"] = requested_mode
        history = self.repository.page_messages(session_id, limit=500).get("messages", [])[-40:]
        try:
            matrix_status = self._matrix_factory().status()
        except Exception:
            matrix_status = {}
        scope_resolution = resolve_request_scope(text, scope_values, matrix_status)
        if requested_mode == "auto" and scope_resolution.status == "not_required" and _is_scope_continuation(text):
            for history_item in reversed(history):
                previous_text = _history_message_text(history_item)
                if not previous_text:
                    continue
                previous_scope = resolve_request_scope(previous_text, scope_values, matrix_status)
                if previous_scope.status != "not_required":
                    scope_resolution = previous_scope
                    break
        if requested_mode == "manual" and scope_resolution.status != "resolved":
            raise ValueError(f"AGENT_SCOPE_INVALID: {scope_resolution.summary}")
        materialized_attachments: list[Json] = []
        try:
            attachments = self._normalize_user_attachments(
                session_id,
                raw_attachments,
                materialized=materialized_attachments,
            )
        except Exception:
            self._cleanup_unreferenced_user_attachments(
                session_id,
                materialized_attachments,
            )
            raise
        session_artifacts = self._session_artifacts(session_id)
        now = _utc_now()
        message_id = f"message_{uuid.uuid4().hex}"
        run_id = f"run_{uuid.uuid4().hex}"
        blocks: list[Json] = []
        if text:
            blocks.append({"type": "text", "data": {"text": text}})
        if attachments:
            blocks.append({"type": "tool", "data": {"name": "attachments", "attachments": attachments}})
        message = {
            "schema": "loom.agent.message.v1",
            "messageId": message_id,
            "sessionId": session_id,
            "role": "user",
            "status": "completed",
            "blocks": blocks,
            "createdAt": now,
            "completedAt": now,
        }
        available_capability_names = [
            str(item.get("name") or "").strip()
            for item in self.capabilities.list_capabilities(available_only=True)
            if isinstance(item, Mapping) and str(item.get("name") or "").strip()
        ]
        supplied_capability_hints = (
            request.get("capabilityHints") if isinstance(request.get("capabilityHints"), list) else []
        )
        capability_hints = list(dict.fromkeys([
            *extract_explicit_capability_hints(text, available_capability_names),
            *[
                str(item or "").strip()
                for item in supplied_capability_hints
                if str(item or "").strip() in available_capability_names
            ],
        ]))
        runtime_request = {
            "prompt": text,
            "brandDisplayName": self.brand_identity.display_name,
            "attachments": attachments,
            "scopeMode": scope_resolution.mode,
            "requestScope": scope_resolution.to_dict(),
            "targets": scope_resolution.targets(),
            "capabilityHints": capability_hints,
            "runtimeProfileId": _native_runtime_profile_id(request.get("runtimeProfileId")),
            "history": history,
        }
        if session_artifacts:
            runtime_request["sessionArtifacts"] = session_artifacts
        if scope_resolution.status == "ambiguous":
            runtime_request["scopeClarification"] = scope_resolution.clarification
        if model_id:
            runtime_request["modelId"] = model_id
        run = {
            "schema": "loom.agent.run.v1",
            "runId": run_id,
            "sessionId": session_id,
            "status": "queued",
            "checkpoint": "",
            "campaignIds": [],
            "request": runtime_request,
        }
        if model_id:
            run["modelId"] = model_id
            run["modelSource"] = model_source
        # Repository submission spans idempotency, active-run validation, the
        # committed history snapshot, and persistence under one process-safe transaction.
        with self._lock:
            if self._closed:
                raise RuntimeError("agent service is closed")
            try:
                result = self.repository.create_message_run(
                    session_id,
                    client_message_id,
                    message,
                    run,
                    reject_active_run=True,
                    history_limit=40,
                )
            except Exception:
                self._cleanup_unreferenced_user_attachments(
                    session_id,
                    materialized_attachments,
                )
                raise
            if not result.get("created"):
                self._cleanup_unreferenced_user_attachments(
                    session_id,
                    materialized_attachments,
                )
            if result.get("created"):
                persisted_request = result["run"].get("request")
                if not isinstance(persisted_request, Mapping):
                    persisted_request = runtime_request
                self.event_bus.publish(
                    session_id,
                    "run.queued",
                    topic="agent.run",
                    entity_id=str(result["run"]["runId"]),
                    data={"status": "queued"},
                )
                self._submit_run(session_id, str(result["run"]["runId"]), persisted_request)
        return {"message": result["message"], "run": result["run"]}

    def _normalize_user_attachments(
        self,
        session_id: str,
        values: list[Any],
        *,
        materialized: list[Json] | None = None,
    ) -> list[Json]:
        if len(values) > _MAX_USER_ATTACHMENTS:
            raise ValueError(
                f"AGENT_ATTACHMENT_LIMIT_EXCEEDED: at most {_MAX_USER_ATTACHMENTS} attachments are allowed"
            )
        normalized: list[Json] = []
        total_bytes = 0
        for value in values:
            if not isinstance(value, Mapping):
                raise ValueError("AGENT_ATTACHMENT_INVALID: attachment must be an object")
            name = _safe_attachment_name(value.get("name"))
            try:
                size = max(0, int(value.get("size") or 0))
            except (TypeError, ValueError):
                raise ValueError(f"AGENT_ATTACHMENT_INVALID: invalid size for {name}") from None
            total_bytes += size
            if total_bytes > _MAX_USER_ATTACHMENT_TOTAL_BYTES:
                raise ValueError(
                    "AGENT_ATTACHMENT_LIMIT_EXCEEDED: attachment total exceeds 16 MB"
                )
            supplied_type = str(value.get("type") or value.get("mime") or "").strip().lower()
            extension = os.path.splitext(name)[1].lower()
            kind = str(value.get("kind") or "").strip().lower()

            if kind == "image" or supplied_type.startswith("image/"):
                encoded = str(value.get("dataUrl") or "")
                header = f"data:{supplied_type};base64,"
                encoded_bytes = max(0, len(encoded) - len(header))
                estimated_bytes = (encoded_bytes * 3) // 4
                total_bytes += max(0, estimated_bytes - size)
                if total_bytes > _MAX_USER_ATTACHMENT_TOTAL_BYTES:
                    raise ValueError(
                        "AGENT_ATTACHMENT_LIMIT_EXCEEDED: attachment total exceeds 16 MB"
                    )
                attachment = self._materialize_user_image_attachment(
                    session_id,
                    name=name,
                    mime=supplied_type,
                    size=size,
                    last_modified=value.get("lastModified"),
                    data_url=encoded,
                )
                normalized.append(attachment)
                if materialized is not None:
                    materialized.append(attachment)
                continue

            is_text = (
                kind in {"", "text"}
                and (
                    supplied_type.startswith("text/")
                    or supplied_type in {
                        "",
                        "application/javascript",
                        "application/json",
                        "application/ld+json",
                        "application/xml",
                        "application/x-yaml",
                        "application/yaml",
                    }
                    or extension in _USER_TEXT_EXTENSIONS
                )
            )
            if is_text:
                content = str(value.get("content") or "")[:_MAX_USER_TEXT_CHARS]
                normalized.append({
                    "name": name,
                    "size": size,
                    "type": supplied_type or "text/plain",
                    "mime": supplied_type or "text/plain",
                    "kind": "text",
                    "lastModified": value.get("lastModified"),
                    "content": content,
                    "truncated": bool(
                        value.get("truncated")
                        or value.get("contentTruncated")
                        or len(str(value.get("content") or "")) > _MAX_USER_TEXT_CHARS
                    ),
                })
                continue

            raise ValueError(
                f"AGENT_ATTACHMENT_TYPE_UNSUPPORTED: {name} is not a supported image or text attachment"
            )
        return normalized

    def _cleanup_unreferenced_user_attachments(
        self,
        session_id: str,
        attachments: list[Json],
    ) -> None:
        attachment_root = os.path.abspath(os.path.join(
            self.paths.data_dir,
            "agent",
            "attachments",
            session_id,
        ))
        candidates: list[str] = []
        for item in attachments:
            raw_path = str(item.get("path") or "").strip() if isinstance(item, Mapping) else ""
            if not raw_path:
                continue
            path = os.path.abspath(raw_path)
            try:
                inside_root = os.path.commonpath([path, attachment_root]) == attachment_root
            except ValueError:
                inside_root = False
            if inside_root and path not in candidates:
                candidates.append(path)
        if not candidates:
            return
        try:
            referenced = self.repository.referenced_attachment_paths(session_id, candidates)
        except Exception:
            # If durable-state inspection fails, retain files so repository
            # recovery cannot resurrect a message with a missing attachment.
            return
        referenced_keys = {os.path.normcase(os.path.abspath(path)) for path in referenced}
        for path in candidates:
            if os.path.normcase(path) in referenced_keys:
                continue
            try:
                os.remove(path)
            except FileNotFoundError:
                pass
            except OSError:
                continue
        try:
            os.rmdir(attachment_root)
        except OSError:
            pass

    def _materialize_user_image_attachment(
        self,
        session_id: str,
        *,
        name: str,
        mime: str,
        size: int,
        last_modified: Any,
        data_url: Any,
    ) -> Json:
        if mime not in _USER_IMAGE_MIME_EXTENSIONS:
            raise ValueError(f"AGENT_ATTACHMENT_TYPE_UNSUPPORTED: unsupported image type for {name}")
        if size > _MAX_USER_IMAGE_BYTES:
            raise ValueError(f"AGENT_ATTACHMENT_LIMIT_EXCEEDED: {name} exceeds 8 MB")
        encoded = str(data_url or "")
        expected_header = f"data:{mime};base64,"
        if not encoded.startswith(expected_header):
            raise ValueError(f"AGENT_ATTACHMENT_INVALID: image data is missing for {name}")
        raw_base64 = encoded[len(expected_header):]
        if len(raw_base64) > ((_MAX_USER_IMAGE_BYTES + 2) // 3) * 4 + 8:
            raise ValueError(f"AGENT_ATTACHMENT_LIMIT_EXCEEDED: {name} exceeds 8 MB")
        try:
            payload = base64.b64decode(raw_base64, validate=True)
        except (ValueError, binascii.Error):
            raise ValueError(f"AGENT_ATTACHMENT_INVALID: image data is invalid for {name}") from None
        if not payload or len(payload) > _MAX_USER_IMAGE_BYTES:
            raise ValueError(f"AGENT_ATTACHMENT_LIMIT_EXCEEDED: {name} exceeds 8 MB")
        if size and size != len(payload):
            raise ValueError(f"AGENT_ATTACHMENT_INVALID: image size mismatch for {name}")
        if not _image_signature_matches(mime, payload):
            raise ValueError(f"AGENT_ATTACHMENT_INVALID: image signature mismatch for {name}")

        attachment_dir = os.path.join(
            self.paths.data_dir,
            "agent",
            "attachments",
            session_id,
        )
        os.makedirs(attachment_dir, exist_ok=True)
        filename = f"{uuid.uuid4().hex}{_USER_IMAGE_MIME_EXTENSIONS[mime]}"
        path = os.path.abspath(os.path.join(attachment_dir, filename))
        if os.path.commonpath([path, os.path.abspath(attachment_dir)]) != os.path.abspath(attachment_dir):
            raise ValueError("AGENT_ATTACHMENT_INVALID: unsafe attachment path")
        temporary_path = f"{path}.tmp"
        try:
            with open(temporary_path, "xb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, path)
        finally:
            if os.path.exists(temporary_path):
                os.remove(temporary_path)
        return {
            "name": name,
            "size": len(payload),
            "type": mime,
            "mime": mime,
            "kind": "image",
            "lastModified": last_modified,
            "path": path,
        }

    def _session_artifacts(self, session_id: str, *, limit: int = 20) -> list[Json]:
        try:
            events = self.repository.replay_events(session_id)
        except Exception:
            return []
        artifacts: list[Json] = []
        seen_paths: set[str] = set()
        for event in reversed(events[-500:]):
            if not isinstance(event, Mapping) or str(event.get("type") or "") != "tool.completed":
                continue
            data = event.get("data") if isinstance(event.get("data"), Mapping) else {}
            attachments = data.get("attachments") if isinstance(data.get("attachments"), list) else []
            for item in reversed(attachments):
                if not isinstance(item, Mapping):
                    continue
                raw_path = str(item.get("path") or "").strip()
                if not raw_path:
                    continue
                path = os.path.abspath(raw_path)
                if not os.path.isfile(path):
                    continue
                path_key = os.path.normcase(path)
                if path_key in seen_paths:
                    continue
                seen_paths.add(path_key)
                artifacts.append({
                    "name": str(item.get("name") or os.path.basename(path) or "media")[:160],
                    "path": path,
                    "mime": str(item.get("mime") or item.get("type") or "")[:120],
                    "kind": str(item.get("kind") or "")[:40],
                })
                if len(artifacts) >= limit:
                    return list(reversed(artifacts))
        return list(reversed(artifacts))

    def _model_catalog(self) -> tuple[list[Json], str]:
        public_session: Mapping[str, Any] = {}
        public_session_reader = getattr(self.account_manager, "public_session", None)
        if callable(public_session_reader):
            try:
                candidate = public_session_reader()
                if isinstance(candidate, Mapping):
                    public_session = candidate
            except Exception:
                public_session = {}

        models_value = public_session.get("models")
        models_by_kind = models_value if isinstance(models_value, Mapping) else {}
        text_models = models_by_kind.get("text") if isinstance(models_by_kind.get("text"), list) else []
        catalog: list[Json] = []
        seen: set[str] = set()
        for item in text_models:
            if isinstance(item, Mapping):
                model_id = str(item.get("modelId") or item.get("id") or item.get("name") or "").strip()
                name = str(item.get("name") or model_id).strip()
                available = bool(item.get("available", True))
            else:
                model_id = str(item or "").strip()
                name = model_id
                available = True
            if not model_id or model_id in seen:
                continue
            seen.add(model_id)
            catalog.append({"modelId": model_id, "name": name or model_id, "available": available})

        selected_value = public_session.get("selectedModels")
        selected_models = selected_value if isinstance(selected_value, Mapping) else {}
        default_model_id = str(selected_models.get("text") or "").strip()
        return catalog, default_model_id

    def _ensure_model_available(self, model_id: str) -> None:
        catalog, _default_model_id = self._model_catalog()
        available_ids = {
            str(item.get("modelId") or "")
            for item in catalog
            if item.get("available") is True
        }
        if model_id not in available_ids:
            raise ValueError(f"AGENT_MODEL_NOT_AVAILABLE: {model_id}")

    def _resolve_run_model(self, session: Mapping[str, Any]) -> tuple[str, str]:
        session_model_id = str(session.get("modelId") or "").strip()
        if session_model_id:
            self._ensure_model_available(session_model_id)
            return session_model_id, "session"
        _catalog, default_model_id = self._model_catalog()
        if default_model_id:
            self._ensure_model_available(default_model_id)
            return default_model_id, "account-default"
        return "", "account-default"

    def get_run(self, run_id: str) -> Json:
        self._require_current_account()
        return self.repository.get_run(run_id)

    def get_trace(self, run_id: str) -> Json:
        self._require_current_account()
        run = self.repository.get_run(run_id)
        session_id = str(run["sessionId"])
        events = self.repository.replay_events(session_id)
        relevant_events = [
            event
            for event in events
            if event.get("entityId") == run_id or event.get("data", {}).get("runId") == run_id
        ]
        trace = self._trace_nodes(run_id, relevant_events)
        return {
            "run": run,
            "trace": trace,
            "nodes": trace,
            "approvals": self.repository.list_approvals(session_id, run_id=run_id),
        }

    def pause_run(self, run_id: str) -> Json:
        self._require_execution_access()
        return self.orchestrator.pause_run(run_id)

    def resume_run(self, run_id: str) -> Json:
        self._require_execution_access()
        with self._lock:
            run = self.repository.get_run(run_id)
            pause_requested = (
                run.get("status") == "running"
                and run.get("controlState") == "pause_requested"
            )
            if (
                run.get("status") != "paused"
                and not pause_requested
            ) or run_id in self._resume_requests:
                return run
            self._resume_requests.add(run_id)
            try:
                self._submit_run(str(run["sessionId"]), run_id, self._request_from_run(run), resume=True)
            except Exception:
                self._resume_requests.discard(run_id)
                raise
        return self.repository.get_run(run_id)

    def cancel_run(self, run_id: str) -> Json:
        self._require_execution_access()
        run = self.repository.get_run(run_id)
        campaign_ids = [
            str(campaign_id)
            for campaign_id in run.get("campaignIds", []) if str(campaign_id)
        ] if isinstance(run.get("campaignIds"), list) else []
        if campaign_ids:
            incomplete = self._cancel_linked_matrix_campaigns(campaign_ids)
            if incomplete:
                session_id = str(run["sessionId"])
                current = self.repository.get_run(run_id, session_id=session_id)
                if current.get("status") not in TERMINAL_RUN_STATUSES:
                    current = self.orchestrator.cancel_run(
                        run_id,
                        session_id=session_id,
                        force_pending=True,
                    )
                updated = self.repository.update_run(
                    run_id,
                    {
                        "status": "running",
                        "controlState": "cancel_requested",
                        "error": {
                            "code": "agent_matrix_cancel_incomplete",
                            "message": (
                                "关联 Matrix 任务尚未确认停止，外部执行可能仍在继续；"
                                f"请等待终态并勿直接重试：{', '.join(incomplete)}"
                            ),
                            "recoverable": False,
                            "outcomeIndeterminate": True,
                            "executionMayContinue": True,
                        },
                    },
                    session_id=session_id,
                )
                self.event_bus.publish(
                    session_id,
                    "run.cancel_pending",
                    topic="agent.run",
                    entity_id=run_id,
                    data={"runId": run_id, "campaignIds": campaign_ids, "incomplete": incomplete},
                )
                return updated
        return self.orchestrator.cancel_run(run_id)

    def resolve_approval(self, approval_id: str, body: Mapping[str, Any]) -> Json:
        self._require_execution_access()
        approval = self.repository.get_approval(approval_id)
        decision = str(body.get("decision") or "").strip().lower()
        decision = {"approve": "approved", "reject": "rejected"}.get(decision, decision)
        confirmation_token: tuple[str, str] | None = None
        if decision == "approved" and approval.get("capability") in MATRIX_CONFIRMATION_CAPABILITIES:
            input_hash = str(approval.get("inputHash") or "")
            if input_hash:
                confirmation_token = (input_hash, approval_id)
                with self._lock:
                    self._matrix_confirmation_tokens.setdefault(input_hash, []).append(approval_id)
        try:
            return self.orchestrator.resolve_approval(
                str(approval["sessionId"]),
                approval_id,
                decision=decision,
                decided_by=str(body.get("operator") or body.get("decidedBy") or "local-user"),
                request=self._request_from_run(self.repository.get_run(str(approval["runId"]))),
            )
        finally:
            if confirmation_token is not None:
                input_hash, token_approval_id = confirmation_token
                with self._lock:
                    tokens = self._matrix_confirmation_tokens.get(input_hash, [])
                    if token_approval_id in tokens:
                        tokens.remove(token_approval_id)
                    if not tokens:
                        self._matrix_confirmation_tokens.pop(input_hash, None)

    def queue_approval_resolution(self, approval_id: str, body: Mapping[str, Any]) -> Json:
        self._require_execution_access()
        approval = self.repository.get_approval(approval_id)
        decision = str(body.get("decision") or "").strip().lower()
        decision = {"approve": "approved", "reject": "rejected"}.get(decision, decision)
        confirmation_token: tuple[str, str] | None = None
        if decision == "approved" and approval.get("capability") in MATRIX_CONFIRMATION_CAPABILITIES:
            input_hash = str(approval.get("inputHash") or "")
            if input_hash:
                confirmation_token = (input_hash, approval_id)
                with self._lock:
                    self._matrix_confirmation_tokens.setdefault(input_hash, []).append(approval_id)

        def release_confirmation() -> None:
            if confirmation_token is None:
                return
            input_hash, token_approval_id = confirmation_token
            with self._lock:
                tokens = self._matrix_confirmation_tokens.get(input_hash, [])
                if token_approval_id in tokens:
                    tokens.remove(token_approval_id)
                if not tokens:
                    self._matrix_confirmation_tokens.pop(input_hash, None)

        run = self.repository.get_run(str(approval["runId"]))
        request = self._request_from_run(run)
        try:
            outcome = self.orchestrator.resolve_approval(
                str(approval["sessionId"]),
                approval_id,
                decision=decision,
                decided_by=str(body.get("operator") or body.get("decidedBy") or "local-user"),
                request=request,
                defer_execution=True,
            )
            if outcome.get("approval", {}).get("status") != "approved":
                release_confirmation()
                return outcome
            self._submit_run(
                str(approval["sessionId"]),
                str(approval["runId"]),
                request,
                emit_runtime_requested=False,
                on_complete=release_confirmation,
                queue_if_busy=True,
            )
            return outcome
        except Exception:
            release_confirmation()
            raise

    def events_after(self, *, session_id: str, after_seq: int) -> list[Json]:
        self._require_current_account()
        return self.event_bus.replay(session_id, after_seq=after_seq, limit=500)

    def _public_account_session(self) -> Mapping[str, Any]:
        reader = getattr(self.account_manager, "public_session", None)
        if not callable(reader):
            return {}
        try:
            value = reader()
        except Exception:
            return {}
        return value if isinstance(value, Mapping) else {}

    def _require_current_account(self) -> None:
        if not self._account_scoped:
            return
        current = _account_id_from_session(self._public_account_session())
        if not current or current != self.owner_account_id:
            raise KeyError("agent account scope")

    def _execution_permitted(self) -> bool:
        try:
            self._require_current_account()
        except KeyError:
            return False
        entitlement = getattr(self.account_manager, "account_entitlement", None)
        current_state = getattr(entitlement, "current_state", None)
        if not callable(current_state):
            return True
        try:
            state = current_state()
        except Exception:
            return False
        return isinstance(state, Mapping) and state.get("authorized") is True

    def _require_execution_access(self) -> None:
        self._require_current_account()
        if not self._execution_permitted():
            raise PermissionError(
                "AGENT_ENTITLEMENT_REQUIRED: account entitlement is inactive"
            )

    def shutdown(self, *, grace_seconds: float = 2.0) -> Json:
        with self._lock:
            first_request = not self._closed
            self._closed = True
            active = [
                (run_id, future)
                for run_id, future in self._futures.items()
                if not future.done()
            ]
        if first_request:
            for run_id, _future in active:
                try:
                    self.orchestrator.pause_run(run_id)
                except Exception:
                    pass
        self._matrix_monitor_stop.set()
        self._matrix_monitor_thread.join(timeout=2.0)
        deadline = time.monotonic() + max(0.0, float(grace_seconds))
        while True:
            with self._lock:
                tracked_runs = list(self._futures.values())
            pending_runs = [future for future in tracked_runs if not future.done()]
            unfinished_workers = self.capabilities.unfinished_worker_count()
            if not tracked_runs and unfinished_workers == 0:
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            if pending_runs:
                wait(pending_runs, timeout=min(remaining, 0.05))
            elif tracked_runs:
                time.sleep(min(remaining, 0.01))
            if unfinished_workers:
                remaining = deadline - time.monotonic()
                if remaining > 0:
                    self.capabilities.drain_workers(timeout=min(remaining, 0.05))
        with self._lock:
            unfinished_runs = len(self._futures)
            if not self._executor_shutdown:
                self._executor.shutdown(wait=False, cancel_futures=True)
                self._executor_shutdown = True
        unfinished_workers = self.capabilities.unfinished_worker_count()
        drained = unfinished_runs == 0 and unfinished_workers == 0
        result: Json = {
            "stopped": drained,
            "drained": drained,
            "unfinishedRuns": unfinished_runs,
            "unfinishedWorkers": unfinished_workers,
            "outcomeIndeterminate": not drained,
            "executionMayContinue": not drained,
        }
        if not drained:
            result.update({
                "code": "agent_shutdown_incomplete",
                "message": "Agent 关闭等待已超时，仍有执行可能继续；全局服务将保留且不会创建第二个实例。",
                "retryable": False,
            })
        return result

    def _submit_run(
        self,
        session_id: str,
        run_id: str,
        request: Mapping[str, Any],
        *,
        resume: bool = False,
        emit_runtime_requested: bool = True,
        on_complete: Callable[[], None] | None = None,
        queue_if_busy: bool = False,
    ) -> bool:
        with self._lock:
            current = self._futures.get(run_id)
            if current is not None and not current.done():
                if resume or queue_if_busy:
                    self._pending_continuations.setdefault(
                        run_id,
                        (session_id, dict(request), resume, emit_runtime_requested, on_complete),
                    )
                    return True
                return False
            if self._closed:
                raise RuntimeError("agent service is closed")

            def execute() -> Json:
                if emit_runtime_requested:
                    snapshot = self._prompt_snapshot(session_id, request)
                    self.event_bus.publish(
                        session_id,
                        "runtime.requested",
                        topic="agent.run",
                        entity_id=run_id,
                        data={"runId": run_id, "promptSnapshot": snapshot},
                    )
                if resume:
                    return self.orchestrator.resume_run(run_id, session_id=session_id, request=request)
                return self.orchestrator.execute_run(session_id, run_id, request=request)

            future = self._executor.submit(execute)
            self._futures[run_id] = future

            def forget(completed: Future[Any]) -> None:
                try:
                    completed.result()
                except Exception as error:
                    safe_error = str(redact_sensitive(str(error)))[:500]
                    try:
                        self.orchestrator.record_unexpected_service_failure(
                            session_id,
                            run_id,
                            safe_error,
                        )
                    except Exception:
                        pass
                continuation: RunContinuation | None = None
                with self._lock:
                    if self._futures.get(run_id) is completed:
                        self._futures.pop(run_id, None)
                        continuation = self._pending_continuations.pop(run_id, None)
                        if resume and continuation is None:
                            self._resume_requests.discard(run_id)
                if on_complete is not None:
                    try:
                        on_complete()
                    except Exception:
                        pass
                if continuation is not None:
                    next_session_id, next_request, next_resume, next_emit, next_on_complete = continuation
                    try:
                        latest_run = self.repository.get_run(run_id, session_id=next_session_id)
                        continuation_is_still_valid = (
                            str(latest_run.get("status") or "") not in TERMINAL_RUN_STATUSES
                        )
                    except Exception:
                        continuation_is_still_valid = False
                    if not continuation_is_still_valid:
                        if next_on_complete is not None:
                            try:
                                next_on_complete()
                            except Exception:
                                pass
                        with self._lock:
                            if next_resume:
                                self._resume_requests.discard(run_id)
                        return
                    try:
                        self._submit_run(
                            next_session_id,
                            run_id,
                            next_request,
                            resume=next_resume,
                            emit_runtime_requested=next_emit,
                            on_complete=next_on_complete,
                            queue_if_busy=True,
                        )
                    except Exception:
                        if next_on_complete is not None:
                            try:
                                next_on_complete()
                            except Exception:
                                pass
                        with self._lock:
                            if next_resume:
                                self._resume_requests.discard(run_id)
                        raise

            future.add_done_callback(forget)
            return True

    def _request_from_run(self, run: Mapping[str, Any]) -> Json:
        request = run.get("request")
        restored = dict(request) if isinstance(request, Mapping) else {
            "prompt": "Resume the saved local agent run from its checkpoint.",
        }
        restored["runtimeProfileId"] = _native_runtime_profile_id(restored.get("runtimeProfileId"))
        return restored

    def _prompt_snapshot(self, session_id: str, request: Mapping[str, Any]) -> Json:
        safe = sanitize_for_storage(dict(request))
        canonical = json.dumps(safe, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
        try:
            message_count = len(self.repository.page_messages(session_id, limit=500).get("messages", []))
        except Exception:
            message_count = 0
        return {
            "snapshotId": f"prompt_{uuid.uuid4().hex}",
            "hash": f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}",
            "createdAt": _utc_now(),
            "runtimeProfileId": _native_runtime_profile_id(request.get("runtimeProfileId")),
            "messageCount": message_count,
            "toolCount": len(self.capabilities.list_capabilities()),
        }

    def _trace_node(self, run_id: str, event: Mapping[str, Any]) -> Json:
        event_type = str(event.get("type") or "runtime.event")
        if event_type.startswith("tool."):
            kind = "tool"
        elif event_type.startswith("approval."):
            kind = "policy"
        elif event_type.startswith("matrix."):
            kind = "matrix"
        elif event_type.startswith("plan."):
            kind = "plan"
        else:
            kind = "runtime"
        status = "failed" if event_type.endswith("failed") else (
            "running" if event_type.endswith(("queued", "started", "requested", "delta", "waiting_approval")) else "completed"
        )
        data = event.get("data") if isinstance(event.get("data"), Mapping) else {}
        error = data.get("error") if isinstance(data.get("error"), Mapping) else None
        node = {
            "traceId": str(event.get("eventId") or f"trace_{uuid.uuid4().hex}"),
            "runId": run_id,
            "ownerAccountId": str(event.get("ownerAccountId") or "").strip(),
            "kind": kind,
            "name": event_type,
            "status": status,
            "startedAt": str(event.get("timestamp") or _utc_now()),
            "inputSummary": redact_sensitive(data),
        }
        if error:
            node["error"] = redact_sensitive(error)
        return node

    def _trace_nodes(self, run_id: str, events: list[Mapping[str, Any]]) -> list[Json]:
        nodes: list[Json] = []
        tool_positions: dict[str, int] = {}
        status_rank = {"running": 0, "completed": 1, "failed": 2}
        for event in events:
            node = self._trace_node(run_id, event)
            data = event.get("data") if isinstance(event.get("data"), Mapping) else {}
            tool_call_id = str(data.get("toolCallId") or "").strip() if node["kind"] == "tool" else ""
            if not tool_call_id:
                nodes.append(node)
                continue
            lifecycle_key = f"{run_id}:{tool_call_id}"
            position = tool_positions.get(lifecycle_key)
            if position is None:
                node["traceId"] = f"tool:{lifecycle_key}"
                node["eventCount"] = 1
                tool_positions[lifecycle_key] = len(nodes)
                nodes.append(node)
                continue
            existing = nodes[position]
            existing["eventCount"] = int(existing.get("eventCount") or 1) + 1
            existing["inputSummary"] = {
                **(existing.get("inputSummary") if isinstance(existing.get("inputSummary"), Mapping) else {}),
                **node["inputSummary"],
            }
            if status_rank[node["status"]] >= status_rank[existing["status"]]:
                existing["name"] = node["name"]
                existing["status"] = node["status"]
                if node.get("error"):
                    existing["error"] = node["error"]
                if node["status"] != "running":
                    existing["completedAt"] = str(event.get("timestamp") or _utc_now())
        return nodes

    def _register_matrix_campaign(self, session_id: str, run_id: str, campaign_id: str, result: Json) -> None:
        with self._lock:
            self._campaign_links[campaign_id] = {
                "sessionId": session_id,
                "runId": run_id,
                "lastSignature": "",
                "missingPolls": 0,
                "attached": sanitize_for_storage(result),
            }

    def _restore_matrix_campaign_links(self) -> None:
        cursor: str | None = None
        while True:
            try:
                page = self.repository.list_sessions(cursor=cursor, limit=200)
            except Exception:
                return
            sessions = page.get("sessions", []) if isinstance(page, Mapping) else []
            for session in sessions if isinstance(sessions, list) else []:
                if not isinstance(session, Mapping) or not session.get("sessionId"):
                    continue
                session_id = str(session["sessionId"])
                try:
                    runs = self.repository.list_runs(session_id)
                except Exception:
                    continue
                for run in runs:
                    if not isinstance(run, Mapping) or run.get("status") in {"failed", "cancelled"}:
                        continue
                    for campaign_id in run.get("campaignIds", []) if isinstance(run.get("campaignIds"), list) else []:
                        if campaign_id:
                            self._register_matrix_campaign(session_id, str(run.get("runId") or ""), str(campaign_id), {})
            next_cursor = str(page.get("nextCursor") or "") if isinstance(page, Mapping) else ""
            if not next_cursor or next_cursor == cursor:
                return
            cursor = next_cursor

    def _cancel_linked_matrix_campaigns(self, campaign_ids: list[str]) -> list[str]:
        incomplete: list[str] = []
        campaign_id_set = set(campaign_ids)
        if self.job_manager is not None:
            try:
                account_id, owner_binding = self._current_job_owner_identity()
                self.job_manager.cancel_matching(
                    lambda job: (
                        self._matrix_job_visible_to_identity(
                            job,
                            account_id=account_id,
                            owner_binding=owner_binding,
                        )
                        and str(
                            (job.get("progress") or {}).get("campaignId") or ""
                        ) in campaign_id_set
                    )
                )
            except Exception:
                incomplete.append("jobs")

        matrix = self._matrix_factory()
        for campaign_id in campaign_ids:
            try:
                matrix.cancel(campaign_id)
            except Exception:
                incomplete.append(campaign_id)
        try:
            snapshot = matrix.status()
            campaigns = snapshot.get("campaigns", []) if isinstance(snapshot, Mapping) else []
            statuses = {
                str(campaign.get("campaignId")): str(campaign.get("status") or "")
                for campaign in campaigns
                if isinstance(campaign, Mapping) and campaign.get("campaignId")
            }
        except Exception:
            return list(dict.fromkeys([*incomplete, *campaign_ids]))

        for campaign_id in campaign_ids:
            status = statuses.get(campaign_id)
            if status not in TERMINAL_MATRIX_STATUSES:
                incomplete.append(campaign_id)
                continue
            with self._lock:
                self._campaign_links.pop(campaign_id, None)
        return list(dict.fromkeys(incomplete))

    def _monitor_matrix_campaigns(self) -> None:
        while not self._matrix_monitor_stop.wait(0.5):
            try:
                snapshot = self._matrix_factory().status()
            except Exception:
                continue
            self._reconcile_matrix_campaign_snapshot(snapshot)

    def _reconcile_matrix_campaign_snapshot(self, snapshot: Mapping[str, Any]) -> None:
        with self._lock:
            links = {campaign_id: dict(link) for campaign_id, link in self._campaign_links.items()}
        if not links:
            return
        campaigns = snapshot.get("campaigns", []) if isinstance(snapshot, Mapping) else []
        by_id = {
            str(campaign.get("campaignId")): campaign
            for campaign in campaigns if isinstance(campaign, Mapping) and campaign.get("campaignId")
        }
        for campaign_id, link in links.items():
            campaign = by_id.get(campaign_id)
            if not isinstance(campaign, Mapping):
                with self._lock:
                    current = self._campaign_links.get(campaign_id)
                    if current is not None:
                        current["missingPolls"] = int(current.get("missingPolls") or 0) + 1
                continue
            tasks = self._matrix_device_tasks(campaign)
            counts = self._matrix_task_counts(tasks)
            status = str(campaign.get("status") or "running")
            data = {
                "messageId": f"matrix:{campaign_id}",
                "sessionId": str(link.get("sessionId") or ""),
                "runId": str(link.get("runId") or ""),
                "campaignId": campaign_id,
                "status": status,
                "counts": sanitize_for_storage(counts),
                "total": int(counts.get("total", len(tasks)) or 0),
                "completed": int(counts.get("completed", 0) or 0),
                "failed": int(counts.get("failed", 0) or 0),
                "deviceIds": [str(task.get("deviceId")) for task in tasks if isinstance(task, Mapping) and task.get("deviceId")],
                "failedDeviceIds": [
                    str(task.get("deviceId"))
                    for task in tasks
                    if isinstance(task, Mapping) and task.get("status") in {"failed", "needs_human", "cancelled"} and task.get("deviceId")
                ],
                "failures": [
                    {
                        "deviceId": str(task.get("deviceId") or ""),
                        "deviceTaskId": str(task.get("deviceTaskId") or ""),
                        "errorCode": str(task.get("failureCode") or "matrix_device_task_failed"),
                        "message": str(task.get("failureReason") or "手机任务执行失败"),
                    }
                    for task in tasks
                    if isinstance(task, Mapping) and task.get("status") in {"failed", "needs_human"}
                ],
            }
            signature = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            should_publish = signature != str(link.get("lastSignature") or "")
            if status in TERMINAL_MATRIX_STATUSES:
                self._persist_matrix_terminal_intent(
                    session_id=data["sessionId"],
                    run_id=data["runId"],
                    campaign=campaign,
                )
            with self._lock:
                current = self._campaign_links.get(campaign_id)
                if current is None:
                    continue
                if status in TERMINAL_MATRIX_STATUSES:
                    self._campaign_links.pop(campaign_id, None)
                else:
                    current["lastSignature"] = signature
                    current["missingPolls"] = 0
            if should_publish:
                event_type = f"matrix.{status}" if status in TERMINAL_MATRIX_STATUSES else "matrix.progress"
                self.event_bus.publish(
                    data["sessionId"],
                    event_type,
                    topic="matrix.campaign",
                    entity_id=campaign_id,
                    data=data,
                )
            if status in TERMINAL_MATRIX_STATUSES:
                self._queue_matrix_terminal_resume(
                    session_id=data["sessionId"],
                    run_id=data["runId"],
                )

    def _persist_matrix_terminal_intent(
        self,
        *,
        session_id: str,
        run_id: str,
        campaign: Mapping[str, Any],
    ) -> None:
        if not session_id or not run_id:
            return
        try:
            run = self.repository.get_run(run_id, session_id=session_id)
        except KeyError:
            return
        if str(run.get("status") or "") in TERMINAL_RUN_STATUSES:
            return
        campaign_id = str(campaign.get("campaignId") or "")
        if not campaign_id:
            return
        raw_intents = run.get("matrixTerminalIntents")
        intents = [
            dict(item)
            for item in raw_intents
            if isinstance(item, Mapping)
            and str(item.get("campaignId") or "") != campaign_id
        ] if isinstance(raw_intents, list) else []
        error = campaign.get("error")
        if isinstance(error, Mapping):
            failure_detail = error.get("message") or error.get("code")
        else:
            failure_detail = error
        failure_detail = failure_detail or campaign.get("message") or campaign.get("reason")
        intents.append({
            "campaignId": campaign_id,
            "status": str(campaign.get("status") or ""),
            "failureDetail": str(redact_sensitive(str(failure_detail or "")))[:300],
            "observedAt": _utc_now(),
        })
        self.repository.update_run(
            run_id,
            {"matrixTerminalIntents": intents},
            session_id=session_id,
        )

    def _queue_matrix_terminal_resume(self, *, session_id: str, run_id: str) -> None:
        if not session_id or not run_id:
            return
        try:
            run = self.repository.get_run(run_id, session_id=session_id)
            if str(run.get("status") or "") in TERMINAL_RUN_STATUSES:
                return
            if str(run.get("controlState") or "") == "cancel_requested":
                self.orchestrator.cancel_run(run_id, session_id=session_id)
                return
            if str(run.get("status") or "") == "waiting_approval":
                return
            self._submit_run(
                session_id,
                run_id,
                self._request_from_run(run),
                resume=True,
                emit_runtime_requested=False,
                queue_if_busy=True,
            )
        except (KeyError, RuntimeError, ValueError):
            return

    @staticmethod
    def _matrix_device_tasks(campaign: Mapping[str, Any]) -> list[Json]:
        tasks = campaign.get("deviceTasks")
        if isinstance(tasks, list):
            return [dict(task) for task in tasks if isinstance(task, Mapping)]
        return [
            dict(task)
            for mission in campaign.get("missions", []) if isinstance(mission, Mapping)
            for task in mission.get("deviceTasks", []) if isinstance(task, Mapping)
        ]

    @staticmethod
    def _matrix_task_counts(tasks: list[Json]) -> Json:
        statuses = [str(task.get("status") or "queued") for task in tasks]
        return {
            "total": len(tasks),
            "queued": sum(status == "queued" for status in statuses),
            "running": sum(status in {"preflight", "running", "retrying"} for status in statuses),
            "completed": sum(status in {"succeeded", "completed"} for status in statuses),
            "failed": sum(status == "failed" for status in statuses),
            "needsHuman": sum(status == "needs_human" for status in statuses),
            "cancelled": sum(status == "cancelled" for status in statuses),
            "paused": sum(status == "paused" for status in statuses),
        }

    def _internal_operations(self) -> Json:
        return {
            "loom.capabilities.list": {
                "executor": self._connected_capability_catalog,
                "permission": "read",
                "risk": "read",
            },
            "loom.matrix.status": {"executor": self._matrix_status, "permission": "read", "risk": "read"},
            "loom.matrix.dispatch": {"executor": self._matrix_dispatch, "permission": "control", "risk": "control_safe", "timeoutSec": 180},
            "loom.matrix.screenshot": {"executor": self._matrix_screenshot, "permission": "read", "risk": "read", "timeoutSec": 60},
            "loom.matrix.cancel": {"executor": self._matrix_cancel, "permission": "control", "risk": "control_safe"},
            "loom.matrix.retry": {"executor": self._matrix_retry, "permission": "control", "risk": "control_safe", "timeoutSec": 180},
            "loom.logs.tail": {"executor": self._logs_tail, "permission": "read", "risk": "read"},
        }

    def _connected_capability_catalog(self, _payload: Json) -> Json:
        capabilities = self.capabilities.list_capabilities(available_only=True)
        domains: dict[str, list[str]] = {}
        for item in capabilities:
            if not isinstance(item, Mapping):
                continue
            domain = str(item.get("domain") or "general")
            display_name = str(item.get("displayName") or "").strip()
            if display_name:
                domains.setdefault(domain, []).append(display_name)
        return {
            "schema": "loom.agent.capability-catalog.v1",
            "count": len(capabilities),
            "domains": [
                {
                    "domain": domain,
                    "count": len(display_names),
                    "capabilities": display_names,
                }
                for domain, display_names in sorted(domains.items())
            ],
        }

    def _require_matrix_access(self) -> None:
        # Production always supplies the Bridge context. The context-free path
        # remains available for isolated service tests and embedded tooling.
        if self.context_factory is None:
            return
        try:
            context = self.context_factory()
        except Exception as exc:
            raise CapabilityExecutionError(
                "capability_unavailable",
                "手机矩阵授权校验服务尚未就绪",
            ) from exc
        protected_error = getattr(context, "protected_error", None)
        if not callable(protected_error):
            raise CapabilityExecutionError(
                "capability_unavailable",
                "手机矩阵授权校验服务尚未就绪",
            )
        if protected_error("/api/matrix/status"):
            raise CapabilityExecutionError(
                "LICENSE_FEATURE_REQUIRED",
                "请先在手机连接页激活手机矩阵授权",
                recoverable=False,
            )

    def _matrix_status(self, _payload: Json) -> Json:
        self._require_matrix_access()
        return self._matrix_factory().status()

    def _load_skill_instructions(self, skill_id: str, payload: Json) -> Json:
        document = self._skill_service.read_readme(skill_id)
        return {
            "skillId": skill_id,
            "instructions": str(document.get("content") or "")[:20_000],
            "requestedContext": sanitize_for_storage(payload),
        }

    def _matrix_dispatch(self, payload: Json) -> Json:
        self._require_matrix_access()
        body = self._matrix_confirmed_payload(payload)
        if "targets" in body and "target" not in body:
            body["target"] = body.pop("targets")
        matrix = self._matrix_factory()
        task = matrix.dispatch(body)
        job = self._start_matrix_job("matrix.dispatch", "Agent Matrix dispatch", matrix, task, body)
        return self._matrix_attachment(task, job)

    def _matrix_cancel(self, payload: Json) -> Json:
        self._require_matrix_access()
        campaign_id = str(payload.get("campaignId") or payload.get("id") or "").strip()
        if not campaign_id:
            raise ValueError("campaignId is required")
        if self.job_manager is not None:
            account_id, owner_binding = self._current_job_owner_identity()
            self.job_manager.cancel_matching(
                lambda job: (
                    self._matrix_job_visible_to_identity(
                        job,
                        account_id=account_id,
                        owner_binding=owner_binding,
                    )
                    and str(
                        (job.get("progress") or {}).get("campaignId") or ""
                    ) == campaign_id
                )
            )
        return self._matrix_factory().cancel(campaign_id)

    def _matrix_retry(self, payload: Json) -> Json:
        self._require_matrix_access()
        campaign_id = str(payload.get("campaignId") or payload.get("id") or "").strip()
        if not campaign_id:
            raise ValueError("campaignId is required")
        matrix = self._matrix_factory()
        body = self._matrix_confirmed_payload(payload)
        retry = matrix.retry_failed(campaign_id, body)
        if retry.get("retried") is not True:
            reason = str(retry.get("reason") or "当前矩阵任务没有可重试的失败项").strip()
            raise CapabilityExecutionError(
                "matrix_retry_not_started",
                f"未创建矩阵重试任务：{reason}",
                recoverable=True,
            )
        task = retry.get("task") if isinstance(retry.get("task"), dict) else None
        if not task:
            raise CapabilityExecutionError(
                "matrix_retry_result_invalid",
                "矩阵重试可能已经创建，但未返回可追踪的新任务",
                recoverable=False,
                outcome_indeterminate=True,
                execution_may_continue=True,
            )
        body = retry.get("dispatchBody") if isinstance(retry.get("dispatchBody"), dict) else body
        job = self._start_matrix_job("matrix.retry", "Agent Matrix retry", matrix, task, body)
        return self._matrix_attachment(task, job)

    def _matrix_confirmed_payload(self, payload: Mapping[str, Any]) -> Json:
        body = dict(payload)
        input_hash = _tool_input_hash(body)
        body.pop("confirmed", None)
        if self.policy.approval_mode == "weak":
            body["confirmed"] = True
            return body
        with self._lock:
            confirmation_tokens = self._matrix_confirmation_tokens.get(input_hash, [])
            if confirmation_tokens:
                confirmation_tokens.pop(0)
                body["confirmed"] = True
                if not confirmation_tokens:
                    self._matrix_confirmation_tokens.pop(input_hash, None)
        return body

    def _start_matrix_job(self, kind: str, title: str, matrix: MatrixControlPlane, task: Json, body: Json) -> Json | None:
        if self.job_manager is None or self.context_factory is None:
            return None
        from api.routes_matrix import _matrix_job_metadata, _run_matrix_campaign

        context = self.context_factory()
        job_metadata = _matrix_job_metadata(context, task)

        def run(job_id: str) -> Json:
            return _run_matrix_campaign(self.context_factory(), matrix, task, body, job_id)

        try:
            job = self.job_manager.submit_progress(
                kind,
                title,
                run,
                initial_progress={
                    "message": "Matrix task queued by central agent",
                    "phase": f"{kind}.queued",
                    "commandId": kind,
                    "campaignId": task.get("campaignId"),
                    **job_metadata,
                },
            )
        except Exception as exc:
            raise CapabilityExecutionError(
                "matrix_job_submission_unknown",
                "矩阵任务可能已经提交，但提交回执连接中断，任务可能仍在执行",
                recoverable=False,
                outcome_indeterminate=True,
                execution_may_continue=True,
            ) from exc
        job_id = str(job.get("id") or "").strip() if isinstance(job, Mapping) else ""
        if not job_id:
            raise CapabilityExecutionError(
                "matrix_job_submission_unknown",
                "矩阵任务已经提交，但未返回可追踪的任务编号，任务可能仍在执行",
                recoverable=False,
                outcome_indeterminate=True,
                execution_may_continue=True,
            )
        return job

    def _current_job_owner_identity(self) -> tuple[str, str]:
        if not callable(self.context_factory):
            return "", ""
        try:
            context = self.context_factory()
        except Exception:
            return "", ""
        return current_account_job_identity(context)

    @staticmethod
    def _matrix_job_visible_to_identity(
        job: dict,
        *,
        account_id: str,
        owner_binding: str,
    ) -> bool:
        return bool(
            str(job.get("kind") or "").startswith("matrix.")
            and job_visible_to_account(
                job,
                account_id=account_id,
                owner_binding=owner_binding,
            )
        )

    def _matrix_attachment(self, task: Json, job: Json | None) -> Json:
        rows = [
            item
            for mission in task.get("missions", []) if isinstance(mission, Mapping)
            for item in mission.get("deviceTasks", []) if isinstance(item, dict)
        ]
        counts = {
            "total": len(rows),
            "completed": sum(item.get("status") == "completed" for item in rows),
            "failed": sum(item.get("status") in {"failed", "needs_human"} for item in rows),
            "running": sum(item.get("status") in {"running", "queued", "retrying"} for item in rows),
        }
        return {
            "campaignId": str(task.get("campaignId") or ""),
            "jobId": str(job.get("id") or "") if isinstance(job, Mapping) else "",
            "status": str(task.get("status") or "queued"),
            "counts": counts,
            "deviceTasks": rows,
        }

    def _matrix_screenshot(self, payload: Json) -> Json:
        self._require_matrix_access()
        device_id = str(payload.get("deviceId") or "").strip()
        if not device_id or self.context_factory is None:
            raise ValueError("deviceId and an active Bridge context are required")
        from api.routes_matrix import _capture_matrix_screen

        return _capture_matrix_screen(self.context_factory(), device_id)

    def _logs_tail(self, payload: Json) -> Json:
        limit = max(1, min(int(payload.get("limit") or 100), 500))
        path = os.path.join(self.paths.data_dir, "logs", "bridge-service.log")
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                lines = handle.readlines()[-limit:]
        except OSError:
            lines = []
        return {"lines": redact_sensitive([line.rstrip() for line in lines]), "count": len(lines)}
