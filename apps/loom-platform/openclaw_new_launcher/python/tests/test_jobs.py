from __future__ import annotations

import os
import json
import sys
import tempfile
import threading
import time
import unittest


PYTHON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)


from services.jobs import JobManager


def wait_for_terminal(manager: JobManager, job_id: str, timeout: float = 2.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = manager.get(job_id)
        if job and job.get("status") in {"succeeded", "failed"}:
            return job
        time.sleep(0.02)
    raise AssertionError(f"job did not finish: {job_id}")


class JobManagerStateTests(unittest.TestCase):
    def test_cancel_waits_for_cooperative_worker_before_publishing_terminal_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = os.path.join(temp_dir, "jobs-state.json")
            manager = JobManager(lambda _message: None, state_path=state_path)
            started = threading.Event()
            finished = threading.Event()

            def target(job_id: str) -> dict:
                started.set()
                while not manager.is_cancelled(job_id):
                    time.sleep(0.01)
                finished.set()
                return {"success": False, "cancelled": True}

            submitted = manager.submit_progress("matrix.dispatch", "Matrix", target)
            self.assertTrue(started.wait(1))

            self.assertTrue(manager.cancel(submitted["id"]))
            snapshot = manager.get(submitted["id"])

            self.assertTrue(finished.is_set())
            self.assertEqual(snapshot["status"], "cancelled")

    def test_cancel_can_publish_terminal_state_without_waiting_for_worker(self) -> None:
        manager = JobManager(lambda _message: None)
        started = threading.Event()
        release = threading.Event()

        def target(job_id: str) -> dict:
            started.set()
            while not manager.is_cancelled(job_id):
                time.sleep(0.01)
            release.wait(1)
            return {"success": False, "cancelled": True}

        submitted = manager.submit_progress("matrix.dispatch", "Matrix", target)
        self.assertTrue(started.wait(1))

        started_at = time.monotonic()
        self.assertTrue(manager.cancel(submitted["id"], wait_for_worker=False))
        elapsed = time.monotonic() - started_at
        snapshot = manager.get(submitted["id"])
        release.set()

        self.assertLess(elapsed, 0.2)
        self.assertEqual(snapshot["status"], "cancelled")

    def test_consecutive_identical_progress_keeps_one_history_entry_and_updates_metadata(self) -> None:
        manager = JobManager(lambda _message: None)
        submitted = manager.submit_progress("component.install", "Install Codex", lambda _job_id: {"success": True})
        wait_for_terminal(manager, submitted["id"])

        manager.progress(
            submitted["id"],
            "Downloading Codex",
            "neutral",
            componentId="codex-desktop",
            phase="downloading",
            percent=10,
        )
        manager.progress(
            submitted["id"],
            "Downloading Codex",
            "neutral",
            componentId="codex-desktop",
            phase="downloading",
            percent=35,
        )

        deduped = manager.get(submitted["id"])
        self.assertIsNotNone(deduped)
        self.assertEqual(len(deduped["progress"]["history"]), 1)
        self.assertEqual(deduped["progress"]["percent"], 35)
        self.assertEqual(deduped["message"], "Downloading Codex")

        manager.progress(
            submitted["id"],
            "Downloading Codex",
            "neutral",
            componentId="claude-code",
            phase="downloading",
        )
        manager.progress(
            submitted["id"],
            "Downloading Codex",
            "neutral",
            componentId="claude-code",
            phase="verifying",
        )
        manager.progress(
            submitted["id"],
            "Downloading Codex",
            "warning",
            componentId="claude-code",
            phase="verifying",
        )

        distinct = manager.get(submitted["id"])
        self.assertIsNotNone(distinct)
        self.assertEqual(len(distinct["progress"]["history"]), 4)

    def test_finished_capability_job_remains_available_for_page_switch(self) -> None:
        logs: list[str] = []
        manager = JobManager(logs.append)

        def target(job_id: str) -> dict:
            manager.progress(job_id, "正在执行能力命令", "neutral", commandId="phone:agent")
            return {
                "success": True,
                "commandId": "phone:agent",
                "stdout": "{\"ok\":true}",
            }

        submitted = manager.submit_progress("cli", "手机 Agent", target)
        finished = wait_for_terminal(manager, submitted["id"])

        self.assertEqual(finished["status"], "succeeded")
        self.assertEqual(finished["kind"], "cli")
        self.assertEqual(finished["result"]["commandId"], "phone:agent")
        self.assertEqual(finished["progress"]["commandId"], "phone:agent")
        self.assertEqual(finished["progress"]["history"][-1]["message"], "正在执行能力命令")

        listed = manager.list(10)
        listed_job = next(job for job in listed if job["id"] == submitted["id"])
        self.assertEqual(listed_job["status"], "succeeded")
        self.assertEqual(listed_job["result"]["stdout"], "{\"ok\":true}")

    def test_failed_media_job_keeps_public_error_for_recent_tasks(self) -> None:
        logs: list[str] = []
        manager = JobManager(logs.append)

        def target(job_id: str) -> dict:
            manager.progress(job_id, "正在生成视频", "neutral")
            return {
                "success": False,
                "error": "视频服务密钥不能为空",
            }

        submitted = manager.submit_progress("video", "视频生成", target)
        finished = wait_for_terminal(manager, submitted["id"])

        self.assertEqual(finished["status"], "failed")
        self.assertEqual(finished["kind"], "video")
        self.assertEqual(finished["error"], "视频服务密钥不能为空")
        self.assertEqual(finished["progress"]["history"][-1]["message"], "正在生成视频")
        self.assertTrue(finished["failure"]["label"])

    def test_job_logs_identify_the_job_kind_and_label(self) -> None:
        logs: list[str] = []
        manager = JobManager(logs.append)

        submitted = manager.submit_progress(
            "phone.quick-task",
            "手机快速任务",
            lambda _job_id: {"success": False, "error": "device locked"},
        )
        wait_for_terminal(manager, submitted["id"])

        joined = "".join(logs)
        self.assertIn("[Job:phone.quick-task]", joined)
        self.assertIn("手机快速任务", joined)
        self.assertIn(submitted["id"], joined)


    def test_job_snapshot_exposes_xinflo_style_type_and_phase_without_losing_progress_history(self) -> None:
        logs: list[str] = []
        manager = JobManager(logs.append)

        def target(job_id: str) -> dict:
            manager.progress(job_id, "下载 Codex", "neutral", phase="downloading", percent=25)
            return {"success": True}

        submitted = manager.submit_progress("component.install", "Install Codex", target)

        self.assertEqual(submitted["type"], "component.install")
        self.assertEqual(submitted["phase"], "queued")

        finished = wait_for_terminal(manager, submitted["id"])

        self.assertEqual(finished["type"], "component.install")
        self.assertEqual(finished["phase"], "downloading")
        self.assertEqual(finished["progress"]["phase"], "downloading")
        self.assertEqual(finished["progress"]["percent"], 25)
        self.assertEqual(finished["progress"]["history"][-1]["message"], "下载 Codex")

    def test_finished_component_job_persists_for_bridge_restart(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = os.path.join(temp_dir, "jobs-state.json")
            logs: list[str] = []
            manager = JobManager(logs.append, state_path=state_path)

            def target(job_id: str) -> dict:
                manager.progress(job_id, "校验 Codex", "neutral", phase="verifying", componentId="codex-desktop")
                return {"success": True, "state": {"status": "ready"}}

            submitted = manager.submit_progress("component.install", "Install Codex", target)
            finished = wait_for_terminal(manager, submitted["id"])

            self.assertEqual(finished["status"], "succeeded")

            restarted = JobManager(logs.append, state_path=state_path)
            restored = restarted.get(submitted["id"])
            listed = restarted.list(10)

            self.assertIsNotNone(restored)
            self.assertEqual(restored["status"], "succeeded")
            self.assertEqual(restored["result"]["state"]["status"], "ready")
            self.assertEqual(restored["progress"]["componentId"], "codex-desktop")
            self.assertEqual(restored["progress"]["history"][-1]["message"], "校验 Codex")
            self.assertIn(submitted["id"], [job["id"] for job in listed])

    def test_large_structured_stdout_is_persisted_without_truncation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = os.path.join(temp_dir, "jobs-state.json")
            expected_stdout = '{"ok":true,"events":[' + ','.join(
                f'{{"round":{index},"message":"' + ("x" * 200) + '"}}'
                for index in range(100)
            ) + "]}"
            manager = JobManager(lambda _message: None, state_path=state_path)

            submitted = manager.submit(
                "phone.task",
                "Phone task",
                lambda: {"success": True, "stdout": expected_stdout},
            )
            finished = wait_for_terminal(manager, submitted["id"])
            restarted = JobManager(lambda _message: None, state_path=state_path)
            restored = restarted.get(submitted["id"])

        self.assertGreater(len(expected_stdout), 20_000)
        self.assertEqual(finished["result"]["stdout"], expected_stdout)
        self.assertEqual(restored["result"]["stdout"], expected_stdout)

    def test_single_large_job_uses_artifact_without_exceeding_state_budget(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = os.path.join(temp_dir, "jobs-state.json")
            expected_stdout = "x" * 20_000
            manager = JobManager(
                lambda _message: None,
                state_path=state_path,
                max_state_bytes=4096,
            )

            submitted = manager.submit(
                "phone.task",
                "Phone task",
                lambda: {"success": True, "stdout": expected_stdout},
            )
            wait_for_terminal(manager, submitted["id"])
            restarted = JobManager(
                lambda _message: None,
                state_path=state_path,
                max_state_bytes=4096,
            )
            state_bytes = os.path.getsize(state_path)
            restored_stdout = restarted.get(submitted["id"])["result"]["stdout"]

        self.assertLessEqual(state_bytes, 4096)
        self.assertEqual(restored_stdout, expected_stdout)

    def test_missing_result_artifact_restores_explicit_unavailable_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = os.path.join(temp_dir, "jobs-state.json")
            manager = JobManager(
                lambda _message: None,
                state_path=state_path,
                max_state_bytes=4096,
            )
            submitted = manager.submit(
                "matrix.dispatch",
                "Matrix",
                lambda: {"success": True, "stdout": "x" * 20_000, "stderr": "full stderr"},
            )
            wait_for_terminal(manager, submitted["id"])
            artifact_path = os.path.join(f"{state_path}.artifacts", f"{submitted['id']}.json")
            os.unlink(artifact_path)

            restored = JobManager(
                lambda _message: None,
                state_path=state_path,
                max_state_bytes=4096,
            ).get(submitted["id"])

        self.assertTrue(restored["result"]["resultUnavailable"])
        self.assertFalse(restored["result"]["success"])
        self.assertEqual(restored["result"]["error"], "job_result_unavailable")
        self.assertEqual(restored["result"]["reason"], "artifact_missing")

    def test_corrupt_result_artifact_restores_explicit_unavailable_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = os.path.join(temp_dir, "jobs-state.json")
            manager = JobManager(
                lambda _message: None,
                state_path=state_path,
                max_state_bytes=4096,
            )
            submitted = manager.submit(
                "matrix.dispatch",
                "Matrix",
                lambda: {"success": True, "stdout": "x" * 20_000, "stderr": "full stderr"},
            )
            wait_for_terminal(manager, submitted["id"])
            artifact_path = os.path.join(f"{state_path}.artifacts", f"{submitted['id']}.json")
            with open(artifact_path, "w", encoding="utf-8") as handle:
                handle.write("{not-json")

            restored = JobManager(
                lambda _message: None,
                state_path=state_path,
                max_state_bytes=4096,
            ).get(submitted["id"])

        self.assertTrue(restored["result"]["resultUnavailable"])
        self.assertFalse(restored["result"]["success"])
        self.assertEqual(restored["result"]["error"], "job_result_unavailable")
        self.assertEqual(restored["result"]["reason"], "artifact_corrupt")

    def test_valid_json_artifact_tampering_restores_explicit_corrupt_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = os.path.join(temp_dir, "jobs-state.json")
            manager = JobManager(
                lambda _message: None,
                state_path=state_path,
                max_state_bytes=4096,
            )
            submitted = manager.submit(
                "matrix.dispatch",
                "Matrix",
                lambda: {"success": True, "stdout": "x" * 20_000},
            )
            wait_for_terminal(manager, submitted["id"])
            artifact_path = os.path.join(f"{state_path}.artifacts", f"{submitted['id']}.json")
            with open(artifact_path, "w", encoding="utf-8") as handle:
                json.dump({"success": True, "stdout": "tampered"}, handle)
                handle.write("\n")

            restored = JobManager(
                lambda _message: None,
                state_path=state_path,
                max_state_bytes=4096,
            ).get(submitted["id"])

        self.assertEqual(restored["status"], "failed")
        self.assertTrue(restored["result"]["resultUnavailable"])
        self.assertEqual(restored["result"]["reason"], "artifact_corrupt")

    def test_matrix_artifact_preserves_full_stdout_and_stderr_above_generic_cap(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = os.path.join(temp_dir, "jobs-state.json")
            expected_stdout = "stdout-" + ("x" * 80_000)
            expected_stderr = "stderr-" + ("y" * 10_000)
            manager = JobManager(
                lambda _message: None,
                state_path=state_path,
                max_state_bytes=4096,
                max_artifact_bytes=64 * 1024,
            )
            submitted = manager.submit(
                "matrix.dispatch",
                "Matrix",
                lambda: {
                    "success": True,
                    "results": [{"stdout": expected_stdout, "stderr": expected_stderr}],
                },
            )
            wait_for_terminal(manager, submitted["id"])

            restored = JobManager(
                lambda _message: None,
                state_path=state_path,
                max_state_bytes=4096,
                max_artifact_bytes=64 * 1024,
            ).get(submitted["id"])

        self.assertEqual(restored["result"]["results"][0]["stdout"], expected_stdout)
        self.assertEqual(restored["result"]["results"][0]["stderr"], expected_stderr)

    def test_matrix_result_over_independent_hard_cap_fails_before_and_after_restart(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = os.path.join(temp_dir, "jobs-state.json")
            manager = JobManager(
                lambda _message: None,
                state_path=state_path,
                max_state_bytes=4096,
                max_artifact_bytes=256 * 1024,
                matrix_artifact_max_bytes=64 * 1024,
            )
            submitted = manager.submit(
                "matrix.dispatch",
                "Oversized Matrix result",
                lambda: {"success": True, "stdout": "x" * 70_000},
            )
            finished = wait_for_terminal(manager, submitted["id"])
            restored = JobManager(
                lambda _message: None,
                state_path=state_path,
                max_state_bytes=4096,
                max_artifact_bytes=256 * 1024,
                matrix_artifact_max_bytes=64 * 1024,
            ).get(submitted["id"])

        self.assertEqual(finished["status"], "failed")
        self.assertEqual(finished["result"]["errorCode"], "job_result_exceeded_artifact_limit")
        self.assertEqual(finished["result"]["maxArtifactBytes"], 64 * 1024)
        self.assertEqual(restored["status"], "failed")
        self.assertEqual(restored["result"], finished["result"])

    def test_result_over_artifact_limit_fails_consistently_before_and_after_restart(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = os.path.join(temp_dir, "jobs-state.json")
            manager = JobManager(
                lambda _message: None,
                state_path=state_path,
                max_state_bytes=4096,
                max_artifact_bytes=64 * 1024,
            )
            submitted = manager.submit(
                "phone.task",
                "Oversized phone task",
                lambda: {"success": True, "stdout": "x" * 70_000},
            )
            finished = wait_for_terminal(manager, submitted["id"])
            restarted = JobManager(
                lambda _message: None,
                state_path=state_path,
                max_state_bytes=4096,
                max_artifact_bytes=64 * 1024,
            )
            restored = restarted.get(submitted["id"])

        self.assertEqual(finished["status"], "failed")
        self.assertEqual(finished["result"]["errorCode"], "job_result_exceeded_artifact_limit")
        self.assertGreater(finished["result"]["originalBytes"], 64 * 1024)
        self.assertEqual(restored["status"], "failed")
        self.assertEqual(restored["result"], finished["result"])

    def test_invalid_utf8_state_is_quarantined_instead_of_breaking_startup(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = os.path.join(temp_dir, "jobs-state.json")
            with open(state_path, "wb") as handle:
                handle.write(b'{"jobs":' + bytes([0x80]))

            manager = JobManager(lambda _message: None, state_path=state_path)
            quarantined = [
                name for name in os.listdir(temp_dir)
                if name.startswith("jobs-state.json.corrupt-")
            ]

        self.assertEqual(manager.list(), [])
        self.assertEqual(len(quarantined), 1)

    def test_cancelled_job_cannot_be_overwritten_by_late_success(self) -> None:
        started = threading.Event()
        release = threading.Event()
        cancellation_observed = threading.Event()

        def append_log(message: str) -> None:
            if " cancelled" in message:
                cancellation_observed.set()

        manager = JobManager(append_log)

        def target(_job_id: str) -> dict:
            started.set()
            if not release.wait(timeout=3):
                raise AssertionError("late-success target was not released")
            return {"success": True}

        submitted = manager.submit_progress("matrix.dispatch", "Matrix", target)
        self.assertTrue(started.wait(timeout=3))
        self.assertTrue(manager.cancel(submitted["id"]))
        release.set()
        self.assertTrue(cancellation_observed.wait(timeout=3))

        self.assertEqual(manager.get(submitted["id"])["status"], "cancelled")

    def test_job_store_prunes_oldest_entries_at_configured_limit(self) -> None:
        manager = JobManager(lambda _message: None, max_jobs=3)
        submitted_ids = []
        for index in range(5):
            submitted = manager.submit(
                "test",
                f"Job {index}",
                lambda: {"success": True},
            )
            submitted_ids.append(submitted["id"])
            wait_for_terminal(manager, submitted["id"])

        listed_ids = [item["id"] for item in manager.list(10)]

        self.assertEqual(len(listed_ids), 3)
        self.assertNotIn(submitted_ids[0], listed_ids)
        self.assertNotIn(submitted_ids[1], listed_ids)

    def test_active_jobs_do_not_force_the_latest_terminal_result_out_of_history(self) -> None:
        manager = JobManager(lambda _message: None, max_jobs=1)
        release = __import__("threading").Event()
        active = manager.submit("test", "Active", lambda: (release.wait(30), {"success": True})[1])
        try:
            completed = manager.submit("test", "Completed", lambda: {"success": True})
            wait_for_terminal(manager, completed["id"])
            listed_ids = [item["id"] for item in manager.list(10)]
        finally:
            release.set()

        self.assertIn(active["id"], listed_ids)
        self.assertIn(completed["id"], listed_ids)

    def test_list_prunes_terminal_jobs_that_expire_without_a_restart(self) -> None:
        manager = JobManager(lambda _message: None, max_age_seconds=60)
        submitted = manager.submit("test", "Old", lambda: {"success": True})
        wait_for_terminal(manager, submitted["id"])
        with manager._lock:
            manager._jobs[submitted["id"]]["finishedAt"] = time.time() - 120
            manager._jobs[submitted["id"]]["updatedAt"] = time.time() - 120

        self.assertEqual(manager.list(), [])

    def test_persisted_terminal_jobs_expire_after_ttl(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = os.path.join(temp_dir, "jobs-state.json")
            old_time = time.time() - 8 * 24 * 60 * 60
            fresh_time = time.time()
            with open(state_path, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "jobs": {
                            "old": {"id": "old", "status": "succeeded", "createdAt": old_time, "updatedAt": old_time},
                            "fresh": {"id": "fresh", "status": "succeeded", "createdAt": fresh_time, "updatedAt": fresh_time},
                        }
                    },
                    handle,
                )

            manager = JobManager(lambda _message: None, state_path=state_path)

        self.assertIsNone(manager.get("old"))
        self.assertIsNotNone(manager.get("fresh"))

    def test_job_store_prunes_old_results_to_respect_byte_budget(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = os.path.join(temp_dir, "jobs-state.json")
            manager = JobManager(
                lambda _message: None,
                max_jobs=100,
                max_state_bytes=12_000,
                state_path=state_path,
            )
            submitted_ids = []
            for index in range(8):
                submitted = manager.submit(
                    "phone.task",
                    f"Job {index}",
                    lambda: {"success": True, "stdout": "x" * 3_000},
                )
                submitted_ids.append(submitted["id"])
                wait_for_terminal(manager, submitted["id"])

            listed_ids = [item["id"] for item in manager.list(100)]
            state_bytes = os.path.getsize(state_path)

        self.assertLessEqual(state_bytes, 12_000)
        self.assertIn(submitted_ids[-1], listed_ids)
        self.assertNotIn(submitted_ids[0], listed_ids)

    def test_running_job_snapshot_is_marked_interrupted_after_bridge_restart(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = os.path.join(temp_dir, "jobs-state.json")
            logs: list[str] = []
            manager = JobManager(logs.append, state_path=state_path)
            event = []

            def target(job_id: str) -> dict:
                manager.progress(job_id, "下载 Hermes", "neutral", phase="downloading", componentId="hermes")
                event.append(job_id)
                time.sleep(0.3)
                return {"success": True}

            submitted = manager.submit_progress("component.install", "Install Hermes", target)
            deadline = time.time() + 1
            while not event and time.time() < deadline:
                time.sleep(0.02)

            restarted = JobManager(logs.append, state_path=state_path)
            restored = restarted.get(submitted["id"])

            self.assertIsNotNone(restored)
            self.assertEqual(restored["status"], "failed")
            self.assertEqual(restored["phase"], "interrupted")
            self.assertIn("已中断", restored["error"])
            self.assertTrue(restored["failure"]["retryable"])
            self.assertEqual(restored["progress"]["componentId"], "hermes")


if __name__ == "__main__":
    unittest.main()
