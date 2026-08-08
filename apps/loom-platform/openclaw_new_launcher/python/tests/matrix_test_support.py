from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Callable

from core.job_ownership import account_job_binding
from core.phone_matrix import MatrixControlPlane


MATRIX_TEST_ACCOUNT_ID = "account-matrix-test"


def allow_phone_operation(_device_ids: list[str], _operation: str) -> None:
    return None


def matrix_test_install_id(paths: Any) -> str:
    return str(
        getattr(paths, "base_path", "")
        or getattr(paths, "launcher_dir", "")
    )


class MatrixTestEntitlement:
    """Post-verification account entitlement state used by Matrix tests."""

    def __init__(
        self,
        paths: Any,
        *,
        account_id: str = MATRIX_TEST_ACCOUNT_ID,
    ) -> None:
        self.account_id = account_id
        self.install_id = matrix_test_install_id(paths)

    def current_state(self, _feature=None) -> dict[str, Any]:
        lease = {
            "accountId": self.account_id,
            "installId": self.install_id,
        }
        return {
            "authorized": True,
            "source": "account_entitlement",
            "accountId": self.account_id,
            "lease": lease,
            "features": ["matrix.devices"],
            "limits": {"devices": 1000, "concurrentTasks": 8},
        }

    def authorize_phone_devices(
        self,
        device_ids,
        operation,
        *,
        session=None,
    ) -> dict[str, Any]:
        del session
        return {
            "authorized": True,
            "source": "account_entitlement",
            "accountId": self.account_id,
            "phoneDeviceIds": list(device_ids),
            "operation": operation,
            "limits": {"devices": 1000, "concurrentTasks": 8},
        }


def matrix_context_for_test(
    paths: Any,
    *,
    entitlement: Any | None = None,
) -> SimpleNamespace:
    entitlement_manager = entitlement or MatrixTestEntitlement(paths)
    return SimpleNamespace(
        paths=paths,
        get_entitlement_mgr=lambda: entitlement_manager,
        protected_error=lambda _path: None,
    )


def matrix_for_test(
    paths: Any,
    *,
    phone_authorizer: Callable[[list[str], str], Any] | None = None,
    owner_account_id: str = MATRIX_TEST_ACCOUNT_ID,
) -> MatrixControlPlane:
    install_id = matrix_test_install_id(paths)
    return MatrixControlPlane(
        paths,
        phone_authorizer=phone_authorizer or allow_phone_operation,
        owner_account_id=owner_account_id,
        owner_account_binding=account_job_binding(owner_account_id, install_id),
    )
