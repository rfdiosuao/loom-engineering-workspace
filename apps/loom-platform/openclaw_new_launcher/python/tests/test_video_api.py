from __future__ import annotations

import json
import os
import sys
import unittest
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


if __name__ == "__main__":
    unittest.main()
