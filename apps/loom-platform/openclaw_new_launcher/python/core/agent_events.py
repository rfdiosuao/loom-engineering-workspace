"""Unified, replayable event publishing for central agent sessions."""

from __future__ import annotations

import copy
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from .agent_sessions import AgentSessionRepository, sanitize_for_storage


JsonObject = Dict[str, Any]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AgentEventBus:
    """Publish schema-versioned events and replay them by session sequence."""

    def __init__(self, repository: Any) -> None:
        if hasattr(repository, "append_event") and hasattr(repository, "replay_events"):
            self.repository = repository
        else:
            self.repository = AgentSessionRepository(repository)

    def publish(
        self,
        session_id: str,
        event_type: Any,
        *,
        topic: Optional[str] = None,
        entity_id: Optional[str] = None,
        data: Optional[JsonObject] = None,
        event_id: Optional[str] = None,
        timestamp: Optional[str] = None,
    ) -> JsonObject:
        if isinstance(event_type, dict):
            supplied = copy.deepcopy(event_type)
            event_name = supplied.get("type")
            topic = supplied.get("topic", topic)
            entity_id = supplied.get("entityId", entity_id)
            data = supplied.get("data", data)
            event_id = supplied.get("eventId", event_id)
            timestamp = supplied.get("timestamp", timestamp)
        else:
            event_name = event_type
        if not isinstance(event_name, str) or not event_name:
            raise ValueError("event type is required")
        if not isinstance(topic, str) or not topic:
            raise ValueError("event topic is required")
        if not isinstance(entity_id, str) or not entity_id:
            raise ValueError("event entity_id is required")
        if data is not None and not isinstance(data, dict):
            raise ValueError("event data must be an object")
        event = {
            "schema": "loom.realtime.event.v1",
            "eventId": event_id or "evt_" + uuid.uuid4().hex,
            "seq": 0,
            "timestamp": timestamp or _utc_now(),
            "topic": topic,
            "entityId": entity_id,
            "type": event_name,
            "data": sanitize_for_storage(data or {}),
        }
        return self.repository.append_event(session_id, event)

    def replay(
        self,
        session_id: str,
        after_seq: int = 0,
        limit: Optional[int] = None,
    ) -> list[JsonObject]:
        return self.repository.replay_events(session_id, after_seq=after_seq, limit=limit)
