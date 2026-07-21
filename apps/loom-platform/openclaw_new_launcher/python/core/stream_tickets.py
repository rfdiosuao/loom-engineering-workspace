from __future__ import annotations

import secrets
import threading
import time
from collections.abc import Callable
from typing import TypedDict


class StreamTicketGrant(TypedDict):
    topic: str
    resource: str
    subject: str
    expiresAt: float


class StreamTicketIssuer:
    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.time,
        ttl_seconds: int = 30,
        max_tickets: int = 4096,
    ) -> None:
        self._clock = clock
        self._ttl_seconds = min(30, max(1, int(ttl_seconds)))
        self._max_tickets = max(1, int(max_tickets))
        self._tickets: dict[str, StreamTicketGrant] = {}
        self._lock = threading.RLock()

    def _purge_expired(self, now: float) -> None:
        expired = [
            ticket
            for ticket, grant in self._tickets.items()
            if grant["expiresAt"] <= now
        ]
        for ticket in expired:
            self._tickets.pop(ticket, None)

    def issue(self, *, topic: str, resource: str, subject: str) -> str:
        with self._lock:
            now = self._clock()
            self._purge_expired(now)
            while len(self._tickets) >= self._max_tickets:
                self._tickets.pop(next(iter(self._tickets)))

            ticket = secrets.token_urlsafe(32)
            while ticket in self._tickets:
                ticket = secrets.token_urlsafe(32)
            self._tickets[ticket] = {
                "topic": topic,
                "resource": resource,
                "subject": subject,
                "expiresAt": now + self._ttl_seconds,
            }
        return ticket

    def consume(
        self,
        ticket: str,
        *,
        topic: str,
        resource: str,
        subject: str,
    ) -> StreamTicketGrant | None:
        with self._lock:
            grant = self._tickets.get(ticket)
            if grant is None:
                return None
            if grant["expiresAt"] <= self._clock():
                self._tickets.pop(ticket, None)
                return None
            if (
                grant["topic"] != topic
                or grant["resource"] != resource
                or grant["subject"] != subject
            ):
                return None
            return self._tickets.pop(ticket)
