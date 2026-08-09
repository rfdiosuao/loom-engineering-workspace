from __future__ import annotations

import logging
from typing import Any, Callable


Route = Callable[[Any, Any], None]
LOGGER = logging.getLogger("openclaw-license")


def _require_service_auth(handler: Any) -> bool:
    api = handler.facade
    if not api.account_redeem_service_configured():
        handler.send_json(
            503,
            {
                "ok": False,
                "error": "Account entitlement service auth is not configured",
                "code": "SERVICE_AUTH_NOT_CONFIGURED",
            },
        )
        return False
    if api.account_redeem_service_token_valid(handler.headers):
        return True
    handler.send_json(
        401,
        {
            "ok": False,
            "error": "Service authentication required",
            "code": "SERVICE_AUTH_REQUIRED",
        },
        headers={"WWW-Authenticate": 'Bearer realm="loom-account-entitlements"'},
    )
    return False


def _send_activation_error(handler: Any, error: Exception) -> None:
    handler.send_json(
        error.status,
        {"ok": False, "error": str(error), "code": error.code},
    )


def post_account_entitlements_redeem(handler: Any, parsed: Any) -> None:
    del parsed
    api = handler.facade
    if not _require_service_auth(handler):
        return
    try:
        entitlement = api.redeem_account_entitlement(
            handler.read_json(),
            request_ip=handler.request_ip(),
        )
        handler.send_json(200, {"ok": True, "entitlement": entitlement})
    except api.ActivationError as error:
        _send_activation_error(handler, error)
    except ValueError:
        handler.send_json(
            400,
            {
                "ok": False,
                "error": "Invalid JSON body",
                "code": "ACCOUNT_REDEEM_INVALID_REQUEST",
            },
        )
    except Exception:
        LOGGER.exception("Account entitlement redeem failed")
        handler.send_json(
            500,
            {
                "ok": False,
                "error": "Internal server error",
                "code": "INTERNAL_ERROR",
            },
        )


def post_account_entitlements_current(handler: Any, parsed: Any) -> None:
    del parsed
    api = handler.facade
    if not _require_service_auth(handler):
        return
    try:
        body = handler.read_json()
        if not isinstance(body, dict):
            raise api.ActivationError(
                "Invalid JSON body",
                400,
                "ACCOUNT_REDEEM_INVALID_REQUEST",
            )
        entitlement = api.current_account_entitlement(body.get("accountId"))
        handler.send_json(200, {"ok": True, "entitlement": entitlement})
    except api.ActivationError as error:
        _send_activation_error(handler, error)
    except ValueError:
        handler.send_json(
            400,
            {
                "ok": False,
                "error": "Invalid JSON body",
                "code": "ACCOUNT_REDEEM_INVALID_REQUEST",
            },
        )
    except Exception:
        LOGGER.exception("Account entitlement current lookup failed")
        handler.send_json(
            500,
            {
                "ok": False,
                "error": "Internal server error",
                "code": "INTERNAL_ERROR",
            },
        )


def post_account_entitlements_migrate_legacy(handler: Any, parsed: Any) -> None:
    del parsed
    api = handler.facade
    if not _require_service_auth(handler):
        return
    try:
        entitlement = api.migrate_legacy_account_entitlement(
            handler.read_json(),
            request_ip=handler.request_ip(),
        )
        handler.send_json(200, {"ok": True, "entitlement": entitlement})
    except api.ActivationError as error:
        _send_activation_error(handler, error)
    except ValueError:
        handler.send_json(
            400,
            {
                "ok": False,
                "error": "Invalid JSON body",
                "code": "ACCOUNT_REDEEM_INVALID_REQUEST",
            },
        )
    except Exception:
        LOGGER.exception("Legacy account entitlement migration failed")
        handler.send_json(
            500,
            {
                "ok": False,
                "error": "Internal server error",
                "code": "INTERNAL_ERROR",
            },
        )


GET_ROUTES: dict[str, Route] = {}

POST_ROUTES: dict[str, Route] = {
    "/api/service/account-entitlements/redeem": post_account_entitlements_redeem,
    "/api/service/account-entitlements/current": post_account_entitlements_current,
    "/api/service/account-entitlements/migrate-legacy": post_account_entitlements_migrate_legacy,
}


__all__ = [
    "GET_ROUTES",
    "POST_ROUTES",
    "post_account_entitlements_current",
    "post_account_entitlements_migrate_legacy",
    "post_account_entitlements_redeem",
]
