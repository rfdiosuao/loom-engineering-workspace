from __future__ import annotations

import sqlite3
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlparse

from test_license_flow import load_server
from luming_license import db
from luming_license.domains import relay
from luming_license.errors import ActivationError
from luming_license.http import routes_relay


class InterleavingCompletionConnection:
    def __init__(self, connection: sqlite3.Connection, replace_lease) -> None:
        self.connection = connection
        self.replace_lease = replace_lease
        self.replaced = False

    def __enter__(self):
        self.connection.__enter__()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return self.connection.__exit__(exc_type, exc_value, traceback)

    def execute(self, sql: str, parameters=()):
        normalized = " ".join(sql.lower().split())
        if normalized.startswith("update publish_relay_packets") and not self.replaced:
            self.replace_lease()
            self.replaced = True
        return self.connection.execute(sql, parameters)

    def __getattr__(self, name: str):
        return getattr(self.connection, name)


class RelayModuleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.server = load_server(Path(self.temp.name))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def connect_with_timeout(self, timeout: float = 0.01) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.server.SETTINGS.db_path,
            timeout=timeout,
            factory=db.ClosingConnection,
        )
        connection.row_factory = sqlite3.Row
        return connection

    def test_enqueue_claim_complete_round_trip(self) -> None:
        queued = relay.publish_relay_enqueue(
            {
                "schema": "openclaw.publish.packet.v1",
                "channelId": "matrix",
                "title": "module relay",
            },
            settings=self.server.SETTINGS,
            defaults=self.server.DB_DEFAULTS,
        )
        claimed = relay.publish_relay_claim(
            "matrix",
            "module-client",
            30000,
            settings=self.server.SETTINGS,
            defaults=self.server.DB_DEFAULTS,
        )
        self.assertEqual(queued["id"], claimed["id"])
        completed = self.server.publish_relay_complete({
            "id": claimed["id"], "leaseId": claimed["leaseId"],
            "clientId": "module-client",
            "success": True, "result": {"ok": True},
        })
        self.assertEqual("done", completed["status"])

    def test_facade_claim_accepts_a_zero_argument_connect_replacement(self) -> None:
        queued = self.server.publish_relay_enqueue({
            "schema": "openclaw.publish.packet.v1",
            "channelId": "zero-argument-connect",
        })
        original_connect = self.server.connect
        calls = 0

        def zero_argument_connect() -> sqlite3.Connection:
            nonlocal calls
            calls += 1
            return original_connect()

        self.server.connect = zero_argument_connect
        try:
            claimed = self.server.publish_relay_claim(
                "zero-argument-connect", "facade-client", 30_000
            )
        finally:
            self.server.connect = original_connect

        self.assertEqual(queued["id"], claimed["id"])
        self.assertEqual(1, calls)

    def test_facade_claim_passes_bounded_timeout_to_aware_connect(self) -> None:
        queued = self.server.publish_relay_enqueue({
            "schema": "openclaw.publish.packet.v1",
            "channelId": "timeout-aware-connect",
        })
        with patch.object(db, "connect", wraps=db.connect) as production_connect:
            claimed = self.server.publish_relay_claim(
                "timeout-aware-connect", "facade-client", 30_000
            )

        self.assertEqual(queued["id"], claimed["id"])
        self.assertEqual(
            relay.PUBLISH_RELAY_CLAIM_CONNECT_TIMEOUT_SECONDS,
            production_connect.call_args.kwargs["timeout"],
        )

    def test_facade_claim_does_not_swallow_collaborator_type_error(self) -> None:
        self.server.publish_relay_enqueue({
            "schema": "openclaw.publish.packet.v1",
            "channelId": "connect-type-error",
        })
        original_connect = self.server.connect
        calls = 0

        def failing_connect(*, timeout: float = 5.0) -> sqlite3.Connection:
            nonlocal calls
            calls += 1
            raise TypeError("connect collaborator failed internally")

        self.server.connect = failing_connect
        try:
            with self.assertRaisesRegex(TypeError, "failed internally"):
                self.server.publish_relay_claim(
                    "connect-type-error", "facade-client", 30_000
                )
        finally:
            self.server.connect = original_connect

        self.assertEqual(1, calls)

    def test_stale_completer_cannot_overwrite_a_newer_lease(self) -> None:
        queued = relay.publish_relay_enqueue(
            {
                "schema": "openclaw.publish.packet.v1",
                "channelId": "stale-completion",
            },
            settings=self.server.SETTINGS,
            defaults=self.server.DB_DEFAULTS,
        )
        claimed = relay.publish_relay_claim(
            "stale-completion",
            "old-client",
            30_000,
            settings=self.server.SETTINGS,
            defaults=self.server.DB_DEFAULTS,
            lease_id_fn=lambda: "old-lease",
        )
        self.assertIsNotNone(claimed)

        def replace_lease() -> None:
            with self.connect_with_timeout(timeout=1) as winner:
                winner.execute(
                    """
                    update publish_relay_packets
                    set status = 'leased', lease_id = 'new-lease',
                        leased_by = 'new-client', lease_until_ms = lease_until_ms + 30000,
                        attempts = attempts + 1
                    where packet_id = ?
                    """,
                    (queued["id"],),
                )
                winner.commit()

        def interleaving_connect():
            return InterleavingCompletionConnection(
                self.connect_with_timeout(timeout=1),
                replace_lease,
            )

        with self.assertRaises(ActivationError) as raised:
            relay.publish_relay_complete(
                {
                    "packetId": queued["id"],
                    "leaseId": "old-lease",
                    "clientId": "old-client",
                    "success": True,
                    "result": {"winner": "old"},
                },
                settings=self.server.SETTINGS,
                defaults=self.server.DB_DEFAULTS,
                connect_fn=interleaving_connect,
            )

        self.assertEqual(409, raised.exception.status)
        current = relay.publish_relay_status(
            queued["id"],
            settings=self.server.SETTINGS,
            defaults=self.server.DB_DEFAULTS,
        )
        self.assertEqual("leased", current["status"])
        self.assertEqual("new-lease", current["leaseId"])
        self.assertEqual("new-client", current["leasedBy"])
        self.assertNotIn("result", current)

    def test_completion_requires_lease_and_client_identity(self) -> None:
        for missing_field in ("leaseId", "clientId"):
            with self.subTest(missing_field=missing_field):
                queued = relay.publish_relay_enqueue(
                    {
                        "schema": "openclaw.publish.packet.v1",
                        "channelId": f"missing-{missing_field}",
                    },
                    settings=self.server.SETTINGS,
                    defaults=self.server.DB_DEFAULTS,
                )
                claimed = relay.publish_relay_claim(
                    f"missing-{missing_field}",
                    "completion-client",
                    30_000,
                    settings=self.server.SETTINGS,
                    defaults=self.server.DB_DEFAULTS,
                )
                self.assertIsNotNone(claimed)
                body = {
                    "packetId": queued["id"],
                    "leaseId": claimed["leaseId"],
                    "clientId": "completion-client",
                    "success": True,
                }
                del body[missing_field]

                with self.assertRaises(ActivationError) as raised:
                    relay.publish_relay_complete(
                        body,
                        settings=self.server.SETTINGS,
                        defaults=self.server.DB_DEFAULTS,
                    )

                self.assertEqual(400, raised.exception.status)

    def test_concurrent_claimers_cannot_claim_the_same_packet(self) -> None:
        claimant_count = 12
        queued = relay.publish_relay_enqueue(
            {
                "schema": "openclaw.publish.packet.v1",
                "channelId": "concurrent-matrix",
                "title": "concurrent relay claim",
            },
            settings=self.server.SETTINGS,
            defaults=self.server.DB_DEFAULTS,
        )
        start = threading.Barrier(claimant_count)
        selected = threading.Barrier(claimant_count)
        selection_lock = threading.Lock()
        selection_count = 0

        def lease_id() -> str:
            nonlocal selection_count
            with selection_lock:
                selection_count += 1
            selected.wait(timeout=5)
            return f"lease-{threading.get_ident()}"

        def claim(index: int) -> dict[str, object] | None:
            start.wait(timeout=10)
            return relay.publish_relay_claim(
                "concurrent-matrix",
                f"claimer-{index}",
                30_000,
                settings=self.server.SETTINGS,
                defaults=self.server.DB_DEFAULTS,
                lease_id_fn=lease_id,
            )

        with ThreadPoolExecutor(max_workers=claimant_count) as executor:
            futures = [executor.submit(claim, index) for index in range(claimant_count)]
            results = [future.result(timeout=20) for future in futures]

        claimed = [result for result in results if result is not None]
        self.assertEqual(claimant_count, selection_count)
        self.assertFalse(selected.broken)
        self.assertEqual(1, len(claimed))
        self.assertEqual(queued["id"], claimed[0]["id"])
        self.assertEqual(1, claimed[0]["attempts"])

    def test_empty_poll_does_not_wait_for_an_unrelated_writer(self) -> None:
        with self.server.connect():
            pass
        with self.connect_with_timeout() as writer:
            writer.execute("begin immediate")

            started = time.monotonic()
            claimed = relay.publish_relay_claim(
                "empty-channel",
                "empty-client",
                30_000,
                settings=self.server.SETTINGS,
                defaults=self.server.DB_DEFAULTS,
                connect_fn=self.connect_with_timeout,
            )
            elapsed = time.monotonic() - started

        self.assertIsNone(claimed)
        self.assertLess(elapsed, 0.5)

    def test_lock_contention_exhausts_bounded_retry_as_sanitized_503(self) -> None:
        relay.publish_relay_enqueue(
            {
                "schema": "openclaw.publish.packet.v1",
                "channelId": "locked-channel",
            },
            settings=self.server.SETTINGS,
            defaults=self.server.DB_DEFAULTS,
        )
        connect_calls = 0

        def connect() -> sqlite3.Connection:
            nonlocal connect_calls
            connect_calls += 1
            return self.connect_with_timeout()

        with self.connect_with_timeout() as writer:
            writer.execute("begin immediate")
            started = time.monotonic()
            with self.assertRaises(ActivationError) as raised:
                relay.publish_relay_claim(
                    "locked-channel",
                    "locked-client",
                    30_000,
                    settings=self.server.SETTINGS,
                    defaults=self.server.DB_DEFAULTS,
                    connect_fn=connect,
                )
            elapsed = time.monotonic() - started

        self.assertEqual(503, raised.exception.status)
        self.assertEqual("Publish relay temporarily unavailable", str(raised.exception))
        self.assertNotIn("locked", str(raised.exception).lower())
        self.assertEqual(3, connect_calls)
        self.assertLess(elapsed, 2.0)

    def test_poll_route_does_not_leak_unexpected_error_details(self) -> None:
        sent: list[tuple[int, dict[str, object]]] = []

        def fail_poll(*_args: object) -> None:
            raise RuntimeError("database is locked at C:\\secret\\license.db")

        api = SimpleNamespace(
            parse_qs=self.server.parse_qs,
            normalize_string=self.server.normalize_string,
            clamp_int=self.server.clamp_int,
            PUBLISH_RELAY_DEFAULT_LEASE_MS=self.server.PUBLISH_RELAY_DEFAULT_LEASE_MS,
            PUBLISH_RELAY_DEFAULT_WAIT_MS=self.server.PUBLISH_RELAY_DEFAULT_WAIT_MS,
            publish_relay_wait_for_packet=fail_poll,
            ActivationError=ActivationError,
        )
        handler = SimpleNamespace(
            facade=api,
            require_publish_relay_auth=lambda: True,
            send_json=lambda status, payload: sent.append((status, payload)),
        )

        with self.assertLogs("openclaw-license", level="ERROR"):
            routes_relay.get_api_lumi_relay_poll(
                handler,
                urlparse("/api/lumi/relay/poll?channelId=locked-channel&waitMs=0"),
            )

        self.assertEqual(
            [(500, {"ok": False, "error": "Internal server error"})],
            sent,
        )

    def test_poll_route_returns_sanitized_503_after_real_lock_contention(self) -> None:
        self.server.publish_relay_enqueue(
            {
                "schema": "openclaw.publish.packet.v1",
                "channelId": "route-locked-channel",
            }
        )
        sent: list[tuple[int, dict[str, object]]] = []
        handler = SimpleNamespace(
            facade=self.server,
            require_publish_relay_auth=lambda: True,
            send_json=lambda status, payload: sent.append((status, payload)),
        )

        with self.connect_with_timeout() as writer:
            writer.execute("begin immediate")
            started = time.monotonic()
            routes_relay.get_api_lumi_relay_poll(
                handler,
                urlparse(
                    "/api/lumi/relay/poll?channelId=route-locked-channel&waitMs=0"
                ),
            )
            elapsed = time.monotonic() - started

        self.assertEqual(
            [(503, {"ok": False, "error": "Publish relay temporarily unavailable"})],
            sent,
        )
        self.assertLess(elapsed, 2.0)

    def test_real_route_bounds_lock_during_schema_and_plan_initialization(self) -> None:
        self.server.publish_relay_enqueue(
            {
                "schema": "openclaw.publish.packet.v1",
                "channelId": "schema-drift-lock",
            }
        )
        with self.server.connect() as connection:
            connection.execute("drop index idx_publish_relay_channel_status")
            connection.execute(
                "update plans set features_json = '[]' where plan_key = 'monthly'"
            )
            connection.commit()

        sent: list[tuple[int, dict[str, object]]] = []
        handler = SimpleNamespace(
            facade=self.server,
            require_publish_relay_auth=lambda: True,
            send_json=lambda status, payload: sent.append((status, payload)),
        )
        with self.connect_with_timeout() as writer:
            writer.execute("begin immediate")
            started = time.monotonic()
            routes_relay.get_api_lumi_relay_poll(
                handler,
                urlparse(
                    "/api/lumi/relay/poll?channelId=schema-drift-lock&waitMs=0"
                ),
            )
            elapsed = time.monotonic() - started

        self.assertEqual(
            [(503, {"ok": False, "error": "Publish relay temporarily unavailable"})],
            sent,
        )
        self.assertLess(elapsed, 1.5)

    def test_all_relay_routes_sanitize_unexpected_error_details(self) -> None:
        def fail(*_args: object) -> None:
            raise RuntimeError("database failed at C:\\private\\license.db")

        api = SimpleNamespace(
            parse_qs=self.server.parse_qs,
            normalize_string=self.server.normalize_string,
            clamp_int=self.server.clamp_int,
            PUBLISH_RELAY_DEFAULT_LEASE_MS=self.server.PUBLISH_RELAY_DEFAULT_LEASE_MS,
            PUBLISH_RELAY_DEFAULT_WAIT_MS=self.server.PUBLISH_RELAY_DEFAULT_WAIT_MS,
            publish_relay_wait_for_packet=fail,
            publish_relay_status=fail,
            publish_relay_stats=fail,
            publish_relay_enqueue=fail,
            publish_relay_complete=fail,
            ActivationError=ActivationError,
        )
        cases = (
            (
                routes_relay.get_api_lumi_relay_poll,
                "/api/lumi/relay/poll?channelId=test&waitMs=0",
                False,
            ),
            (
                routes_relay.get_api_lumi_relay_status,
                "/api/lumi/relay/status?id=packet",
                False,
            ),
            (routes_relay.post_api_lumi_relay_packet, "/api/lumi/relay/packet", True),
            (routes_relay.post_api_lumi_relay_complete, "/api/lumi/relay/complete", True),
        )
        for route, path, needs_body in cases:
            with self.subTest(path=path):
                sent: list[tuple[int, dict[str, object]]] = []
                handler = SimpleNamespace(
                    facade=api,
                    require_publish_relay_auth=lambda: True,
                    send_json=lambda status, payload: sent.append((status, payload)),
                    read_json=(lambda: {}) if needs_body else None,
                )
                with self.assertLogs("openclaw-license", level="ERROR"):
                    route(handler, urlparse(path))
                self.assertEqual(
                    [(500, {"ok": False, "error": "Internal server error"})],
                    sent,
                )
