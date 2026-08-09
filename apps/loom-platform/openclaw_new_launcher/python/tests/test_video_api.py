from __future__ import annotations

import json
import io
import os
import sys
import unittest
import urllib.error
from unittest import mock


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PYTHON_ROOT = os.path.join(REPO_ROOT, "python")
if PYTHON_ROOT not in sys.path:
    sys.path.insert(0, PYTHON_ROOT)

from services.video_api import DashScopeVideoClient, VideoApiError


class _JsonResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload
        self.headers = {"Content-Type": "application/json"}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


class _RawResponse(_JsonResponse):
    def __init__(self, payload: bytes) -> None:
        self._raw_payload = payload
        self.headers = {"Content-Type": "application/json"}

    def read(self) -> bytes:
        return self._raw_payload


class AgnesVideoClientTests(unittest.TestCase):
    def test_agnes_provider_uses_videos_endpoint_and_video_id_polling(self) -> None:
        client = DashScopeVideoClient()
        responses = [
            _JsonResponse({
                "id": "task_123",
                "task_id": "task_123",
                "video_id": "video_456",
                "status": "queued",
            }),
            _JsonResponse({
                "id": "task_123",
                "video_id": "video_456",
                "status": "completed",
                "url": "https://cdn.example.com/result.mp4",
            }),
        ]

        with (
            mock.patch("services.video_api.urllib.request.urlopen", side_effect=responses) as urlopen,
            mock.patch("services.video_api.time.sleep"),
            mock.patch.object(client, "_download_video", return_value=b"video-bytes") as download,
        ):
            result = client.generate(
                "test-key",
                "A polished LOOM product demo",
                "t2v",
                "720P",
                5,
                "9:16",
                provider_id="agnes",
                api_base="https://api.example.com/v1",
                model="agnes-video-v2.0",
            )

        self.assertEqual(result, b"video-bytes")
        self.assertEqual(urlopen.call_count, 2)
        submit_request = urlopen.call_args_list[0].args[0]
        poll_request = urlopen.call_args_list[1].args[0]
        self.assertEqual(submit_request.full_url, "https://api.example.com/v1/videos")
        self.assertEqual(
            poll_request.full_url,
            "https://api.example.com/agnesapi?video_id=video_456&model_name=agnes-video-v2.0",
        )
        submit_body = json.loads(submit_request.data.decode("utf-8"))
        self.assertEqual(submit_body["model"], "agnes-video-v2.0")
        self.assertEqual(submit_body["prompt"], "A polished LOOM product demo")
        self.assertEqual(submit_body["width"], 720)
        self.assertEqual(submit_body["height"], 1280)
        self.assertEqual(submit_body["num_frames"], 121)
        self.assertEqual(submit_body["frame_rate"], 24)
        download.assert_called_once_with("https://cdn.example.com/result.mp4")

    def test_completed_gateway_wrapper_exposes_nested_video_url(self) -> None:
        client = DashScopeVideoClient()
        payload = {
            "status": "completed",
            "data": {
                "result": {
                    "videos": [
                        {"video": {"download_url": "https://cdn.example.com/wrapped.mp4"}}
                    ]
                }
            },
        }

        self.assertEqual(
            client._extract_seedance_video_url(payload),
            "https://cdn.example.com/wrapped.mp4",
        )

    def test_stringified_custom_gateway_payload_exposes_video_file_url(self) -> None:
        client = DashScopeVideoClient()
        payload = {
            "response_payload": json.dumps({
                "asset": {
                    "file_url": "https://cdn.example.com/custom-wrapper.mp4",
                }
            })
        }

        self.assertEqual(
            client._extract_seedance_video_url(payload),
            "https://cdn.example.com/custom-wrapper.mp4",
        )

    def test_missing_completed_url_reports_key_shape_without_values(self) -> None:
        client = DashScopeVideoClient()
        responses = [
            _JsonResponse({"task_id": "task_safe", "video_id": "video_safe"}),
            _JsonResponse({
                "status": "completed",
                "data": {"mystery": "PRIVATE_RESPONSE_VALUE"},
            }),
        ]

        with (
            mock.patch("services.video_api.urllib.request.urlopen", side_effect=responses),
            mock.patch("services.video_api.time.sleep"),
        ):
            with self.assertRaises(VideoApiError) as raised:
                client.generate(
                    "test-key",
                    "LOOM demo",
                    "t2v",
                    "720P",
                    3,
                    "9:16",
                    provider_id="agnes",
                    api_base="https://api.example.com/v1",
                    model="agnes-video-v2.0",
                )

        message = str(raised.exception)
        self.assertIn("response_shape=", message)
        self.assertIn("data.mystery", message)
        self.assertNotIn("PRIVATE_RESPONSE_VALUE", message)

    def test_polling_transient_failure_reuses_the_original_agnes_task(self) -> None:
        client = DashScopeVideoClient()
        transient = urllib.error.HTTPError(
            "https://api.example.com/agnesapi",
            503,
            "Unavailable",
            {},
            io.BytesIO(b'{"message":"busy"}'),
        )
        responses = [
            _JsonResponse({"task_id": "task_123", "video_id": "video_456"}),
            transient,
            _JsonResponse({
                "status": "completed",
                "url": "https://cdn.example.com/result.mp4",
            }),
        ]

        with (
            mock.patch("services.video_api.urllib.request.urlopen", side_effect=responses) as urlopen,
            mock.patch("services.video_api.time.sleep"),
            mock.patch.object(client, "_download_video", return_value=b"video-bytes"),
        ):
            result = client.generate(
                "test-key",
                "LOOM demo",
                "t2v",
                "720P",
                5,
                "9:16",
                provider_id="agnes",
                api_base="https://api.example.com/v1",
                model="agnes-video-v2.0",
                request_key="request-1",
            )

        self.assertEqual(result, b"video-bytes")
        self.assertEqual(urlopen.call_count, 3)
        self.assertEqual(
            sum(1 for call in urlopen.call_args_list if call.args[0].data is not None),
            1,
        )

    def test_submission_503_is_indeterminate_and_is_not_retried(self) -> None:
        client = DashScopeVideoClient()
        transient = urllib.error.HTTPError(
            "https://api.example.com/v1/videos",
            503,
            "Unavailable",
            {},
            io.BytesIO(b'{"message":"busy"}'),
        )

        with mock.patch(
            "services.video_api.urllib.request.urlopen",
            side_effect=transient,
        ) as urlopen:
            with self.assertRaises(VideoApiError) as raised:
                client.generate(
                    "test-key",
                    "LOOM demo",
                    "t2v",
                    "720P",
                    5,
                    "9:16",
                    provider_id="agnes",
                    api_base="https://api.example.com/v1",
                    model="agnes-video-v2.0",
                    request_key="request-uncertain",
                )

        self.assertEqual(urlopen.call_count, 1)
        self.assertEqual(raised.exception.status_code, 503)
        self.assertEqual(raised.exception.phase, "submit")
        self.assertEqual(raised.exception.request_key, "request-uncertain")
        self.assertTrue(raised.exception.outcome_indeterminate)

    def test_malformed_http_200_submission_is_indeterminate(self) -> None:
        client = DashScopeVideoClient()

        with mock.patch(
            "services.video_api.urllib.request.urlopen",
            return_value=_RawResponse(b'{"task_id":'),
        ) as urlopen:
            with self.assertRaises(VideoApiError) as raised:
                client.generate(
                    "test-key",
                    "LOOM demo",
                    "t2v",
                    "720P",
                    5,
                    "9:16",
                    provider_id="agnes",
                    api_base="https://api.example.com/v1",
                    model="agnes-video-v2.0",
                    request_key="request-malformed-200",
                )

        self.assertEqual(urlopen.call_count, 1)
        self.assertEqual(raised.exception.phase, "submit")
        self.assertEqual(raised.exception.request_key, "request-malformed-200")
        self.assertTrue(raised.exception.outcome_indeterminate)

    def test_video_download_retries_without_resubmitting_generation(self) -> None:
        client = DashScopeVideoClient()
        transient = urllib.error.HTTPError(
            "https://cdn.example.com/result.mp4",
            503,
            "Unavailable",
            {},
            None,
        )
        response = mock.MagicMock()
        response.__enter__.return_value.headers = {"Content-Type": "video/mp4"}
        response.__enter__.return_value.read.return_value = b"\x00\x00\x00\x18ftypisomvideo"

        with mock.patch(
            "services.video_api.urllib.request.urlopen",
            side_effect=[transient, response],
        ) as urlopen, mock.patch("services.video_api.time.sleep"):
            result = client._download_video("https://cdn.example.com/result.mp4")

        self.assertIn(b"ftyp", result)
        self.assertEqual(urlopen.call_count, 2)


if __name__ == "__main__":
    unittest.main()
