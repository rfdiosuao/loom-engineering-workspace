from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from unittest import mock


PYTHON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)


from services.pippit_video_api import PippitManualRequired, PippitVideoClient, PippitVideoError


class PippitVideoClientTests(unittest.TestCase):
    def test_first_run_persists_ids_and_restart_only_polls_original_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = os.path.join(temp_dir, "pippit-runs.json")
            client = PippitVideoClient()
            completed = {
                "thread": {
                    "run_list": [
                        {
                            "thread_id": "thread-1",
                            "run_id": "run-1",
                            "state": 3,
                            "entry_list": [
                                {
                                    "artifact": {
                                        "content": [
                                            {
                                                "data": json.dumps(
                                                    {"download_url": "https://cdn.example.com/video.mp4"}
                                                )
                                            }
                                        ]
                                    }
                                }
                            ],
                        }
                    ]
                }
            }

            with (
                mock.patch.object(
                    client,
                    "_submit_run",
                    return_value={
                        "thread_id": "thread-1",
                        "run_id": "run-1",
                        "web_thread_link": "https://xyq.jianying.com/thread-1",
                    },
                ) as submit,
                mock.patch.object(client, "_get_thread", return_value=completed) as poll,
                mock.patch.object(client, "_download_video", return_value=b"video-bytes") as download,
            ):
                first = client.generate(
                    "access-key",
                    "生成一条产品视频",
                    "t2v",
                    "1080P",
                    8,
                    "9:16",
                    api_base="https://xyq.jianying.com",
                    request_key="request-1",
                    state_path=state_path,
                    poll_interval_ms=0,
                    timeout_ms=1000,
                )

            self.assertEqual(first, b"video-bytes")
            submit.assert_called_once()
            poll.assert_called_once_with("access-key", "https://xyq.jianying.com", "thread-1", "run-1")
            download.assert_called_once_with("https://cdn.example.com/video.mp4")

            with open(state_path, "r", encoding="utf-8") as handle:
                persisted = json.load(handle)["runs"]["request-1"]
            self.assertEqual(persisted["threadId"], "thread-1")
            self.assertEqual(persisted["runId"], "run-1")
            self.assertEqual(persisted["status"], "succeeded")
            self.assertNotIn("access-key", json.dumps(persisted))

            restarted = PippitVideoClient()
            with (
                mock.patch.object(restarted, "_submit_run") as submit_after_restart,
                mock.patch.object(restarted, "_download_video", return_value=b"cached-url-video") as download_after_restart,
            ):
                second = restarted.generate(
                    "access-key",
                    "生成一条产品视频",
                    "t2v",
                    "1080P",
                    8,
                    "9:16",
                    api_base="https://xyq.jianying.com",
                    request_key="request-1",
                    state_path=state_path,
                    poll_interval_ms=0,
                    timeout_ms=1000,
                )

            self.assertEqual(second, b"cached-url-video")
            submit_after_restart.assert_not_called()
            download_after_restart.assert_called_once_with("https://cdn.example.com/video.mp4")

    def test_manual_question_keeps_original_thread_and_continuation_uses_it(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = os.path.join(temp_dir, "pippit-runs.json")
            client = PippitVideoClient()
            question_payload = {
                "thread": {
                    "run_list": [
                        {
                            "thread_id": "thread-2",
                            "run_id": "run-2",
                            "state": 1,
                            "entry_list": [
                                {
                                    "type": "questionnaire",
                                    "question": "是否确认开始生成完整成片？",
                                }
                            ],
                        }
                    ]
                }
            }
            completed_payload = {
                "thread": {
                    "run_list": [
                        {
                            "thread_id": "thread-2",
                            "run_id": "run-3",
                            "state": 3,
                            "entry_list": [{"video_url": "https://cdn.example.com/final.mov"}],
                        }
                    ]
                }
            }

            with (
                mock.patch.object(
                    client,
                    "_submit_run",
                    return_value={
                        "thread_id": "thread-2",
                        "run_id": "run-2",
                        "web_thread_link": "https://xyq.jianying.com/thread-2",
                    },
                ),
                mock.patch.object(client, "_get_thread", return_value=question_payload),
            ):
                with self.assertRaises(PippitManualRequired) as raised:
                    client.generate(
                        "access-key",
                        "生成一条产品视频",
                        "t2v",
                        "720P",
                        5,
                        "16:9",
                        api_base="https://xyq.jianying.com",
                        request_key="request-2",
                        state_path=state_path,
                        poll_interval_ms=0,
                        timeout_ms=1000,
                    )

            self.assertEqual(raised.exception.request_key, "request-2")
            self.assertEqual(raised.exception.thread_id, "thread-2")
            self.assertEqual(raised.exception.run_id, "run-2")
            self.assertEqual(raised.exception.question, "是否确认开始生成完整成片？")

            with (
                mock.patch.object(
                    client,
                    "_submit_run",
                    return_value={
                        "thread_id": "thread-2",
                        "run_id": "run-3",
                        "web_thread_link": "https://xyq.jianying.com/thread-2",
                    },
                ) as continue_submit,
                mock.patch.object(client, "_get_thread", return_value=completed_payload),
                mock.patch.object(client, "_download_video", return_value=b"continued-video"),
            ):
                result = client.generate(
                    "access-key",
                    "",
                    "t2v",
                    "720P",
                    5,
                    "16:9",
                    api_base="https://xyq.jianying.com",
                    request_key="request-2",
                    state_path=state_path,
                    continuation_message="确认生成完整成片",
                    poll_interval_ms=0,
                    timeout_ms=1000,
                )

            self.assertEqual(result, b"continued-video")
            self.assertEqual(continue_submit.call_args.kwargs["thread_id"], "thread-2")
            self.assertEqual(continue_submit.call_args.kwargs["message"], "确认生成完整成片")

    def test_nested_video_extraction_prefers_video_artifact_and_deduplicates_query_variants(self) -> None:
        client = PippitVideoClient()
        payload = [
            {"url": "https://cdn.example.com/preview.jpg"},
            {"data": json.dumps({"url": "https://cdn.example.com/result.mp4?token=one"})},
            {"download_url": "https://cdn.example.com/result.mp4?token=two"},
        ]

        self.assertEqual(
            client._extract_video_urls(payload),
            ["https://cdn.example.com/result.mp4?token=one"],
        )

    def test_initial_run_claim_is_atomic_and_blocks_duplicate_paid_submission(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = os.path.join(temp_dir, "pippit-runs.json")
            client = PippitVideoClient()
            first, claimed_first = client._claim_initial_run(
                state_path,
                "request-atomic",
                {"requestKey": "request-atomic", "status": "submitting", "operationId": "first"},
            )
            second, claimed_second = client._claim_initial_run(
                state_path,
                "request-atomic",
                {"requestKey": "request-atomic", "status": "submitting", "operationId": "second"},
            )

            self.assertTrue(claimed_first)
            self.assertFalse(claimed_second)
            self.assertEqual(first["operationId"], "first")
            self.assertEqual(second["operationId"], "first")

    def test_failed_run_without_ids_is_not_automatically_resubmitted(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = os.path.join(temp_dir, "pippit-runs.json")
            client = PippitVideoClient()
            client._write_run(
                state_path,
                "request-failed",
                {"requestKey": "request-failed", "status": "failed"},
            )

            with mock.patch.object(client, "_submit_run") as submit:
                with self.assertRaises(PippitVideoError) as raised:
                    client.generate(
                        "access-key",
                        "不要重复提交",
                        "t2v",
                        "720P",
                        5,
                        "16:9",
                        request_key="request-failed",
                        state_path=state_path,
                    )

            submit.assert_not_called()
            self.assertIn("禁止自动重建", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
