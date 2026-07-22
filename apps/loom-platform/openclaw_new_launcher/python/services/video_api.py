"""DashScope video generation client."""

from __future__ import annotations

import base64
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable

from core.constants import DASHSCOPE_TASK_URL, DASHSCOPE_VIDEO_URL, VIDEO_MODEL_I2V, VIDEO_MODEL_T2V
from services.pippit_video_api import PippitManualRequired, PippitVideoClient, PippitVideoError

StatusCallback = Callable[[str, str], None]


class VideoApiError(RuntimeError):
    pass


def _http_error_message(error: urllib.error.HTTPError) -> str:
    try:
        body = error.read().decode("utf-8")
        data = json.loads(body)
        detail = data.get("message") or data.get("error", {}).get("message") or ""
        return f"HTTP {error.code}: {detail}" if detail else f"HTTP {error.code}"
    except Exception:
        return f"HTTP {error.code}"


def _api_error_message(data: dict, fallback: str) -> str:
    message = data.get("message")
    if isinstance(message, str) and message:
        return message
    error = data.get("error")
    if isinstance(error, dict):
        message = error.get("message")
        if isinstance(message, str) and message:
            return message
    if isinstance(error, str) and error:
        return error
    return fallback


class DashScopeVideoClient:
    def generate(
        self,
        dash_key: str,
        prompt: str,
        mode: str,
        resolution: str,
        duration: int,
        ratio: str,
        image_path: str | None = None,
        provider_id: str = "dashscope",
        api_base: str = "",
        model: str = "",
        on_status: StatusCallback | None = None,
        request_key: str = "",
        state_path: str = "",
        continuation_message: str = "",
        poll_interval_ms: int | None = None,
        timeout_ms: int | None = None,
    ) -> bytes:
        try:
            provider_id = (provider_id or "dashscope").strip().lower()
            if provider_id in ("pippit", "xyq", "xiaoyunque", "小云雀"):
                return PippitVideoClient().generate(
                    dash_key,
                    prompt,
                    mode,
                    resolution,
                    duration,
                    ratio,
                    image_path,
                    api_base=api_base,
                    request_key=request_key,
                    state_path=state_path,
                    continuation_message=continuation_message,
                    poll_interval_ms=poll_interval_ms,
                    timeout_ms=timeout_ms,
                    on_status=on_status,
                )
            if provider_id == "agnes" or "agnes-video" in (model or "").strip().lower():
                return self._generate_agnes_compatible(
                    dash_key, prompt, mode, resolution, duration, ratio, image_path,
                    api_base=api_base, model=model, on_status=on_status
                )
            if provider_id in ("seedance", "custom"):
                return self._generate_seedance_compatible(
                    dash_key, prompt, mode, resolution, duration, ratio, image_path,
                    api_base=api_base, model=model, on_status=on_status
                )

            submit_url, task_url = self._dashscope_urls(api_base)
            body = self._build_dashscope_body(prompt, mode, resolution, duration, ratio, image_path, model)
            task_id = self._submit_dashscope_task(dash_key, body, submit_url)
            if on_status:
                on_status(f"任务已提交：{task_id[:8]}...，等待生成", "accent")
            return self._poll_dashscope_and_download(dash_key, task_id, on_status, task_url)
        except PippitManualRequired:
            raise
        except PippitVideoError as error:
            raise VideoApiError(str(error)) from error
        except VideoApiError:
            raise
        except urllib.error.HTTPError as error:
            raise VideoApiError(_http_error_message(error)) from error
        except Exception as error:
            raise VideoApiError(str(error)) from error

    def _generate_agnes_compatible(
        self,
        api_key: str,
        prompt: str,
        mode: str,
        resolution: str,
        duration: int,
        ratio: str,
        image_path: str | None,
        api_base: str,
        model: str,
        on_status: StatusCallback | None,
    ) -> bytes:
        model = (model or "agnes-video-v2.0").strip()
        if mode == "i2v" and not image_path:
            raise VideoApiError("图生视频需要上传参考图")

        submit_url, result_root = self._agnes_urls(api_base)
        body = self._build_agnes_body(
            prompt, mode, resolution, duration, ratio, image_path, model
        )
        task_id, video_id = self._submit_agnes_task(api_key, submit_url, body)
        if on_status:
            on_status(f"Agnes 任务已提交：{(video_id or task_id)[:8]}...，等待生成", "accent")
        return self._poll_agnes_and_download(
            api_key,
            result_root,
            submit_url,
            task_id,
            video_id,
            model,
            on_status,
        )

    def _agnes_urls(self, api_base: str) -> tuple[str, str]:
        base = (api_base or "https://apihub.agnes-ai.com/v1").strip().rstrip("/")
        if base.endswith("/videos"):
            base = base[: -len("/videos")]
        if not base.endswith("/v1"):
            base = f"{base}/v1"
        return f"{base}/videos", base[: -len("/v1")]

    def _build_agnes_body(
        self,
        prompt: str,
        mode: str,
        resolution: str,
        duration: int,
        ratio: str,
        image_path: str | None,
        model: str,
    ) -> dict:
        width, height = self._agnes_dimensions(resolution, ratio)
        target_frames = max(1, int(duration)) * 24
        num_frames = max(81, min(441, round((target_frames - 1) / 8) * 8 + 1))
        body = {
            "model": model,
            "prompt": prompt,
            "width": width,
            "height": height,
            "num_frames": num_frames,
            "frame_rate": 24,
        }
        if mode == "i2v" and image_path:
            body["image"] = self._image_reference_url(image_path)
        return body

    def _agnes_dimensions(self, resolution: str, ratio: str) -> tuple[int, int]:
        dimensions = {
            "480p": {
                "16:9": (854, 480), "9:16": (480, 854), "1:1": (512, 512),
                "4:3": (640, 480), "3:4": (480, 640),
            },
            "720p": {
                "16:9": (1280, 720), "9:16": (720, 1280), "1:1": (768, 768),
                "4:3": (1024, 768), "3:4": (768, 1024),
            },
            "1080p": {
                "16:9": (1920, 1080), "9:16": (1080, 1920), "1:1": (1080, 1080),
                "4:3": (1440, 1080), "3:4": (1080, 1440),
            },
        }
        tier = dimensions.get(str(resolution or "720P").lower(), dimensions["720p"])
        return tier.get(str(ratio or "16:9"), tier["16:9"])

    def _submit_agnes_task(self, api_key: str, submit_url: str, body: dict) -> tuple[str, str]:
        request = urllib.request.Request(
            submit_url,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            data = json.loads(response.read().decode("utf-8"))
        task_id = str(data.get("task_id") or data.get("id") or "").strip()
        video_id = str(data.get("video_id") or "").strip()
        if not task_id and not video_id:
            raise VideoApiError(_api_error_message(data, "Agnes 视频任务提交失败"))
        return task_id, video_id

    def _poll_agnes_and_download(
        self,
        api_key: str,
        result_root: str,
        submit_url: str,
        task_id: str,
        video_id: str,
        model: str,
        on_status: StatusCallback | None,
    ) -> bytes:
        query = urllib.parse.urlencode({"video_id": video_id, "model_name": model})
        recommended_url = f"{result_root.rstrip('/')}/agnesapi?{query}" if video_id else ""
        legacy_url = f"{submit_url.rstrip('/')}/{urllib.parse.quote(task_id)}" if task_id else ""
        poll_url = recommended_url or legacy_url
        using_legacy = not bool(recommended_url)

        for attempt in range(180):
            time.sleep(4)
            request = urllib.request.Request(poll_url, headers={"Authorization": f"Bearer {api_key}"})
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    data = json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as error:
                if error.code in (404, 405) and not using_legacy and legacy_url:
                    poll_url = legacy_url
                    using_legacy = True
                    continue
                raise

            status = str(
                data.get("status")
                or data.get("task_status")
                or data.get("output", {}).get("task_status")
                or ""
            ).lower()
            if status in ("succeeded", "success", "completed", "done"):
                video_url = self._extract_seedance_video_url(data)
                if not video_url:
                    raise VideoApiError(
                        "Agnes 已完成任务，但没有返回视频地址; "
                        f"response_shape={self._response_shape(data)}"
                    )
                if on_status:
                    on_status("正在下载 Agnes 视频...", "accent")
                return self._download_video(video_url)
            if status in ("failed", "error", "canceled", "cancelled"):
                raise VideoApiError(_api_error_message(data, "Agnes 视频生成失败"))
            if on_status:
                progress = data.get("progress")
                suffix = f" {progress}%" if progress is not None else ""
                on_status(f"Agnes 状态：{status or 'running'}{suffix}", "accent")
        raise VideoApiError("Agnes 视频生成超时，请稍后重试")

    def _response_shape(self, value: object) -> str:
        entries: list[str] = []

        def visit(item: object, prefix: str = "", depth: int = 0) -> None:
            if depth > 4 or len(entries) >= 80:
                return
            if isinstance(item, dict):
                for raw_key, child in item.items():
                    key = re.sub(r"[^A-Za-z0-9_.-]", "_", str(raw_key))[:80] or "field"
                    path = f"{prefix}.{key}" if prefix else key
                    entries.append(f"{path}:{type(child).__name__}")
                    if isinstance(child, (dict, list)):
                        visit(child, path, depth + 1)
            elif isinstance(item, list):
                if item:
                    visit(item[0], f"{prefix}[]", depth + 1)

        visit(value)
        return ",".join(entries)[:1200] or "empty"

    def _build_dashscope_body(
        self,
        prompt: str,
        mode: str,
        resolution: str,
        duration: int,
        ratio: str,
        image_path: str | None,
        model: str = "",
    ) -> dict:
        if mode == "t2v":
            return {
                "model": model or VIDEO_MODEL_T2V,
                "input": {"prompt": prompt},
                "parameters": {"resolution": resolution, "ratio": ratio, "duration": duration},
            }
        if not image_path:
            raise VideoApiError("图生视频需要上传参考图")
        with open(image_path, "rb") as file:
            image_data = file.read()
        ext = os.path.splitext(image_path)[1].lower()
        mime = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
            ".bmp": "image/bmp",
        }.get(ext, "image/png")
        data_url = f"data:{mime};base64,{base64.b64encode(image_data).decode('utf-8')}"
        return {
            "model": model or VIDEO_MODEL_I2V,
            "input": {"prompt": prompt, "media": [{"type": "first_frame", "url": data_url}]},
            "parameters": {"resolution": resolution, "duration": duration},
        }

    def _dashscope_urls(self, api_base: str) -> tuple[str, str]:
        """Resolve the DashScope-compatible submit/poll URLs.

        When ``api_base`` is empty this reproduces the official Aliyun
        endpoints.  When the member gateway (or another model service) supplies a
        compatible base URL we derive the submit and task-poll URLs from it so
        the gateway token is sent to the gateway instead of real Aliyun.
        """
        base = (api_base or "").strip().rstrip("/")
        if not base:
            return DASHSCOPE_VIDEO_URL, DASHSCOPE_TASK_URL
        submit_suffix = "/services/aigc/video-generation/video-synthesis"
        root = base[: -len(submit_suffix)] if base.endswith(submit_suffix) else base
        return f"{root}{submit_suffix}", f"{root}/tasks/{{task_id}}"

    def _submit_dashscope_task(self, dash_key: str, body: dict, submit_url: str = DASHSCOPE_VIDEO_URL) -> str:
        request = urllib.request.Request(
            submit_url,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {dash_key}",
                "X-DashScope-Async": "enable",
            },
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            data = json.loads(response.read().decode("utf-8"))
        task_id = data.get("output", {}).get("task_id")
        if not task_id:
            raise VideoApiError(data.get("message", "任务提交失败"))
        return task_id

    def _poll_dashscope_and_download(
        self,
        dash_key: str,
        task_id: str,
        on_status: StatusCallback | None,
        task_url_template: str = DASHSCOPE_TASK_URL,
    ) -> bytes:
        poll_url = task_url_template.format(task_id=task_id)
        for attempt in range(120):
            time.sleep(5)
            request = urllib.request.Request(poll_url, headers={"Authorization": f"Bearer {dash_key}"})
            with urllib.request.urlopen(request, timeout=30) as response:
                data = json.loads(response.read().decode("utf-8"))
            output = data.get("output", {})
            status = output.get("task_status", "")
            if status == "SUCCEEDED":
                video_url = self._extract_video_url(output)
                if not video_url:
                    raise VideoApiError("未获取到视频地址")
                if on_status:
                    on_status("正在下载视频...", "accent")
                return self._download_video(video_url)
            if status == "FAILED":
                raise VideoApiError(output.get("message", "生成失败"))
            if on_status:
                on_status(f"状态：{status or 'RUNNING'}... ({(attempt + 1) * 5}s)", "accent")
        raise VideoApiError("生成超时，请稍后重试")

    def _generate_seedance_compatible(
        self,
        api_key: str,
        prompt: str,
        mode: str,
        resolution: str,
        duration: int,
        ratio: str,
        image_path: str | None,
        api_base: str,
        model: str,
        on_status: StatusCallback | None,
    ) -> bytes:
        if not model:
            raise VideoApiError("火山引擎 Seedance 需要填写模型 ID")
        if mode == "i2v" and not image_path:
            raise VideoApiError("图生视频需要上传参考图")

        task_url = self._seedance_task_url(api_base)
        body = self._build_seedance_body(prompt, mode, resolution, duration, ratio, image_path, model)
        task_id = self._submit_seedance_task(api_key, task_url, body)
        if on_status:
            on_status(f"Seedance 任务已提交：{task_id[:8]}...，等待生成", "accent")
        return self._poll_seedance_and_download(api_key, task_url, task_id, on_status)

    def _seedance_task_url(self, api_base: str) -> str:
        base = (api_base or "https://ark.cn-beijing.volces.com").strip().rstrip("/")
        if base.endswith("/contents/generations/tasks"):
            return base
        if base.endswith("/api/v3"):
            return f"{base}/contents/generations/tasks"
        return f"{base}/api/v3/contents/generations/tasks"

    def _build_seedance_body(
        self,
        prompt: str,
        mode: str,
        resolution: str,
        duration: int,
        ratio: str,
        image_path: str | None,
        model: str,
    ) -> dict:
        content: list[dict] = [{"type": "text", "text": prompt}]
        if mode == "i2v" and image_path:
            content.append({
                "type": "image_url",
                "image_url": {"url": self._image_reference_url(image_path)},
                "role": "first_frame",
            })
        return {
            "model": model,
            "content": content,
            "parameters": {
                "resolution": str(resolution).lower(),
                "duration": int(duration),
                "ratio": ratio,
            },
        }

    def _image_reference_url(self, image_path: str) -> str:
        if image_path.startswith(("http://", "https://", "data:")):
            return image_path
        with open(image_path, "rb") as file:
            image_data = file.read()
        ext = os.path.splitext(image_path)[1].lower()
        mime = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
            ".bmp": "image/bmp",
        }.get(ext, "image/png")
        return f"data:{mime};base64,{base64.b64encode(image_data).decode('utf-8')}"

    def _submit_seedance_task(self, api_key: str, task_url: str, body: dict) -> str:
        request = urllib.request.Request(
            task_url,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            data = json.loads(response.read().decode("utf-8"))
        task_id = data.get("id") or data.get("task_id") or data.get("output", {}).get("task_id")
        if not task_id:
            raise VideoApiError(_api_error_message(data, "Seedance 任务提交失败"))
        return task_id

    def _poll_seedance_and_download(
        self,
        api_key: str,
        task_url: str,
        task_id: str,
        on_status: StatusCallback | None,
    ) -> bytes:
        poll_url = f"{task_url.rstrip('/')}/{task_id}"
        for attempt in range(180):
            time.sleep(4)
            request = urllib.request.Request(poll_url, headers={"Authorization": f"Bearer {api_key}"})
            with urllib.request.urlopen(request, timeout=30) as response:
                data = json.loads(response.read().decode("utf-8"))
            status = str(data.get("status") or data.get("task_status") or data.get("output", {}).get("task_status") or "").lower()
            if status in ("succeeded", "success", "completed", "done"):
                video_url = self._extract_seedance_video_url(data)
                if not video_url:
                    raise VideoApiError("Seedance 未返回视频地址")
                if on_status:
                    on_status("正在下载 Seedance 视频...", "accent")
                return self._download_video(video_url)
            if status in ("failed", "error", "canceled", "cancelled"):
                raise VideoApiError(_api_error_message(data, "Seedance 生成失败"))
            if on_status:
                on_status(f"Seedance 状态：{status or 'running'}... ({(attempt + 1) * 4}s)", "accent")
        raise VideoApiError("Seedance 生成超时，请稍后重试")

    def _extract_seedance_video_url(self, data: dict) -> str | None:
        direct_keys = (
            "video_url",
            "videoUrl",
            "download_url",
            "downloadUrl",
            "file_url",
            "fileUrl",
            "url",
        )
        container_keys = (
            "data",
            "output",
            "result",
            "results",
            "content",
            "video",
            "videos",
            "files",
            "artifacts",
            "items",
            "response",
        )

        def find(value: object, depth: int = 0) -> str | None:
            if depth > 8:
                return None
            if isinstance(value, str):
                text = value.strip()
                lower = text.lower()
                if text.startswith(("http://", "https://")) and (
                    any(marker in lower for marker in (".mp4", ".webm", ".mov", ".m3u8"))
                    or "/video" in lower
                ):
                    return text
                if text.startswith(("{", "[")):
                    try:
                        return find(json.loads(text), depth + 1)
                    except (TypeError, ValueError, json.JSONDecodeError):
                        return None
                return None
            if isinstance(value, dict):
                for key in direct_keys:
                    candidate = value.get(key)
                    if isinstance(candidate, str) and candidate.startswith(("http://", "https://")):
                        return candidate
                    if isinstance(candidate, (dict, list)):
                        nested = find(candidate, depth + 1)
                        if nested:
                            return nested
                for key in container_keys:
                    candidate = value.get(key)
                    if isinstance(candidate, (dict, list, str)):
                        nested = find(candidate, depth + 1)
                        if nested:
                            return nested
                for key, candidate in value.items():
                    if key in direct_keys or key in container_keys:
                        continue
                    if isinstance(candidate, (dict, list, str)):
                        nested = find(candidate, depth + 1)
                        if nested:
                            return nested
            elif isinstance(value, list):
                for item in value:
                    nested = find(item, depth + 1)
                    if nested:
                        return nested
            return None

        return find(data)

    def _extract_video_url(self, output: dict) -> str | None:
        results = output.get("video_url") or output.get("results", [])
        if isinstance(results, str):
            return results
        if isinstance(results, dict):
            return results.get("video_url") or results.get("url")
        if isinstance(results, list) and results:
            first = results[0]
            if isinstance(first, dict):
                return first.get("video_url") or first.get("url")
        return output.get("video_url")

    def _download_video(self, video_url: str) -> bytes:
        request = urllib.request.Request(video_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, timeout=180) as response:
            content_type = response.headers.get("Content-Type", "")
            data = response.read()
        if not data:
            raise VideoApiError("视频下载结果为空")
        if not self._looks_like_video(data, content_type):
            preview = data[:160].decode("utf-8", errors="replace").replace("\n", " ")
            raise VideoApiError(
                f"视频下载结果不是可播放的 MP4：content-type={content_type or 'unknown'}, "
                f"size={len(data)}, preview={preview[:100]}"
            )
        return data

    def _looks_like_video(self, data: bytes, content_type: str) -> bool:
        lower_type = (content_type or "").lower()
        if lower_type.startswith("video/") and len(data) > 1024:
            return True
        head = data[:128]
        return b"ftyp" in head or head.startswith(b"\x1aE\xdf\xa3")
