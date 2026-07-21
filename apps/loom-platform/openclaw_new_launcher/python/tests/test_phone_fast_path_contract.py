from __future__ import annotations

import inspect
import os
import sys
import unittest


PYTHON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)


class PhoneFastPathContractTests(unittest.TestCase):
    def test_screenshot_uses_bridge_screenshot_endpoint_without_agent(self) -> None:
        from loom_cli import dispatch

        code, payload = dispatch(["phone", "screenshot", "--json", "--dry-run"])

        self.assertEqual(code, 0)
        self.assertEqual(payload["data"]["endpoint"], "/api/phone/screenshot")
        self.assertNotIn("maxRounds", payload["data"]["body"])

    def test_template_read_screen_uses_fast_read_path(self) -> None:
        from loom_cli import dispatch

        code, payload = dispatch(["phone", "template-task", "--template", "read-screen", "--json", "--dry-run"])

        self.assertEqual(code, 0)
        self.assertEqual(payload["data"]["endpoint"], "/api/phone/read")
        self.assertEqual(payload["data"]["body"]["profile"], "fast")
        self.assertEqual(payload["data"]["body"]["fastPath"], "observe_fast")

    def test_cli_read_screen_can_send_known_hash_for_incremental_observe(self) -> None:
        from loom_cli import dispatch

        code, payload = dispatch(["phone", "read", "--known-hash", "abc123", "--json", "--dry-run"])

        self.assertEqual(code, 0)
        self.assertEqual(payload["data"]["endpoint"], "/api/phone/read")
        self.assertEqual(payload["data"]["body"]["fastPath"], "observe_fast")
        self.assertEqual(payload["data"]["body"]["knownHash"], "abc123")

    def test_cli_task_modes_send_low_round_budgets_by_default(self) -> None:
        from loom_cli import dispatch

        cases = [
            ("observe", "observe", "fast", 4),
            ("safe", "safe", "fast", 12),
            ("full", "full", "standard", 30),
            ("deep", "full", "deep", 30),
        ]
        for requested_mode, expected_mode, expected_profile, expected_rounds in cases:
            with self.subTest(mode=requested_mode):
                code, payload = dispatch(
                    [
                        "phone",
                        "quick-task",
                        "--prompt",
                        "读取当前屏幕并返回可见内容" if requested_mode == "observe" else "打开设置并返回页面名称",
                        "--mode",
                        requested_mode,
                        "--permission",
                        "control",
                        "--json",
                        "--dry-run",
                    ]
                )

                self.assertEqual(code, 0)
                body = payload["data"]["body"]
                self.assertEqual(body["mode"], expected_mode)
                self.assertEqual(body["profile"], expected_profile)
                self.assertEqual(body["maxRounds"], expected_rounds)

    def test_cli_quick_task_passes_explicit_runtime_budget(self) -> None:
        from loom_cli import dispatch

        code, payload = dispatch(
            [
                "phone",
                "quick-task",
                "--prompt",
                "complete a complex multi-step phone flow",
                "--mode",
                "safe",
                "--profile",
                "standard",
                "--timeout-sec",
                "300",
                "--max-wait-sec",
                "320",
                "--max-rounds",
                "40",
                "--poll-ms",
                "700",
                "--permission",
                "control",
                "--json",
                "--dry-run",
            ]
        )

        self.assertEqual(code, 0)
        body = payload["data"]["body"]
        self.assertEqual(body["mode"], "safe")
        self.assertEqual(body["profile"], "standard")
        self.assertEqual(body["timeoutSec"], 300)
        self.assertEqual(body["maxWaitSec"], 320)
        self.assertEqual(body["maxRounds"], 40)
        self.assertEqual(body["pollMs"], 700)

    def test_deep_profile_is_only_used_when_explicitly_requested(self) -> None:
        from loom_cli import dispatch

        code, payload = dispatch(
            [
                "phone",
                "quick-task",
                "--prompt",
                "打开应用并完成多步骤任务",
                "--mode",
                "deep",
                "--permission",
                "control",
                "--json",
                "--dry-run",
            ]
        )

        self.assertEqual(code, 0)
        self.assertEqual(payload["data"]["endpoint"], "/api/phone/task")
        self.assertEqual(payload["data"]["body"]["profile"], "deep")
        self.assertEqual(payload["data"]["body"]["mode"], "full")
        self.assertEqual(payload["data"]["body"]["maxRounds"], 30)

    def test_observe_routes_allow_slow_devices_and_inherit_decrypted_phone_credentials(self) -> None:
        from api import routes_phone

        routes_source = inspect.getsource(routes_phone.register_phone_routes)
        process_source = inspect.getsource(routes_phone._run_phone_process_with_matrix_stream)

        self.assertGreaterEqual(routes_phone._PHONE_OBSERVE_TIMEOUT_SEC, 45)
        self.assertGreaterEqual(routes_phone._PHONE_OBSERVE_STEP_TIMEOUT_SEC, 30)
        self.assertGreaterEqual(routes_source.count("timeout_sec=_PHONE_OBSERVE_TIMEOUT_SEC"), 2)
        self.assertGreaterEqual(routes_source.count("step_timeout_sec=_PHONE_OBSERVE_STEP_TIMEOUT_SEC"), 2)
        self.assertGreaterEqual(routes_source.count("exact_timeout=True"), 2)
        self.assertIn("env=phone_process_env(ctx)", process_source)
        self.assertEqual(routes_phone._PHONE_RUNTIME_CONFIG_ENV, "LOOM_PHONE_RUNTIME_CONFIG_JSON")


if __name__ == "__main__":
    unittest.main()
