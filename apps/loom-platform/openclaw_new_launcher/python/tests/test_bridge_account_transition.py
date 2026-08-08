from __future__ import annotations

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch


PYTHON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)


from core.job_ownership import AccountRuntimeIdentity, account_job_binding


class BridgeAccountTransitionTests(unittest.TestCase):
    def test_logout_uses_account_session_identity_when_entitlement_anchor_changed(
        self,
    ) -> None:
        import bridge

        install_id = "install-a"
        identity = AccountRuntimeIdentity(
            account_id="account-a",
            owner_binding=account_job_binding("account-a", install_id),
            logged_in=True,
        )

        class FakeJobs:
            def cancel_matching(self, _predicate, *, wait_for_workers=True):
                self.wait_for_workers = wait_for_workers
                return []

            def list(self, limit=30):
                del limit
                return []

        class FakeMatrix:
            def __init__(self, _paths, **_kwargs) -> None:
                pass

            def emergency_stop(self, *, all_tasks=False):
                return {
                    "cancelled": all_tasks,
                    "executionMayContinue": False,
                }

        current_ctx = SimpleNamespace(
            get_newapi_account_mgr=lambda: SimpleNamespace(
                public_session=lambda: {
                    "loggedIn": True,
                    "memberId": "newapi:account-a",
                },
            ),
            get_entitlement_mgr=lambda: SimpleNamespace(
                current_state=lambda _feature: {
                    "accountId": "account-b",
                    "lease": {"installId": install_id},
                },
            ),
            paths=SimpleNamespace(base_path=install_id),
        )
        with (
            patch.object(bridge, "_build_fastapi_context", return_value=current_ctx),
            patch.object(bridge, "_get_job_mgr", return_value=FakeJobs()),
            patch.object(
                bridge,
                "_shutdown_agent_service",
                return_value={
                    "stopped": True,
                    "drained": True,
                    "executionMayContinue": False,
                },
            ) as shutdown_agent,
            patch("core.phone_matrix.MatrixControlPlane", FakeMatrix),
            patch(
                "api.routes_phone.stop_phone_event_syncs_for_account",
                return_value={"ok": True, "executionMayContinue": False},
            ),
            patch(
                "api.routes_phone.stop_phone_daemon",
                return_value={
                    "ok": True,
                    "running": False,
                    "stopped": True,
                    "executionMayContinue": False,
                },
            ) as stop_daemon,
            patch(
                "api.routes_phone.cleanup_phone_usb_for_account",
                return_value={
                    "failedDeviceIds": [],
                    "executionMayContinue": False,
                },
            ),
        ):
            result = bridge._account_logout_cleanup(identity)

        self.assertFalse(result["identityChanged"])
        self.assertTrue(result["ok"])
        shutdown_agent.assert_called_once_with()
        stop_daemon.assert_called_once_with(base_root=bridge.paths.base_path)

    def test_agent_service_cannot_be_recreated_during_account_transition(
        self,
    ) -> None:
        import bridge

        token = bridge._begin_account_transition()
        try:
            with self.assertRaisesRegex(ValueError, "account transition in progress"):
                bridge._get_agent_service()
        finally:
            self.assertTrue(bridge._end_account_transition(token))

        self.assertFalse(bridge._account_transition_active())

    def test_bridge_shutdown_stops_phone_daemon_even_if_agent_shutdown_fails(
        self,
    ) -> None:
        import bridge

        with (
            patch.object(
                bridge,
                "_shutdown_agent_service",
                side_effect=RuntimeError("agent shutdown failed"),
            ),
            patch(
                "api.routes_phone.stop_phone_daemon",
                return_value={
                    "ok": True,
                    "running": False,
                    "stopped": True,
                },
            ) as stop_daemon,
        ):
            result = bridge._shutdown_bridge_runtime()

        stop_daemon.assert_called_once_with(base_root=bridge.paths.base_path)
        self.assertTrue(result["daemon"]["stopped"])
        self.assertEqual(result["errors"], ["agent"])

    def test_stale_cleanup_targets_old_account_without_stopping_new_global_runtime(
        self,
    ) -> None:
        import bridge

        install_id = "install-a"
        old_identity = AccountRuntimeIdentity(
            account_id="account-a",
            owner_binding=account_job_binding("account-a", install_id),
            logged_in=True,
        )
        new_binding = account_job_binding("account-b", install_id)
        cancelled: list[str] = []
        matrix_identity: list[tuple[str, str]] = []

        class FakeJobs:
            candidates = [
                {
                    "id": "job-a",
                    "kind": "phone.task",
                    "status": "running",
                    "progress": {
                        "ownerAccountBinding": old_identity.owner_binding,
                    },
                },
                {
                    "id": "job-b",
                    "kind": "phone.task",
                    "status": "running",
                    "progress": {
                        "ownerAccountBinding": new_binding,
                    },
                },
            ]

            def cancel_matching(self, predicate, *, wait_for_workers=True):
                self.wait_for_workers = wait_for_workers
                cancelled.extend(
                    item["id"] for item in self.candidates if predicate(item)
                )
                for item in self.candidates:
                    if item["id"] in cancelled:
                        item["status"] = "cancelled"
                return list(cancelled)

            def list(self, limit=30):
                del limit
                return list(self.candidates)

        class FakeMatrix:
            def __init__(
                self,
                _paths,
                *,
                owner_account_id="",
                owner_account_binding="",
                **_kwargs,
            ) -> None:
                matrix_identity.append(
                    (owner_account_id, owner_account_binding)
                )

            def emergency_stop(self, *, all_tasks=False):
                self.assert_all = all_tasks
                return {
                    "cancelled": True,
                    "affectedTaskCount": 1,
                    "executionMayContinue": False,
                }

        current_ctx = SimpleNamespace(
            get_entitlement_mgr=lambda: SimpleNamespace(
                current_state=lambda _feature: {
                    "accountId": "account-b",
                    "lease": {"installId": install_id},
                },
            ),
            paths=SimpleNamespace(base_path=install_id),
        )
        with (
            patch.object(bridge, "_build_fastapi_context", return_value=current_ctx),
            patch.object(bridge, "_get_job_mgr", return_value=FakeJobs()),
            patch.object(bridge, "_shutdown_agent_service") as shutdown_agent,
            patch("core.phone_matrix.MatrixControlPlane", FakeMatrix),
            patch(
                "api.routes_phone.stop_phone_event_syncs_for_account",
                return_value={
                    "ok": True,
                    "executionMayContinue": False,
                },
            ) as stop_events,
            patch("api.routes_phone.stop_phone_daemon") as stop_daemon,
            patch(
                "api.routes_phone.cleanup_phone_usb_for_account",
                return_value={
                    "cleanedDeviceIds": ["phone-a"],
                    "failedDeviceIds": [],
                    "executionMayContinue": False,
                },
            ) as cleanup_usb,
        ):
            result = bridge._account_logout_cleanup(old_identity)

        self.assertEqual(cancelled, ["job-a"])
        self.assertNotIn("job-b", result["cancelledJobIds"])
        self.assertEqual(
            matrix_identity,
            [("account-a", old_identity.owner_binding)],
        )
        stop_events.assert_called_once_with("account-a")
        cleanup_usb.assert_called_once()
        self.assertEqual(cleanup_usb.call_args.args[1], "account-a")
        shutdown_agent.assert_not_called()
        stop_daemon.assert_not_called()
        self.assertTrue(result["identityChanged"])
        self.assertTrue(result["executionMayContinue"])

    def test_unresolved_identity_fails_closed_before_global_cleanup(self) -> None:
        import bridge

        unresolved = AccountRuntimeIdentity(
            account_id="",
            owner_binding="",
            logged_in=True,
        )
        with (
            patch.object(bridge, "_shutdown_agent_service") as shutdown_agent,
            patch.object(bridge, "_get_job_mgr") as jobs,
            patch("api.routes_phone.stop_phone_daemon") as stop_daemon,
        ):
            result = bridge._account_logout_cleanup(unresolved)

        self.assertFalse(result["ok"])
        self.assertEqual(
            result["code"],
            "account_runtime_identity_unresolved",
        )
        self.assertTrue(result["executionMayContinue"])
        shutdown_agent.assert_not_called()
        jobs.assert_not_called()
        stop_daemon.assert_not_called()

    def test_account_cleanup_fails_closed_when_daemon_shutdown_is_indeterminate(
        self,
    ) -> None:
        import bridge

        install_id = "install-a"
        identity = AccountRuntimeIdentity(
            account_id="account-a",
            owner_binding=account_job_binding("account-a", install_id),
            logged_in=True,
        )

        class FakeJobs:
            def cancel_matching(self, _predicate, *, wait_for_workers=True):
                self.wait_for_workers = wait_for_workers
                return []

            def list(self, limit=30):
                del limit
                return []

        class FakeMatrix:
            def __init__(self, _paths, **_kwargs) -> None:
                pass

            def emergency_stop(self, *, all_tasks=False):
                return {
                    "cancelled": all_tasks,
                    "executionMayContinue": False,
                }

        current_ctx = SimpleNamespace(
            get_entitlement_mgr=lambda: SimpleNamespace(
                current_state=lambda _feature: {
                    "accountId": "account-a",
                    "lease": {"installId": install_id},
                },
            ),
            paths=SimpleNamespace(base_path=install_id),
        )
        with (
            patch.object(bridge, "_build_fastapi_context", return_value=current_ctx),
            patch.object(bridge, "_get_job_mgr", return_value=FakeJobs()),
            patch.object(
                bridge,
                "_shutdown_agent_service",
                return_value={
                    "stopped": True,
                    "drained": True,
                    "executionMayContinue": False,
                },
            ),
            patch("core.phone_matrix.MatrixControlPlane", FakeMatrix),
            patch(
                "api.routes_phone.stop_phone_event_syncs_for_account",
                return_value={
                    "ok": True,
                    "executionMayContinue": False,
                },
            ),
            patch(
                "api.routes_phone.stop_phone_daemon",
                return_value={
                    "ok": False,
                    "running": False,
                    "stopped": True,
                    "executionMayContinue": True,
                    "outcomeIndeterminate": True,
                },
            ),
            patch(
                "api.routes_phone.cleanup_phone_usb_for_account",
                return_value={
                    "failedDeviceIds": [],
                    "executionMayContinue": False,
                },
            ),
        ):
            result = bridge._account_logout_cleanup(identity)

        self.assertFalse(result["ok"])
        self.assertTrue(result["executionMayContinue"])


if __name__ == "__main__":
    unittest.main()
