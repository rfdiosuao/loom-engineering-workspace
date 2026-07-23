from __future__ import annotations

import os
import sys
import tempfile
import unittest


PYTHON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)


from core.agent_session_retention import (
    SessionRetentionError,
    assert_agent_sessions_preserved,
    capture_agent_session_inventory,
    resolve_agent_session_home,
)


class AgentSessionRetentionTests(unittest.TestCase):
    def test_resolve_codex_home_preserves_explicit_customer_namespace(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            custom_home = os.path.join(temp_dir, "customer-codex")

            resolved = resolve_agent_session_home(
                "codex-desktop",
                env={"CODEX_HOME": custom_home},
                user_home=os.path.join(temp_dir, "profile"),
            )

            self.assertEqual(resolved["homePath"], os.path.abspath(custom_home))
            self.assertEqual(resolved["homeSource"], "CODEX_HOME")

    def test_capture_codex_inventory_counts_active_and_archived_threads_without_reading_content(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            active_dir = os.path.join(temp_dir, "sessions", "2026", "07")
            archived_dir = os.path.join(temp_dir, "archived_sessions")
            os.makedirs(active_dir, exist_ok=True)
            os.makedirs(archived_dir, exist_ok=True)
            for path in (
                os.path.join(active_dir, "one.jsonl"),
                os.path.join(active_dir, "two.JSONL"),
                os.path.join(archived_dir, "old.jsonl"),
            ):
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write("content must not be parsed\n")
            with open(os.path.join(temp_dir, "state_5.sqlite"), "wb") as handle:
                handle.write(b"not-a-real-database")

            inventory = capture_agent_session_inventory("codex-desktop", home_path=temp_dir)

            self.assertEqual(inventory["activeThreads"], 2)
            self.assertEqual(inventory["archivedThreads"], 1)
            self.assertEqual(inventory["totalThreads"], 3)
            self.assertTrue(inventory["indexes"]["stateDatabase"])

    def test_capture_claude_inventory_counts_project_threads(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_dir = os.path.join(temp_dir, "projects", "customer-project")
            os.makedirs(project_dir, exist_ok=True)
            for name in ("one.jsonl", "two.jsonl"):
                with open(os.path.join(project_dir, name), "w", encoding="utf-8") as handle:
                    handle.write("{}\n")

            inventory = capture_agent_session_inventory("claude-code", home_path=temp_dir)

            self.assertEqual(inventory["projectThreads"], 2)
            self.assertEqual(inventory["totalThreads"], 2)

    def test_guard_rejects_home_changes_and_thread_loss(self) -> None:
        baseline = {
            "componentId": "codex-desktop",
            "homePath": r"C:\Users\customer\.codex",
            "totalThreads": 8,
            "indexes": {"stateDatabase": True},
        }

        with self.assertRaises(SessionRetentionError):
            assert_agent_sessions_preserved(
                baseline,
                {**baseline, "homePath": r"D:\LOOM\data\.codex"},
            )
        with self.assertRaises(SessionRetentionError):
            assert_agent_sessions_preserved(
                baseline,
                {**baseline, "totalThreads": 7},
            )
        with self.assertRaises(SessionRetentionError):
            assert_agent_sessions_preserved(
                baseline,
                {**baseline, "indexes": {"stateDatabase": False}},
            )


if __name__ == "__main__":
    unittest.main()
