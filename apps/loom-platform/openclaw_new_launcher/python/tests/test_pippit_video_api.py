from __future__ import annotations

import json
import io
import os
import sys
import tempfile
import unittest
import urllib.error
from unittest import mock


PYTHON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)


from services.pippit_video_api import (
    MAX_DOWNLOAD_BYTES,
    PippitManualRequired,
    PippitSubmissionUncertain,
    PippitTransientError,
    PippitVideoClient,
    PippitVideoError,
)


class PippitVideoClientTests(unittest.TestCase):
    @staticmethod
    def _completed_payload(url: str = "https://cdn.example.com/video.mp4") -> dict:
        return {
            "thread": {
                "run_list": [
                    {
                        "thread_id": "thread-1",
                        "run_id": "run-1",
                        "state": 3,
                        "entry_list": [{"artifact": {"content": [{"video": {"download_url": url}}]}}],
                    }
                ]
            }
        }

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

    def test_completed_run_can_still_require_manual_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = os.path.join(temp_dir, "pippit-runs.json")
            client = PippitVideoClient()
            completed_question = {
                "thread": {
                    "run_list": [
                        {
                            "thread_id": "thread-1",
                            "run_id": "run-1",
                            "state": 3,
                            "entry_list": [
                                {
                                    "message": {
                                        "client_tool_calls": [
                                            {
                                                "type": "questionnaire",
                                                "question": "请选择视频风格后继续",
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
                    return_value={"thread_id": "thread-1", "run_id": "run-1", "web_thread_link": ""},
                ),
                mock.patch.object(client, "_get_thread", return_value=completed_question),
            ):
                with self.assertRaises(PippitManualRequired) as raised:
                    client.generate(
                        "access-key",
                        "生成视频",
                        "t2v",
                        "720P",
                        5,
                        "16:9",
                        request_key="request-completed-question",
                        state_path=state_path,
                        poll_interval_ms=0,
                        timeout_ms=1000,
                    )
            self.assertEqual(raised.exception.question, "请选择视频风格后继续")

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

    def test_upload_failure_is_safe_to_retry_without_deadlocking_request_key(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = os.path.join(temp_dir, "pippit-runs.json")
            image_path = os.path.join(temp_dir, "reference.png")
            with open(image_path, "wb") as handle:
                handle.write(b"png")
            client = PippitVideoClient()

            with mock.patch.object(client, "_upload_asset", side_effect=PippitVideoError("upload failed")):
                with self.assertRaises(PippitVideoError):
                    client.generate(
                        "access-key",
                        "参考图片生成视频",
                        "i2v",
                        "720P",
                        5,
                        "16:9",
                        image_path,
                        request_key="request-upload-retry",
                        state_path=state_path,
                    )

            with open(state_path, "r", encoding="utf-8") as handle:
                self.assertEqual(
                    json.load(handle)["runs"]["request-upload-retry"]["status"],
                    "upload_failed",
                )

            with (
                mock.patch.object(client, "_upload_asset", return_value="asset-1"),
                mock.patch.object(
                    client,
                    "_submit_run",
                    return_value={"thread_id": "thread-1", "run_id": "run-1", "web_thread_link": ""},
                ) as submit,
                mock.patch.object(client, "_get_thread", return_value=self._completed_payload()),
                mock.patch.object(client, "_download_video", return_value=b"video"),
            ):
                result = client.generate(
                    "access-key",
                    "参考图片生成视频",
                    "i2v",
                    "720P",
                    5,
                    "16:9",
                    image_path,
                    request_key="request-upload-retry",
                    state_path=state_path,
                    poll_interval_ms=0,
                    timeout_ms=1000,
                )

            self.assertEqual(result, b"video")
            submit.assert_called_once()

    def test_submit_http_503_is_uncertain_and_never_automatically_retried(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = os.path.join(temp_dir, "pippit-runs.json")
            client = PippitVideoClient()
            http_error = urllib.error.HTTPError(
                "https://xyq.jianying.com/api/biz/v1/skill/submit_run",
                503,
                "Service Unavailable",
                {},
                io.BytesIO(b'{"ret":"503","errmsg":"busy"}'),
            )
            with mock.patch("urllib.request.urlopen", side_effect=http_error) as request:
                with self.assertRaises(PippitSubmissionUncertain):
                    client.generate(
                        "access-key",
                        "生成视频",
                        "t2v",
                        "720P",
                        5,
                        "16:9",
                        request_key="request-uncertain",
                        state_path=state_path,
                    )
            self.assertEqual(request.call_count, 1)

            with open(state_path, "r", encoding="utf-8") as handle:
                self.assertEqual(json.load(handle)["runs"]["request-uncertain"]["status"], "uncertain")

            with mock.patch("urllib.request.urlopen") as retry_request:
                with self.assertRaises(PippitVideoError) as raised:
                    client.generate(
                        "access-key",
                        "生成视频",
                        "t2v",
                        "720P",
                        5,
                        "16:9",
                        request_key="request-uncertain",
                        state_path=state_path,
                    )
            retry_request.assert_not_called()
            self.assertIn("停止自动重提", str(raised.exception))

    def test_query_http_503_is_transient_instead_of_submission_uncertain(self) -> None:
        client = PippitVideoClient()
        http_error = urllib.error.HTTPError(
            "https://xyq.jianying.com/api/biz/v1/skill/get_thread",
            503,
            "Service Unavailable",
            {},
            io.BytesIO(b'{"ret":"503","errmsg":"busy"}'),
        )
        with mock.patch("urllib.request.urlopen", side_effect=http_error):
            with self.assertRaises(PippitTransientError):
                client._get_thread("access-key", "https://xyq.jianying.com", "thread-1", "run-1")

    def test_transient_poll_failure_retries_original_run_without_resubmission(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = os.path.join(temp_dir, "pippit-runs.json")
            client = PippitVideoClient()
            with (
                mock.patch.object(
                    client,
                    "_submit_run",
                    return_value={"thread_id": "thread-1", "run_id": "run-1", "web_thread_link": ""},
                ) as submit,
                mock.patch.object(
                    client,
                    "_get_thread",
                    side_effect=[PippitTransientError("temporary network error"), self._completed_payload()],
                ) as poll,
                mock.patch.object(client, "_download_video", return_value=b"video"),
            ):
                result = client.generate(
                    "access-key",
                    "生成视频",
                    "t2v",
                    "720P",
                    5,
                    "16:9",
                    request_key="request-poll-retry",
                    state_path=state_path,
                    poll_interval_ms=0,
                    timeout_ms=1000,
                )

            self.assertEqual(result, b"video")
            submit.assert_called_once()
            self.assertEqual(poll.call_count, 2)

    def test_same_request_key_rejects_changed_generation_input(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = os.path.join(temp_dir, "pippit-runs.json")
            client = PippitVideoClient()
            original_hash = client._input_hash("原提示词", "t2v", "720P", 5, "16:9", None)
            client._write_run(
                state_path,
                "request-input",
                {
                    "requestKey": "request-input",
                    "inputHash": original_hash,
                    "status": "submitted",
                    "threadId": "thread-1",
                    "runId": "run-1",
                },
            )

            with mock.patch.object(client, "_get_thread") as poll:
                with self.assertRaises(PippitVideoError) as raised:
                    client.generate(
                        "access-key",
                        "另一个提示词",
                        "t2v",
                        "720P",
                        5,
                        "16:9",
                        request_key="request-input",
                        state_path=state_path,
                    )
            poll.assert_not_called()
            self.assertIn("输入已变化", str(raised.exception))

    def test_input_hash_uses_reference_content_not_temporary_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            first_path = os.path.join(temp_dir, "first-reference.png")
            second_path = os.path.join(temp_dir, "second-reference.png")
            for path in (first_path, second_path):
                with open(path, "wb") as handle:
                    handle.write(b"same-reference-content")
            client = PippitVideoClient()

            first = client._input_hash("prompt", "i2v", "720P", 5, "16:9", first_path)
            second = client._input_hash("prompt", "i2v", "720P", 5, "16:9", second_path)

            self.assertEqual(first, second)

    def test_extensionless_signed_url_nested_under_video_is_recognized(self) -> None:
        client = PippitVideoClient()
        payload = {
            "artifact": {
                "content": [
                    {
                        "video": {
                            "thumbnail_url": "https://cdn.example.com/cover.jpg",
                            "download_url": "https://cdn.example.com/object?id=1",
                        }
                    }
                ]
            }
        }
        self.assertEqual(
            client._extract_video_urls(payload),
            ["https://cdn.example.com/object?id=1"],
        )

    def test_submit_preserves_user_prompt_without_client_side_rewriting(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = os.path.join(temp_dir, "pippit-runs.json")
            client = PippitVideoClient()
            prompt = "让这张图自然地动起来，不要改变人物表情"
            with (
                mock.patch.object(
                    client,
                    "_submit_run",
                    return_value={"thread_id": "thread-1", "run_id": "run-1", "web_thread_link": ""},
                ) as submit,
                mock.patch.object(client, "_get_thread", return_value=self._completed_payload()),
                mock.patch.object(client, "_download_video", return_value=b"video"),
            ):
                client.generate(
                    "access-key",
                    prompt,
                    "t2v",
                    "1080P",
                    9,
                    "9:16",
                    request_key="request-raw-prompt",
                    state_path=state_path,
                    poll_interval_ms=0,
                    timeout_ms=1000,
                )

            self.assertEqual(submit.call_args.kwargs["message"], prompt)

    def test_explicit_resume_ignores_changed_ui_fields_and_never_submits(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = os.path.join(temp_dir, "pippit-runs.json")
            with open(state_path, "w", encoding="utf-8") as handle:
                json.dump({
                    "schemaVersion": 1,
                    "runs": {
                        "request-resume": {
                            "requestKey": "request-resume",
                            "inputHash": "original-input-hash",
                            "status": "running",
                            "threadId": "thread-1",
                            "runId": "run-1",
                        }
                    },
                }, handle)
            client = PippitVideoClient()
            with (
                mock.patch.object(client, "_submit_run") as submit,
                mock.patch.object(client, "_get_thread", return_value=self._completed_payload()),
                mock.patch.object(client, "_download_video", return_value=b"video") as download,
            ):
                result = client.generate(
                    "access-key",
                    "页面重启后变化的提示词",
                    "i2v",
                    "480P",
                    30,
                    "1:1",
                    request_key="request-resume",
                    state_path=state_path,
                    resume_existing=True,
                    poll_interval_ms=0,
                    timeout_ms=1000,
                )

            self.assertEqual(result, b"video")
            submit.assert_not_called()
            download.assert_called_once()

    def test_explicit_resume_without_existing_ids_never_creates_paid_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = os.path.join(temp_dir, "pippit-runs.json")
            client = PippitVideoClient()
            with mock.patch.object(client, "_submit_run") as submit:
                with self.assertRaises(PippitVideoError) as raised:
                    client.generate(
                        "access-key",
                        "prompt",
                        "t2v",
                        "720P",
                        5,
                        "16:9",
                        request_key="missing-run",
                        state_path=state_path,
                        resume_existing=True,
                    )
            submit.assert_not_called()
            self.assertIn("禁止创建新任务", str(raised.exception))

    def test_upload_rejects_non_media_files_before_network_request(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "payload.txt")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("not media")
            client = PippitVideoClient()
            with mock.patch("urllib.request.urlopen") as request:
                with self.assertRaises(PippitVideoError) as raised:
                    client._upload_asset("access-key", "https://xyq.jianying.com", path)
            request.assert_not_called()
            self.assertIn("仅支持图片或视频", str(raised.exception))

    def test_api_base_rejects_non_official_host_to_protect_access_key(self) -> None:
        client = PippitVideoClient()
        with self.assertRaises(PippitVideoError) as raised:
            client._normalize_base("https://attacker.example.com")
        self.assertIn("官方接口地址", str(raised.exception))

        for unsafe_base in (
            "https://xyq.jianying.com:444",
            "https://xyq.jianying.com?redirect=https://attacker.example.com",
            "https://user@xyq.jianying.com",
        ):
            with self.subTest(unsafe_base=unsafe_base):
                with self.assertRaises(PippitVideoError):
                    client._normalize_base(unsafe_base)

    def test_download_rejects_html_even_when_content_type_claims_video(self) -> None:
        client = PippitVideoClient()

        class Response:
            headers = {"Content-Type": "video/mp4"}

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, *_args):
                return b"<html>gateway error</html>" * 100

        with mock.patch("urllib.request.urlopen", return_value=Response()):
            with self.assertRaises(PippitVideoError) as raised:
                client._download_video("https://cdn.example.com/result")
        self.assertIn("不是可播放视频", str(raised.exception))

    def test_download_rejects_oversized_response_before_reading_body(self) -> None:
        client = PippitVideoClient()

        class Response:
            headers = {"Content-Length": str(MAX_DOWNLOAD_BYTES + 1)}

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, *_args):
                raise AssertionError("oversized response body must not be read")

        with mock.patch("urllib.request.urlopen", return_value=Response()):
            with self.assertRaises(PippitVideoError) as raised:
                client._download_video("https://cdn.example.com/oversized")
        self.assertIn("超过 512MB", str(raised.exception))

    def test_download_rejects_insecure_or_local_urls_before_network_request(self) -> None:
        client = PippitVideoClient()
        with mock.patch("urllib.request.urlopen") as request:
            for unsafe_url in (
                "http://cdn.example.com/result.mp4",
                "https://127.0.0.1/result.mp4",
                "https://169.254.169.254/latest/meta-data/result.mp4",
                "https://user:pass@cdn.example.com/result.mp4",
            ):
                with self.subTest(unsafe_url=unsafe_url):
                    with self.assertRaises(PippitVideoError):
                        client._download_video(unsafe_url)
        request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
