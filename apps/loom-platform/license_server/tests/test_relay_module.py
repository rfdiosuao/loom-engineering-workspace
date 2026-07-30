from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
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

    def create_producer_authorization(
        self,
        account_id: str,
        *,
        activate: bool,
        digest_character: str = "a",
    ) -> dict[str, object]:
        if activate:
            code = self.server.create_code_records(
                count=1,
                licensee=f"Relay {account_id}",
                edition="pro",
                features=["openclaw", "matrix.devices", "publishing.draft"],
                expires=(date.today() + timedelta(days=30)).isoformat(),
                max_activations=4,
                member_mode=True,
                plan="matrix_pro",
                quotas={"concurrentTasks": 3},
            )[0]
            entitlement = self.server.redeem_account_entitlement(
                {"code": code, "accountId": account_id}
            )
        else:
            entitlement = {
                "source": "authorization_code",
                "plan": "matrix_pro",
                "features": ["openclaw", "matrix.devices"],
                "limits": {
                    "devices": 1000,
                    "concurrentTasks": 3,
                    "unlimitedDevices": True,
                },
            }

        now_seconds = int(time.time())
        entitlement_version = 1
        producer_token = self.producer_token(account_id)
        entitlement_lease = self.server.sign_license(
            {
                "schema": "loom.entitlement_lease.v1",
                "accountId": account_id,
                "sessionBinding": hashlib.sha256(
                    b"loom-entitlement-session-v1\0"
                    + producer_token.encode("utf-8")
                ).hexdigest(),
                "installId": f"install-{account_id}",
                "deviceId": f"host-{account_id}",
                "hostDeviceId": f"host-{account_id}",
                "plan": entitlement["plan"],
                "source": entitlement["source"],
                "features": entitlement["features"],
                "limits": entitlement["limits"],
                "issuedAt": now_seconds - 60,
                "expiresAt": now_seconds + 3600,
                "offlineGraceUntil": now_seconds + 7200,
                "entitlementVersion": entitlement_version,
                "keyId": "openclaw-ed25519-v1",
            }
        )
        phone_seat_lease = self.server.sign_license(
            {
                "schema": "loom.phone_seat_lease.v1",
                "accountId": account_id,
                "installId": f"install-{account_id}",
                "hostDeviceId": f"host-{account_id}",
                "phoneDeviceIds": [f"phone-{account_id}"],
                "limit": 1000,
                "issuedAt": now_seconds - 60,
                "expiresAt": now_seconds + 3600,
                "entitlementVersion": entitlement_version,
                "keyId": "openclaw-ed25519-v1",
            }
        )
        return {
            "schema": "loom.phone.publish.authorization.v1",
            "accountId": account_id,
            "entitlementVersion": entitlement_version,
            "runtimeConfigDigest": digest_character * 64,
            "selectedDeviceId": f"phone-{account_id}",
            "selectedDeviceInstanceId": "phone-http",
            "authorizedDeviceIds": [f"phone-{account_id}"],
            "entitlementLease": entitlement_lease,
            "phoneSeatLease": phone_seat_lease,
        }

    @staticmethod
    def relay_packet(authorization: dict[str, object] | None = None) -> dict[str, object]:
        packet: dict[str, object] = {
            "schema": "openclaw.publish.packet.v1",
            "channelId": "matrix",
            "title": "account-scoped relay",
            "draftOnly": True,
            "executionPolicy": {
                "requireSignedEntitlementAtDequeue": True,
                "requireSignedEntitlementBeforeCommit": True,
                "denyCommitOnRevocation": True,
            },
        }
        if authorization is not None:
            packet["authorization"] = authorization
        return packet

    @staticmethod
    def producer_token(account_id: str) -> str:
        return f"model-session-{account_id}"

    @classmethod
    def producer_headers(
        cls,
        authorization: dict[str, object],
    ) -> dict[str, str]:
        account_id = str(authorization["accountId"])
        return {
            "Authorization": f"Bearer {cls.producer_token(account_id)}",
            "X-LOOM-Account-ID": account_id,
            "X-LOOM-Entitlement-Version": str(
                authorization["entitlementVersion"]
            ),
            "X-LOOM-Runtime-Config-Digest": str(
                authorization["runtimeConfigDigest"]
            ),
        }

    def post_packet_route(
        self,
        packet: dict[str, object],
        headers: dict[str, str],
    ) -> list[tuple[int, dict[str, object]]]:
        sent: list[tuple[int, dict[str, object]]] = []
        handler = SimpleNamespace(
            facade=self.server,
            headers=headers,
            require_publish_relay_auth=lambda: (_ for _ in ()).throw(
                AssertionError("producer route must not require the consumer relay token")
            ),
            read_json=lambda: packet,
            send_json=lambda status, payload, **_kwargs: sent.append((status, payload)),
        )
        routes_relay.post_api_lumi_relay_packet(
            handler,
            urlparse("/api/lumi/relay/packet"),
        )
        return sent

    def test_consumer_token_alone_cannot_enqueue(self) -> None:
        sent = self.post_packet_route(
            self.relay_packet(),
            {"X-OpenClaw-Relay-Token": "test-relay-token"},
        )

        self.assertEqual(401, sent[0][0])
        self.assertFalse(sent[0][1]["ok"])
        with self.server.connect() as connection:
            count = connection.execute(
                "select count(*) from publish_relay_packets"
            ).fetchone()[0]
        self.assertEqual(0, count)

    def test_consumer_token_cannot_replay_a_signed_producer_authorization(self) -> None:
        authorization = self.create_producer_authorization(
            "relay-replay-owner",
            activate=True,
        )
        headers = {
            **self.producer_headers(authorization),
            "Authorization": "Bearer test-relay-token",
        }

        sent = self.post_packet_route(
            self.relay_packet(authorization),
            headers,
        )

        self.assertEqual(401, sent[0][0])
        self.assertFalse(sent[0][1]["ok"])
        with self.server.connect() as connection:
            count = connection.execute(
                "select count(*) from publish_relay_packets"
            ).fetchone()[0]
        self.assertEqual(0, count)

    def test_signed_but_unactivated_account_cannot_enqueue(self) -> None:
        authorization = self.create_producer_authorization(
            "relay-inactive",
            activate=False,
        )

        sent = self.post_packet_route(
            self.relay_packet(authorization),
            self.producer_headers(authorization),
        )

        self.assertEqual(403, sent[0][0])
        self.assertFalse(sent[0][1]["ok"])
        serialized = str(sent[0][1])
        self.assertNotIn("relay-inactive", serialized)
        self.assertNotIn(
            str(authorization["entitlementLease"]["signature"]),
            serialized,
        )

    def test_activated_account_with_tampered_signature_cannot_enqueue(self) -> None:
        authorization = self.create_producer_authorization(
            "relay-tampered",
            activate=True,
        )
        authorization["entitlementLease"] = {
            **authorization["entitlementLease"],
            "signature": "forged-signature",
        }

        sent = self.post_packet_route(
            self.relay_packet(authorization),
            self.producer_headers(authorization),
        )

        self.assertEqual(401, sent[0][0])
        self.assertFalse(sent[0][1]["ok"])
        self.assertNotIn("relay-tampered", str(sent[0][1]))

    def test_activated_account_with_unknown_entitlement_key_cannot_enqueue(self) -> None:
        authorization = self.create_producer_authorization(
            "relay-unknown-key",
            activate=True,
        )
        unsigned_lease = {
            **authorization["entitlementLease"],
            "keyId": "unknown-entitlement-key",
        }
        unsigned_lease.pop("signature")
        authorization["entitlementLease"] = self.server.sign_license(unsigned_lease)

        sent = self.post_packet_route(
            self.relay_packet(authorization),
            self.producer_headers(authorization),
        )

        self.assertEqual(401, sent[0][0])
        self.assertFalse(sent[0][1]["ok"])
        self.assertNotIn("relay-unknown-key", str(sent[0][1]))

    def test_activated_signed_account_can_enqueue_and_binds_account_id(self) -> None:
        authorization = self.create_producer_authorization(
            "relay-active",
            activate=True,
        )

        sent = self.post_packet_route(
            self.relay_packet(authorization),
            self.producer_headers(authorization),
        )

        self.assertEqual(202, sent[0][0])
        self.assertTrue(sent[0][1]["ok"])
        packet_id = sent[0][1]["data"]["packetId"]
        with self.server.connect() as connection:
            columns = {
                str(row["name"])
                for row in connection.execute(
                    "pragma table_info(publish_relay_packets)"
                ).fetchall()
            }
            self.assertIn("account_id", columns)
            row = connection.execute(
                """
                select account_id, status from publish_relay_packets
                where packet_id = ?
                """,
                (packet_id,),
            ).fetchone()
        self.assertEqual("relay-active", row["account_id"])
        self.assertEqual("pending", row["status"])

        status_responses: list[tuple[int, dict[str, object]]] = []
        status_handler = SimpleNamespace(
            facade=self.server,
            headers=self.producer_headers(authorization),
            require_publish_relay_auth=lambda: (_ for _ in ()).throw(
                AssertionError("producer status must not require the consumer relay token")
            ),
            send_json=lambda status, payload, **_kwargs: status_responses.append(
                (status, payload)
            ),
        )
        routes_relay.get_api_lumi_relay_status(
            status_handler,
            urlparse(f"/api/lumi/relay/status?id={packet_id}"),
        )
        self.assertEqual(200, status_responses[0][0])
        self.assertEqual("relay-active", status_responses[0][1]["data"]["accountId"])
        self.assertNotIn(
            "authorization",
            status_responses[0][1]["data"]["packet"],
        )

    def test_consumer_token_alone_cannot_query_producer_status(self) -> None:
        sent: list[tuple[int, dict[str, object]]] = []
        handler = SimpleNamespace(
            facade=self.server,
            headers={"X-OpenClaw-Relay-Token": "test-relay-token"},
            require_publish_relay_auth=lambda: True,
            send_json=lambda status, payload, **_kwargs: sent.append((status, payload)),
        )

        routes_relay.get_api_lumi_relay_status(
            handler,
            urlparse("/api/lumi/relay/status?id=relay_unknown"),
        )

        self.assertEqual(401, sent[0][0])
        self.assertFalse(sent[0][1]["ok"])

    def test_status_query_is_hidden_from_another_activated_account(self) -> None:
        owner = self.create_producer_authorization(
            "relay-owner",
            activate=True,
            digest_character="c",
        )
        other = self.create_producer_authorization(
            "relay-other",
            activate=True,
            digest_character="d",
        )
        queued = self.post_packet_route(
            self.relay_packet(owner),
            self.producer_headers(owner),
        )
        packet_id = queued[0][1]["data"]["packetId"]
        sent: list[tuple[int, dict[str, object]]] = []
        handler = SimpleNamespace(
            facade=self.server,
            headers=self.producer_headers(other),
            require_publish_relay_auth=lambda: True,
            send_json=lambda status, payload, **_kwargs: sent.append((status, payload)),
        )

        routes_relay.get_api_lumi_relay_status(
            handler,
            urlparse(f"/api/lumi/relay/status?id={packet_id}"),
        )

        self.assertEqual(404, sent[0][0])
        self.assertFalse(sent[0][1]["ok"])
        self.assertNotIn("relay-owner", str(sent[0][1]))

        forged_scope_headers = {
            **self.producer_headers(owner),
            "Authorization": f"Bearer {self.producer_token('relay-other')}",
        }
        forged_scope_responses: list[tuple[int, dict[str, object]]] = []
        forged_scope_handler = SimpleNamespace(
            facade=self.server,
            headers=forged_scope_headers,
            require_publish_relay_auth=lambda: True,
            send_json=lambda status, payload, **_kwargs: forged_scope_responses.append(
                (status, payload)
            ),
        )
        routes_relay.get_api_lumi_relay_status(
            forged_scope_handler,
            urlparse(f"/api/lumi/relay/status?id={packet_id}"),
        )
        self.assertEqual(404, forged_scope_responses[0][0])
        self.assertFalse(forged_scope_responses[0][1]["ok"])

    def test_http_producer_and_consumer_credentials_remain_separate(self) -> None:
        from http.server import ThreadingHTTPServer
        from urllib.error import HTTPError
        from urllib.request import Request, urlopen

        authorization = self.create_producer_authorization(
            "relay-http-owner",
            activate=True,
        )
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), self.server.Handler)
        server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        server_thread.start()
        base_url = f"http://127.0.0.1:{httpd.server_address[1]}"

        def request_json(
            method: str,
            path: str,
            *,
            payload: dict[str, object] | None = None,
            headers: dict[str, str] | None = None,
            expected_status: int = 200,
        ) -> dict[str, object]:
            request_headers = dict(headers or {})
            data = None
            if payload is not None:
                data = json.dumps(payload).encode("utf-8")
                request_headers["Content-Type"] = "application/json"
            request = Request(
                f"{base_url}{path}",
                method=method,
                headers=request_headers,
                data=data,
            )
            try:
                response = urlopen(request, timeout=5)
                status = response.status
                body = response.read()
            except HTTPError as error:
                status = error.code
                body = error.read()
            self.assertEqual(
                expected_status,
                status,
                body.decode("utf-8", errors="replace"),
            )
            return json.loads(body.decode("utf-8") or "{}")

        try:
            queued = request_json(
                "POST",
                "/api/lumi/relay/packet",
                payload=self.relay_packet(authorization),
                headers=self.producer_headers(authorization),
                expected_status=202,
            )
            packet_id = queued["data"]["packetId"]
            consumer_headers = {
                "X-OpenClaw-Relay-Token": "test-relay-token",
            }
            polled = request_json(
                "GET",
                "/api/lumi/relay/poll?channelId=matrix&clientId=phone-http&waitMs=0",
                headers=consumer_headers,
            )
            self.assertEqual(packet_id, polled["data"]["packetId"])
            self.assertEqual(
                "relay-http-owner",
                polled["data"]["packet"]["authorization"]["accountId"],
            )
            completed = request_json(
                "POST",
                "/api/lumi/relay/complete",
                payload={
                    "packetId": packet_id,
                    "leaseId": polled["data"]["leaseId"],
                    "clientId": "phone-http",
                    "success": True,
                    "result": {"ok": True},
                },
                headers=consumer_headers,
            )
            self.assertEqual("done", completed["data"]["status"])
            status = request_json(
                "GET",
                f"/api/lumi/relay/status?id={packet_id}",
                headers=self.producer_headers(authorization),
            )
            self.assertEqual("done", status["data"]["status"])
            self.assertNotIn("authorization", status["data"]["packet"])

            formal_packet = self.relay_packet(authorization)
            formal_packet["draftOnly"] = False
            formal_queued = request_json(
                "POST",
                "/api/lumi/relay/packet",
                payload=formal_packet,
                headers=self.producer_headers(authorization),
                expected_status=202,
            )
            formal_packet_id = formal_queued["data"]["packetId"]
            formal_polled = request_json(
                "GET",
                "/api/lumi/relay/poll?channelId=matrix&clientId=phone-http&waitMs=0",
                headers=consumer_headers,
            )
            self.assertEqual(formal_packet_id, formal_polled["data"]["packetId"])
            commit = request_json(
                "POST",
                "/api/lumi/relay/commit-authorize",
                payload={
                    "packetId": formal_packet_id,
                    "leaseId": formal_polled["data"]["leaseId"],
                    "clientId": "phone-http",
                    "channelId": "matrix",
                },
                headers=consumer_headers,
            )
            commit_token = commit["data"]["commitToken"]
            self.assertGreaterEqual(len(commit_token), 32)
            formal_status = request_json(
                "GET",
                f"/api/lumi/relay/status?id={formal_packet_id}",
                headers=self.producer_headers(authorization),
            )
            self.assertEqual("authorized", formal_status["data"]["commitState"])
            self.assertNotIn("commitToken", formal_status["data"])

            missing_token = request_json(
                "POST",
                "/api/lumi/relay/complete",
                payload={
                    "packetId": formal_packet_id,
                    "leaseId": formal_polled["data"]["leaseId"],
                    "clientId": "phone-http",
                    "success": True,
                },
                headers=consumer_headers,
                expected_status=409,
            )
            self.assertFalse(missing_token["ok"])

            formal_completed = request_json(
                "POST",
                "/api/lumi/relay/complete",
                payload={
                    "packetId": formal_packet_id,
                    "leaseId": formal_polled["data"]["leaseId"],
                    "clientId": "phone-http",
                    "commitToken": commit_token,
                    "success": True,
                    "result": {"published": True},
                },
                headers=consumer_headers,
            )
            self.assertEqual("done", formal_completed["data"]["status"])
            self.assertEqual("consumed", formal_completed["data"]["commitState"])
        finally:
            httpd.shutdown()
            httpd.server_close()
            server_thread.join(timeout=5)

    def disable_account_entitlement(self, account_id: str) -> None:
        with self.server.connect() as connection:
            connection.execute(
                """
                update codes set disabled = 1
                where code_hash in (
                    select code_hash from account_entitlement_redemptions
                    where account_id = ?
                )
                """,
                (account_id,),
            )
            connection.commit()

    def enqueue_formal_packet(
        self,
        account_id: str,
        *,
        consumer_id: str,
    ) -> tuple[dict[str, object], str]:
        authorization = self.create_producer_authorization(
            account_id,
            activate=True,
        )
        authorization["selectedDeviceInstanceId"] = consumer_id
        packet = self.relay_packet(authorization)
        packet["draftOnly"] = False
        queued = self.post_packet_route(
            packet,
            self.producer_headers(authorization),
        )
        self.assertEqual(202, queued[0][0], queued)
        return authorization, queued[0][1]["data"]["packetId"]

    def test_revoked_entitlement_is_rejected_before_dequeue(self) -> None:
        _authorization, packet_id = self.enqueue_formal_packet(
            "relay-revoked-before-dequeue",
            consumer_id="revoked-consumer",
        )
        self.disable_account_entitlement("relay-revoked-before-dequeue")

        claimed = self.server.publish_relay_claim(
            "matrix",
            "revoked-consumer",
            30_000,
        )

        self.assertIsNone(claimed)
        status = relay.publish_relay_status(
            packet_id,
            settings=self.server.SETTINGS,
            defaults=self.server.DB_DEFAULTS,
        )
        self.assertEqual("failed", status["status"])
        self.assertEqual("denied", status["commitState"])
        self.assertEqual(
            "Relay authorization is no longer active",
            status["lastError"],
        )

    def test_formal_packet_can_only_be_claimed_by_selected_phone_instance(self) -> None:
        _authorization, packet_id = self.enqueue_formal_packet(
            "relay-device-bound-claim",
            consumer_id="selected-phone-instance",
        )

        self.assertIsNone(
            self.server.publish_relay_claim(
                "matrix",
                "different-phone-instance",
                30_000,
            )
        )
        claimed = self.server.publish_relay_claim(
            "matrix",
            "selected-phone-instance",
            30_000,
        )

        self.assertEqual(packet_id, claimed["id"])
        self.assertEqual("selected-phone-instance", claimed["leasedBy"])

    def test_producer_authorization_requires_selected_phone_instance(self) -> None:
        authorization = self.create_producer_authorization(
            "relay-missing-device-instance",
            activate=True,
        )
        authorization.pop("selectedDeviceInstanceId")

        response = self.post_packet_route(
            self.relay_packet(authorization),
            self.producer_headers(authorization),
        )

        self.assertEqual(401, response[0][0], response)
        self.assertEqual(
            "RELAY_PRODUCER_AUTH_REQUIRED",
            response[0][1]["error"]["code"],
        )

    def test_formal_publish_requires_one_time_commit_token(self) -> None:
        _authorization, packet_id = self.enqueue_formal_packet(
            "relay-commit-token",
            consumer_id="commit-consumer",
        )
        claimed = self.server.publish_relay_claim(
            "matrix",
            "commit-consumer",
            30_000,
        )
        self.assertEqual(packet_id, claimed["id"])

        decision = self.server.publish_relay_authorize_commit(
            {
                "packetId": packet_id,
                "leaseId": claimed["leaseId"],
                "clientId": "commit-consumer",
            }
        )
        self.assertGreaterEqual(len(decision["commitToken"]), 32)
        public_status = relay.publish_relay_status(
            packet_id,
            settings=self.server.SETTINGS,
            defaults=self.server.DB_DEFAULTS,
        )
        self.assertEqual("authorized", public_status["commitState"])
        self.assertNotIn("commitToken", public_status)
        self.assertNotIn("commit_token_hash", public_status)

        with self.assertRaises(ActivationError) as missing:
            self.server.publish_relay_complete(
                {
                    "packetId": packet_id,
                    "leaseId": claimed["leaseId"],
                    "clientId": "commit-consumer",
                    "success": True,
                }
            )
        self.assertEqual("RELAY_COMMIT_TOKEN_REQUIRED", missing.exception.code)

        completed = self.server.publish_relay_complete(
            {
                "packetId": packet_id,
                "leaseId": claimed["leaseId"],
                "clientId": "commit-consumer",
                "commitToken": decision["commitToken"],
                "success": True,
                "result": {"published": True},
            }
        )
        self.assertEqual("done", completed["status"])
        self.assertEqual("consumed", completed["commitState"])

        with self.assertRaises(ActivationError):
            self.server.publish_relay_complete(
                {
                    "packetId": packet_id,
                    "leaseId": claimed["leaseId"],
                    "clientId": "commit-consumer",
                    "commitToken": decision["commitToken"],
                    "success": True,
                }
            )

    def test_revocation_after_dequeue_blocks_final_commit(self) -> None:
        _authorization, packet_id = self.enqueue_formal_packet(
            "relay-revoked-before-commit",
            consumer_id="revoked-after-claim",
        )
        claimed = self.server.publish_relay_claim(
            "matrix",
            "revoked-after-claim",
            30_000,
        )
        self.assertEqual(packet_id, claimed["id"])
        self.disable_account_entitlement("relay-revoked-before-commit")

        with self.assertRaises(ActivationError) as raised:
            self.server.publish_relay_authorize_commit(
                {
                    "packetId": packet_id,
                    "leaseId": claimed["leaseId"],
                    "clientId": "revoked-after-claim",
                }
            )
        self.assertEqual(403, raised.exception.status)
        self.assertEqual(
            "RELAY_PRODUCER_ENTITLEMENT_REQUIRED",
            raised.exception.code,
        )

    def test_failure_after_commit_authorization_is_terminal_and_not_requeued(self) -> None:
        _authorization, packet_id = self.enqueue_formal_packet(
            "relay-indeterminate",
            consumer_id="indeterminate-consumer",
        )
        claimed = self.server.publish_relay_claim(
            "matrix",
            "indeterminate-consumer",
            30_000,
        )
        decision = self.server.publish_relay_authorize_commit(
            {
                "packetId": packet_id,
                "leaseId": claimed["leaseId"],
                "clientId": "indeterminate-consumer",
            }
        )

        failed = self.server.publish_relay_complete(
            {
                "packetId": packet_id,
                "leaseId": claimed["leaseId"],
                "clientId": "indeterminate-consumer",
                "commitToken": decision["commitToken"],
                "success": False,
                "error": "connection dropped after final tap",
            }
        )

        self.assertEqual("failed", failed["status"])
        self.assertEqual("indeterminate", failed["commitState"])
        self.assertTrue(failed["outcomeIndeterminate"])
        self.assertEqual(
            relay.PUBLISH_RELAY_COMMIT_INDETERMINATE_ERROR,
            failed["lastError"],
        )
        self.assertIsNone(
            self.server.publish_relay_claim(
                "matrix",
                "second-consumer",
                30_000,
            )
        )

    def test_expired_authorized_lease_is_terminal_and_not_requeued(self) -> None:
        _authorization, packet_id = self.enqueue_formal_packet(
            "relay-expired-after-authorization",
            consumer_id="expired-authorized-consumer",
        )
        claimed = self.server.publish_relay_claim(
            "matrix",
            "expired-authorized-consumer",
            30_000,
        )
        self.server.publish_relay_authorize_commit(
            {
                "packetId": packet_id,
                "leaseId": claimed["leaseId"],
                "clientId": "expired-authorized-consumer",
            }
        )
        with self.server.connect() as connection:
            connection.execute(
                """
                update publish_relay_packets
                set lease_until_ms = ?
                where packet_id = ?
                """,
                (self.server.now_ms() - 1, packet_id),
            )
            connection.commit()

        self.assertIsNone(
            self.server.publish_relay_claim(
                "matrix",
                "replacement-consumer",
                30_000,
            )
        )
        status = relay.publish_relay_status(
            packet_id,
            settings=self.server.SETTINGS,
            defaults=self.server.DB_DEFAULTS,
        )
        self.assertEqual("failed", status["status"])
        self.assertEqual("indeterminate", status["commitState"])
        self.assertTrue(status["outcomeIndeterminate"])
        self.assertEqual(
            relay.PUBLISH_RELAY_COMMIT_INDETERMINATE_ERROR,
            status["lastError"],
        )

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
            publish_relay_authorize_commit=fail,
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
            (
                routes_relay.post_api_lumi_relay_commit_authorize,
                "/api/lumi/relay/commit-authorize",
                True,
            ),
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
