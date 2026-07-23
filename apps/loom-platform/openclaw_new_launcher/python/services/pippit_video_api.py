"""Pippit (小云雀) asynchronous video generation client.

The upstream API is conversation based rather than a single request/response
endpoint.  This client keeps a small launcher-owned run ledger so a retry can
poll the original paid run instead of accidentally submitting it twice.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import mimetypes
import os
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from contextlib import contextmanager
from typing import Callable


StatusCallback = Callable[[str, str], None]
DEFAULT_API_BASE = "https://xyq.jianying.com"
MAX_UPLOAD_BYTES = 200 * 1024 * 1024
MAX_DOWNLOAD_BYTES = 512 * 1024 * 1024
_STORE_LOCK = threading.RLock()


class PippitVideoError(RuntimeError):
    pass


class PippitSubmissionUncertain(PippitVideoError):
    pass


class PippitTransientError(PippitVideoError):
    pass


class PippitResumeRequired(PippitVideoError):
    def __init__(
        self,
        message: str,
        *,
        request_key: str,
        thread_id: str,
        run_id: str,
        web_thread_link: str = "",
    ) -> None:
        super().__init__(message)
        self.request_key = request_key
        self.thread_id = thread_id
        self.run_id = run_id
        self.web_thread_link = web_thread_link


class PippitManualRequired(PippitVideoError):
    def __init__(
        self,
        message: str,
        *,
        request_key: str,
        thread_id: str,
        run_id: str,
        web_thread_link: str = "",
        question: str = "",
    ) -> None:
        super().__init__(message)
        self.request_key = request_key
        self.thread_id = thread_id
        self.run_id = run_id
        self.web_thread_link = web_thread_link
        self.question = question or message


class PippitVideoClient:
    def generate(
        self,
        access_key: str,
        prompt: str,
        mode: str,
        resolution: str,
        duration: int,
        ratio: str,
        image_path: str | None = None,
        *,
        api_base: str = "",
        request_key: str = "",
        state_path: str = "",
        continuation_message: str = "",
        resume_existing: bool = False,
        poll_interval_ms: int | None = None,
        timeout_ms: int | None = None,
        on_status: StatusCallback | None = None,
    ) -> bytes:
        access_key = str(access_key or "").strip()
        if not access_key:
            raise PippitVideoError("小云雀 Access Key 不能为空")
        request_key = str(request_key or "").strip()
        if not request_key:
            raise PippitVideoError("小云雀任务缺少 request_key，已阻止重复计费风险")
        if not state_path:
            raise PippitVideoError("小云雀任务账本路径不能为空")

        api_base = self._normalize_base(api_base)
        poll_interval_ms = self._positive_int(
            poll_interval_ms,
            os.environ.get("XYQ_POLL_INTERVAL_MS"),
            default=10_000,
            minimum=0,
        )
        timeout_ms = self._positive_int(
            timeout_ms,
            os.environ.get("XYQ_JOB_TIMEOUT_MS"),
            default=1_200_000,
            minimum=1_000,
        )
        continuation_message = str(continuation_message or "").strip()

        state = self._read_run(state_path, request_key)
        if resume_existing and not (
            (state.get("threadId") and state.get("runId"))
            or (state.get("status") == "succeeded" and state.get("videoUrl"))
        ):
            raise PippitVideoError("没有可恢复的小云雀原任务，已禁止创建新任务")
        input_hash = "" if resume_existing else self._input_hash(
            prompt,
            mode,
            resolution,
            duration,
            ratio,
            image_path,
        )
        if (
            not resume_existing
            and not continuation_message
            and state.get("inputHash")
            and state.get("status") != "upload_failed"
            and state.get("inputHash") != input_hash
        ):
            raise PippitVideoError(
                "同一 request_key 的生成输入已变化，已阻止串用原付费任务。请新建任务。"
            )
        if state.get("status") == "succeeded" and state.get("videoUrl"):
            if on_status:
                on_status("正在恢复已完成的小云雀视频", "accent")
            try:
                return self._download_video(str(state["videoUrl"]))
            except PippitVideoError as error:
                raise self._resume_error(str(error), request_key, state) from error

        if continuation_message:
            state = self._continue_run(
                access_key,
                api_base,
                request_key,
                state_path,
                state,
                continuation_message,
                on_status,
            )
        elif state.get("threadId") and state.get("runId"):
            if on_status:
                on_status("正在恢复原小云雀任务，不会重复提交", "accent")
        else:
            if resume_existing:
                raise PippitVideoError("没有可恢复的小云雀原任务，已禁止创建新任务")
            if state.get("status") in {"submitting", "uncertain"}:
                raise PippitVideoError(
                    "小云雀上次提交结果尚不确定，已停止自动重提以避免重复计费。请打开任务页确认。"
                )
            if state.get("status") in {"failed", "cancelled"}:
                raise PippitVideoError(
                    "小云雀原任务已失败或终止，已禁止自动重建付费任务。请新建任务后再试。"
                )
            if not str(prompt or "").strip():
                raise PippitVideoError("视频提示词不能为空")
            state = self._create_run(
                access_key,
                api_base,
                request_key,
                state_path,
                prompt,
                mode,
                resolution,
                duration,
                ratio,
                image_path,
                input_hash,
                on_status,
            )

        return self._poll_and_download(
            access_key,
            api_base,
            request_key,
            state_path,
            state,
            poll_interval_ms,
            timeout_ms,
            on_status,
        )

    def _create_run(
        self,
        access_key: str,
        api_base: str,
        request_key: str,
        state_path: str,
        prompt: str,
        mode: str,
        resolution: str,
        duration: int,
        ratio: str,
        image_path: str | None,
        input_hash: str,
        on_status: StatusCallback | None,
    ) -> dict:
        operation_id = uuid.uuid4().hex
        now = time.time()
        initial_state = {
            "requestKey": request_key,
            "inputHash": input_hash,
            "status": "uploading" if image_path else "submitting",
            "operationId": operation_id,
            "leaseExpiresAt": now + 1_200 if image_path else 0,
            "createdAt": now,
            "updatedAt": now,
        }
        state, claimed = self._claim_initial_run(state_path, request_key, initial_state)
        if not claimed:
            if state.get("threadId") and state.get("runId"):
                return state
            raise PippitVideoError(
                "小云雀相同任务正在提交或结果尚不确定，已阻止重复创建。"
            )

        asset_ids: list[str] = []
        if image_path:
            if on_status:
                on_status("正在向小云雀上传参考素材", "neutral")
            try:
                asset_ids.append(self._upload_asset(access_key, api_base, image_path))
            except Exception:
                state.update({
                    "status": "upload_failed",
                    "leaseExpiresAt": 0,
                    "updatedAt": time.time(),
                })
                self._write_run(state_path, request_key, state)
                raise
            state.update({
                "assetIds": asset_ids,
                "status": "submitting",
                "leaseExpiresAt": 0,
                "updatedAt": time.time(),
            })
            self._write_run(state_path, request_key, state)

        if on_status:
            on_status("正在创建小云雀视频任务", "neutral")
        message = self._build_message(prompt, mode, resolution, duration, ratio)
        try:
            submitted = self._submit_run(
                access_key,
                api_base,
                message=message,
                asset_ids=asset_ids,
                request_key=request_key,
            )
        except Exception as error:
            state.update({
                "status": "uncertain" if isinstance(error, PippitSubmissionUncertain) else "failed",
                "updatedAt": time.time(),
            })
            self._write_run(state_path, request_key, state)
            raise

        state.update({
            "status": "submitted",
            "threadId": submitted["thread_id"],
            "runId": submitted["run_id"],
            "webThreadLink": submitted.get("web_thread_link", ""),
            "updatedAt": time.time(),
        })
        self._write_run(state_path, request_key, state)
        if on_status:
            on_status(f"小云雀任务已提交：{state['runId'][:8]}...", "accent")
        return state

    def _continue_run(
        self,
        access_key: str,
        api_base: str,
        request_key: str,
        state_path: str,
        state: dict,
        continuation_message: str,
        on_status: StatusCallback | None,
    ) -> dict:
        thread_id = str(state.get("threadId") or "").strip()
        if not thread_id:
            raise PippitVideoError("没有可继续的小云雀原会话，请重新创建视频任务")
        continuation_hash = hashlib.sha256(continuation_message.encode("utf-8")).hexdigest()
        state, claimed = self._claim_continuation(
            state_path,
            request_key,
            continuation_hash,
        )
        continuations = state.get("continuations") if isinstance(state.get("continuations"), dict) else {}
        prior = continuations.get(continuation_hash) if isinstance(continuations.get(continuation_hash), dict) else {}
        if prior.get("runId"):
            state.update({
                "status": "submitted",
                "runId": prior["runId"],
                "updatedAt": time.time(),
            })
            self._write_run(state_path, request_key, state)
            return state
        if not claimed:
            raise PippitVideoError(
                "小云雀相同补充内容正在提交或结果尚不确定，已阻止重复发送。"
            )
        if on_status:
            on_status("正在用原小云雀会话继续生成", "neutral")
        try:
            submitted = self._submit_run(
                access_key,
                api_base,
                message=continuation_message,
                thread_id=thread_id,
                request_key=f"{request_key}:{continuation_hash}",
            )
        except Exception as error:
            state.update({
                "status": "uncertain" if isinstance(error, PippitSubmissionUncertain) else "needs_manual",
                "continuationPendingHash": continuation_hash if isinstance(error, PippitSubmissionUncertain) else "",
                "updatedAt": time.time(),
            })
            self._write_run(state_path, request_key, state)
            raise

        continuations[continuation_hash] = {
            "runId": submitted["run_id"],
            "createdAt": time.time(),
        }
        state.update({
            "status": "submitted",
            "threadId": submitted.get("thread_id") or thread_id,
            "runId": submitted["run_id"],
            "webThreadLink": submitted.get("web_thread_link") or state.get("webThreadLink", ""),
            "continuations": continuations,
            "continuationPendingHash": "",
            "updatedAt": time.time(),
        })
        self._write_run(state_path, request_key, state)
        return state

    def _poll_and_download(
        self,
        access_key: str,
        api_base: str,
        request_key: str,
        state_path: str,
        state: dict,
        poll_interval_ms: int,
        timeout_ms: int,
        on_status: StatusCallback | None,
    ) -> bytes:
        thread_id = str(state.get("threadId") or "").strip()
        run_id = str(state.get("runId") or "").strip()
        if not thread_id or not run_id:
            raise PippitVideoError("小云雀没有返回 thread_id/run_id，无法安全查询任务")

        deadline = time.monotonic() + (timeout_ms / 1000)
        attempt = 0
        consecutive_query_failures = 0
        while time.monotonic() < deadline:
            try:
                payload = self._get_thread(access_key, api_base, thread_id, run_id)
                consecutive_query_failures = 0
            except PippitTransientError as error:
                consecutive_query_failures += 1
                state.update({"status": "running", "updatedAt": time.time()})
                self._write_run(state_path, request_key, state)
                if on_status:
                    on_status(
                        f"小云雀查询暂时失败，正在重试（{consecutive_query_failures}/3）",
                        "warning",
                    )
                if consecutive_query_failures >= 3:
                    raise self._resume_error(
                        "小云雀连续 3 次查询失败，原任务仍已保留，请继续原任务查询",
                        request_key,
                        state,
                    ) from error
                if poll_interval_ms:
                    time.sleep(poll_interval_ms / 1000)
                continue
            run = self._find_run(payload, run_id)
            if run:
                run_state = self._state_number(run.get("state"))
                if run_state == 3:
                    video_urls = self._extract_video_urls(run.get("entry_list") or run)
                    if not video_urls:
                        question = self._extract_manual_question(run)
                        if question:
                            state.update({
                                "status": "needs_manual",
                                "question": question,
                                "updatedAt": time.time(),
                            })
                            self._write_run(state_path, request_key, state)
                            raise PippitManualRequired(
                                "小云雀需要您补充信息后继续",
                                request_key=request_key,
                                thread_id=thread_id,
                                run_id=run_id,
                                web_thread_link=str(state.get("webThreadLink") or ""),
                                question=question,
                            )
                        state.update({"status": "failed", "updatedAt": time.time()})
                        self._write_run(state_path, request_key, state)
                        raise PippitVideoError("小云雀任务已完成，但没有发现可下载的视频")
                    video_url = video_urls[0]
                    state.update({
                        "status": "succeeded",
                        "videoUrl": video_url,
                        "updatedAt": time.time(),
                    })
                    self._write_run(state_path, request_key, state)
                    if on_status:
                        on_status("正在下载并校验小云雀视频", "accent")
                    try:
                        return self._download_video(video_url)
                    except PippitVideoError as error:
                        raise self._resume_error(str(error), request_key, state) from error
                if run_state in {4, 5}:
                    state.update({
                        "status": "failed" if run_state == 4 else "cancelled",
                        "updatedAt": time.time(),
                    })
                    self._write_run(state_path, request_key, state)
                    message = self._extract_error_message(run)
                    raise PippitVideoError(message or ("小云雀视频生成失败" if run_state == 4 else "小云雀任务已终止"))

                question = self._extract_manual_question(run)
                if question:
                    state.update({
                        "status": "needs_manual",
                        "question": question,
                        "updatedAt": time.time(),
                    })
                    self._write_run(state_path, request_key, state)
                    raise PippitManualRequired(
                        "小云雀需要您补充信息后继续",
                        request_key=request_key,
                        thread_id=thread_id,
                        run_id=run_id,
                        web_thread_link=str(state.get("webThreadLink") or ""),
                        question=question,
                    )

            attempt += 1
            state.update({"status": "running", "updatedAt": time.time()})
            self._write_run(state_path, request_key, state)
            if on_status:
                elapsed = max(0, int(attempt * poll_interval_ms / 1000))
                on_status(f"小云雀正在生成视频（已等待 {elapsed} 秒）", "accent")
            if poll_interval_ms:
                time.sleep(poll_interval_ms / 1000)

        state.update({"status": "running", "updatedAt": time.time()})
        self._write_run(state_path, request_key, state)
        raise self._resume_error(
            "小云雀本轮等待超时，原任务已保留；继续原任务只会查询，不会重复创建",
            request_key,
            state,
        )

    def _upload_asset(self, access_key: str, api_base: str, path: str) -> str:
        path = os.path.abspath(str(path or ""))
        if not os.path.isfile(path):
            raise PippitVideoError("小云雀参考素材不存在，请重新选择")
        size = os.path.getsize(path)
        if size > MAX_UPLOAD_BYTES:
            raise PippitVideoError("小云雀参考素材不能超过 200MB")
        with open(path, "rb") as handle:
            file_bytes = handle.read()

        boundary = f"----loom-pippit-{uuid.uuid4().hex}"
        mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
        if not mime.startswith(("image/", "video/")):
            raise PippitVideoError("小云雀参考素材仅支持图片或视频文件")
        filename = os.path.basename(path).replace('"', "")
        parts = [
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"accessKey\"\r\n\r\n{access_key}\r\n".encode("utf-8"),
            (
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\n"
                f"Content-Type: {mime}\r\n\r\n"
            ).encode("utf-8"),
            file_bytes,
            f"\r\n--{boundary}--\r\n".encode("ascii"),
        ]
        request = urllib.request.Request(
            f"{api_base}/api/biz/v1/skill/upload_file",
            data=b"".join(parts),
            headers={
                "Authorization": f"Bearer {access_key}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
        )
        data = self._read_envelope(request, timeout=180)
        asset_id = str(data.get("pippit_asset_id") or data.get("asset_id") or "").strip()
        if not asset_id:
            raise PippitVideoError("小云雀素材上传成功，但没有返回 asset_id")
        return asset_id

    def _submit_run(
        self,
        access_key: str,
        api_base: str,
        *,
        message: str,
        asset_ids: list[str] | None = None,
        thread_id: str = "",
        request_key: str = "",
    ) -> dict:
        body: dict = {"message": message}
        if asset_ids:
            body["asset_ids"] = asset_ids
        if thread_id:
            body["thread_id"] = thread_id
        data = self._post_json(
            access_key,
            f"{api_base}/api/biz/v1/skill/submit_run",
            body,
            idempotency_key=request_key,
            timeout=90,
            outcome_uncertain=True,
        )
        run = data.get("run") if isinstance(data.get("run"), dict) else {}
        returned_thread_id = str(run.get("thread_id") or thread_id or "").strip()
        run_id = str(run.get("run_id") or "").strip()
        if not returned_thread_id or not run_id:
            raise PippitSubmissionUncertain("小云雀没有返回 thread_id/run_id，任务状态不确定")
        return {
            "thread_id": returned_thread_id,
            "run_id": run_id,
            "web_thread_link": str(data.get("web_thread_link") or run.get("web_thread_link") or "").strip(),
        }

    def _get_thread(self, access_key: str, api_base: str, thread_id: str, run_id: str) -> dict:
        return self._post_json(
            access_key,
            f"{api_base}/api/biz/v1/skill/get_thread",
            {"thread_id": thread_id, "run_id": run_id, "after_seq": 0},
            timeout=60,
        )

    def _post_json(
        self,
        access_key: str,
        url: str,
        body: dict,
        *,
        idempotency_key: str = "",
        timeout: int = 60,
        outcome_uncertain: bool = False,
    ) -> dict:
        headers = {
            "Authorization": f"Bearer {access_key}",
            "Content-Type": "application/json",
        }
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        request = urllib.request.Request(
            url,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers=headers,
        )
        return self._read_envelope(
            request,
            timeout=timeout,
            outcome_uncertain=outcome_uncertain,
        )

    def _read_envelope(
        self,
        request: urllib.request.Request,
        *,
        timeout: int,
        outcome_uncertain: bool = False,
    ) -> dict:
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            try:
                payload = json.loads(error.read().decode("utf-8"))
                detail = self._public_message(payload)
            except Exception:
                detail = ""
            if outcome_uncertain and (error.code == 408 or error.code >= 500):
                raise PippitSubmissionUncertain(
                    f"HTTP {error.code}: {detail or '小云雀提交结果不确定'}"
                ) from error
            if not outcome_uncertain and (error.code == 408 or error.code >= 500):
                raise PippitTransientError(
                    f"HTTP {error.code}: {detail or '小云雀接口暂时不可用'}"
                ) from error
            raise PippitVideoError(f"HTTP {error.code}: {detail or '小云雀接口请求失败'}") from error
        except urllib.error.URLError as error:
            error_type = PippitSubmissionUncertain if outcome_uncertain else PippitTransientError
            raise error_type(f"小云雀网络请求失败：{error.reason}") from error
        except (UnicodeError, json.JSONDecodeError) as error:
            error_type = PippitSubmissionUncertain if outcome_uncertain else PippitTransientError
            raise error_type("小云雀返回了无法解析的响应") from error

        if not isinstance(payload, dict):
            raise PippitVideoError("小云雀返回格式不正确")
        if str(payload.get("ret")) != "0":
            raise PippitVideoError(self._public_message(payload) or "小云雀接口返回失败")
        data = payload.get("data")
        return data if isinstance(data, dict) else {}

    def _find_run(self, payload: dict, run_id: str) -> dict:
        thread = payload.get("thread") if isinstance(payload.get("thread"), dict) else {}
        if not thread and isinstance(payload.get("data"), dict):
            thread = payload["data"].get("thread") if isinstance(payload["data"].get("thread"), dict) else {}
        runs = thread.get("run_list") if isinstance(thread.get("run_list"), list) else []
        for run in runs:
            if isinstance(run, dict) and str(run.get("run_id") or "") == run_id:
                return run
        return {}

    def _extract_video_urls(self, value: object) -> list[str]:
        candidates: list[str] = []
        video_extensions = (".mp4", ".mov", ".m4v", ".webm", ".mkv")

        def visit(item: object, key_path: tuple[str, ...] = (), depth: int = 0) -> None:
            if depth > 12:
                return
            if isinstance(item, str):
                text = item.strip()
                if text.startswith(("{", "[")):
                    try:
                        visit(json.loads(text), key_path, depth + 1)
                    except (TypeError, ValueError, json.JSONDecodeError):
                        pass
                    return
                if not text.startswith("https://"):
                    return
                parsed = urllib.parse.urlsplit(text)
                lowered = parsed.path.lower()
                leaf_key = key_path[-1].lower() if key_path else ""
                is_preview = any(marker in leaf_key for marker in ("thumbnail", "poster", "cover", "preview"))
                is_video_field = any("video" in key.lower() for key in key_path) and leaf_key in {
                    "url",
                    "src",
                    "download_url",
                    "downloadurl",
                    "play_url",
                    "playurl",
                    "video_url",
                    "videourl",
                }
                if not is_preview and (
                    lowered.endswith(video_extensions) or "/video/" in lowered or is_video_field
                ):
                    candidates.append(text)
                return
            if isinstance(item, dict):
                mime = str(item.get("mime_type") or item.get("mimeType") or item.get("content_type") or "").lower()
                for key, child in item.items():
                    key_lower = str(key).lower()
                    is_preview = any(marker in key_lower for marker in ("thumbnail", "poster", "cover", "preview"))
                    if (
                        isinstance(child, str)
                        and mime.startswith("video/")
                        and child.startswith("https://")
                        and not is_preview
                    ):
                        candidates.append(child)
                    visit(child, (*key_path, str(key)), depth + 1)
                return
            if isinstance(item, list):
                for child in item:
                    visit(child, key_path, depth + 1)

        visit(value)
        seen: set[str] = set()
        result: list[str] = []
        for candidate in candidates:
            parsed = urllib.parse.urlsplit(candidate)
            identity = urllib.parse.urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path, "", ""))
            if identity in seen:
                continue
            seen.add(identity)
            result.append(candidate)
        return result

    def _extract_manual_question(self, run: dict) -> str:
        explicit_keys = {
            "question",
            "questions",
            "questionnaire",
            "need_user_input",
            "needs_user_input",
            "requires_input",
            "manual_required",
            "input_required",
        }

        def text_from(value: object, depth: int = 0) -> str:
            if depth > 8:
                return ""
            if isinstance(value, str):
                text = value.strip()
                if text.startswith(("{", "[")):
                    try:
                        return text_from(json.loads(text), depth + 1)
                    except (TypeError, ValueError, json.JSONDecodeError):
                        pass
                return text[:500]
            if isinstance(value, dict):
                for key in ("question", "title", "prompt", "message", "text", "content", "description"):
                    if key in value:
                        found = text_from(value[key], depth + 1)
                        if found:
                            return found
                for child in value.values():
                    found = text_from(child, depth + 1)
                    if found:
                        return found
            if isinstance(value, list):
                for child in value:
                    found = text_from(child, depth + 1)
                    if found:
                        return found
            return ""

        def find(value: object, depth: int = 0) -> str:
            if depth > 10:
                return ""
            if isinstance(value, dict):
                kind = str(value.get("type") or value.get("kind") or "").lower()
                if any(marker in kind for marker in ("question", "form", "user_input", "manual")):
                    found = text_from(value)
                    if found:
                        return found
                for raw_key, child in value.items():
                    key = str(raw_key).lower()
                    if key in explicit_keys and child not in (False, None, "", [], {}):
                        found = text_from(child) or text_from(value)
                        if found:
                            return found
                    found = find(child, depth + 1)
                    if found:
                        return found
            elif isinstance(value, list):
                for child in reversed(value):
                    found = find(child, depth + 1)
                    if found:
                        return found
            elif isinstance(value, str) and value.strip().startswith(("{", "[")):
                try:
                    return find(json.loads(value), depth + 1)
                except (TypeError, ValueError, json.JSONDecodeError):
                    return ""
            return ""

        return find(run.get("entry_list") or [])

    def _extract_error_message(self, run: dict) -> str:
        for key in ("error_message", "error", "message", "reason"):
            value = run.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()[:500]
            if isinstance(value, dict):
                message = value.get("message")
                if isinstance(message, str) and message.strip():
                    return message.strip()[:500]
        return ""

    def _download_video(self, video_url: str) -> bytes:
        self._validate_download_url(video_url)
        request = urllib.request.Request(video_url, headers={"User-Agent": "LOOM/1.0"})
        try:
            with urllib.request.urlopen(request, timeout=240) as response:
                content_length = str(response.headers.get("Content-Length", "")).strip()
                if content_length:
                    try:
                        if int(content_length) > MAX_DOWNLOAD_BYTES:
                            raise PippitVideoError("小云雀返回的视频超过 512MB，已停止下载")
                    except ValueError:
                        pass
                data = response.read(MAX_DOWNLOAD_BYTES + 1)
        except urllib.error.HTTPError as error:
            raise PippitVideoError(f"HTTP {error.code}: 小云雀视频下载失败") from error
        except urllib.error.URLError as error:
            raise PippitVideoError(f"小云雀视频下载失败：{error.reason}") from error
        if not data:
            raise PippitVideoError("小云雀视频下载结果为空")
        if len(data) > MAX_DOWNLOAD_BYTES:
            raise PippitVideoError("小云雀返回的视频超过 512MB，已停止下载")
        head = data[:128]
        valid = b"ftyp" in head or head.startswith(b"\x1aE\xdf\xa3")
        if not valid:
            raise PippitVideoError("小云雀返回的文件不是可播放视频")
        return data

    def _validate_download_url(self, video_url: str) -> None:
        parsed = urllib.parse.urlsplit(str(video_url or "").strip())
        hostname = (parsed.hostname or "").lower().rstrip(".")
        if (
            parsed.scheme.lower() != "https"
            or not hostname
            or parsed.username
            or parsed.password
            or hostname == "localhost"
            or hostname.endswith((".localhost", ".local"))
        ):
            raise PippitVideoError("小云雀返回了不安全的视频下载地址")
        try:
            address = ipaddress.ip_address(hostname)
        except ValueError:
            return
        if not address.is_global:
            raise PippitVideoError("小云雀返回了不安全的视频下载地址")

    def _read_run(self, state_path: str, request_key: str) -> dict:
        with self._store_guard(state_path):
            store = self._read_store(state_path)
            value = store.get("runs", {}).get(request_key)
            return dict(value) if isinstance(value, dict) else {}

    def _write_run(self, state_path: str, request_key: str, state: dict) -> None:
        with self._store_guard(state_path):
            store = self._read_store(state_path)
            runs = store.get("runs") if isinstance(store.get("runs"), dict) else {}
            runs[request_key] = dict(state)
            self._write_store(state_path, {
                "schemaVersion": 1,
                "updatedAt": time.time(),
                "runs": runs,
            })

    def _claim_initial_run(
        self,
        state_path: str,
        request_key: str,
        initial_state: dict,
    ) -> tuple[dict, bool]:
        with self._store_guard(state_path):
            store = self._read_store(state_path)
            runs = store.get("runs") if isinstance(store.get("runs"), dict) else {}
            existing = runs.get(request_key)
            if isinstance(existing, dict):
                existing_status = str(existing.get("status") or "")
                lease_expired = (
                    existing_status == "uploading"
                    and float(existing.get("leaseExpiresAt") or 0) > 0
                    and float(existing.get("leaseExpiresAt") or 0) <= time.time()
                )
                if existing_status != "upload_failed" and not lease_expired:
                    return dict(existing), False
            runs[request_key] = dict(initial_state)
            self._write_store(state_path, {
                "schemaVersion": 1,
                "updatedAt": time.time(),
                "runs": runs,
            })
            return dict(initial_state), True

    def _claim_continuation(
        self,
        state_path: str,
        request_key: str,
        continuation_hash: str,
    ) -> tuple[dict, bool]:
        with self._store_guard(state_path):
            store = self._read_store(state_path)
            runs = store.get("runs") if isinstance(store.get("runs"), dict) else {}
            state = runs.get(request_key)
            if not isinstance(state, dict):
                raise PippitVideoError("没有可继续的小云雀原任务")
            state = dict(state)
            continuations = state.get("continuations") if isinstance(state.get("continuations"), dict) else {}
            prior = continuations.get(continuation_hash)
            if isinstance(prior, dict) and prior.get("runId"):
                return state, False
            if state.get("continuationPendingHash"):
                return state, False
            state.update({
                "status": "submitting",
                "continuationPendingHash": continuation_hash,
                "updatedAt": time.time(),
            })
            runs[request_key] = state
            self._write_store(state_path, {
                "schemaVersion": 1,
                "updatedAt": time.time(),
                "runs": runs,
            })
            return state, True

    @contextmanager
    def _store_guard(self, state_path: str):
        directory = os.path.dirname(state_path) or "."
        os.makedirs(directory, exist_ok=True)
        lock_path = f"{state_path}.lock"
        with _STORE_LOCK:
            with open(lock_path, "a+b") as lock_handle:
                lock_handle.seek(0, os.SEEK_END)
                if lock_handle.tell() == 0:
                    lock_handle.write(b"\0")
                    lock_handle.flush()
                lock_handle.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(lock_handle.fileno(), msvcrt.LK_LOCK, 1)
                else:
                    import fcntl

                    fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    lock_handle.seek(0)
                    if os.name == "nt":
                        msvcrt.locking(lock_handle.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)

    def _write_store(self, state_path: str, payload: dict) -> None:
        directory = os.path.dirname(state_path) or "."
        os.makedirs(directory, exist_ok=True)
        fd, temp_path = tempfile.mkstemp(prefix=".pippit-runs-", suffix=".tmp", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, state_path)
        finally:
            try:
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
            except OSError:
                pass

    def _read_store(self, state_path: str) -> dict:
        if not os.path.exists(state_path):
            return {"schemaVersion": 1, "runs": {}}
        try:
            with open(state_path, "r", encoding="utf-8-sig") as handle:
                payload = json.load(handle)
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise PippitVideoError("小云雀任务账本损坏，已停止自动提交以避免重复计费") from error
        if not isinstance(payload, dict) or not isinstance(payload.get("runs"), dict):
            raise PippitVideoError("小云雀任务账本格式异常，已停止自动提交以避免重复计费")
        return payload

    def _build_message(self, prompt: str, mode: str, resolution: str, duration: int, ratio: str) -> str:
        return str(prompt or "").strip()

    def _input_hash(
        self,
        prompt: str,
        mode: str,
        resolution: str,
        duration: int,
        ratio: str,
        image_path: str | None,
    ) -> str:
        image_identity: dict[str, object] | None = None
        if image_path:
            normalized = os.path.abspath(str(image_path))
            image_identity = {}
            try:
                digest = hashlib.sha256()
                size = 0
                with open(normalized, "rb") as handle:
                    while True:
                        chunk = handle.read(1024 * 1024)
                        if not chunk:
                            break
                        digest.update(chunk)
                        size += len(chunk)
                image_identity.update({"sha256": digest.hexdigest(), "size": size})
            except OSError:
                image_identity["path"] = os.path.normcase(normalized)
        payload = {
            "prompt": str(prompt or "").strip(),
            "mode": str(mode or "").strip().lower(),
            "resolution": str(resolution or "").strip().upper(),
            "duration": max(1, int(duration)),
            "ratio": str(ratio or "").strip(),
            "image": image_identity,
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def _resume_error(self, message: str, request_key: str, state: dict) -> PippitResumeRequired:
        return PippitResumeRequired(
            message,
            request_key=request_key,
            thread_id=str(state.get("threadId") or ""),
            run_id=str(state.get("runId") or ""),
            web_thread_link=str(state.get("webThreadLink") or ""),
        )

    def _normalize_base(self, api_base: str) -> str:
        base = str(api_base or DEFAULT_API_BASE).strip().rstrip("/") or DEFAULT_API_BASE
        parsed = urllib.parse.urlsplit(base)
        if (
            parsed.scheme.lower() != "https"
            or parsed.netloc.lower() != "xyq.jianying.com"
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
        ):
            raise PippitVideoError("小云雀仅允许使用官方接口地址 https://xyq.jianying.com")
        return DEFAULT_API_BASE

    def _state_number(self, value: object) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return -1

    def _positive_int(self, explicit: object, environment: object, *, default: int, minimum: int) -> int:
        for value in (explicit, environment):
            if value in (None, ""):
                continue
            try:
                return max(minimum, int(value))
            except (TypeError, ValueError):
                continue
        return default

    def _public_message(self, payload: dict) -> str:
        for key in ("message", "msg", "error_message"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()[:500]
        error = payload.get("error")
        if isinstance(error, str):
            return error.strip()[:500]
        if isinstance(error, dict) and isinstance(error.get("message"), str):
            return error["message"].strip()[:500]
        return ""
