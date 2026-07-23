from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from unittest.mock import patch

from python.core.agent_sessions import AgentSessionRepository


class AgentSessionRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.repository = AgentSessionRepository(self.temp_dir.name)

    def test_create_update_list_and_archive_session_in_exact_layout(self) -> None:
        first = self.repository.create_session(
            title="Alpha launch",
            runtime_profile_id="default",
            session_id="session_alpha",
        )
        second = self.repository.create_session(
            title="Beta review",
            runtime_profile_id="careful",
            session_id="session_beta",
        )

        expected_root = os.path.join(self.temp_dir.name, "agent")
        self.assertTrue(os.path.isfile(os.path.join(expected_root, "sessions-index.json")))
        self.assertTrue(
            os.path.isfile(os.path.join(expected_root, "sessions", first["sessionId"], "session.json"))
        )
        for ledger_name in ("messages.jsonl", "events.jsonl"):
            self.assertTrue(
                os.path.isfile(os.path.join(expected_root, "sessions", first["sessionId"], ledger_name))
            )
        for directory_name in ("runs", "approvals"):
            self.assertTrue(
                os.path.isdir(os.path.join(expected_root, "sessions", first["sessionId"], directory_name))
            )
        self.assertEqual(self.repository.get_session("session_beta"), second)

        updated = self.repository.update_session("session_alpha", {"title": "Alpha renamed"})
        self.assertEqual(updated["title"], "Alpha renamed")

        page = self.repository.list_sessions(query="alpha", limit=1)
        self.assertEqual([item["sessionId"] for item in page["sessions"]], ["session_alpha"])
        self.assertIsNone(page.get("nextCursor"))

        archived = self.repository.archive_session("session_alpha")
        self.assertEqual(archived["status"], "archived")
        self.assertTrue(os.path.isdir(os.path.join(expected_root, "sessions", "session_alpha")))
        self.assertEqual(self.repository.list_sessions()["sessions"], [second])
        self.assertEqual(
            [item["sessionId"] for item in self.repository.list_sessions(status="archived")["sessions"]],
            ["session_alpha"],
        )

    def test_session_cursor_pages_without_duplicates(self) -> None:
        for index in range(3):
            self.repository.create_session(
                title=f"Session {index}",
                session_id=f"session_{index}",
            )

        first_page = self.repository.list_sessions(limit=2)
        second_page = self.repository.list_sessions(limit=2, cursor=first_page["nextCursor"])

        first_ids = {item["sessionId"] for item in first_page["sessions"]}
        second_ids = {item["sessionId"] for item in second_page["sessions"]}
        self.assertEqual(len(first_ids), 2)
        self.assertEqual(len(second_ids), 1)
        self.assertFalse(first_ids & second_ids)
        self.assertIsNone(second_page.get("nextCursor"))

    def test_session_model_id_is_persisted_updated_and_cleared(self) -> None:
        created = self.repository.create_session(
            title="Model routing",
            model_id="qwen3.7-plus",
            session_id="session_model",
        )

        self.assertEqual(created["modelId"], "qwen3.7-plus")
        self.assertEqual(
            self.repository.get_session("session_model")["modelId"],
            "qwen3.7-plus",
        )

        updated = self.repository.update_session("session_model", {"modelId": "glm-5"})
        self.assertEqual(updated["modelId"], "glm-5")

        cleared = self.repository.update_session("session_model", {"modelId": ""})
        self.assertNotIn("modelId", cleared)
        self.assertNotIn("modelId", self.repository.get_session("session_model"))

    def test_corrupt_index_is_rebuilt_from_session_directories(self) -> None:
        session = self.repository.create_session(title="Recover me", session_id="session_recover")
        index_path = os.path.join(self.temp_dir.name, "agent", "sessions-index.json")
        with open(index_path, "w", encoding="utf-8") as handle:
            handle.write("{not-json")

        restarted = AgentSessionRepository(self.temp_dir.name)

        self.assertEqual(restarted.get_session("session_recover"), session)
        self.assertEqual(restarted.list_sessions()["sessions"], [session])
        with open(index_path, "r", encoding="utf-8") as handle:
            rebuilt = json.load(handle)
        self.assertEqual(rebuilt["sessions"]["session_recover"], session)

    def test_messages_page_from_newest_to_oldest_and_skip_a_corrupt_jsonl_record(self) -> None:
        self.repository.create_session(title="Messages", session_id="session_messages")
        for index in range(3):
            self.repository.append_message(
                "session_messages",
                {
                    "schema": "loom.agent.message.v1",
                    "messageId": f"message_{index}",
                    "sessionId": "session_messages",
                    "role": "assistant",
                    "status": "completed",
                    "blocks": [{"type": "text", "data": {"text": f"Reply {index}"}}],
                    "createdAt": f"2026-07-16T00:00:0{index}+00:00",
                    "completedAt": f"2026-07-16T00:00:0{index}+00:00",
                },
            )

        ledger_path = os.path.join(
            self.temp_dir.name, "agent", "sessions", "session_messages", "messages.jsonl"
        )
        with open(ledger_path, "a", encoding="utf-8") as handle:
            handle.write("{truncated")

        first_page = self.repository.page_messages("session_messages", limit=2)
        second_page = self.repository.page_messages(
            "session_messages", limit=2, cursor=first_page["nextCursor"]
        )

        self.assertEqual(
            [message["messageId"] for message in first_page["messages"]],
            ["message_1", "message_2"],
        )
        self.assertEqual(
            [message["messageId"] for message in second_page["messages"]],
            ["message_0"],
        )

    def test_runs_and_approvals_are_created_updated_and_read_by_stable_id(self) -> None:
        self.repository.create_session(title="Run state", session_id="session_state")
        run = self.repository.create_run(
            {
                "schema": "loom.agent.run.v1",
                "runId": "run_state",
                "sessionId": "session_state",
                "status": "queued",
                "campaignIds": [],
            }
        )
        self.assertEqual(self.repository.get_run("run_state"), run)
        updated_run = self.repository.update_run(
            "run_state", {"status": "running", "startedAt": "2026-07-16T00:00:00+00:00"}
        )
        self.assertEqual(updated_run["status"], "running")

        approval = self.repository.create_approval(
            {
                "schema": "loom.agent.approval.v1",
                "approvalId": "approval_state",
                "sessionId": "session_state",
                "runId": "run_state",
                "toolCallId": "tool_state",
                "capability": "loom.phone.publish",
                "inputHash": "sha256:" + "0" * 64,
                "actionSummary": "Publish one post",
                "targets": {"deviceIds": ["phone_1"]},
                "inputSummary": {"platform": "douyin"},
                "risk": "outbound",
                "riskReason": "External write",
                "status": "pending",
                "requestedAt": "2026-07-16T00:00:00+00:00",
                "expiresAt": "2026-07-16T00:05:00+00:00",
            }
        )
        self.assertEqual(self.repository.get_approval("approval_state"), approval)
        resolved = self.repository.update_approval(
            "approval_state",
            {
                "status": "approved",
                "decision": "approved",
                "decidedBy": "operator",
                "decidedAt": "2026-07-16T00:01:00+00:00",
            },
        )
        self.assertEqual(resolved["status"], "approved")

    def test_approval_compare_and_swap_has_one_winner(self) -> None:
        from python.core.agent_sessions import RepositoryConflictError

        self.repository.create_session(title="Approval CAS", session_id="session_cas")
        self.repository.create_approval(
            {
                "approvalId": "approval_cas",
                "sessionId": "session_cas",
                "runId": "run_cas",
                "status": "pending",
            }
        )
        ready = threading.Barrier(2)
        winners: list[dict] = []
        conflicts: list[RepositoryConflictError] = []

        def approve(decided_by: str) -> None:
            ready.wait()
            try:
                winners.append(
                    self.repository.compare_and_update_approval(
                        "approval_cas",
                        {"status": "approved", "decidedBy": decided_by},
                        expected_status="pending",
                        session_id="session_cas",
                    )
                )
            except RepositoryConflictError as exc:
                conflicts.append(exc)

        workers = [threading.Thread(target=approve, args=(f"user-{index}",)) for index in range(2)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(2)

        self.assertTrue(all(not worker.is_alive() for worker in workers))
        self.assertEqual(len(winners), 1)
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(self.repository.get_approval("approval_cas")["decidedBy"], winners[0]["decidedBy"])

    def test_recover_unfinished_runs_after_restart(self) -> None:
        self.repository.create_session(title="Recovery", session_id="session_runs")
        for run_id, status in (
            ("run_running", "running"),
            ("run_paused", "paused"),
            ("run_done", "completed"),
        ):
            self.repository.create_run(
                {
                    "schema": "loom.agent.run.v1",
                    "runId": run_id,
                    "sessionId": "session_runs",
                    "status": status,
                    "campaignIds": [],
                }
            )

        restarted = AgentSessionRepository(self.temp_dir.name)
        recovered = restarted.recover_unfinished_runs()

        self.assertEqual({run["runId"] for run in recovered}, {"run_running", "run_paused"})
        self.assertEqual(restarted.get_session("session_runs")["activeRunId"], "run_paused")

    def test_run_update_only_removes_allowlisted_transient_fields(self) -> None:
        self.repository.create_session(title="Transient fields", session_id="session_transient")
        self.repository.create_run(
            {
                "schema": "loom.agent.run.v1",
                "runId": "run_transient",
                "sessionId": "session_transient",
                "status": "paused",
                "campaignIds": [],
                "error": {
                    "code": "agent_restart_recovery",
                    "message": "safe to resume",
                    "recoverable": True,
                },
                "completedAt": "2026-07-23T00:00:00Z",
            }
        )

        updated = self.repository.update_run(
            "run_transient",
            {"status": "queued"},
            remove_fields=("error", "completedAt"),
        )

        self.assertEqual(updated["status"], "queued")
        self.assertNotIn("error", updated)
        self.assertNotIn("completedAt", updated)
        with self.assertRaisesRegex(ValueError, "run field cannot be removed"):
            self.repository.update_run(
                "run_transient",
                {},
                remove_fields=("runId",),
            )
        self.assertEqual(self.repository.get_run("run_transient")["runId"], "run_transient")

    def test_client_message_id_is_idempotent_after_restart_and_index_rebuild(self) -> None:
        self.repository.create_session(title="Idempotency", session_id="session_idempotent")
        first = self.repository.create_message_run(
            "session_idempotent",
            "client-message-1",
            self._message("message_first", "session_idempotent", "Hello"),
            self._run("run_first", "session_idempotent"),
        )
        index_path = os.path.join(self.temp_dir.name, "agent", "sessions-index.json")
        with open(index_path, "w", encoding="utf-8") as handle:
            handle.write("corrupt")

        restarted = AgentSessionRepository(self.temp_dir.name)
        duplicate = restarted.create_message_run(
            "session_idempotent",
            "client-message-1",
            self._message("message_duplicate", "session_idempotent", "Hello again"),
            self._run("run_duplicate", "session_idempotent"),
        )

        self.assertTrue(first["created"])
        self.assertFalse(duplicate["created"])
        self.assertEqual(duplicate["message"]["messageId"], "message_first")
        self.assertEqual(duplicate["run"]["runId"], "run_first")
        self.assertEqual(
            [message["messageId"] for message in restarted.page_messages("session_idempotent")["messages"]],
            ["message_first"],
        )
        with self.assertRaises(KeyError):
            restarted.get_run("run_duplicate")

    def test_incomplete_message_transaction_recovers_without_duplicate_run(self) -> None:
        self.repository.create_session(title="Crash recovery", session_id="session_crash")
        with patch("python.core.agent_sessions._append_jsonl", side_effect=OSError("simulated crash")):
            with self.assertRaises(OSError):
                self.repository.create_message_run(
                    "session_crash",
                    "client-crash-1",
                    self._message("message_original", "session_crash", "Original"),
                    self._run("run_original", "session_crash"),
                )

        restarted = AgentSessionRepository(self.temp_dir.name)
        duplicate = restarted.create_message_run(
            "session_crash",
            "client-crash-1",
            self._message("message_duplicate", "session_crash", "Duplicate"),
            self._run("run_duplicate", "session_crash"),
        )

        self.assertFalse(duplicate["created"])
        self.assertEqual(duplicate["message"]["messageId"], "message_original")
        self.assertEqual(duplicate["run"]["runId"], "run_original")
        self.assertEqual(
            [message["messageId"] for message in restarted.page_messages("session_crash")["messages"]],
            ["message_original"],
        )
        accepted = next(
            event
            for event in restarted.replay_events("session_crash")
            if event["data"].get("clientMessageId") == "client-crash-1"
        )
        self.assertEqual(accepted["data"]["message"]["messageId"], "message_original")
        self.assertEqual(accepted["data"]["message"]["role"], "user")
        with self.assertRaises(KeyError):
            restarted.get_run("run_duplicate")

    def test_session_metadata_is_sanitized_before_persistence(self) -> None:
        created = self.repository.create_session(
            title="Secret sk-session-title-123456789",
            runtime_profile_id="Bearer raw-runtime-token",
            session_id="session_metadata",
        )
        updated = self.repository.update_session(
            "session_metadata",
            {"title": "Authorization: Bearer updated-secret-token"},
        )

        self.assertNotIn("sk-session-title-123456789", created["title"])
        self.assertNotIn("raw-runtime-token", created["runtimeProfileId"])
        self.assertNotIn("updated-secret-token", updated["title"])
        with open(
            os.path.join(self.temp_dir.name, "agent", "sessions", "session_metadata", "session.json"),
            "r",
            encoding="utf-8",
        ) as handle:
            persisted = handle.read()
        self.assertNotIn("sk-session-title-123456789", persisted)
        self.assertNotIn("raw-runtime-token", persisted)
        self.assertNotIn("updated-secret-token", persisted)

    def test_secret_and_private_fields_are_redacted_before_any_payload_reaches_disk(self) -> None:
        self.repository.create_session(title="Redaction", session_id="session_redaction")
        self.repository.append_message(
            "session_redaction",
            self._message(
                "message_secret",
                "session_redaction",
                "Authorization: Bearer raw-bearer-value and " + "sk-" + "rawpromptcredential123456",
                extra={
                    "apiKey": "raw-api-key",
                    "privateContent": "raw-private-chat",
                    "nested": {"cookie": "raw-cookie"},
                },
            ),
        )
        self.repository.create_approval(
            {
                "schema": "loom.agent.approval.v1",
                "approvalId": "approval_secret",
                "sessionId": "session_redaction",
                "runId": "run_secret",
                "toolCallId": "tool_secret",
                "capability": "loom.phone.publish",
                "inputHash": "sha256:" + "1" * 64,
                "actionSummary": "Publish",
                "targets": {"deviceIds": ["phone_1"], "accessToken": "raw-access-token"},
                "inputSummary": {"password": "raw-password"},
                "risk": "critical",
                "riskReason": "Writes externally",
                "status": "pending",
                "requestedAt": "2026-07-16T00:00:00+00:00",
                "expiresAt": "2026-07-16T00:05:00+00:00",
            }
        )

        session_dir = os.path.join(self.temp_dir.name, "agent", "sessions", "session_redaction")
        persisted = ""
        for root, _directories, filenames in os.walk(session_dir):
            for filename in filenames:
                with open(os.path.join(root, filename), "r", encoding="utf-8") as handle:
                    persisted += handle.read()
        for secret in (
            "raw-bearer-value",
            "raw-api-key",
            "raw-private-chat",
            "raw-cookie",
            "raw-access-token",
            "raw-password",
            "sk-" + "rawpromptcredential123456",
        ):
            self.assertNotIn(secret, persisted)
        self.assertIn("[REDACTED]", persisted)

    @staticmethod
    def _message(message_id: str, session_id: str, text: str, extra: dict | None = None) -> dict:
        data = {"text": text}
        data.update(extra or {})
        return {
            "schema": "loom.agent.message.v1",
            "messageId": message_id,
            "sessionId": session_id,
            "role": "user",
            "status": "completed",
            "blocks": [{"type": "text", "data": data}],
            "createdAt": "2026-07-16T00:00:00+00:00",
            "completedAt": "2026-07-16T00:00:00+00:00",
        }

    @staticmethod
    def _run(run_id: str, session_id: str) -> dict:
        return {
            "schema": "loom.agent.run.v1",
            "runId": run_id,
            "sessionId": session_id,
            "status": "queued",
            "campaignIds": [],
        }


if __name__ == "__main__":
    unittest.main()
