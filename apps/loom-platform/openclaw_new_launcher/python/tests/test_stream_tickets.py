from __future__ import annotations

import unittest

from core.stream_tickets import StreamTicketIssuer


class FakeClock:
    def __init__(self, value: float = 1_000.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class StreamTicketIssuerTests(unittest.TestCase):
    def test_ticket_is_single_use_and_bound_to_topic_resource_and_subject(self) -> None:
        clock = FakeClock()
        issuer = StreamTicketIssuer(clock=clock, ttl_seconds=30)

        ticket = issuer.issue(topic="matrix", resource="all", subject="desktop")

        self.assertIsNone(issuer.consume(ticket, topic="agent", resource="all", subject="desktop"))
        self.assertIsNone(issuer.consume(ticket, topic="matrix", resource="campaign-1", subject="desktop"))
        self.assertIsNone(issuer.consume(ticket, topic="matrix", resource="all", subject="other-desktop"))
        grant = issuer.consume(ticket, topic="matrix", resource="all", subject="desktop")
        self.assertIsNotNone(grant)
        self.assertEqual(grant["subject"], "desktop")
        self.assertEqual(grant["resource"], "all")
        self.assertIsNone(issuer.consume(ticket, topic="matrix", resource="all", subject="desktop"))

    def test_expired_ticket_cannot_be_consumed(self) -> None:
        clock = FakeClock()
        issuer = StreamTicketIssuer(clock=clock, ttl_seconds=5)
        ticket = issuer.issue(topic="agent", resource="session-1", subject="desktop")

        clock.advance(5)

        self.assertIsNone(issuer.consume(ticket, topic="agent", resource="session-1", subject="desktop"))

    def test_ticket_ttl_is_clamped_to_thirty_seconds(self) -> None:
        clock = FakeClock()
        issuer = StreamTicketIssuer(clock=clock, ttl_seconds=300)
        ticket = issuer.issue(topic="matrix", resource="all", subject="desktop")

        clock.advance(30.001)

        self.assertIsNone(issuer.consume(ticket, topic="matrix", resource="all", subject="desktop"))

    def test_ticket_ttl_has_one_second_minimum(self) -> None:
        clock = FakeClock()
        issuer = StreamTicketIssuer(clock=clock, ttl_seconds=0)
        ticket = issuer.issue(topic="matrix", resource="all", subject="desktop")

        clock.advance(0.999)

        self.assertIsNotNone(issuer.consume(ticket, topic="matrix", resource="all", subject="desktop"))

    def test_issue_purges_expired_unconsumed_tickets(self) -> None:
        clock = FakeClock()
        issuer = StreamTicketIssuer(clock=clock, ttl_seconds=5)
        expired_ticket = issuer.issue(topic="agent", resource="session-1", subject="desktop")

        clock.advance(5)
        current_ticket = issuer.issue(topic="matrix", resource="all", subject="desktop")

        self.assertNotIn(expired_ticket, issuer._tickets)
        self.assertIn(current_ticket, issuer._tickets)
        self.assertEqual(len(issuer._tickets), 1)

    def test_issue_keeps_ticket_state_bounded(self) -> None:
        clock = FakeClock()
        issuer = StreamTicketIssuer(clock=clock, max_tickets=2)

        oldest_ticket = issuer.issue(topic="matrix", resource="all", subject="desktop-1")
        retained_ticket = issuer.issue(topic="matrix", resource="all", subject="desktop-2")
        newest_ticket = issuer.issue(topic="matrix", resource="all", subject="desktop-3")

        self.assertEqual(len(issuer._tickets), 2)
        self.assertIsNone(issuer.consume(oldest_ticket, topic="matrix", resource="all", subject="desktop-1"))
        self.assertIsNotNone(issuer.consume(retained_ticket, topic="matrix", resource="all", subject="desktop-2"))
        self.assertIsNotNone(issuer.consume(newest_ticket, topic="matrix", resource="all", subject="desktop-3"))


if __name__ == "__main__":
    unittest.main()
