"""First-party capability adapters for the native LOOM agent."""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from typing import Any, Callable

from core.agent_capabilities import (
    MEDIA_IMAGE_INPUT_SCHEMA,
    MEDIA_JOB_OUTPUT_SCHEMA,
    MEDIA_VIDEO_INPUT_SCHEMA,
    PHONE_PUBLISH_INPUT_SCHEMA,
    CapabilityExecutionError,
)


Json = dict[str, Any]


def _media_attachments(kind: str, result: Json) -> list[Json]:
    candidates = result.get("files") if isinstance(result.get("files"), list) else []
    if kind == "video" and not candidates and result.get("path"):
        candidates = [result]
    attachments: list[Json] = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "").strip()
        if not path:
            continue
        attachment: Json = {
            "name": str(item.get("filename") or os.path.basename(path) or f"loom-{kind}"),
            "path": path,
            "mime": str(item.get("mime") or ("video/mp4" if kind == "video" else "image/png")),
            "kind": kind,
        }
        if isinstance(item.get("size"), int):
            attachment["size"] = item["size"]
        attachments.append(attachment)
    return attachments


class AgentBuiltinCapabilityProvider:
    def __init__(
        self,
        *,
        context_factory: Callable[[], Any] | None,
        job_manager: Any | None,
        matrix_factory: Callable[[], Any],
    ) -> None:
        self.context_factory = context_factory
        self.job_manager = job_manager
        self.matrix_factory = matrix_factory

    def operations(self) -> dict[str, Json]:
        connected = callable(self.context_factory) and callable(
            getattr(self.job_manager, "submit_progress", None)
        )
        return {
            "loom.media.image.generate": {
                "executor": (
                    lambda payload, cancellation_token=None: self._submit_media(
                        "image",
                        payload,
                        cancellation_token=cancellation_token,
                    )
                ) if connected else None,
                "displayName": "生成图片",
                "description": "根据文字提示生成或编辑图片，并保存到麓鸣媒体库",
                "domain": "media",
                "targetScope": "optional-device-write",
                "permission": "control",
                "risk": "control_safe",
                "timeoutSec": 600,
                "inputSchema": MEDIA_IMAGE_INPUT_SCHEMA,
                "outputSchema": MEDIA_JOB_OUTPUT_SCHEMA,
            },
            "loom.media.video.generate": {
                "executor": (
                    lambda payload, cancellation_token=None: self._submit_media(
                        "video",
                        payload,
                        cancellation_token=cancellation_token,
                    )
                ) if connected else None,
                "displayName": "生成视频",
                "description": "根据文字或参考图片提交视频生成任务，并保存到麓鸣媒体库",
                "domain": "media",
                "targetScope": "optional-device-write",
                "permission": "control",
                "risk": "control_safe",
                "timeoutSec": 1800,
                "inputSchema": MEDIA_VIDEO_INPUT_SCHEMA,
                "outputSchema": MEDIA_JOB_OUTPUT_SCHEMA,
            },
            "loom.phone.publish": {
                "executor": self._submit_phone_publish if connected else None,
                "displayName": "手机自动发布",
                "description": "把指定媒体上传到目标手机平台；支持独立的 title、body、notes、mediaPaths、deviceId 和 draftOnly 字段，默认只保存草稿，正式发布需要单次确认",
                "domain": "phone",
                "targetScope": "single-device-write",
                "permission": "control",
                "risk": "outbound",
                "timeoutSec": 690,
                "inputSchema": PHONE_PUBLISH_INPUT_SCHEMA,
                "outputSchema": MEDIA_JOB_OUTPUT_SCHEMA,
            },
        }

    def _submit_media(
        self,
        kind: str,
        payload: Json,
        *,
        cancellation_token: Any | None = None,
    ) -> Json:
        if not callable(self.context_factory) or not callable(
            getattr(self.job_manager, "submit_progress", None)
        ):
            raise CapabilityExecutionError(
                "capability_unavailable",
                "媒体生成服务尚未就绪",
            )

        try:
            context = self.context_factory()
        except Exception as exc:
            raise CapabilityExecutionError(
                "capability_unavailable",
                "媒体生成服务尚未就绪",
            ) from exc

        protected_error = getattr(context, "protected_error", None)
        if not callable(protected_error):
            raise CapabilityExecutionError(
                "capability_unavailable",
                "媒体授权校验服务尚未就绪",
            )
        protected_path = (
            "/api/image/generate" if kind == "image" else "/api/video/generate"
        )
        if protected_error(protected_path):
            raise CapabilityExecutionError(
                "LICENSE_FEATURE_REQUIRED",
                "当前商业授权未开通此功能",
                recoverable=False,
            )

        from api.routes_media import (
            _async_media_job_result,
            _configured_phone_snapshot,
            _image_generate_payload,
            _video_generation_failure,
            _video_generate_payload,
        )
        from services.pippit_video_api import PippitManualRequired
        from services.video_api import VideoApiError

        requested_device_ids = [
            str(value).strip()
            for value in payload.get("deviceIds", [])
            if str(value).strip()
        ] if isinstance(payload.get("deviceIds"), list) else []
        requested_groups = [
            str(value).strip()
            for value in payload.get("groups", [])
            if str(value).strip()
        ] if isinstance(payload.get("groups"), list) else []
        all_online = payload.get("allOnline") is True
        target_selector_present = bool(requested_device_ids or requested_groups or all_online)
        if requested_groups or all_online:
            requested_device_ids = self._resolve_media_target_device_ids(
                requested_groups,
                all_online=all_online,
            )
        body = {
            **{
                key: value
                for key, value in payload.items()
                if key not in {"deviceIds", "groups", "allOnline"}
            },
            "source": str(payload.get("source") or "agent"),
        }
        phone_snapshot = _configured_phone_snapshot(
            context,
            requested_device_ids if target_selector_present else None,
        )

        def ensure_job_active(job_id: str) -> None:
            is_cancelled = getattr(self.job_manager, "is_cancelled", None)
            if callable(is_cancelled) and is_cancelled(job_id):
                raise CapabilityExecutionError("capability_cancelled", "媒体生成任务已取消")

        def update_progress(
            job_id: str,
            message: str,
            tone: str = "neutral",
            **details: Any,
        ) -> None:
            ensure_job_active(job_id)
            progress = getattr(self.job_manager, "progress", None)
            if callable(progress):
                progress(job_id, message, tone, **details)

        def target(job_id: str) -> Json:
            ensure_job_active(job_id)
            if kind == "image":
                update_progress(job_id, "正在生成图片")
                generated = _image_generate_payload(context, body)
            else:
                update_progress(job_id, "正在提交视频任务", phase="submitting")
                try:
                    generated = _video_generate_payload(
                        context,
                        body,
                        on_status=lambda message, tone="neutral": update_progress(
                            job_id,
                            message,
                            tone,
                            phase="generating",
                        ),
                        request_key=str(body.get("requestKey") or job_id),
                    )
                except (VideoApiError, PippitManualRequired, ValueError) as exc:
                    return _video_generation_failure(exc)
            ensure_job_active(job_id)
            update_progress(job_id, "正在传送到已配置手机相册", phase="phone-transfer")
            return _async_media_job_result(
                context,
                kind,
                generated,
                phone_snapshot=phone_snapshot,
            )

        label = "图片生成" if kind == "image" else "视频生成"
        job = self.job_manager.submit_progress(kind, label, target)
        job_id = str(job.get("id") or "") if isinstance(job, dict) else ""
        if not job_id:
            raise CapabilityExecutionError(
                "capability_failed",
                "媒体任务创建失败",
            )
        terminal = self._wait_for_media_job(
            job_id,
            kind=kind,
            cancellation_token=cancellation_token,
        )
        result = terminal.get("result") if isinstance(terminal.get("result"), dict) else {}
        if terminal.get("status") == "needs_manual":
            return {
                "jobId": job_id,
                "kind": kind,
                "status": "needs_manual",
                "result": result,
                "manualRequired": True,
                "question": result.get("question"),
                "requestKey": result.get("requestKey"),
                "webThreadLink": result.get("webThreadLink"),
                "attachments": [],
            }
        if terminal.get("status") == "cancelled":
            raise CapabilityExecutionError("capability_cancelled", "媒体生成任务已取消")
        if terminal.get("status") != "succeeded" or result.get("success") is False:
            failure = terminal.get("failure") if isinstance(terminal.get("failure"), dict) else {}
            code = str(result.get("errorCode") or failure.get("code") or "media_job_failed")
            message = str(
                terminal.get("error")
                or result.get("error")
                or result.get("message")
                or "媒体生成任务失败"
            )
            raise CapabilityExecutionError(
                code,
                message,
                recoverable=bool(failure.get("retryable", True)),
            )
        return {
            "jobId": job_id,
            "kind": kind,
            "status": "succeeded",
            "result": result,
            "attachments": _media_attachments(kind, result),
            "phoneTransfer": result.get("phoneTransfer") if isinstance(result.get("phoneTransfer"), dict) else None,
        }

    def _resolve_media_target_device_ids(
        self,
        groups: list[str],
        *,
        all_online: bool,
    ) -> list[str]:
        try:
            matrix = self.matrix_factory()
            status = matrix.status()
        except Exception:
            return []
        devices = status.get("devices") if isinstance(status, dict) else []
        requested_groups = set(groups)
        resolved: list[str] = []
        for item in devices if isinstance(devices, list) else []:
            if not isinstance(item, dict):
                continue
            device_id = str(item.get("deviceId") or item.get("id") or "").strip()
            if not device_id:
                continue
            raw_groups = item.get("groups") if isinstance(item.get("groups"), list) else []
            item_groups = {
                str(value or "").strip()
                for value in [item.get("group"), *raw_groups]
                if str(value or "").strip()
            }
            selected = item.get("online") is True if all_online else bool(item_groups & requested_groups)
            if selected and device_id not in resolved:
                resolved.append(device_id)
        return resolved

    def _wait_for_media_job(
        self,
        job_id: str,
        *,
        kind: str,
        cancellation_token: Any | None = None,
    ) -> Json:
        get_job = getattr(self.job_manager, "get", None)
        if not callable(get_job):
            raise CapabilityExecutionError("capability_unavailable", "媒体任务状态服务尚未就绪")
        wait_seconds = 570 if kind == "image" else 1770
        deadline = time.monotonic() + wait_seconds
        while time.monotonic() < deadline:
            if cancellation_token is not None and bool(getattr(cancellation_token, "cancelled", False)):
                cancel = getattr(self.job_manager, "cancel", None)
                if callable(cancel):
                    cancel(job_id)
                raise CapabilityExecutionError("capability_cancelled", "媒体生成任务已取消")
            job = get_job(job_id)
            if isinstance(job, dict) and str(job.get("status") or "") in {"succeeded", "failed", "cancelled", "needs_manual"}:
                return job
            token_wait = getattr(cancellation_token, "wait", None)
            if callable(token_wait):
                token_wait(0.1)
            else:
                time.sleep(0.1)
        cancel = getattr(self.job_manager, "cancel", None)
        if callable(cancel):
            cancel(job_id)
        raise CapabilityExecutionError("media_job_timeout", "媒体生成任务执行超时")

    def _submit_phone_publish(self, payload: Json, *, cancellation_token: Any | None = None) -> Json:
        if not callable(self.context_factory) or not callable(
            getattr(self.job_manager, "submit_progress", None)
        ):
            raise CapabilityExecutionError(
                "capability_unavailable",
                "手机发布服务尚未就绪",
            )

        try:
            context = self.context_factory()
        except Exception as exc:
            raise CapabilityExecutionError(
                "capability_unavailable",
                "手机发布服务尚未就绪",
            ) from exc

        protected_error = getattr(context, "protected_error", None)
        if not callable(protected_error):
            raise CapabilityExecutionError(
                "capability_unavailable",
                "手机发布授权校验服务尚未就绪",
            )
        if protected_error("/api/phone/publish"):
            raise CapabilityExecutionError(
                "LICENSE_FEATURE_REQUIRED",
                "当前商业授权未开通此功能",
                recoverable=False,
            )

        media_paths = [
            os.path.abspath(str(item).strip())
            for item in payload.get("mediaPaths", [])
            if str(item).strip()
        ]
        missing = [path for path in media_paths if not os.path.isfile(path)]
        if not media_paths or missing:
            raise CapabilityExecutionError(
                "publish_media_missing",
                "发布素材不存在，请先生成或选择本地媒体文件",
                recoverable=False,
            )

        normalized = {
            **payload,
            "mediaPaths": media_paths,
            "draftOnly": bool(payload.get("draftOnly", True)),
        }

        def target(job_id: str) -> Json:
            progress = getattr(self.job_manager, "progress", None)
            if callable(progress):
                progress(job_id, "正在上传素材并执行手机发布流程", "neutral", phase="publishing")
            return run_phone_publish(context, normalized)

        label = "手机发布草稿" if normalized["draftOnly"] else "手机自动发布"
        job = self.job_manager.submit_progress("publish", label, target)
        job_id = str(job.get("id") or "") if isinstance(job, dict) else ""
        if not job_id:
            raise CapabilityExecutionError("capability_failed", "手机发布任务创建失败")
        terminal = self._wait_for_publish_job(job_id, cancellation_token=cancellation_token)
        result = terminal.get("result") if isinstance(terminal.get("result"), dict) else {}
        if terminal.get("status") != "succeeded" or result.get("success") is False:
            failure = terminal.get("failure") if isinstance(terminal.get("failure"), dict) else {}
            code = str(result.get("errorCode") or failure.get("code") or "phone_publish_failed")
            message = str(
                terminal.get("error")
                or result.get("error")
                or result.get("message")
                or "手机发布任务失败"
            )
            raise CapabilityExecutionError(
                code,
                message,
                recoverable=bool(failure.get("retryable", True)),
            )
        return {
            "jobId": job_id,
            "kind": "publish",
            "status": "succeeded",
            "result": result,
        }

    def _wait_for_publish_job(self, job_id: str, *, cancellation_token: Any | None = None) -> Json:
        get_job = getattr(self.job_manager, "get", None)
        if not callable(get_job):
            raise CapabilityExecutionError("capability_unavailable", "手机发布任务状态服务尚未就绪")
        deadline = time.monotonic() + 675
        while time.monotonic() < deadline:
            if cancellation_token is not None and bool(getattr(cancellation_token, "cancelled", False)):
                cancel = getattr(self.job_manager, "cancel", None)
                if callable(cancel):
                    cancel(job_id)
                raise CapabilityExecutionError("capability_cancelled", "手机发布任务已取消")
            job = get_job(job_id)
            if isinstance(job, dict) and str(job.get("status") or "") in {"succeeded", "failed", "cancelled"}:
                return job
            time.sleep(0.1)
        cancel = getattr(self.job_manager, "cancel", None)
        if callable(cancel):
            cancel(job_id)
        raise CapabilityExecutionError("publish_job_timeout", "手机发布任务执行超时")


