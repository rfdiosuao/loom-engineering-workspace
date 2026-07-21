"""Image generation API client."""

from __future__ import annotations

import base64
import io
import json
import time
import urllib.error
import urllib.parse
import urllib.request

from core.constants import IMAGE_MODEL
from services.url_safety import assert_public_http_url


class ImageApiError(RuntimeError):
    pass


def _http_error_message(error: urllib.error.HTTPError) -> str:
    try:
        body = error.read().decode("utf-8")
        data = json.loads(body)
        if isinstance(data.get("error"), dict):
            return data["error"].get("message", f"HTTP {error.code}")
        return data.get("message", f"HTTP {error.code}")
    except Exception:
        return f"HTTP {error.code}"


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
        base_url = assert_public_http_url(base_url, "image baseUrl").rstrip("/")
        # The request builders append "/v1/images/...", so the base must be the
        # provider root. Tolerate a base that already ends in /v1 (e.g. copied
        # from a member-gateway URL) instead of producing a broken /v1/v1 path.
        if base_url.endswith("/v1"):
            base_url = base_url[:-3].rstrip("/")
        count = max(1, min(count, 9))
        try:
            request = self._build_edit_request(base_url, prompt, size, edit_image_path, model=model) if edit_image_path else self._build_generation_request(base_url, prompt, size, count=count, model=model)
            if api_key:
                request.add_header("Authorization", f"Bearer {api_key}")
            with urllib.request.urlopen(request, timeout=self.REQUEST_TIMEOUT_SEC) as response:
                data = json.loads(response.read().decode("utf-8"))
            images = self._extract_images_bytes(data, base_url)
            if len(images) >= count:
                return images[:count]
            while len(images) < count and not edit_image_path:
                images.append(self.generate(base_url, api_key, prompt, size, model=model))
            return images
        except urllib.error.HTTPError as error:
            if count > 1 and not edit_image_path:
                return [self.generate(base_url, api_key, prompt, size, model=model) for _ in range(count)]
            raise ImageApiError(_http_error_message(error)) from error
        except Exception as error:
            raise ImageApiError(str(error)) from error

    def _build_generation_request(self, base_url: str, prompt: str, size: str, *, count: int = 1, model: str = "") -> urllib.request.Request:
        body = json.dumps({"model": model or IMAGE_MODEL, "prompt": prompt, "n": count, "size": size}).encode("utf-8")
        return urllib.request.Request(f"{base_url}/v1/images/generations", data=body, headers={"Content-Type": "application/json"})

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
            f"{base_url}/v1/images/edits",
            data=b"".join(parts),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )

    def _resolve_image_url(self, base_url: str, image_url: str) -> str:
        image_url = image_url.strip()
        parsed = urllib.parse.urlparse(image_url)
        if parsed.scheme in ("http", "https"):
            return assert_public_http_url(image_url, "图片 URL")
        if parsed.scheme:
            raise ImageApiError(f"不支持的图片 URL 协议: {parsed.scheme}")
        return assert_public_http_url(urllib.parse.urljoin(f"{base_url.rstrip('/')}/", image_url), "图片 URL")

    def _extract_images_bytes(self, data: dict, base_url: str) -> list[bytes]:
        items = data.get("data")
        if not items:
            raise ImageApiError("返回结果中没有图片数据")
        images: list[bytes] = []
        for item in items:
            if item.get("b64_json"):
                images.append(base64.b64decode(item["b64_json"]))
            elif item.get("url"):
                image_url = self._resolve_image_url(base_url, item["url"])
                with urllib.request.urlopen(image_url, timeout=self.REQUEST_TIMEOUT_SEC) as response:
                    images.append(response.read())
        if not images:
            raise ImageApiError("未提取到任何图片数据")
        return images
