"""Image generation API client."""

from __future__ import annotations

import base64
import io
import json
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

from core.constants import IMAGE_MODEL


class ImageApiError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        phase: str = "",
        retry_after: str = "",
        outcome_indeterminate: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.phase = phase
        self.retry_after = retry_after
        self.outcome_indeterminate = outcome_indeterminate


def _validated_image_bytes(payload: bytes) -> bytes:
    if payload.startswith(b"\x89PNG\r\n\x1a\n"):
        return payload
    if payload.startswith(b"\xff\xd8\xff"):
        return payload
    if payload.startswith(b"RIFF") and len(payload) >= 12 and payload[8:12] == b"WEBP":
        return payload
    raise ImageApiError("图片生成结果不是可识别的图片，请检查模型接口配置后重试")


def _http_error_message(error: urllib.error.HTTPError) -> str:
    try:
        body = error.read().decode("utf-8")
        data = json.loads(body)
        if isinstance(data.get("error"), dict):
            return data["error"].get("message", f"HTTP {error.code}")
        return data.get("message", f"HTTP {error.code}")
    except Exception:
        return f"HTTP {error.code}"


def _retry_after(error: urllib.error.HTTPError) -> str:
    headers = getattr(error, "headers", None)
    return str(headers.get("Retry-After") or "").strip() if headers else ""


def _submission_outcome_indeterminate(status_code: int | None) -> bool:
    return bool(status_code and (status_code in {408, 502, 503, 504} or 520 <= status_code <= 524))


def _batch_parameter_unsupported(message: str) -> bool:
    lowered = str(message or "").lower()
    return (
        any(marker in lowered for marker in ("parameter n", "'n'", '"n"', "batch", "multiple image"))
        and any(marker in lowered for marker in ("unsupported", "not support", "must be 1", "only 1", "invalid"))
    )