def run_phone_publish(context: Any, payload: Json) -> Json:
    from api.routes_cli import _script_path
    from api.routes_phone import phone_process_env

    script_path = _script_path(context, "openclaw-publish-phone.mjs")
    node_exe = str(getattr(context.paths, "node_exe", "") or "")
    if not os.path.isfile(script_path):
        return {"success": False, "errorCode": "publish_script_missing", "error": "手机发布执行器缺失"}
    if not os.path.isfile(node_exe):
        return {"success": False, "errorCode": "node_runtime_missing", "error": "Node.js 运行时缺失"}

    args = [
        node_exe,
        script_path,
        "--platform",
        str(payload.get("platform") or "douyin"),
        "--timeout-sec",
        "600",
        "--max-wait-sec",
        "615",
        "--max-rounds",
        "60",
        "--json",
    ]
    for key, option in (
        ("title", "--title"),
        ("body", "--body"),
        ("hashtags", "--hashtags"),
        ("notes", "--notes"),
    ):
        value = str(payload.get(key) or "").strip()
        if value:
            args.extend([option, value])
    if str(payload.get("deviceId") or "").strip():
        args.extend(["--device-id", str(payload["deviceId"]).strip()])
    args.append("--draft-only" if payload.get("draftOnly", True) else "--commit")
    for media_path in payload.get("mediaPaths", []):
        args.extend(["--file", str(media_path)])

    try:
        completed = subprocess.run(
            args,
            cwd=context.paths.base_path,
            env=phone_process_env(context),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=660,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired:
        return {"success": False, "errorCode": "publish_timeout", "error": "手机发布任务执行超时"}

    try:
        result = json.loads((completed.stdout or "").strip())
    except (TypeError, ValueError, json.JSONDecodeError):
        result = {}
    semantic_error = _publish_business_failure(result.get("answer"))
    if semantic_error:
        return {
            "success": False,
            "errorCode": "phone_publish_semantic_failure",
            "error": semantic_error,
            "status": "error",
            "answer": str(result.get("answer") or ""),
        }
    if completed.returncode != 0:
        return {
            "success": False,
            "errorCode": str(result.get("errorCode") or "phone_publish_failed"),
            "error": str(result.get("error") or "手机发布任务失败，详情已写入运行日志"),
            "status": str(result.get("status") or "error"),
        }
    if result.get("success") is False or str(result.get("status") or "").lower() in {"error", "failed", "cancelled"}:
        return {
            "success": False,
            "errorCode": str(result.get("errorCode") or "phone_publish_failed"),
            "error": str(result.get("error") or "手机发布任务失败，详情已写入运行日志"),
            "status": str(result.get("status") or "error"),
        }
    return {"success": True, **result}


def _publish_business_failure(answer: Any) -> str:
    text = str(answer or "").strip()
    if not text:
        return ""
    patterns = (
        r"(?m)^\s*(?:Task completed:\s*)?任务(?:执行)?(?:受阻|阻塞)(?:\s|[：:，,。-]|$)",
        r"(?m)^\s*(?:Task completed:\s*)?任务\s+blocked\b",
        r"任务无法完成",
        r"任务未能完成",
        r"无法完成任务",
        r"(?:发布|保存草稿)(?:失败|未完成)",
        r"(?:当前)?未登录[^\n]*(?:发布|草稿)",
        r"(?:需要|请)先登录[^\n]*(?:发布|草稿)",
        r"\b(?:cannot|unable to|failed to)\s+(?:complete|publish|save)\b",
        r"\b(?:not logged in|login required)\b",
    )
    return text[:1000] if any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns) else ""
