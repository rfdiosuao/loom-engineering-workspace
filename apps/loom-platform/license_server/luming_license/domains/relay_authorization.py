from __future__ import annotations

import hashlib
import logging
import secrets
import time
from collections.abc import Callable
from typing import Any

from .. import security, signing
from ..config import Settings
from ..errors import ActivationError
from ..serialization import normalize_string


LOGGER = logging.getLogger("openclaw-license")
PUBLISH_RELAY_PRODUCER_AUTH_SCHEMA = "loom.phone.publish.authorization.v1"
PUBLISH_RELAY_ENTITLEMENT_SCHEMA = "loom.entitlement_lease.v1"
PUBLISH_RELAY_PHONE_SEAT_SCHEMA = "loom.phone_seat_lease.v1"
PUBLISH_RELAY_ENTITLEMENT_KEY_ID = "openclaw-ed25519-v1"
PUBLISH_RELAY_PRODUCER_FEATURES = frozenset({"matrix.devices", "phoneAgent"})
PUBLISH_RELAY_MAX_CLOCK_SKEW_SECONDS = 300

CurrentEntitlementFn = Callable[[str], dict[str, Any]]


def _settings(settings: Settings | None) -> Settings:
    return settings or Settings.from_env()


def _producer_authentication_error() -> ActivationError:
    return ActivationError(
        "Relay producer authentication required",
        401,
        "RELAY_PRODUCER_AUTH_REQUIRED",
    )


def _producer_entitlement_error() -> ActivationError:
    return ActivationError(
        "Relay producer entitlement required",
        403,
        "RELAY_PRODUCER_ENTITLEMENT_REQUIRED",
    )


def _producer_auth_unavailable() -> ActivationError:
    return ActivationError(
        "Relay producer authentication unavailable",
        503,
        "RELAY_PRODUCER_AUTH_UNAVAILABLE",
    )


def _producer_account_id(value: Any) -> str:
    account_id = normalize_string(value)
    if (
        not account_id
        or len(account_id) > 128
        or any(ord(character) < 32 or ord(character) == 127 for character in account_id)
    ):
        raise _producer_authentication_error()
    return account_id


def _producer_device_instance_id(value: Any) -> str:
    device_instance_id = normalize_string(value)
    if (
        not device_instance_id
        or len(device_instance_id) > 256
        or any(
            ord(character) < 32 or ord(character) == 127
            for character in device_instance_id
        )
    ):
        raise _producer_authentication_error()
    return device_instance_id


def _positive_int(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise _producer_authentication_error()
    return value


def _producer_features(value: Any) -> set[str]:
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) or not item.strip() for item in value)
    ):
        raise _producer_authentication_error()
    return {item.strip() for item in value}


def _validate_signed_lease_window(
    lease: dict[str, Any],
    *,
    now_seconds: int,
    allow_offline_grace: bool,
) -> None:
    issued_at = _positive_int(lease.get("issuedAt"))
    expires_at = _positive_int(lease.get("expiresAt"))
    offline_grace_until = (
        _positive_int(lease.get("offlineGraceUntil"))
        if "offlineGraceUntil" in lease
        else expires_at
    )
    if (
        issued_at >= expires_at
        or expires_at > offline_grace_until
        or issued_at > now_seconds + PUBLISH_RELAY_MAX_CLOCK_SKEW_SECONDS
        or now_seconds > (offline_grace_until if allow_offline_grace else expires_at)
    ):
        raise _producer_authentication_error()


def _verify_producer_signature(
    lease: dict[str, Any],
    *,
    settings: Settings,
) -> None:
    try:
        valid = signing.verify_license(
            lease,
            private_key_file=settings.private_key_file,
        )
    except (OSError, RuntimeError):
        LOGGER.exception("Publish relay producer signature verification unavailable")
        raise _producer_auth_unavailable() from None
    if not valid:
        raise _producer_authentication_error()


def publish_relay_producer_request_token(headers: Any) -> str:
    token = security.extract_bearer_token(headers)
    if not token:
        raise _producer_authentication_error()
    return token


def _producer_session_binding(token: str) -> str:
    return hashlib.sha256(
        b"loom-entitlement-session-v1\0" + token.encode("utf-8")
    ).hexdigest()