def _openai_endpoint(base_url: str, path: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/v1") and path.startswith("/v1/"):
        return f"{base}{path[3:]}"
    return f"{base}{path}"


class ImageApiClient:
    REQUEST_TIMEOUT_SEC = 600

    def generate(
        self,
        base_url: str,
        api_key: str,
        prompt: str,
        size: str,
        *,
        edit_image_path: str | None = None,
        model: str = "",
    ) -> bytes:
        return self.generate_many(base_url, api_key, prompt, size, count=1, edit_image_path=edit_image_path, model=model)[0]

    def generate_many(
        self,
        base_url: str,
        api_key: str,
        prompt: str,
        size: str,
        *,
        count: int = 1,
        edit_image_path: str | None = None,
        model: str = "",
    ) -> list[bytes]:
        base_url = base_url.rstrip("/")
        count = max(1, min(count, 9))
        try:
            request = self._build_edit_request(base_url, prompt, size, edit_image_path, model=model) if edit_image_path else self._build_generation_request(base_url, prompt, size, count=count, model=model)
            if api_key:
                request.add_header("Authorization", f"Bearer {api_key}")
            with urllib.request.urlopen(request, timeout=self.REQUEST_TIMEOUT_SEC) as response:
                try:
                    data = json.loads(response.read().decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as error:
                    raise ImageApiError(
                        "图片服务返回了损坏的 HTTP 200 JSON 回执",
                        phase="submit",
                        outcome_indeterminate=True,
                    ) from error
            if not isinstance(data, dict):
                raise ImageApiError(
                    "图片服务返回了无效的 HTTP 200 JSON 回执",
                    phase="submit",
                    outcome_indeterminate=True,
                )
            images = self._extract_images_bytes(data, base_url)
            if len(images) >= count:
                return images[:count]
            # A partial batch response is still a paid provider result. Never
            # fan it out into fresh single-image submissions behind the user's
            # back; callers surface the smaller result as a partial success.
            return images
        except urllib.error.HTTPError as error:
            detail = _http_error_message(error)
            if (
                count > 1
                and not edit_image_path
                and error.code in {400, 422}
                and _batch_parameter_unsupported(detail)
            ):
                return [self.generate(base_url, api_key, prompt, size, model=model) for _ in range(count)]
            raise ImageApiError(
                detail,
                status_code=error.code,
                phase="submit",
                retry_after=_retry_after(error),
                outcome_indeterminate=_submission_outcome_indeterminate(error.code),
            ) from error
        except (urllib.error.URLError, TimeoutError, socket.timeout) as error:
            raise ImageApiError(
                str(error),
                phase="submit",
                outcome_indeterminate=True,
            ) from error
        except ImageApiError:
            raise
        except Exception as error:
            raise ImageApiError(str(error)) from error

    def _build_generation_request(self, base_url: str, prompt: str, size: str, *, count: int = 1, model: str = "") -> urllib.request.Request:
        body = json.dumps({"model": model or IMAGE_MODEL, "prompt": prompt, "n": count, "size": size}).encode("utf-8")
        return urllib.request.Request(_openai_endpoint(base_url, "/v1/images/generations"), data=body, headers={"Content-Type": "application/json"})

    def _build_edit_request(self, base_url: str, prompt: str, size: str, image_path: str | None, *, model: str = "") -> urllib.request.Request:
        if not image_path:
            raise ImageApiError("图片编辑模式需要上传参考图")
        boundary = f"----OpenClawFormBoundary{int(time.time() * 1000)}"
        parts: list[bytes] = []
        for field, value in [("model", model or IMAGE_MODEL), ("prompt", prompt), ("n", "1"), ("size", size)]:
            parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{field}\"\r\n\r\n{value}\r\n".encode("utf-8"))
        with open(image_path, "rb") as file:
            file_data = file.read()
        try:
            # Imported lazily so Pillow (a heavy C-extension) stays off the
            # bridge cold-start path — it is only needed for image editing.
            from PIL import Image

            source = Image.open(io.BytesIO(file_data))
            buffer = io.BytesIO()
            source.save(buffer, format="PNG")
            file_data = buffer.getvalue()
        except Exception:
            pass
        parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"image.png\"\r\nContent-Type: image/png\r\n\r\n".encode("utf-8"))
        parts.append(file_data)
        parts.append(f"\r\n--{boundary}--\r\n".encode("utf-8"))
        return urllib.request.Request(
            _openai_endpoint(base_url, "/v1/images/edits"),
            data=b"".join(parts),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )

    def _resolve_image_url(self, base_url: str, image_url: str) -> str:
        image_url = image_url.strip()
        parsed = urllib.parse.urlparse(image_url)
        if parsed.scheme in ("http", "https"):
            return image_url
        if parsed.scheme:
            raise ImageApiError(f"不支持的图片 URL 协议: {parsed.scheme}")
        return urllib.parse.urljoin(f"{base_url.rstrip('/')}/", image_url)

    def _extract_images_bytes(self, data: dict, base_url: str) -> list[bytes]:
        items = data.get("data")
        if not items:
            raise ImageApiError("返回结果中没有图片数据")
        images: list[bytes] = []
        for item in items:
            if item.get("b64_json"):
                images.append(_validated_image_bytes(base64.b64decode(item["b64_json"])))
            elif item.get("url"):
                image_url = self._resolve_image_url(base_url, item["url"])
                images.append(self._download_image(image_url))
        if not images:
            raise ImageApiError("未提取到任何图片数据")
        return images

    def _download_image(self, image_url: str) -> bytes:
        for attempt in range(3):
            try:
                with urllib.request.urlopen(image_url, timeout=self.REQUEST_TIMEOUT_SEC) as response:
                    try:
                        return _validated_image_bytes(response.read())
                    except ImageApiError as error:
                        raise ImageApiError(str(error), phase="download") from error
            except urllib.error.HTTPError as error:
                if attempt < 2 and (
                    error.code in {408, 429, 500, 502, 503, 504}
                    or 520 <= error.code <= 524
                ):
                    time.sleep(0.5 * (attempt + 1))
                    continue
                raise ImageApiError(
                    _http_error_message(error),
                    status_code=error.code,
                    phase="download",
                    retry_after=_retry_after(error),
                ) from error
            except (urllib.error.URLError, TimeoutError, socket.timeout) as error:
                if attempt < 2:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                raise ImageApiError(str(error), phase="download") from error
        raise ImageApiError("图片下载失败", phase="download")
