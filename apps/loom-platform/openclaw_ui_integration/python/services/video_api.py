"""DashScope video generation client."""

from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Callable

from core.constants import DASHSCOPE_TASK_URL, DASHSCOPE_VIDEO_URL, VIDEO_MODEL_I2V, VIDEO_MODEL_T2V
from services.url_safety import assert_public_http_url

StatusCallback = Callable[[str, str], None]


class VideoApiError(RuntimeError):
    pass


def _http_error_message(error: urllib.error.HTTPError) -> str:
    try:
        body = error.read().decode("utf-8")
        data = json.loads(body)
        return data.get("message") or data.get("error", {}).get("message") or f"HTTP {error.code}"
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
    TRANSIENT_HTTP_CODES = (429, 500, 502, 503, 504)

    def _poll_attempts(self, default_seconds: int, interval_seconds: int) -> int:
        try:
            seconds = int(os.environ.get("OPENCLAW_VIDEO_POLL_TIMEOUT_SEC", str(default_seconds)) or default_seconds)
        except Exception:
            seconds = default_seconds
        return max(1, seconds // max(1, interval_seconds))

    def _post_json_with_retries(
        self,
        url: str,
        body: dict,
        headers: dict[str, str],
        timeout: int,
        label: str,
        max_attempts: int = 3,
    ) -> dict:
        last_error: Exception | None = None
        for attempt in range(max(1, max_attempts)):
            request = urllib.request.Request(
                url,
                data=json.dumps(body).encode("utf-8"),
                headers=headers,
            )
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as error:
                if error.code not in self.TRANSIENT_HTTP_CODES:
                    raise
                last_error = error
            except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
                last_error = error
            if attempt < max_attempts - 1:
                time.sleep(2 * (attempt + 1))
        reason = getattr(last_error, "reason", last_error)
        raise VideoApiError(f"{label}提交连续失败：{reason}")

    def _status_message(self, provider: str, status: str, elapsed_seconds: int, progress: object = None) -> str:
        clean_status = str(status or "").strip().lower()
        progress_text = ""
        if isinstance(progress, (int, float)) and 0 < float(progress) < 100:
            progress_text = f"进度 {int(progress)}%，"
        if clean_status in ("queued", "pending"):
            return f"{provider} 排队中，已等待 {elapsed_seconds}s"
        if clean_status in ("running", "processing", "in_progress", "generating"):
            return f"{provider} 生成中，{progress_text}已等待 {elapsed_seconds}s"
        if clean_status:
            return f"{provider} 状态：{clean_status}，已等待 {elapsed_seconds}s"
        return f"{provider} 正在同步任务状态，已等待 {elapsed_seconds}s"

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
    ) -> bytes:
        try:
            provider_id = (provider_id or "dashscope").strip().lower()
            if provider_id == "agnes" or "agnes-ai.com" in (api_base or "").lower() or (model or "").lower().startswith("agnes-video"):
                return self._generate_agnes(
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
        except urllib.error.HTTPError as error:
            raise VideoApiError(_http_error_message(error)) from error
        except Exception as error:
            raise VideoApiError(str(error)) from error

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
        endpoints.  When the member gateway (or a "快乐马"/中转站) supplies a
        compatible base URL we derive the submit and task-poll URLs from it so
        the gateway token is sent to the gateway instead of real Aliyun.
        """
        base = (api_base or "").strip().rstrip("/")
        if not base:
            return DASHSCOPE_VIDEO_URL, DASHSCOPE_TASK_URL
        base = assert_public_http_url(base, "video baseUrl").rstrip("/")
        submit_suffix = "/services/aigc/video-generation/video-synthesis"
        root = base[: -len(submit_suffix)] if base.endswith(submit_suffix) else base
        return f"{root}{submit_suffix}", f"{root}/tasks/{{task_id}}"

    def _submit_dashscope_task(self, dash_key: str, body: dict, submit_url: str = DASHSCOPE_VIDEO_URL) -> str:
        data = self._post_json_with_retries(
            submit_url,
            body,
            {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {dash_key}",
                "X-DashScope-Async": "enable",
            },
            timeout=60,
            label="DashScope",
        )
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
        transient_errors = 0
        for attempt in range(self._poll_attempts(1200, 5)):
            time.sleep(5)
            request = urllib.request.Request(poll_url, headers={"Authorization": f"Bearer {dash_key}"})
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    data = json.loads(response.read().decode("utf-8"))
                transient_errors = 0
            except urllib.error.HTTPError as error:
                if error.code not in (429, 500, 502, 503, 504):
                    raise
                transient_errors += 1
                if on_status:
                    on_status(f"DashScope 轮询临时失败，正在重试：HTTP {error.code}", "warn")
                if transient_errors >= 8:
                    raise VideoApiError(f"DashScope 轮询连续失败：HTTP {error.code}") from error
                continue
            except (urllib.error.URLError, TimeoutError) as error:
                transient_errors += 1
                if on_status:
                    on_status(f"DashScope 轮询超时，正在重试：{getattr(error, 'reason', error)}", "warn")
                if transient_errors >= 8:
                    raise VideoApiError(f"DashScope 轮询连续超时：{getattr(error, 'reason', error)}") from error
                continue
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
                on_status(self._status_message("DashScope", status or "running", (attempt + 1) * 5, output.get("progress")), "accent")
        raise VideoApiError("生成超时，请稍后重试")

    def _generate_agnes(
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
        task_url = self._agnes_task_url(api_base)
        body = self._build_agnes_body(prompt, mode, resolution, duration, ratio, image_path, model)
        task_id = self._submit_agnes_task(api_key, task_url, body)
        if on_status:
            on_status(f"Agnes 任务已提交：{task_id[:8]}...，等待生成", "accent")
        return self._poll_agnes_and_download(api_key, task_url, task_id, on_status)

    def _agnes_task_url(self, api_base: str) -> str:
        base = assert_public_http_url(api_base or "https://apihub.agnes-ai.com/v1", "Agnes baseUrl").rstrip("/")
        if base.endswith("/videos"):
            return base
        if base.endswith("/v1"):
            return f"{base}/videos"
        return f"{base}/v1/videos"

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
        width, height = self._video_dimensions(resolution, ratio)
        frame_rate = 24
        body = {
            "model": model or "agnes-video-v2.0",
            "prompt": prompt,
            "height": height,
            "width": width,
            "num_frames": self._frame_count(duration, frame_rate),
            "frame_rate": frame_rate,
        }
        if mode == "i2v":
            if not image_path:
                raise VideoApiError("图生视频需要上传参考图")
            body["image"] = self._image_reference_url(image_path)
        return body

    def _video_dimensions(self, resolution: str, ratio: str) -> tuple[int, int]:
        target = self._resolution_pixels(resolution)
        parts = str(ratio or "16:9").split(":", 1)
        try:
            ratio_w = max(1, float(parts[0]))
            ratio_h = max(1, float(parts[1])) if len(parts) > 1 else 9.0
        except Exception:
            ratio_w, ratio_h = 16.0, 9.0
        if ratio_w >= ratio_h:
            height = target
            width = int(round(height * ratio_w / ratio_h))
        else:
            width = target
            height = int(round(width * ratio_h / ratio_w))
        return self._even(width), self._even(height)

    def _resolution_pixels(self, resolution: str) -> int:
        digits = "".join(ch for ch in str(resolution or "720P") if ch.isdigit())
        value = int(digits or "720")
        return max(256, min(value, 2160))

    def _even(self, value: int) -> int:
        return max(2, int(round(value / 2)) * 2)

    def _frame_count(self, duration: int, frame_rate: int) -> int:
        try:
            seconds = max(1, int(duration))
        except Exception:
            seconds = 5
        raw = min(441, max(9, seconds * frame_rate + 1))
        return ((raw - 1) // 8) * 8 + 1

    def _submit_agnes_task(self, api_key: str, task_url: str, body: dict) -> str:
        # Video submits can be slow to queue (some gateways hold the connection
        # while they accept the task); 60s was too tight and surfaced as a raw
        # "read operation timed out". Give it room and retry transient network
        # failures such as SSL EOF or gateway resets.
        data = self._post_json_with_retries(
            task_url,
            body,
            {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            timeout=180,
            label="Agnes",
        )
        task_id = data.get("id") or data.get("task_id") or data.get("output", {}).get("task_id")
        if not task_id:
            raise VideoApiError(_api_error_message(data, "Agnes 任务提交失败"))
        return task_id

    def _poll_agnes_and_download(
        self,
        api_key: str,
        task_url: str,
        task_id: str,
        on_status: StatusCallback | None,
    ) -> bytes:
        poll_url = f"{task_url.rstrip('/')}/{task_id}"
        transient_errors = 0
        for attempt in range(self._poll_attempts(1200, 4)):
            time.sleep(4)
            request = urllib.request.Request(poll_url, headers={"Authorization": f"Bearer {api_key}"})
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    data = json.loads(response.read().decode("utf-8"))
                transient_errors = 0
            except urllib.error.HTTPError as error:
                if error.code not in (429, 500, 502, 503, 504):
                    raise
                transient_errors += 1
                if on_status:
                    on_status(f"Agnes 轮询临时失败，正在重试：HTTP {error.code}", "warn")
                if transient_errors >= 8:
                    raise VideoApiError(f"Agnes 轮询连续失败：HTTP {error.code}") from error
                continue
            except (urllib.error.URLError, TimeoutError) as error:
                transient_errors += 1
                if on_status:
                    on_status(f"Agnes 轮询超时，正在重试：{getattr(error, 'reason', error)}", "warn")
                if transient_errors >= 8:
                    raise VideoApiError(f"Agnes 轮询连续超时：{getattr(error, 'reason', error)}") from error
                continue
            status = str(data.get("status") or data.get("task_status") or data.get("output", {}).get("task_status") or "").lower()
            if status in ("completed", "succeeded", "success", "done") or (not status and self._extract_agnes_video_url(data)):
                video_url = self._extract_agnes_video_url(data)
                if not video_url:
                    raise VideoApiError("Agnes 未返回视频地址")
                if on_status:
                    on_status("正在下载 Agnes 视频...", "accent")
                return self._download_video(video_url)
            if status in ("failed", "error", "canceled", "cancelled"):
                raise VideoApiError(_api_error_message(data, "Agnes 生成失败"))
            if on_status:
                on_status(self._status_message("Agnes", status or "running", (attempt + 1) * 4, data.get("progress")), "accent")
        raise VideoApiError("Agnes 生成超时，请稍后重试")

    def _extract_agnes_video_url(self, data: dict) -> str | None:
        deep_url = self._extract_video_url_deep(data)
        if deep_url:
            return deep_url
        candidates = [
            data,
            data.get("output", {}) if isinstance(data.get("output"), dict) else {},
            data.get("result", {}) if isinstance(data.get("result"), dict) else {},
            data.get("data", {}) if isinstance(data.get("data"), dict) else {},
        ]
        for candidate in candidates:
            for key in ("video_url", "url", "download_url", "remixed_from_video_id"):
                url = candidate.get(key)
                if isinstance(url, str) and url.startswith(("http://", "https://")):
                    return url
        return self._extract_seedance_video_url(data)

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
        base = assert_public_http_url(api_base or "https://ark.cn-beijing.volces.com", "Seedance baseUrl").rstrip("/")
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
        data = self._post_json_with_retries(
            task_url,
            body,
            {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            timeout=60,
            label="Seedance",
        )
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
        transient_errors = 0
        for attempt in range(self._poll_attempts(1200, 4)):
            time.sleep(4)
            request = urllib.request.Request(poll_url, headers={"Authorization": f"Bearer {api_key}"})
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    data = json.loads(response.read().decode("utf-8"))
                transient_errors = 0
            except urllib.error.HTTPError as error:
                if error.code not in (429, 500, 502, 503, 504):
                    raise
                transient_errors += 1
                if on_status:
                    on_status(f"Seedance 轮询临时失败，正在重试：HTTP {error.code}", "warn")
                if transient_errors >= 8:
                    raise VideoApiError(f"Seedance 轮询连续失败：HTTP {error.code}") from error
                continue
            except (urllib.error.URLError, TimeoutError) as error:
                transient_errors += 1
                if on_status:
                    on_status(f"Seedance 轮询超时，正在重试：{getattr(error, 'reason', error)}", "warn")
                if transient_errors >= 8:
                    raise VideoApiError(f"Seedance 轮询连续超时：{getattr(error, 'reason', error)}") from error
                continue
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
                on_status(self._status_message("Seedance", status or "running", (attempt + 1) * 4, data.get("progress")), "accent")
        raise VideoApiError("Seedance 生成超时，请稍后重试")

    def _extract_seedance_video_url(self, data: dict) -> str | None:
        deep_url = self._extract_video_url_deep(data)
        if deep_url:
            return deep_url
        candidates = [
            data,
            data.get("output", {}) if isinstance(data.get("output"), dict) else {},
            data.get("result", {}) if isinstance(data.get("result"), dict) else {},
            data.get("data", {}) if isinstance(data.get("data"), dict) else {},
        ]
        for candidate in candidates:
            url = candidate.get("video_url") or candidate.get("url")
            if isinstance(url, str) and url:
                return url
            content = candidate.get("content")
            if isinstance(content, dict):
                url = content.get("video_url") or content.get("url")
                if isinstance(url, str) and url:
                    return url
            if isinstance(content, list):
                for item in content:
                    if not isinstance(item, dict):
                        continue
                    url = item.get("video_url") or item.get("url")
                    if isinstance(url, str) and url:
                        return url
                    video_url = item.get("video_url")
                    if isinstance(video_url, dict) and isinstance(video_url.get("url"), str):
                        return video_url["url"]
        return None

    def _extract_video_url_deep(self, value: object) -> str | None:
        preferred_keys = [
            "video_url",
            "videoUrl",
            "download_url",
            "downloadUrl",
            "url",
            "uri",
            "src",
        ]
        if isinstance(value, str):
            return value if value.startswith(("http://", "https://")) else None
        if isinstance(value, list):
            for item in value:
                found = self._extract_video_url_deep(item)
                if found:
                    return found
            return None
        if not isinstance(value, dict):
            return None
        for key in preferred_keys:
            found = self._extract_video_url_deep(value.get(key))
            if found:
                return found
        for nested_key in ("video", "videos", "file", "files", "content", "output", "outputs", "result", "results", "data"):
            found = self._extract_video_url_deep(value.get(nested_key))
            if found:
                return found
        return None

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
        video_url = assert_public_http_url(video_url, "视频下载 URL")
        last_error: Exception | None = None
        for attempt in range(3):
            request = urllib.request.Request(video_url, headers={"User-Agent": "Mozilla/5.0"})
            try:
                with urllib.request.urlopen(request, timeout=180) as response:
                    content_type = response.headers.get("Content-Type", "")
                    data = response.read()
                break
            except urllib.error.HTTPError as error:
                if error.code not in self.TRANSIENT_HTTP_CODES:
                    raise
                last_error = error
            except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
                last_error = error
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
        else:
            reason = getattr(last_error, "reason", last_error)
            raise VideoApiError(f"视频下载连续失败：{reason}")
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