def publish_relay_validate_producer_authorization(
    authorization: Any,
    *,
    current_entitlement_fn: CurrentEntitlementFn,
    producer_token: str = "",
    settings: Settings | None = None,
    now_seconds: int | None = None,
    require_session_binding: bool = True,
) -> dict[str, Any]:
    active_settings = _settings(settings)
    if not isinstance(authorization, dict):
        raise _producer_authentication_error()
    if normalize_string(authorization.get("schema")) != PUBLISH_RELAY_PRODUCER_AUTH_SCHEMA:
        raise _producer_authentication_error()

    account_id = _producer_account_id(authorization.get("accountId"))
    selected_device_instance_id = _producer_device_instance_id(
        authorization.get("selectedDeviceInstanceId")
    )
    entitlement_version = _positive_int(authorization.get("entitlementVersion"))
    runtime_digest = normalize_string(authorization.get("runtimeConfigDigest")).lower()
    if len(runtime_digest) != 64 or any(
        character not in "0123456789abcdef" for character in runtime_digest
    ):
        raise _producer_authentication_error()

    entitlement_lease = authorization.get("entitlementLease")
    if not isinstance(entitlement_lease, dict):
        raise _producer_authentication_error()
    if (
        normalize_string(entitlement_lease.get("schema"))
        != PUBLISH_RELAY_ENTITLEMENT_SCHEMA
        or normalize_string(entitlement_lease.get("keyId"))
        != PUBLISH_RELAY_ENTITLEMENT_KEY_ID
        or _producer_account_id(entitlement_lease.get("accountId")) != account_id
        or _positive_int(entitlement_lease.get("entitlementVersion"))
        != entitlement_version
        or normalize_string(entitlement_lease.get("source")) != "authorization_code"
    ):
        raise _producer_authentication_error()
    lease_features = _producer_features(entitlement_lease.get("features"))
    lease_limits = entitlement_lease.get("limits")
    if (
        not isinstance(lease_limits, dict)
        or lease_limits.get("unlimitedDevices") is not True
        or _positive_int(lease_limits.get("devices")) < 1
        or _positive_int(lease_limits.get("concurrentTasks")) < 1
        or not lease_features.intersection(PUBLISH_RELAY_PRODUCER_FEATURES)
    ):
        raise _producer_authentication_error()

    current_seconds = int(time.time()) if now_seconds is None else int(now_seconds)
    _validate_signed_lease_window(
        entitlement_lease,
        now_seconds=current_seconds,
        allow_offline_grace=False,
    )
    _verify_producer_signature(entitlement_lease, settings=active_settings)
    if require_session_binding:
        expected_session_binding = normalize_string(
            entitlement_lease.get("sessionBinding")
        ).lower()
        actual_session_binding = _producer_session_binding(
            normalize_string(producer_token)
        )
        if (
            len(expected_session_binding) != 64
            or any(
                character not in "0123456789abcdef"
                for character in expected_session_binding
            )
            or not producer_token
            or not secrets.compare_digest(
                actual_session_binding,
                expected_session_binding,
            )
        ):
            raise _producer_authentication_error()

    phone_seat_lease = authorization.get("phoneSeatLease")
    if phone_seat_lease is not None:
        if not isinstance(phone_seat_lease, dict):
            raise _producer_authentication_error()
        if (
            normalize_string(phone_seat_lease.get("schema"))
            != PUBLISH_RELAY_PHONE_SEAT_SCHEMA
            or normalize_string(phone_seat_lease.get("keyId"))
            != PUBLISH_RELAY_ENTITLEMENT_KEY_ID
            or _producer_account_id(phone_seat_lease.get("accountId")) != account_id
            or normalize_string(phone_seat_lease.get("installId"))
            != normalize_string(entitlement_lease.get("installId"))
            or normalize_string(phone_seat_lease.get("hostDeviceId"))
            != normalize_string(
                entitlement_lease.get("hostDeviceId")
                or entitlement_lease.get("deviceId")
            )
            or _positive_int(phone_seat_lease.get("entitlementVersion"))
            != entitlement_version
        ):
            raise _producer_authentication_error()
        phone_device_ids = phone_seat_lease.get("phoneDeviceIds")
        if (
            not isinstance(phone_device_ids, list)
            or any(
                not isinstance(device_id, str) or not device_id.strip()
                for device_id in phone_device_ids
            )
            or len(set(phone_device_ids)) != len(phone_device_ids)
        ):
            raise _producer_authentication_error()
        _positive_int(phone_seat_lease.get("limit"))
        _validate_signed_lease_window(
            phone_seat_lease,
            now_seconds=current_seconds,
            allow_offline_grace=False,
        )
        _verify_producer_signature(phone_seat_lease, settings=active_settings)
        selected_device_id = normalize_string(authorization.get("selectedDeviceId"))
        authorized_device_ids = authorization.get("authorizedDeviceIds")
        if (
            not selected_device_id
            or not isinstance(authorized_device_ids, list)
            or selected_device_id not in authorized_device_ids
            or selected_device_id not in phone_device_ids
        ):
            raise _producer_authentication_error()

    try:
        current_entitlement = current_entitlement_fn(account_id)
    except ActivationError as error:
        if error.status < 500:
            raise _producer_entitlement_error() from None
        LOGGER.warning(
            "Publish relay entitlement lookup failed closed with code %s",
            error.code,
        )
        raise _producer_auth_unavailable() from None
    except Exception:
        LOGGER.exception("Publish relay entitlement lookup failed")
        raise _producer_auth_unavailable() from None

    current_features = (
        {
            item.strip()
            for item in current_entitlement.get("features", [])
            if isinstance(item, str) and item.strip()
        }
        if isinstance(current_entitlement, dict)
        else set()
    )
    current_limits = (
        current_entitlement.get("limits")
        if isinstance(current_entitlement, dict)
        and isinstance(current_entitlement.get("limits"), dict)
        else {}
    )
    if (
        not isinstance(current_entitlement, dict)
        or normalize_string(current_entitlement.get("source")) != "authorization_code"
        or not normalize_string(current_entitlement.get("plan"))
        or not current_features.intersection(PUBLISH_RELAY_PRODUCER_FEATURES)
        or current_limits.get("unlimitedDevices") is not True
        or not isinstance(current_limits.get("devices"), int)
        or isinstance(current_limits.get("devices"), bool)
        or int(current_limits["devices"]) <= 0
        or not isinstance(current_limits.get("concurrentTasks"), int)
        or isinstance(current_limits.get("concurrentTasks"), bool)
        or int(current_limits["concurrentTasks"]) <= 0
        or normalize_string(current_entitlement.get("plan"))
        != normalize_string(entitlement_lease.get("plan"))
        or current_features != lease_features
        or int(current_limits["devices"]) != int(lease_limits["devices"])
        or int(current_limits["concurrentTasks"])
        != int(lease_limits["concurrentTasks"])
    ):
        raise _producer_entitlement_error()

    return {
        "accountId": account_id,
        "entitlementVersion": entitlement_version,
        "runtimeConfigDigest": runtime_digest,
        "selectedDeviceInstanceId": selected_device_instance_id,
    }


def publish_relay_validate_current_authorization(
    authorization: Any,
    *,
    current_entitlement_fn: CurrentEntitlementFn,
    settings: Settings | None = None,
    now_seconds: int | None = None,
) -> dict[str, Any]:
    return publish_relay_validate_producer_authorization(
        authorization,
        current_entitlement_fn=current_entitlement_fn,
        settings=settings,
        now_seconds=now_seconds,
        require_session_binding=False,
    )


def publish_relay_producer_scope_from_headers(headers: Any) -> dict[str, Any]:
    account_id = _producer_account_id(headers.get("X-LOOM-Account-ID", ""))
    entitlement_header = normalize_string(
        headers.get("X-LOOM-Entitlement-Version", "")
    )
    entitlement_version = _positive_int(
        int(entitlement_header) if entitlement_header.isdigit() else None
    )
    runtime_digest = normalize_string(
        headers.get("X-LOOM-Runtime-Config-Digest", "")
    ).lower()
    if len(runtime_digest) != 64 or any(
        character not in "0123456789abcdef" for character in runtime_digest
    ):
        raise _producer_authentication_error()
    return {
        "accountId": account_id,
        "entitlementVersion": entitlement_version,
        "runtimeConfigDigest": runtime_digest,
    }
