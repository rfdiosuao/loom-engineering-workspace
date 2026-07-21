from __future__ import annotations

import os
import unittest


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
APP_FILE = os.path.join(REPO_ROOT, "src", "App.tsx")
TERMINAL_FILE = os.path.join(REPO_ROOT, "src", "components", "terminal", "TerminalPage.tsx")


class TerminalLogContractTests(unittest.TestCase):
    def test_bridge_logs_are_polled_without_requiring_openclaw_service_state(self) -> None:
        with open(APP_FILE, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertNotIn("if (serviceRunning) startLogPolling();", source)
        self.assertNotIn("if (!commercialAccessGranted)", source)
        self.assertIn("lastLogPollingError", source)
        self.assertIn("message !== lastLogPollingError.current", source)
        self.assertRegex(
            source,
            r"useEffect\(\(\) => \{\s*startLogPolling\(\);[\s\S]+?\}, \[\]\);",
        )

    def test_terminal_page_defaults_to_real_errors_and_warnings(self) -> None:
        with open(TERMINAL_FILE, "r", encoding="utf-8") as handle:
            source = handle.read()

        for marker in (
            "type LogView = 'issues' | 'all'",
            "ERROR_OR_WARNING_PATTERN",
            "错误与警告",
            "全部日志",
            "当前没有错误或警告",
            "暂无运行日志",
        ):
            self.assertIn(marker, source)

        self.assertNotIn("127.0.0.1:18790", source)
        self.assertNotIn("Live Output", source)
        self.assertNotIn("等待服务启动...", source)


if __name__ == "__main__":
    unittest.main()
