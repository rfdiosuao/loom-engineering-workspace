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
PHONE_AGENT_REPO = APPS_DIR / "loom-phone-agent"
UNIFIED_PHONE_SKILL = (
    APPS_DIR
    / "loom-platform"
    / "packages"
    / "luming-skills-library"
    / "skills"
    / "luming-phone-agent"
    / "SKILL.md"
)


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
        proof_over_usb = parser(
            {
                "payload": (
                    "lumi://pair?v=3&b=http%3A%2F%2F192.168.1.8%3A9527"
                    f"&d=lumi-phone-a&s=session-a&k={BOOTSTRAP_SECRET_HEX}"
                    "&n=Pixel&x=lan"
                ),
                "usbSerial": "ABC123",
            }
        )

        self.assertEqual("http://192.168.1.8:9527", payload["baseUrl"])
        self.assertEqual("lumi-phone-a", payload["deviceInstanceId"])
        self.assertEqual("session-a", payload["sessionId"])
        self.assertEqual(BOOTSTRAP_SECRET_HEX, payload["bootstrapSecret"])
        self.assertEqual("", payload["code"])
        self.assertEqual("654321", usb["code"])
        self.assertEqual("lan", proof_over_usb["transportHint"])
        self.assertEqual("ABC123", proof_over_usb["usbSerial"])
        self.assertEqual("", proof_over_usb["code"])
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
                "http://127.0.0.1:19527",
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

    def test_pairing_rotation_uses_a_fresh_launcher_identity(self) -> None:
        source = Path(routes_phone.__file__).read_text(encoding="utf-8")
        route = source.split('@app.post("/api/phone/pairing/claim")', 1)[1].split(
            '@app.delete("/api/phone/config/device/{device_id}")',
            1,
        )[0]

        self.assertIn('launcher_id = f"loom-desktop-{secrets.token_hex(8)}"', route)
        self.assertNotIn('_clip(existing.get("launcherId")', route)

    def test_phone_config_get_does_not_wait_for_confirmation_network_io(self) -> None:
        source = Path(routes_phone.__file__).read_text(encoding="utf-8")
        route = source.split(
            '@app.api_route("/api/phone/config", methods=["GET", "POST"])',
            1,
        )[1].split('@app.post("/api/phone/pairing/claim")', 1)[0]

        self.assertNotIn("_retry_pending_phone_pairing_confirmations", route)
        self.assertIn("store = _load_store(ctx)", route)

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
                continuing_store = {}
                for attempt in range(7):
                    continuing_store = retry(ctx, force=True, now_ms=3_000 + attempt)

            continuing_public = routes_phone._public_store(continuing_store)["devices"][0]
            self.assertEqual(7, bounded_confirm.call_count)
            self.assertTrue(continuing_public["confirmationPending"])
            self.assertFalse(continuing_public["confirmed"])
            self.assertGreater(
                continuing_store["devices"][0]["pairingConfirmationNextRetryAt"],
                3_006,
            )
            self.assertIn("持续自动重试", continuing_public["confirmationStatus"])

    def test_pending_confirmation_has_a_periodic_background_retry_task(self) -> None:
        source = Path(routes_phone.__file__).read_text(encoding="utf-8")

        self.assertIn("async def retry_pending_phone_pairing_confirmations_forever()", source)
        self.assertIn("phone_pairing_confirmation_retry_task", source)
        self.assertIn("app.router.on_shutdown.append(stop_phone_pairing_confirmation_retry)", source)

    def test_legacy_cli_pairing_never_sends_old_token_over_lan(self) -> None:
        secure_client = (
            APPS_DIR
            / "loom-platform"
            / "openclaw_new_launcher"
            / "scripts"
            / "openclaw-phone-secure.mjs"
        ).read_text(encoding="utf-8")
        pairing_function = secure_client.split(
            "export async function pairLumiLauncher", 1
        )[1].split("export async function signedJsonRequest", 1)[0]

        self.assertIn("assertLegacyPairingUsbOnly(config)", pairing_function)
        self.assertIn("phone_legacy_pairing_usb_required", secure_client)

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

    def test_user_onboarding_exposes_pairing_instead_of_manual_phone_tokens(self) -> None:
        readme = (PHONE_AGENT_REPO / "README.md").read_text(encoding="utf-8")
        readme_cn = (PHONE_AGENT_REPO / "README_CN.md").read_text(encoding="utf-8")
        unified_skill = UNIFIED_PHONE_SKILL.read_text(encoding="utf-8")

        self.assertIn("Step 4: 与 LOOM 配对", readme)
        self.assertIn("配对码", readme)
        self.assertIn("LOOM CLI/MCP", unified_skill)
        self.assertIn("配对", unified_skill)
        for obsolete in (
            "Settings → API Token",
            "配置 API Token",
            "your-api-token",
            "your-token",
            "your-token-here",
            "prompt: API Token",
            "X-AGENT-PHONE-TOKEN",
            "X-APKCLAW-TOKEN",
        ):
            self.assertNotIn(obsolete, readme)
            self.assertNotIn(obsolete, readme_cn)
            self.assertNotIn(obsolete, unified_skill)

        legacy_skills = list((PHONE_AGENT_REPO / "skills").glob("*/SKILL.md"))
        self.assertEqual(
            [],
            legacy_skills,
            "legacy direct-token phone Skills must not remain as a competing entrypoint",
        )

    def test_phone_long_lived_credentials_use_android_keystore_with_plaintext_migration(self) -> None:
        vault_path = (
            PHONE_AGENT_DIR
            / "java/com/apk/claw/android/utils/PhoneCredentialVault.kt"
        )
        self.assertTrue(vault_path.is_file(), "phone credential vault must exist")
        vault = vault_path.read_text(encoding="utf-8")
        kv = (
            PHONE_AGENT_DIR / "java/com/apk/claw/android/utils/KVUtils.kt"
        ).read_text(encoding="utf-8")

        self.assertIn("AndroidKeyStore", vault)
        self.assertIn("AES/GCM/NoPadding", vault)
        self.assertIn("KeyProperties.PURPOSE_ENCRYPT", vault)
        self.assertIn("migratePlaintext", vault)
        self.assertIn("return plaintext", vault)
        self.assertIn("PhoneCredentialVault.init(context)", kv)
        self.assertRegex(kv, r"PhoneCredentialVault\.get\(\s*KEY_API_TOKEN")
        self.assertIn("KEY_API_TOKEN to phoneToken", kv)
        self.assertRegex(
            kv,
            r"PhoneCredentialVault\.get\(\s*KEY_LUMI_LAUNCHER_SECRET",
        )
        self.assertIn("KEY_LUMI_LAUNCHER_SECRET to launcherSecret", kv)
        self.assertIn("KEY_LUMI_LAUNCHER_ID to launcherId", kv)
        self.assertIn("KEY_PREVIOUS_LUMI_LAUNCHER_ID to rollbackLauncherId", kv)
        self.assertIn("KEY_PREVIOUS_PHONE_CREDENTIAL_VALID_UNTIL to", kv)
        self.assertIn("PhoneCredentialVault.putAll(", kv)
        self.assertIn("if (stored) remove(KEY_API_TOKEN)", kv)
        self.assertIn(
            "remove(KEY_LUMI_LAUNCHER_ID, KEY_LUMI_LAUNCHER_SECRET)",
            kv,
        )
        self.assertNotIn(
            "fun getApiToken(): String = getString(KEY_API_TOKEN",
            kv,
        )
        self.assertNotIn(
            "fun setApiToken(value: String) = putString(KEY_API_TOKEN",
            kv,
        )


if __name__ == "__main__":
    unittest.main()
