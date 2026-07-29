from __future__ import annotations

from typing import Any, Callable

from core.phone_matrix import MatrixControlPlane


def allow_phone_operation(_device_ids: list[str], _operation: str) -> None:
    return None


def matrix_for_test(
    paths: Any,
    *,
    phone_authorizer: Callable[[list[str], str], Any] | None = None,
) -> MatrixControlPlane:
    return MatrixControlPlane(
        paths,
        phone_authorizer=phone_authorizer or allow_phone_operation,
    )
