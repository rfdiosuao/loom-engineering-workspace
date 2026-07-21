from __future__ import annotations

import json
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor

from python.core.agent_events import AgentEventBus
from python.core.agent_sessions import AgentSessionRepository


class AgentEventLedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.repository = AgentSessionRepository(self.temp_dir.name)
        self.repository.create_session(title="Events", session_id="session_events")
        self.bus = AgentEventBus(self.repository)

    def test_publish_assigns_monotonic_sequence_and_replays_after_sequence(self) -> None:
        first = self.bus.publish(
            "session_events",
            "tool.started",
            topic="agent.run",
            entity_id="run_1",
            event_id="evt_stable",
            timestamp="2026-07-16T00:00:00+00:00",
            data={"runId": "run_1", "toolCallId": "tool_1", "campaignId": "campaign_1"},
        )
        second = self.bus.publish(
            "session_events",
            "tool.completed",
            topic="agent.run",
            entity_id="run_1",
            data={"runId": "run_1", "toolCallId": "tool_1", "campaignId": "campaign_1"},
        )

        restarted = AgentEventBus(AgentSessionRepository(self.temp_dir.name))
        replay = restarted.replay("session_events", after_seq=1)

        self.assertEqual(first["eventId"], "evt_stable")
        self.assertEqual(first["timestamp"], "2026-07-16T00:00:00+00:00")
        self.assertEqual([first["seq"], second["seq"]], [1, 2])
        self.assertEqual(replay, [second])
        self.assertEqual(replay[0]["entityId"], "run_1")
        self.assertEqual(replay[0]["data"]["campaignId"], "campaign_1")

    def test_sequence_recovers_from_restart_and_malformed_jsonl_line(self) -> None:
        self.bus.publish(
            "session_events", "run.paused", topic="agent.run", entity_id="run_1", data={}
        )
        ledger_path = self._ledger_path()
        with open(ledger_path, "a", encoding="utf-8") as handle:
            handle.write("{malformed-event\n")

        restarted = AgentEventBus(AgentSessionRepository(self.temp_dir.name))
        event = restarted.publish(
            "session_events", "run.completed", topic="agent.run", entity_id="run_1", data={}
        )

        self.assertEqual(event["seq"], 2)
        self.assertEqual(
            [item["type"] for item in restarted.replay("session_events", after_seq=0)],
            ["run.paused", "run.completed"],
        )

    def test_concurrent_publish_keeps_jsonl_valid_and_sequences_unique(self) -> None:
        def publish(index: int) -> dict:
            return self.bus.publish(
                "session_events",
                "message.delta",
                topic="agent.message",
                entity_id="message_1",
                data={"index": index},
            )

        with ThreadPoolExecutor(max_workers=8) as executor:
            published = list(executor.map(publish, range(32)))

        self.assertEqual(sorted(event["seq"] for event in published), list(range(1, 33)))
        with open(self._ledger_path(), "r", encoding="utf-8") as handle:
            persisted = [json.loads(line) for line in handle if line.strip()]
        self.assertEqual(len(persisted), 32)
        self.assertEqual({event["eventId"] for event in persisted}, {event["eventId"] for event in published})

    def test_event_payload_is_redacted_before_publish_and_persistence(self) -> None:
        event = self.bus.publish(
            "session_events",
            "tool.completed",
            topic="agent.run",
            entity_id="run_secret",
            data={
                "toolInput": {"apiKey": "raw-event-key"},
                "toolOutput": "Bearer raw-event-token",
                "privateContent": "raw-private-output",
            },
        )

        with open(self._ledger_path(), "r", encoding="utf-8") as handle:
            persisted = handle.read()
        for secret in ("raw-event-key", "raw-event-token", "raw-private-output"):
            self.assertNotIn(secret, persisted)
        self.assertEqual(event["data"]["toolInput"]["apiKey"], "[REDACTED]")
        self.assertIn("[REDACTED]", event["data"]["toolOutput"])

    def _ledger_path(self) -> str:
        return os.path.join(
            self.temp_dir.name, "agent", "sessions", "session_events", "events.jsonl"
        )


if __name__ == "__main__":
    unittest.main()
