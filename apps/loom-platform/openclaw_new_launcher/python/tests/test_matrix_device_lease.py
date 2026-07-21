from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import patch


PYTHON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)


class MatrixDeviceLeaseTests(unittest.TestCase):
    def test_lease_is_exclusive_renewable_and_releasable(self) -> None:
        from core.paths import AppPaths
        from core.phone_matrix import MatrixControlPlane, MatrixTargetError

        with tempfile.TemporaryDirectory() as temp_dir:
            matrix = MatrixControlPlane(AppPaths(base_path=temp_dir))
            matrix.register_device({"deviceId": "phone-a", "online": True})

            first = matrix.acquire_lease(
                "phone-a",
                {"holderType": "human", "holderId": "operator-1", "token": "phone-secret"},
            )
            renewed = matrix.acquire_lease(
                "phone-a",
                {
                    "holderType": "human",
                    "holderId": "operator-1",
                    "leaseId": first["leaseId"],
                    "credential": "another-secret",
                },
            )
            with self.assertRaises(MatrixTargetError) as raised:
                matrix.acquire_lease(
                    "phone-a",
                    {"holderType": "agent", "holderId": "run-2"},
                )
            current = matrix.get_lease("phone-a")
            released = matrix.release_lease("phone-a", first["leaseId"])

        self.assertEqual(raised.exception.code, "device_lease_conflict")
        self.assertEqual(renewed["leaseId"], first["leaseId"])
        self.assertEqual(current["lease"]["holderId"], "operator-1")
        self.assertGreater(current["remainingTtlMs"], 0)
        self.assertLessEqual(current["remainingTtlMs"], 30_000)
        self.assertTrue(released["released"])
        self.assertIsNone(released["lease"])
        serialized = json.dumps({"first": first, "renewed": renewed, "current": current})
        self.assertNotIn("phone-secret", serialized)
        self.assertNotIn("another-secret", serialized)

    def test_expired_lease_can_be_replaced_by_another_holder(self) -> None:
        from core.paths import AppPaths
        from core.phone_matrix import MatrixControlPlane

        with tempfile.TemporaryDirectory() as temp_dir:
            matrix = MatrixControlPlane(AppPaths(base_path=temp_dir))
            matrix.register_device({"deviceId": "phone-a", "online": True})
            first = matrix.acquire_lease(
                "phone-a",
                {"holderType": "agent", "holderId": "run-old"},
            )
            with open(matrix.leases_path, "r", encoding="utf-8") as handle:
                state = json.load(handle)
            state["leases"][0]["expiresAt"] = "2000-01-01T00:00:00Z"
            with open(matrix.leases_path, "w", encoding="utf-8") as handle:
                json.dump(state, handle)

            replacement = matrix.acquire_lease(
                "phone-a",
                {"holderType": "human", "holderId": "operator-new"},
            )

        self.assertNotEqual(replacement["leaseId"], first["leaseId"])
        self.assertEqual(replacement["holderType"], "human")
        self.assertGreater(
            datetime.fromisoformat(replacement["expiresAt"].replace("Z", "+00:00")),
            datetime.now(timezone.utc),
        )

    def test_emergency_stop_releases_only_matching_agent_leases(self) -> None:
        from core.paths import AppPaths
        from core.phone_matrix import MatrixControlPlane

        with tempfile.TemporaryDirectory() as temp_dir:
            matrix = MatrixControlPlane(AppPaths(base_path=temp_dir))
            for device_id in ("phone-a", "phone-b", "phone-c"):
                matrix.register_device({"deviceId": device_id, "online": True})
            matrix.acquire_lease("phone-a", {"holderType": "agent", "holderId": "run-a"})
            matrix.acquire_lease("phone-b", {"holderType": "agent", "holderId": "run-b"})
            matrix.acquire_lease("phone-c", {"holderType": "human", "holderId": "operator-c"})
            matrix.dispatch({"prompt": "read", "target": {"deviceIds": ["phone-a"]}})

            result = matrix.emergency_stop(device_ids={"phone-a"})

            lease_a = matrix.get_lease("phone-a")["lease"]
            lease_b = matrix.get_lease("phone-b")["lease"]
            lease_c = matrix.get_lease("phone-c")["lease"]

        self.assertEqual(result["releasedAgentLeaseDeviceIds"], ["phone-a"])
        self.assertIsNone(lease_a)
        self.assertEqual(lease_b["holderId"], "run-b")
        self.assertEqual(lease_c["holderId"], "operator-c")

    def test_lease_acquisition_fails_closed_on_corrupt_ledger(self) -> None:
        from core.paths import AppPaths
        from core.phone_matrix import MatrixControlPlane, MatrixTargetError

        with tempfile.TemporaryDirectory() as temp_dir:
            matrix = MatrixControlPlane(AppPaths(base_path=temp_dir))
            matrix.register_device({"deviceId": "phone-a", "online": True})
            with open(matrix.leases_path, "w", encoding="utf-8") as handle:
                handle.write("{corrupt")

            with self.assertRaises(MatrixTargetError) as first:
                matrix.acquire_lease(
                    "phone-a", {"holderType": "human", "holderId": "operator-1"}
                )
            with self.assertRaises(MatrixTargetError) as second:
                matrix.acquire_lease(
                    "phone-a", {"holderType": "human", "holderId": "operator-1"}
                )

        self.assertEqual(first.exception.code, "matrix_lease_ledger_unavailable")
        self.assertEqual(second.exception.code, "matrix_lease_ledger_unavailable")

    def test_lease_acquisition_fails_closed_on_ledger_read_error(self) -> None:
        from core.paths import AppPaths
        from core.phone_matrix import MatrixControlPlane, MatrixTargetError

        with tempfile.TemporaryDirectory() as temp_dir:
            matrix = MatrixControlPlane(AppPaths(base_path=temp_dir))
            matrix.register_device({"deviceId": "phone-a", "online": True})
            lease = matrix.acquire_lease(
                "phone-a", {"holderType": "human", "holderId": "operator-1"}
            )
            matrix.release_lease("phone-a", lease["leaseId"])
            real_open = open

            def deny_lease_ledger(path, *args, **kwargs):
                if os.path.abspath(path) == os.path.abspath(matrix.leases_path):
                    raise PermissionError("lease ledger denied")
                return real_open(path, *args, **kwargs)

            with patch("core.phone_matrix.open", side_effect=deny_lease_ledger, create=True):
                with self.assertRaises(MatrixTargetError) as raised:
                    matrix.acquire_lease(
                        "phone-a", {"holderType": "human", "holderId": "operator-2"}
                    )

        self.assertEqual(raised.exception.code, "matrix_lease_ledger_unavailable")


if __name__ == "__main__":
    unittest.main()
