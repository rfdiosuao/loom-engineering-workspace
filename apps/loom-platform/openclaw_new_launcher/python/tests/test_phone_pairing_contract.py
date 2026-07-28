from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


PYTHON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)

from api import routes_phone


BOOTSTRAP_SECRET_HEX = "11" * 32
PHONE_TOKEN = "phone-token-" + ("a" * 64)
LAUNCHER_SECRET = "launcher-secret-" + ("b" * 64)
APPS_DIR = Path(__file__).resolve().parents[4]
PHONE_AGENT_DIR = APPS_DIR / "loom-phone-agent" / "app" / "src" / "main"


def _derive_key(secret_hex: str, session_id: str, nonce: str) -> bytes:
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=session_id.encode("utf-8"),
        info=f"LOOM-PHONE-PAIRING-V3\n{nonce}".encode("utf-8"),
    ).derive(bytes.fromhex(secret_hex))


def _aad(session_id: str, nonce: str, device_id: str, launcher_id: str) -> bytes:
    return "\n".join(
        ("LOOM-PAIR-RESPONSE-V3", session_id, nonce, device_id, launcher_id)
    ).encode("utf-8")


class PhonePairingContractTests(unittest.TestCase):
    def test_pairing_payload_parser_rejects_embedded_permanent_credentials(self) -> None:
        parser = getattr(routes_phone, "_parse_phone_pairing_input", None)
        self.assertTrue(callable(parser), "pairing payload parser must exist")

        with self.assertRaises(ValueError):
            parser(
                {
                    "payload": (
                        "lumi://pair?v=3&b=http%3A%2F%2F192.168.1.8%3A9527"
                        f"&d=lumi-phone-a&s=session-a&k={BOOTSTRAP_SECRET_HEX}"
                        "&phoneToken=permanent-secret"
                    )
                }
            )

    def test_lan_pairing_requires_high_entropy_payload_and_usb_allows_code(self) -> None:
        parser = getattr(routes_phone, "_parse_phone_pairing_input", None)
        self.assertTrue(callable(parser), "pairing payload parser must exist")

        payload = parser(
            {
                "payload": (
                    "lumi://pair?v=3&b=http%3A%2F%2F192.168.1.8%3A9527"
                    f"&d=lumi-phone-a&s=session-a&k={BOOTSTRAP_SECRET_HEX}"
                    "&n=Pixel&x=lan"
                )
            }
        )
        usb = parser({"usbSerial": "ABC123", "code": "654321"})

        self.assertEqual("http://192.168.1.8:9527", payload["baseUrl"])
        self.assertEqual("lumi-phone-a", payload["deviceInstanceId"])
        self.assertEqual("session-a", payload["sessionId"])
        self.assertEqual(BOOTSTRAP_SECRET_HEX, payload["bootstrapSecret"])
        self.assertEqual("", payload["code"])
        self.assertEqual("654321", usb["code"])
        with self.assertRaisesRegex(ValueError, "完整配对信息"):
            parser({"baseUrl": "192.168.1.9:9531", "code": "654321"})

    def test_lan_claim_uses_proof_and_encrypted_credentials_only(self) -> None:
        claim = getattr(routes_phone, "_claim_phone_pairing_over_http", None)
        self.assertTrue(callable(claim), "phone bootstrap claim helper must exist")
        captured: dict = {}

        class FakeResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _amount: int = -1) -> bytes:
                request_body = json.loads(captured["request"].data.decode("utf-8"))
                nonce = request_body["nonce"]
                session_id = request_body["sessionId"]
                launcher_id = request_body["launcherId"]
                device_id = request_body["deviceInstanceId"]
                iv = bytes.fromhex("22" * 12)
                plaintext = json.dumps(
                    {
                        "phoneToken": PHONE_TOKEN,
                        "launcherId": launcher_id,
                        "launcherName": "LOOM",
                        "launcherSecret": LAUNCHER_SECRET,
                        "pairedAt": 1_000_000,
                    },
                    separators=(",", ":"),
                ).encode("utf-8")
                ciphertext = AESGCM(
                    _derive_key(BOOTSTRAP_SECRET_HEX, session_id, nonce)
                ).encrypt(iv, plaintext, _aad(session_id, nonce, device_id, launcher_id))
                response = {
                    "success": True,
                    "data": {
                        "paired": True,
                        "sessionId": session_id,
                        "nonce": nonce,
                        "launcherId": launcher_id,
                        "deviceInstanceId": device_id,
                        "listeningPort": 9527,
                        "encryptedCredentials": {
                            "algorithm": "AES-256-GCM-HKDF-SHA256",
                            "iv": iv.hex(),
                            "ciphertext": ciphertext.hex(),
                        },
                    },
                }
                captured["response_bytes"] = json.dumps(response).encode("utf-8")
                return captured["response_bytes"]

        def fake_urlopen(request, timeout):
            captured["request"] = request
            captured["timeout"] = timeout
            return FakeResponse()

        with patch("api.routes_phone.urlopen", side_effect=fake_urlopen):
            result = claim(
                "http://192.168.1.8:9527",
                {
                    "sessionId": "session-a",
                    "code": "123456",
                    "bootstrapSecret": BOOTSTRAP_SECRET_HEX,
                    "deviceInstanceId": "lumi-phone-a",
                    "transportHint": "lan",
                },
                launcher_id="loom-desktop-a",
                launcher_name="LOOM",
            )

        request = captured["request"]
        headers = {key.lower(): value for key, value in request.header_items()}
        body = json.loads(request.data.decode("utf-8"))
        serialized_request = json.dumps(body)
        serialized_response = captured["response_bytes"].decode("utf-8")
        self.assertNotIn("x-agent-phone-token", headers)
        self.assertNotIn("x-apkclaw-token", headers)
        self.assertNotIn("code", body)
        self.assertNotIn("bootstrapSecret", body)
        self.assertNotIn("123456", serialized_request)
        self.assertNotIn(BOOTSTRAP_SECRET_HEX, serialized_request)
        self.assertIn("proof", body)
        self.assertIn("nonce", body)
        expected_proof = hmac.new(
            bytes.fromhex(BOOTSTRAP_SECRET_HEX),
            "\n".join(
                (
                    "LOOM-PAIR-CLAIM-V3",
                    "session-a",
                    body["nonce"],
                    "lumi-phone-a",
                    "loom-desktop-a",
                )
            ).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        self.assertEqual(expected_proof, body["proof"])
        self.assertNotIn(PHONE_TOKEN, serialized_response)
        self.assertNotIn(LAUNCHER_SECRET, serialized_response)
        self.assertEqual(PHONE_TOKEN, result["phoneToken"])
        self.assertEqual(LAUNCHER_SECRET, result["launcherSecret"])

    def test_lan_claim_rejects_tampered_ciphertext(self) -> None:
        claim = getattr(routes_phone, "_claim_phone_pairing_over_http", None)
        captured: dict = {}

        class FakeResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _amount: int = -1) -> bytes:
                body = json.loads(captured["request"].data.decode("utf-8"))
                iv = bytes.fromhex("33" * 12)
                ciphertext = AESGCM(
                    _derive_key(BOOTSTRAP_SECRET_HEX, body["sessionId"], body["nonce"])
                ).encrypt(
                    iv,
                    json.dumps(
                        {
                            "phoneToken": PHONE_TOKEN,
                            "launcherId": body["launcherId"],
                            "launcherName": "LOOM",
                            "launcherSecret": LAUNCHER_SECRET,
                            "pairedAt": 1_000_000,
                        },
                        separators=(",", ":"),
                    ).encode("utf-8"),
                    _aad(
                        body["sessionId"],
                        body["nonce"],
                        body["deviceInstanceId"],
                        body["launcherId"],
                    ),
                )
                tampered = bytearray(ciphertext)
                tampered[-1] ^= 1
                return json.dumps(
                    {
                        "success": True,
                        "data": {
                            "sessionId": body["sessionId"],
                            "nonce": body["nonce"],
                            "launcherId": body["launcherId"],
                            "deviceInstanceId": body["deviceInstanceId"],
                            "encryptedCredentials": {
                                "algorithm": "AES-256-GCM-HKDF-SHA256",
                                "iv": iv.hex(),
                                "ciphertext": bytes(tampered).hex(),
                            },
                        },
                    }
                ).encode("utf-8")

        def fake_urlopen(request, timeout):
            captured["request"] = request
            return FakeResponse()

        with patch("api.routes_phone.urlopen", side_effect=fake_urlopen):
            with self.assertRaises(routes_phone.PhonePairingError) as raised:
                claim(
                    "http://192.168.1.8:9527",
                    {
                        "sessionId": "session-a",
                        "bootstrapSecret": BOOTSTRAP_SECRET_HEX,
                        "deviceInstanceId": "lumi-phone-a",
                        "transportHint": "lan",
                    },
                    launcher_id="loom-desktop-a",
                    launcher_name="LOOM",
                )
        self.assertEqual("phone_pairing_credential_invalid", raised.exception.code)

    def test_pairing_response_redaction_removes_bootstrap_secrets_and_codes(self) -> None:
        sanitizer = getattr(routes_phone, "_public_phone_pairing_result", None)
        self.assertTrue(callable(sanitizer), "pairing response sanitizer must exist")

        public = sanitizer(
            {
                "ok": True,
                "code": "123456",
                "bootstrapSecret": BOOTSTRAP_SECRET_HEX,
                "phoneToken": "phone-secret",
                "launcherSecret": "launcher-secret",
                "launcherId": "loom-desktop-a",
                "deviceInstanceId": "lumi-phone-a",
            }
        )
        serialized = json.dumps(public)

        self.assertNotIn("123456", serialized)
        self.assertNotIn(BOOTSTRAP_SECRET_HEX, serialized)
        self.assertNotIn("phone-secret", serialized)
        self.assertNotIn("launcher-secret", serialized)
        self.assertEqual("connected", public["state"])
        self.assertEqual("lumi-phone-a", public["deviceInstanceId"])

    def test_phone_confirms_rotation_only_after_desktop_store_persists(self) -> None:
        source = Path(routes_phone.__file__).read_text(encoding="utf-8")
        route = source.split('@app.post("/api/phone/pairing/claim")', 1)[1].split(
            '@app.delete("/api/phone/config/device/{device_id}")',
            1,
        )[0]

        persist_index = route.index("_write_phone_store(ctx, next_store)")
        confirm_index = route.index("_retry_pending_phone_pairing_confirmations")
        self.assertLess(persist_index, confirm_index)
        self.assertIn("desktop credentials persisted", route)

    def test_pending_confirmation_persists_and_recovers_without_false_success(self) -> None:
        retry = getattr(routes_phone, "_retry_pending_phone_pairing_confirmations", None)
        self.assertTrue(callable(retry), "pending pairing confirmation retry helper must exist")

        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "phone-agents.json")
            storage = {
                path: {
                    "selectedDeviceId": "phone-a",
                    "devices": [{
                        "id": "phone-a",
                        "name": "Phone A",
                        "baseUrl": "http://192.168.1.8:9527",
                        "token": PHONE_TOKEN,
                        "launcherId": "loom-desktop-a",
                        "launcherSecret": LAUNCHER_SECRET,
                        "pairingConfirmed": False,
                        "pairingConfirmationPending": True,
                        "pairingConfirmationAttempts": 0,
                        "pairingConfirmationNextRetryAt": 0,
                    }],
                }
            }
            logs: list[str] = []
            ctx = SimpleNamespace(
                paths=SimpleNamespace(launcher_dir=temp_dir),
                read_json=lambda target, default: storage.get(target, default),
                write_json=lambda target, value: storage.__setitem__(target, value),
                append_log=logs.append,
            )

            def protect(value):
                return {
                    routes_phone.SECRET_MARKER: routes_phone.DPAPI_PROVIDER,
                    "value": str(value).encode("utf-8").hex(),
                }

            def unprotect(value):
                if isinstance(value, dict):
                    return bytes.fromhex(str(value.get("value") or "")).decode("utf-8")
                return str(value or "")

            pending_error = routes_phone.PhonePairingError(
                "phone_pairing_confirmation_pending",
                "手机暂不可达",
                retryable=True,
                status_code=409,
            )
            with patch("api.routes_phone.protect_secret", side_effect=protect), patch(
                "api.routes_phone.unprotect_secret",
                side_effect=unprotect,
            ), patch(
                "api.routes_phone._confirm_phone_pairing_persisted",
                side_effect=[pending_error, {"confirmed": True}],
            ) as confirm:
                pending_store = retry(ctx, force=True, now_ms=1_000)
                pending_public = routes_phone._public_store(pending_store)["devices"][0]
                recovered_store = retry(ctx, force=True, now_ms=2_000)
                recovered_public = routes_phone._public_store(recovered_store)["devices"][0]

            self.assertEqual(2, confirm.call_count)
            self.assertTrue(pending_public["confirmationPending"])
            self.assertFalse(pending_public["confirmed"])
            self.assertIn("自动重试", pending_public["confirmationStatus"])
            self.assertFalse(recovered_public["confirmationPending"])
            self.assertTrue(recovered_public["confirmed"])
            self.assertIn("已确认", recovered_public["confirmationStatus"])
            serialized = json.dumps(storage[path], ensure_ascii=False)
            self.assertNotIn(PHONE_TOKEN, serialized)
            self.assertNotIn(LAUNCHER_SECRET, serialized)

            stored_device = storage[path]["devices"][0]
            stored_device.update({
                "pairingConfirmed": False,
                "pairingConfirmationPending": True,
                "pairingConfirmationAttempts": 0,
                "pairingConfirmationNextRetryAt": 0,
            })
            with patch("api.routes_phone.protect_secret", side_effect=protect), patch(
                "api.routes_phone.unprotect_secret",
                side_effect=unprotect,
            ), patch(
                "api.routes_phone._confirm_phone_pairing_persisted",
                side_effect=routes_phone.PhonePairingError(
                    "phone_pairing_confirmation_pending",
                    "手机仍不可达",
                    retryable=True,
                    status_code=409,
                ),
            ) as bounded_confirm:
                exhausted_store = {}
                for attempt in range(7):
                    exhausted_store = retry(ctx, force=True, now_ms=3_000 + attempt)

            exhausted_public = routes_phone._public_store(exhausted_store)["devices"][0]
            self.assertEqual(routes_phone._PHONE_PAIRING_CONFIRMATION_MAX_ATTEMPTS, bounded_confirm.call_count)
            self.assertTrue(exhausted_public["confirmationPending"])
            self.assertFalse(exhausted_public["confirmed"])
            self.assertIn("达到上限", exhausted_public["confirmationStatus"])

    def test_phone_pairing_ui_separates_lan_payload_from_usb_code_and_uses_pairing_icon(self) -> None:
        activity = (
            PHONE_AGENT_DIR
            / "java/com/apk/claw/android/ui/settings/PcPairingActivity.kt"
        ).read_text(encoding="utf-8")
        layout = (
            PHONE_AGENT_DIR / "res/layout/activity_pc_pairing.xml"
        ).read_text(encoding="utf-8")
        settings = (
            PHONE_AGENT_DIR
            / "java/com/apk/claw/android/ui/settings/SettingsActivity.kt"
        ).read_text(encoding="utf-8")
        pairing_block = settings.split(
            "menuItems[SettingsViewModel.MenuAction.PC_PAIRING.name]",
            1,
        )[1].split(
            "menuItems[SettingsViewModel.MenuAction.LAN_CONFIG.name]",
            1,
        )[0]

        self.assertIn('android:id="@+id/pairingCodeSection"', layout)
        self.assertIn("codeSection.visibility", activity)
        self.assertIn("pc_pairing_tip_usb", activity)
        self.assertIn("pc_pairing_tip_lan", activity)
        self.assertIn("R.drawable.ic_pc_pairing", pairing_block)
        self.assertNotIn("R.drawable.ic_api_token", pairing_block)


if __name__ == "__main__":
    unittest.main()
