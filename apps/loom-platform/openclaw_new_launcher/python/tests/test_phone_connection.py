from __future__ import annotations

import unittest

from core.phone_connection import select_phone_connection


class PhoneConnectionTest(unittest.TestCase):
    def test_parallel_probe_prefers_usb_when_usb_and_hotspot_are_both_verified(self) -> None:
        device = {
            "baseUrl": "http://127.0.0.1:19631",
            "connectionMode": "usb",
            "lanBaseUrl": "http://192.168.1.9:9527",
        }
        status = {
            "configServerRunning": True,
            "networkCandidates": [
                {
                    "baseUrl": "http://192.168.43.1:9527",
                    "mode": "hotspot-host",
                    "interface": "ap0",
                }
            ],
        }

        result = select_phone_connection(
            device,
            status=status,
            probe=lambda url: {"ok": True, "baseUrl": url, "deviceInstanceId": "phone-a"},
        )

        self.assertTrue(result["ok"])
        self.assertEqual("usb-loopback", result["activeTransport"])
        self.assertEqual("http://127.0.0.1:19631", result["baseUrl"])
        self.assertEqual(3, len(result["candidates"]))

    def test_hotspot_candidate_but_no_verified_endpoint_reports_computer_not_connected(self) -> None:
        result = select_phone_connection(
            {"baseUrl": "http://192.168.43.1:9527"},
            status={
                "configServerRunning": True,
                "networkCandidates": [
                    {"baseUrl": "http://192.168.43.1:9527", "mode": "hotspot-host"}
                ],
            },
            probe=lambda _url: {"ok": False, "status": "identity_check_failed"},
        )

        self.assertFalse(result["ok"])
        self.assertEqual("phone_hotspot_client_disconnected", result["errorCode"])

    def test_missing_expected_hotspot_and_stopped_service_have_distinct_failures(self) -> None:
        missing = select_phone_connection(
            {"expectedNetworkMode": "hotspot-host"},
            status={"configServerRunning": True, "networkCandidates": []},
            probe=lambda _url: {"ok": False},
        )
        stopped = select_phone_connection(
            {"baseUrl": "http://192.168.1.9:9527"},
            status={"configServerRunning": False, "networkCandidates": []},
            probe=lambda _url: {"ok": False},
        )

        self.assertEqual("phone_hotspot_not_enabled", missing["errorCode"])
        self.assertEqual("phone_connection_service_stopped", stopped["errorCode"])

    def test_invalid_pairing_identity_is_not_misreported_as_network_failure(self) -> None:
        result = select_phone_connection(
            {"baseUrl": "http://192.168.1.9:9527"},
            status={"configServerRunning": True},
            probe=lambda _url: {"ok": False, "status": "device_identity_mismatch"},
        )

        self.assertEqual("phone_pairing_credential_invalid", result["errorCode"])


if __name__ == "__main__":
    unittest.main()
