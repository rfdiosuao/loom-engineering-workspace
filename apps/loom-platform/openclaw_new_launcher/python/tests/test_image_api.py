from __future__ import annotations

import base64
import io
import os
import sys
import unittest
import urllib.error
from unittest import mock


PYTHON_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)


class ImageApiTests(unittest.TestCase):
    def test_bulk_gateway_timeout_does_not_fan_out_into_single_requests(self) -> None:
        from services.image_api import ImageApiClient, ImageApiError

        error = urllib.error.HTTPError(
            "https://gateway.example/v1/images/generations",
            524,
            "Gateway Timeout",
            {},
            None,
        )
        with mock.patch("urllib.request.urlopen", side_effect=error) as opener:
            with self.assertRaisesRegex(ImageApiError, "HTTP 524"):
                ImageApiClient().generate_many(
                    "https://gateway.example/v1",
                    "test-key",
                    "poster",
                    "1024x1024",
                    count=3,
                )

        self.assertEqual(opener.call_count, 1)

    def test_bulk_validation_error_can_fall_back_to_single_requests(self) -> None:
        from services.image_api import ImageApiClient

        error = urllib.error.HTTPError(
            "https://gateway.example/v1/images/generations",
            400,
            "Bad Request",
            {"Content-Type": "application/json"},
            io.BytesIO(b'{"error":{"message":"parameter n is not supported; only 1 image"}}'),
        )
        image = b"\x89PNG\r\n\x1a\ncontent"
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = (
            b'{"data":[{"b64_json":"' + base64.b64encode(image) + b'"}]}'
        )
        with mock.patch(
            "urllib.request.urlopen",
            side_effect=[error, response, response, response],
        ) as opener:
            images = ImageApiClient().generate_many(
                "https://gateway.example/v1",
                "test-key",
                "poster",
                "1024x1024",
                count=3,
            )

        self.assertEqual(images, [image, image, image])
        self.assertEqual(opener.call_count, 4)

    def test_model_validation_error_does_not_fan_out_or_lose_status(self) -> None:
        from services.image_api import ImageApiClient, ImageApiError

        error = urllib.error.HTTPError(
            "https://gateway.example/v1/images/generations",
            400,
            "Bad Request",
            {"Content-Type": "application/json"},
            io.BytesIO(b'{"error":{"message":"model is not available"}}'),
        )
        with mock.patch("urllib.request.urlopen", side_effect=error) as opener:
            with self.assertRaises(ImageApiError) as raised:
                ImageApiClient().generate_many(
                    "https://gateway.example/v1",
                    "test-key",
                    "poster",
                    "1024x1024",
                    count=3,
                )

        self.assertEqual(opener.call_count, 1)
        self.assertEqual(raised.exception.status_code, 400)
        self.assertEqual(raised.exception.phase, "submit")

    def test_json_rate_limit_preserves_http_status_and_retry_after(self) -> None:
        from services.image_api import ImageApiClient, ImageApiError

        error = urllib.error.HTTPError(
            "https://gateway.example/v1/images/generations",
            429,
            "Too Many Requests",
            {"Content-Type": "application/json", "Retry-After": "3"},
            io.BytesIO(b'{"message":"busy"}'),
        )
        with mock.patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaises(ImageApiError) as raised:
                ImageApiClient().generate(
                    "https://gateway.example/v1",
                    "test-key",
                    "poster",
                    "1024x1024",
                )

        self.assertEqual(str(raised.exception), "busy")
        self.assertEqual(raised.exception.status_code, 429)
        self.assertEqual(raised.exception.retry_after, "3")
        self.assertFalse(raised.exception.outcome_indeterminate)

    def test_image_download_retries_without_resubmitting_generation(self) -> None:
        from services.image_api import ImageApiClient

        transient = urllib.error.HTTPError(
            "https://cdn.example/result.png",
            503,
            "Unavailable",
            {},
            None,
        )
        image = b"\x89PNG\r\n\x1a\ncontent"
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = image
        with mock.patch(
            "urllib.request.urlopen",
            side_effect=[transient, response],
        ) as opener, mock.patch("services.image_api.time.sleep"):
            result = ImageApiClient()._extract_images_bytes(
                {"data": [{"url": "https://cdn.example/result.png"}]},
                "https://gateway.example/v1",
            )

        self.assertEqual(result, [image])
        self.assertEqual(opener.call_count, 2)

    def test_rejects_non_image_base64_payload(self) -> None:
        from services.image_api import ImageApiClient, ImageApiError

        payload = base64.b64encode(b'{"error":"provider failed"}').decode("ascii")

        with self.assertRaisesRegex(ImageApiError, "可识别的图片"):
            ImageApiClient()._extract_images_bytes(
                {"data": [{"b64_json": payload}]},
                "https://gateway.example/v1",
            )

    def test_rejects_non_image_download_payload(self) -> None:
        from services.image_api import ImageApiClient, ImageApiError

        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b"<html>provider error</html>"
        with mock.patch("urllib.request.urlopen", return_value=response):
            with self.assertRaisesRegex(ImageApiError, "可识别的图片"):
                ImageApiClient()._extract_images_bytes(
                    {"data": [{"url": "/result.png"}]},
                    "https://gateway.example/v1",
                )

    def test_accepts_supported_image_signatures(self) -> None:
        from services.image_api import ImageApiClient

        payloads = [
            b"\x89PNG\r\n\x1a\ncontent",
            b"\xff\xd8\xffcontent",
            b"RIFF\x04\x00\x00\x00WEBPcontent",
        ]

        encoded = [
            {"b64_json": base64.b64encode(payload).decode("ascii")}
            for payload in payloads
        ]
        self.assertEqual(
            ImageApiClient()._extract_images_bytes(
                {"data": encoded},
                "https://gateway.example/v1",
            ),
            payloads,
        )


if __name__ == "__main__":
    unittest.main()
