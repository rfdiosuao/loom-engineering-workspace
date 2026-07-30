"""Signed account entitlement verification and phone-seat enforcement."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from core.license_manager import LICENSE_PUBLIC_KEY_B64, LicenseManager
from core.paths import AppPaths
from core.secret_store import protect_secret, unprotect_secret
from core.storage import read_json, write_json


ENTITLEMENT_SCHEMA = "loom.entitlement_lease.v1"
PHONE_SEAT_LEASE_SCHEMA = "loom.phone_seat_lease.v1"
DEFAULT_ENTITLEMENT_KEY_ID = "openclaw-ed25519-v1"
ENTITLEMENT_PUBLIC_KEYS = {DEFAULT_ENTITLEMENT_KEY_ID: LICENSE_PUBLIC_KEY_B64}
MAX_CLOCK_SKEW_SEC = 300
MAX_LEASE_WINDOW_SEC = 8 * 24 * 3600
ENTITLEMENT_ANCHOR_SCHEMA = "loom.entitlement_anchor.v1"
_ACCOUNT_TASK_CONDITION = threading.Condition()
_ACCOUNT_TASK_ACTIVE: dict[str, int] = {}
_ACCOUNT_DEVICE_ACTIVE: set[tuple[str, str]] = set()
PERMANENT_ONLINE_ENTITLEMENT_ERROR_CODES = frozenset({
    "account_entitlement_not_found",
    "account_entitlement_revoked",
    "account_mismatch",
    "account_session_mismatch",
    "authorization_code_disabled",
    "authorization_code_expired",
    "authorization_code_revoked",
    "authorization_required",
    "entitlement_required",
    "lease_expired",
    "lease_revoked",
    "license_disabled",
    "license_expired",
    "license_invalid",
})


def _system_uptime_ms() -> int:
    if os.name == "nt":
        try:
            import ctypes

            get_tick_count = ctypes.windll.kernel32.GetTickCount64
            get_tick_count.restype = ctypes.c_ulonglong
            return int(get_tick_count())
        except Exception:
            pass
    try:
        with open("/proc/uptime", "r", encoding="ascii") as handle:
            return max(0, int(float(handle.read().split()[0]) * 1000))
    except (OSError, ValueError, IndexError):
        return max(0, int(time.monotonic() * 1000))


def _strict_json_int(
    value: Any,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    if type(value) is not int:
        raise TypeError("expected JSON integer")
    if minimum is not None and value < minimum:
        raise ValueError("integer below minimum")
    if maximum is not None and value > maximum:
        raise ValueError("integer above maximum")
    return value


class AccountEntitlementError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        code: str,
        action: str = "",
        details: dict[str, Any] | None = None,
        status_code: int = 403,
    ):
        super().__init__(message)
        self.code = code
        self.action = action
        self.details = details or {}
        self.status_code = status_code

    def payload(self) -> dict[str, Any]:
        return {
            "error": str(self),
            "message": str(self),
            "code": self.code,
            "action": self.action,
            "details": self.details,
        }


class AccountEntitlementManager:
    def __init__(
        self,
        paths: AppPaths,
        *,
        legacy_license_manager: LicenseManager | None = None,
        public_keys: dict[str, str] | None = None,
        now=None,
        uptime_ms=None,
        unprotect=None,
        anchor_reader=None,
        anchor_writer=None,
    ):
        self.paths = paths
        self.legacy = legacy_license_manager or LicenseManager(paths)
        self.public_keys = dict(public_keys or ENTITLEMENT_PUBLIC_KEYS)
        self._now = now or (lambda: int(time.time()))
        self._uptime_ms = uptime_ms or _system_uptime_ms
        self._unprotect = unprotect or unprotect_secret
        self._anchor_reader = anchor_reader or self._read_external_anchor
        self._anchor_writer = anchor_writer or self._write_external_anchor

    @staticmethod
    def _canonical(payload: dict[str, Any]) -> bytes:
        return json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    def _state(self) -> dict[str, Any]:
        state = read_json(self.paths.account_entitlement_state_file, {})
        return state if isinstance(state, dict) else {}

    def _anchor_path(self) -> str:
        install_hash = hashlib.sha256(self.legacy.get_install_id().encode("utf-8")).hexdigest()
        local_app_data = str(os.environ.get("LOCALAPPDATA") or "").strip()
        if not local_app_data:
            local_app_data = os.path.join(os.path.expanduser("~"), ".local", "share")
        return os.path.join(local_app_data, "LOOM", "entitlements", f"{install_hash}.json")

    def _read_external_anchor(self) -> dict[str, Any] | None:
        protected = read_json(self._anchor_path(), None)
        if protected in (None, {}, ""):
            return None
        try:
            plaintext = unprotect_secret(protected)
            payload = json.loads(plaintext)
        except Exception:
            raise AccountEntitlementError(
                "本机账号权益安全锚点无法读取，请联网刷新权益。",
                code="entitlement_anchor_invalid",
                action="refresh_entitlement",
            ) from None
        if not isinstance(payload, dict):
            raise AccountEntitlementError(
                "本机账号权益安全锚点格式无效，请联网刷新权益。",
                code="entitlement_anchor_invalid",
                action="refresh_entitlement",
            )
        return payload

    def _write_external_anchor(self, payload: dict[str, Any]) -> None:
        protected = protect_secret(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        write_json(self._anchor_path(), protected)

    def _lease_hash(self, lease: dict[str, Any]) -> str:
        payload = dict(lease)
        payload.pop("signature", None)
        return hashlib.sha256(self._canonical(payload)).hexdigest()

    def _verified_anchor(
        self,
        state: dict[str, Any],
        lease: dict[str, Any],
        *,
        required: bool,
    ) -> dict[str, Any] | None:
        anchor = self._anchor_reader()
        if not isinstance(anchor, dict):
            if not required:
                return None
            raise AccountEntitlementError(
                "本机账号权益安全锚点缺失，请联网刷新权益。",
                code="entitlement_anchor_missing",
                action="refresh_entitlement",
            )
        try:
            version = _strict_json_int(anchor["entitlementVersion"], minimum=1)
            last_seen_at = _strict_json_int(anchor["lastSeenAt"], minimum=1)
        except (KeyError, TypeError, ValueError):
            raise AccountEntitlementError(
                "本机账号权益安全锚点格式无效，请联网刷新权益。",
                code="entitlement_anchor_invalid",
                action="refresh_entitlement",
            ) from None
        expected = {
            "schema": ENTITLEMENT_ANCHOR_SCHEMA,
            "accountId": str(lease.get("accountId") or ""),
            "installId": str(lease.get("installId") or ""),
            "anchorId": str(state.get("anchorId") or ""),
            "leaseHash": str(state.get("leaseHash") or self._lease_hash(lease)),
        }
        actual = {key: str(anchor.get(key) or "") for key in expected}
        state_has_uptime = "uptimeMs" in state or "bootMarker" in state
        anchor_has_uptime = "uptimeMs" in anchor or "bootMarker" in anchor
        clock_anchor_mismatch = state_has_uptime != anchor_has_uptime
        if state_has_uptime and anchor_has_uptime:
            try:
                state_uptime = _strict_json_int(state["uptimeMs"], minimum=0)
                anchor_uptime = _strict_json_int(anchor["uptimeMs"], minimum=0)
                state_boot_marker = _strict_json_int(
                    state["bootMarker"],
                    minimum=1,
                )
                anchor_boot_marker = _strict_json_int(
                    anchor["bootMarker"],
                    minimum=1,
                )
                clock_anchor_mismatch = (
                    state_uptime != anchor_uptime
                    or state_boot_marker != anchor_boot_marker
                )
            except (KeyError, TypeError, ValueError):
                clock_anchor_mismatch = True
        if (
            actual != expected
            or version != int(state.get("entitlementVersion") or 0)
            or version != int(lease.get("entitlementVersion") or 0)
            or last_seen_at < int(state.get("lastSeenAt") or 0)
            or clock_anchor_mismatch
        ):
            raise AccountEntitlementError(
                "检测到账号权益状态被回滚或替换，请联网刷新权益。",
                code="entitlement_anchor_mismatch",
                action="refresh_entitlement",
            )
        return anchor

    def _record_seen(
        self,
        state: dict[str, Any],
        lease: dict[str, Any],
        anchor: dict[str, Any],
    ) -> None:
        effective_state = {
            **state,
            "lastSeenAt": max(
                int(state.get("lastSeenAt") or 0),
                int(anchor.get("lastSeenAt") or 0),
            ),
        }
        effective_now = self._effective_now(effective_state)
        uptime_ms = max(0, int(self._uptime_ms()))
        previous = max(
            int(state.get("lastSeenAt") or 0),
            int(anchor.get("lastSeenAt") or 0),
        )
        previous_uptime_ms = max(
            int(state.get("uptimeMs") or 0),
            int(anchor.get("uptimeMs") or 0),
        )
        if (
            effective_now <= previous + 60
            and uptime_ms <= previous_uptime_ms + 60_000
        ):
            return
        same_boot = previous_uptime_ms > 0 and uptime_ms >= previous_uptime_ms
        boot_marker = (
            int(anchor.get("bootMarker") or state.get("bootMarker") or 0)
            if same_boot
            else 0
        ) or max(1, effective_now - uptime_ms // 1000)
        clock_fields = {
            "lastSeenAt": effective_now,
            "uptimeMs": uptime_ms,
            "bootMarker": boot_marker,
        }
        next_state = {**state, **clock_fields}
        next_anchor = {**anchor, **clock_fields}
        self._anchor_writer(next_anchor)
        write_json(self.paths.account_entitlement_state_file, next_state)

    def _raw_session(self) -> dict[str, Any] | None:
        session = read_json(self.paths.member_session_file, None)
        if not isinstance(session, dict):
            return None
        if str(session.get("source") or "") not in {"newapi_account", "heang_account"}:
            return None
        return session

    @staticmethod
    def _session_account_ids(session: dict[str, Any] | None) -> set[str]:
        if not isinstance(session, dict):
            return set()
        newapi = session.get("newApi") if isinstance(session.get("newApi"), dict) else {}
        member_id = str(session.get("memberId") or "").strip()
        values = {
            str(newapi.get("userId") or "").strip(),
            member_id,
            member_id.removeprefix("newapi:"),
        }
        return {value for value in values if value}

    def _effective_now(self, state: dict[str, Any]) -> int:
        now = int(self._now())
        last_seen = int(state.get("lastSeenAt") or 0)
        current_uptime_ms = max(0, int(self._uptime_ms()))
        previous_uptime_ms = int(state.get("uptimeMs") or 0)
        if previous_uptime_ms > 0:
            if current_uptime_ms >= previous_uptime_ms:
                elapsed = (current_uptime_ms - previous_uptime_ms) // 1000
                return max(now, last_seen + elapsed)
            if last_seen and now <= last_seen:
                raise AccountEntitlementError(
                    "检测到电脑已重启但系统时间没有前进，请联网刷新账号权益。",
                    code="clock_integrity_online_required",
                    action="refresh_entitlement",
                    details={
                        "lastSeenAt": last_seen,
                        "currentTime": now,
                        "previousUptimeMs": previous_uptime_ms,
                        "currentUptimeMs": current_uptime_ms,
                    },
                )
            return max(now, last_seen)
        if last_seen and now + MAX_CLOCK_SKEW_SEC < last_seen:
            raise AccountEntitlementError(
                "检测到系统时间明显回拨，请联网同步时间后重试。",
                code="clock_rollback_detected",
                action="sync_system_clock",
                details={"lastSeenAt": last_seen, "currentTime": now},
            )
        return max(now, last_seen)

    def _verify_signature(self, lease: dict[str, Any]) -> None:
        key_id = str(lease.get("keyId") or "")
        public_key_b64 = self.public_keys.get(key_id)
        if not public_key_b64:
            raise AccountEntitlementError(
                "账号权益租约使用了未知签名密钥。",
                code="lease_key_unknown",
                action="update_loom",
                details={"keyId": key_id},
            )
        signature_text = str(lease.get("signature") or "")
        signed = dict(lease)
        signed.pop("signature", None)
        try:
            public_key = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64))
            public_key.verify(
                base64.b64decode(signature_text, validate=True),
                self._canonical(signed),
            )
        except (binascii.Error, ValueError, InvalidSignature, TypeError):
            raise AccountEntitlementError(
                "账号权益租约验签失败，文件可能被修改或复制。",
                code="lease_signature_invalid",
                action="relogin",
            ) from None

    def verify_lease(
        self,
        lease: Any,
        *,
        feature: str | None = None,
        session: dict[str, Any] | None = None,
        _require_anchor: bool = True,
    ) -> dict[str, Any]:
        if not isinstance(lease, dict):
            raise AccountEntitlementError(
                "缺少账号权益租约，请重新登录。",
                code="entitlement_required",
                action="relogin",
                status_code=401,
            )
        required = {
            "schema",
            "accountId",
            "sessionBinding",
            "installId",
            "deviceId",
            "features",
            "limits",
            "issuedAt",
            "expiresAt",
            "offlineGraceUntil",
            "entitlementVersion",
            "keyId",
            "signature",
        }
        missing = sorted(required.difference(lease))
        if missing:
            raise AccountEntitlementError(
                "账号权益租约字段不完整。",
                code="lease_malformed",
                action="relogin",
                details={"missing": missing},
                status_code=401,
            )
        if lease.get("schema") != ENTITLEMENT_SCHEMA:
            raise AccountEntitlementError(
                "账号权益租约版本不受支持。",
                code="lease_schema_unsupported",
                action="update_loom",
            )
        self._verify_signature(lease)

        if str(lease.get("installId") or "") != self.legacy.get_install_id():
            raise AccountEntitlementError(
                "账号权益租约不属于当前安装目录。",
                code="install_id_mismatch",
                action="relogin",
            )
        host_device_id = str(lease.get("hostDeviceId") or lease.get("deviceId") or "")
        if host_device_id not in self.legacy.device_id_candidates():
            raise AccountEntitlementError(
                "账号权益租约不属于当前电脑或运行磁盘。",
                code="host_device_mismatch",
                action="relogin",
            )

        active_session = session if isinstance(session, dict) else self._raw_session()
        account_ids = self._session_account_ids(active_session)
        if not account_ids or str(lease.get("accountId") or "") not in account_ids:
            raise AccountEntitlementError(
                "当前登录账号与权益租约不一致。",
                code="account_mismatch",
                action="relogin",
            )
        try:
            session_token = self._unprotect(
                (active_session or {}).get("memberToken")
            ).strip()
        except Exception:
            raise AccountEntitlementError(
                "当前模型账号会话安全凭据无法读取，请重新登录。",
                code="account_session_binding_unreadable",
                action="relogin",
                status_code=401,
            ) from None
        if not session_token:
            raise AccountEntitlementError(
                "当前模型账号会话缺少安全凭据，请重新登录。",
                code="account_session_binding_required",
                action="relogin",
                status_code=401,
            )
        expected_binding = hashlib.sha256(
            b"loom-entitlement-session-v1\0" + session_token.encode("utf-8")
        ).hexdigest()
        if not hmac.compare_digest(
            str(lease.get("sessionBinding") or ""),
            expected_binding,
        ):
            raise AccountEntitlementError(
                "当前模型账号会话与权益租约不一致，请重新登录。",
                code="account_session_mismatch",
                action="relogin",
                status_code=401,
            )

        try:
            issued_at = _strict_json_int(lease["issuedAt"], minimum=1)
            expires_at = _strict_json_int(lease["expiresAt"], minimum=1)
            grace_until = _strict_json_int(lease["offlineGraceUntil"], minimum=1)
            version = _strict_json_int(lease["entitlementVersion"], minimum=1)
        except (TypeError, ValueError):
            raise AccountEntitlementError(
                "账号权益租约时间或版本字段无效。",
                code="lease_malformed",
                action="relogin",
            ) from None
        if not (0 < issued_at < expires_at <= grace_until):
            raise AccountEntitlementError(
                "账号权益租约时间窗口无效。",
                code="lease_time_window_invalid",
                action="relogin",
            )
        if grace_until - issued_at > MAX_LEASE_WINDOW_SEC:
            raise AccountEntitlementError(
                "账号权益租约时间窗口异常。",
                code="lease_time_window_invalid",
                action="relogin",
            )

        state = self._state()
        persisted = os.path.isfile(self.paths.account_entitlement_file) or bool(
            state.get("accountLeaseSeen")
        )
        anchor = (
            self._verified_anchor(state, lease, required=persisted)
            if _require_anchor
            else None
        )
        effective_state = dict(state)
        if anchor:
            effective_state["lastSeenAt"] = max(
                int(state.get("lastSeenAt") or 0),
                int(anchor.get("lastSeenAt") or 0),
            )
        effective_now = self._effective_now(effective_state)
        if issued_at > effective_now + MAX_CLOCK_SKEW_SEC:
            raise AccountEntitlementError(
                "账号权益租约签发时间晚于本机时间。",
                code="lease_not_yet_valid",
                action="sync_system_clock",
            )
        if effective_now > grace_until:
            raise AccountEntitlementError(
                "账号权益离线宽限已结束，请联网刷新账号。",
                code="lease_expired",
                action="refresh_entitlement",
                details={"offlineGraceUntil": grace_until},
            )
        previous_version = int(state.get("entitlementVersion") or 0)
        previous_account = str(state.get("accountId") or "")
        if previous_account == str(lease["accountId"]) and version < previous_version:
            raise AccountEntitlementError(
                "检测到旧版本权益租约，可能已被撤销。",
                code="lease_version_rollback",
                action="refresh_entitlement",
            )
        features = lease.get("features")
        limits = lease.get("limits")
        if not isinstance(features, list) or not isinstance(limits, dict):
            raise AccountEntitlementError(
                "账号权益能力或额度字段无效。",
                code="lease_malformed",
                action="relogin",
            )
        try:
            device_limit = _strict_json_int(
                limits["devices"],
                minimum=1,
                maximum=1000,
            )
            concurrent_limit = _strict_json_int(
                limits["concurrentTasks"],
                minimum=1,
                maximum=100,
            )
        except (KeyError, TypeError, ValueError):
            raise AccountEntitlementError(
                "账号权益能力或额度字段无效。",
                code="lease_malformed",
                action="relogin",
            ) from None
        if concurrent_limit > device_limit:
            raise AccountEntitlementError(
                "账号权益并发额度不能超过设备额度。",
                code="lease_malformed",
                action="relogin",
            )
        if feature and feature not in features:
            raise AccountEntitlementError(
                f"当前账号未开通 {feature} 能力。",
                code="entitlement_feature_required",
                action="upgrade_plan",
                details={"feature": feature},
            )
        return {
            "authorized": True,
            "lease": lease,
            "features": list(features),
            "limits": dict(limits),
            "offline": effective_now > expires_at,
            "expiresAt": expires_at,
            "offlineGraceUntil": grace_until,
            "entitlementVersion": version,
            "plan": str(lease.get("plan") or "activated"),
            "anchor": anchor,
        }

    def verify_phone_seat_lease(
        self,
        seat_lease: Any,
        *,
        entitlement_lease: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(seat_lease, dict):
            raise AccountEntitlementError(
                "缺少服务端签名的手机席位凭证。",
                code="phone_seat_lease_required",
                action="refresh_entitlement",
                status_code=503,
            )
        required = {
            "schema",
            "accountId",
            "installId",
            "hostDeviceId",
            "phoneDeviceIds",
            "limit",
            "issuedAt",
            "expiresAt",
            "entitlementVersion",
            "keyId",
            "signature",
        }
        missing = sorted(required.difference(seat_lease))
        if missing:
            raise AccountEntitlementError(
                "手机席位凭证字段不完整。",
                code="phone_seat_lease_malformed",
                action="refresh_entitlement",
                details={"missing": missing},
            )
        if seat_lease.get("schema") != PHONE_SEAT_LEASE_SCHEMA:
            raise AccountEntitlementError(
                "手机席位凭证版本不受支持。",
                code="phone_seat_lease_schema_unsupported",
                action="update_loom",
            )
        self._verify_signature(seat_lease)

        account_id = str(entitlement_lease.get("accountId") or "")
        install_id = str(entitlement_lease.get("installId") or "")
        host_device_id = str(
            entitlement_lease.get("hostDeviceId")
            or entitlement_lease.get("deviceId")
            or ""
        )
        if str(seat_lease.get("accountId") or "") != account_id:
            raise AccountEntitlementError(
                "手机席位凭证不属于当前账号。",
                code="phone_seat_account_mismatch",
                action="refresh_entitlement",
            )
        if str(seat_lease.get("installId") or "") != install_id:
            raise AccountEntitlementError(
                "手机席位凭证不属于当前安装目录。",
                code="phone_seat_install_mismatch",
                action="refresh_entitlement",
            )
        if (
            str(seat_lease.get("hostDeviceId") or "") != host_device_id
            or host_device_id not in self.legacy.device_id_candidates()
        ):
            raise AccountEntitlementError(
                "手机席位凭证不属于当前电脑。",
                code="phone_seat_host_mismatch",
                action="refresh_entitlement",
            )
        try:
            issued_at = _strict_json_int(seat_lease["issuedAt"], minimum=1)
            expires_at = _strict_json_int(seat_lease["expiresAt"], minimum=1)
            version = _strict_json_int(
                seat_lease["entitlementVersion"],
                minimum=1,
            )
            limit = _strict_json_int(
                seat_lease["limit"],
                minimum=1,
                maximum=1000,
            )
            entitlement_version = _strict_json_int(
                entitlement_lease["entitlementVersion"],
                minimum=1,
            )
            entitlement_limit = _strict_json_int(
                (entitlement_lease.get("limits") or {})["devices"],
                minimum=1,
                maximum=1000,
            )
        except (TypeError, ValueError, KeyError):
            raise AccountEntitlementError(
                "手机席位凭证时间、版本或额度无效。",
                code="phone_seat_lease_malformed",
                action="refresh_entitlement",
            ) from None
        unlimited_devices = (
            (entitlement_lease.get("limits") or {}).get("unlimitedDevices") is True
        )
        if (
            version != entitlement_version
            or limit < 1
            or (not unlimited_devices and limit > entitlement_limit)
        ):
            raise AccountEntitlementError(
                "手机席位凭证与当前账号权益不一致。",
                code="phone_seat_entitlement_mismatch",
                action="refresh_entitlement",
            )
        if not (0 < issued_at < expires_at) or expires_at - issued_at > MAX_LEASE_WINDOW_SEC:
            raise AccountEntitlementError(
                "手机席位凭证时间窗口无效。",
                code="phone_seat_time_window_invalid",
                action="refresh_entitlement",
            )
        effective_now = self._effective_now(self._state())
        if issued_at > effective_now + MAX_CLOCK_SKEW_SEC:
            raise AccountEntitlementError(
                "手机席位凭证签发时间晚于本机时间。",
                code="phone_seat_not_yet_valid",
                action="sync_system_clock",
            )
        if effective_now > expires_at:
            raise AccountEntitlementError(
                "手机席位离线凭证已过期，请联网刷新。",
                code="phone_seat_lease_expired",
                action="refresh_entitlement",
            )
        phone_ids = seat_lease.get("phoneDeviceIds")
        if not isinstance(phone_ids, list):
            raise AccountEntitlementError(
                "手机席位凭证设备列表无效。",
                code="phone_seat_lease_malformed",
                action="refresh_entitlement",
            )
        normalized = sorted({str(value).strip() for value in phone_ids if str(value).strip()})
        if (
            len(normalized) != len(phone_ids)
            or (not unlimited_devices and len(normalized) > limit)
        ):
            raise AccountEntitlementError(
                "手机席位凭证设备列表或额度无效。",
                code="phone_seat_lease_malformed",
                action="refresh_entitlement",
            )
        return {
            "authorized": True,
            "lease": seat_lease,
            "phoneDeviceIds": normalized,
            "limit": limit,
            "expiresAt": expires_at,
        }

    def _verified_phone_seat_lease(
        self,
        entitlement_lease: dict[str, Any],
    ) -> dict[str, Any] | None:
        seat_lease = read_json(self.paths.account_phone_seat_lease_file, None)
        if not isinstance(seat_lease, dict):
            return None
        try:
            return self.verify_phone_seat_lease(
                seat_lease,
                entitlement_lease=entitlement_lease,
            )
        except AccountEntitlementError:
            return None

    def accept_lease(
        self,
        lease: Any,
        *,
        session: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        verified = self.verify_lease(
            lease,
            session=session,
            _require_anchor=False,
        )
        state = self._state()
        account_id = str(verified["lease"]["accountId"])
        existing_anchor = self._anchor_reader()
        if isinstance(existing_anchor, dict) and str(existing_anchor.get("accountId") or "") == account_id:
            try:
                anchor_version = _strict_json_int(
                    existing_anchor["entitlementVersion"],
                    minimum=1,
                )
                anchor_last_seen = _strict_json_int(existing_anchor["lastSeenAt"], minimum=1)
            except (KeyError, TypeError, ValueError):
                raise AccountEntitlementError(
                    "本机账号权益安全锚点格式无效，请联网修复后重试。",
                    code="entitlement_anchor_invalid",
                    action="contact_support",
                ) from None
            if int(verified["entitlementVersion"]) < anchor_version:
                raise AccountEntitlementError(
                    "检测到旧版本账号权益租约，可能已被撤销。",
                    code="lease_version_rollback",
                    action="refresh_entitlement",
                )
            if int(self._now()) + MAX_CLOCK_SKEW_SEC < anchor_last_seen:
                raise AccountEntitlementError(
                    "检测到系统时间明显回拨，请联网同步时间后重试。",
                    code="clock_rollback_detected",
                    action="sync_system_clock",
                )
        account_changed = str(state.get("accountId") or "") != account_id
        version_changed = int(state.get("entitlementVersion") or 0) != int(
            verified["entitlementVersion"]
        )
        if account_changed or version_changed:
            claimed: list[str] = []
            try:
                os.remove(self.paths.account_phone_seat_lease_file)
            except FileNotFoundError:
                pass
        else:
            claimed = [
                str(value)
                for value in state.get("claimedPhoneDeviceIds") or []
                if str(value).strip()
            ]
        anchor_id = (
            str(existing_anchor.get("anchorId") or "")
            if isinstance(existing_anchor, dict)
            and str(existing_anchor.get("accountId") or "") == account_id
            else ""
        ) or secrets.token_hex(16)
        last_seen_at = max(
            int(self._now()),
            int(verified["lease"]["issuedAt"]),
            int(state.get("lastSeenAt") or 0),
            int((existing_anchor or {}).get("lastSeenAt") or 0),
        )
        uptime_ms = max(0, int(self._uptime_ms()))
        previous_uptime_ms = max(
            int(state.get("uptimeMs") or 0),
            int((existing_anchor or {}).get("uptimeMs") or 0),
        )
        same_boot = previous_uptime_ms > 0 and uptime_ms >= previous_uptime_ms
        boot_marker = (
            int(
                (existing_anchor or {}).get("bootMarker")
                or state.get("bootMarker")
                or 0
            )
            if same_boot
            else 0
        ) or max(1, last_seen_at - uptime_ms // 1000)
        lease_hash = self._lease_hash(verified["lease"])
        next_state = {
            "accountLeaseSeen": True,
            "accountId": account_id,
            "entitlementVersion": verified["entitlementVersion"],
            "keyId": verified["lease"]["keyId"],
            "lastSeenAt": last_seen_at,
            "uptimeMs": uptime_ms,
            "bootMarker": boot_marker,
            "anchorId": anchor_id,
            "leaseHash": lease_hash,
            "claimedPhoneDeviceIds": sorted(set(claimed)),
        }
        next_anchor = {
            "schema": ENTITLEMENT_ANCHOR_SCHEMA,
            "accountId": account_id,
            "installId": str(verified["lease"]["installId"]),
            "entitlementVersion": verified["entitlementVersion"],
            "lastSeenAt": last_seen_at,
            "uptimeMs": uptime_ms,
            "bootMarker": boot_marker,
            "anchorId": anchor_id,
            "leaseHash": lease_hash,
        }
        self._anchor_writer(next_anchor)
        write_json(self.paths.account_entitlement_file, verified["lease"])
        write_json(self.paths.account_entitlement_state_file, next_state)
        return verified

    def clear_active(self) -> None:
        for path in (
            self.paths.account_entitlement_file,
            self.paths.account_phone_seat_lease_file,
        ):
            try:
                os.remove(path)
            except FileNotFoundError:
                pass

    def current_state(self, feature: str | None = None) -> dict[str, Any]:
        state = self._state()
        session = self._raw_session()
        lease = read_json(self.paths.account_entitlement_file, None)
        if isinstance(lease, dict) and lease:
            if not os.path.isfile(self.paths.account_entitlement_state_file):
                return {
                    "authorized": False,
                    "source": "account_entitlement",
                    "accountLeaseSeen": True,
                    "code": "lease_state_missing",
                    "message": "账号权益状态文件缺失，无法安全使用离线租约。",
                    "action": "refresh_entitlement",
                    "details": {},
                }
            try:
                verified = self.verify_lease(lease, feature=feature, session=session)
            except AccountEntitlementError as error:
                return {
                    "authorized": False,
                    **error.payload(),
                    "source": "account_entitlement",
                    "accountLeaseSeen": bool(state.get("accountLeaseSeen")),
                }
            anchor = verified.pop("anchor", None)
            if isinstance(anchor, dict):
                self._record_seen(state, lease, anchor)
                state = self._state()
            return {
                **verified,
                "source": "account_entitlement",
                "accountLeaseSeen": True,
                "claimedPhoneDeviceIds": list(state.get("claimedPhoneDeviceIds") or []),
            }
        if session is not None or state.get("accountLeaseSeen"):
            entitlement = (
                session.get("accountEntitlement")
                if isinstance(session, dict)
                and isinstance(session.get("accountEntitlement"), dict)
                else {}
            )
            if (
                not state.get("accountLeaseSeen")
                and str(entitlement.get("source") or "") == "authorization_required"
            ):
                return {
                    "authorized": False,
                    "source": "account_entitlement",
                    "accountLeaseSeen": False,
                    "code": "authorization_required",
                    "message": "当前账号尚未激活手机矩阵，请输入授权码绑定当前账号。",
                    "action": "bind_authorization_code",
                    "details": {},
                }
            return {
                "authorized": False,
                "source": "account_entitlement",
                "accountLeaseSeen": bool(state.get("accountLeaseSeen")),
                "code": "entitlement_required",
                "message": "请刷新当前模型账号的矩阵权益。",
                "action": "relogin",
                "details": {},
            }
        authorized = self.legacy.is_authorized(feature)
        if authorized and str(feature or "").startswith("matrix."):
            return {
                "authorized": False,
                "source": "legacy_license_migration_required",
                "accountLeaseSeen": False,
                "code": "account_entitlement_required",
                "message": "手机矩阵商业权限已改为绑定模型账号，请登录后绑定原授权码。",
                "action": "login_and_bind_authorization_code",
                "details": {"legacyLicenseDetected": True},
            }
        return {
            "authorized": authorized,
            "source": "legacy_license" if authorized else "none",
            "accountLeaseSeen": False,
            "code": "ok" if authorized else "entitlement_required",
            "message": "" if authorized else "请登录模型账号并输入授权码完成绑定。",
            "action": "" if authorized else "login_and_bind_authorization_code",
            "details": {},
        }

    def is_authorized(self, feature: str | None = None) -> bool:
        return bool(self.current_state(feature).get("authorized"))

    def claimed_phone_device_ids(self) -> list[str]:
        current = self.current_state("matrix.devices")
        if not current.get("authorized") or not isinstance(current.get("lease"), dict):
            raise AccountEntitlementError(
                str(current.get("message") or "当前账号尚未激活手机矩阵。"),
                code=str(current.get("code") or "authorization_required"),
                action=str(current.get("action") or "bind_authorization_code"),
                details=(
                    current.get("details")
                    if isinstance(current.get("details"), dict)
                    else {}
                ),
            )
        verified = self._verified_phone_seat_lease(current["lease"])
        return list(verified.get("phoneDeviceIds") or []) if isinstance(verified, dict) else []

    def phone_runtime_authorization(
        self,
        phone_device_ids: list[str],
        *,
        session: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        active_session = session if isinstance(session, dict) else self._raw_session()
        entitlement_lease = read_json(
            self.paths.account_entitlement_file,
            None,
        )
        verified = self.verify_lease(
            entitlement_lease,
            feature="matrix.devices",
            session=active_session,
        )
        entitlement_lease = verified["lease"]
        verified_seats = self.verify_phone_seat_lease(
            read_json(self.paths.account_phone_seat_lease_file, None),
            entitlement_lease=entitlement_lease,
        )
        authorized_ids = list(verified_seats["phoneDeviceIds"])
        requested_ids = sorted(
            {
                str(value).strip()
                for value in phone_device_ids
                if str(value).strip()
            }
        )
        unauthorized = sorted(set(requested_ids).difference(authorized_ids))
        if unauthorized:
            raise AccountEntitlementError(
                "所选手机不在当前账号签名席位凭证中。",
                code="phone_device_not_authorized",
                action="refresh_entitlement",
                details={"phoneDeviceIds": unauthorized},
                status_code=403,
            )
        return {
            "accountId": str(entitlement_lease["accountId"]),
            "entitlementLease": entitlement_lease,
            "phoneSeatLease": verified_seats["lease"],
            "authorizedPhoneDeviceIds": authorized_ids,
            "requestedPhoneDeviceIds": requested_ids,
        }

    def pending_phone_device_releases(self) -> list[str]:
        state = self._state()
        pending = state.get("pendingPhoneDeviceReleases")
        if not isinstance(pending, list):
            return []
        return sorted(
            {
                str(value).strip()
                for value in pending
                if str(value).strip()
            }
        )

    def queue_phone_device_release(
        self,
        phone_device_ids: list[str],
        *,
        reason: str = "",
    ) -> list[str]:
        normalized = sorted(
            {
                str(value).strip()
                for value in phone_device_ids
                if str(value).strip()
            }
        )
        if not normalized:
            return self.pending_phone_device_releases()
        state = self._state()
        pending = sorted(
            set(self.pending_phone_device_releases()).union(normalized)
        )
        metadata = (
            dict(state.get("pendingPhoneDeviceReleaseMeta"))
            if isinstance(state.get("pendingPhoneDeviceReleaseMeta"), dict)
            else {}
        )
        queued_at = int(self._now())
        for device_id in normalized:
            metadata[device_id] = {
                "queuedAt": queued_at,
                "reason": str(reason or "")[:120],
            }
        write_json(
            self.paths.account_entitlement_state_file,
            {
                **state,
                "pendingPhoneDeviceReleases": pending,
                "pendingPhoneDeviceReleaseMeta": metadata,
            },
        )
        return pending

    def _retry_pending_phone_device_releases(
        self,
        *,
        current: dict[str, Any],
        state: dict[str, Any],
        session: dict[str, Any],
    ) -> dict[str, Any]:
        pending = self.pending_phone_device_releases()
        if not pending:
            return state
        try:
            payload = self._server_check(
                lease=current["lease"],
                phone_device_ids=pending,
                operation="matrix.device.release",
                session=session,
            )
        except AccountEntitlementError as error:
            if error.code == "entitlement_service_unreachable":
                return state
            raise
        seat_lease = payload.get("phoneSeatLease") if isinstance(payload, dict) else None
        try:
            self.verify_phone_seat_lease(
                seat_lease,
                entitlement_lease=current["lease"],
            )
        except AccountEntitlementError as error:
            raise AccountEntitlementError(
                f"权益服务未返回可信的手机席位凭证：{error}",
                code="phone_seat_lease_invalid",
                action="retry",
                status_code=503,
            ) from error
        write_json(self.paths.account_phone_seat_lease_file, seat_lease)
        metadata = (
            dict(state.get("pendingPhoneDeviceReleaseMeta"))
            if isinstance(state.get("pendingPhoneDeviceReleaseMeta"), dict)
            else {}
        )
        for device_id in pending:
            metadata.pop(device_id, None)
        next_state = {
            **state,
            "pendingPhoneDeviceReleases": [],
            "pendingPhoneDeviceReleaseMeta": metadata,
        }
        write_json(self.paths.account_entitlement_state_file, next_state)
        return next_state

    @contextmanager
    def account_task_slot(
        self,
        entitlement: dict[str, Any],
        operation: str,
        *,
        cancelled=None,
        device_ids: list[str] | tuple[str, ...] | set[str] | None = None,
    ):
        lease = entitlement.get("lease") if isinstance(entitlement.get("lease"), dict) else {}
        account_id = str(entitlement.get("accountId") or lease.get("accountId") or "").strip()
        limits = entitlement.get("limits") if isinstance(entitlement.get("limits"), dict) else {}
        try:
            limit = _strict_json_int(limits.get("concurrentTasks"), minimum=1, maximum=100)
        except (TypeError, ValueError):
            raise AccountEntitlementError(
                "账号并发权益字段无效，请刷新权益。",
                code="entitlement_concurrency_invalid",
                action="refresh_entitlement",
            ) from None
        if not account_id:
            raise AccountEntitlementError(
                "账号权益缺少账号标识，请重新登录。",
                code="entitlement_account_missing",
                action="relogin",
            )
        normalized_device_ids = tuple(sorted({
            str(device_id or "").strip()
            for device_id in (device_ids or [])
            if str(device_id or "").strip()
        }))
        device_keys = tuple(
            (account_id, device_id)
            for device_id in normalized_device_ids
        )
        acquired = False
        with _ACCOUNT_TASK_CONDITION:
            while (
                _ACCOUNT_TASK_ACTIVE.get(account_id, 0) >= limit
                or any(key in _ACCOUNT_DEVICE_ACTIVE for key in device_keys)
            ):
                if callable(cancelled) and cancelled():
                    raise AccountEntitlementError(
                        "任务在等待账号并发席位时已取消。",
                        code="task_cancelled",
                        action="retry",
                        details={
                            "operation": operation,
                            "deviceIds": list(normalized_device_ids),
                        },
                        status_code=409,
                    )
                _ACCOUNT_TASK_CONDITION.wait(timeout=0.1)
            _ACCOUNT_TASK_ACTIVE[account_id] = _ACCOUNT_TASK_ACTIVE.get(account_id, 0) + 1
            _ACCOUNT_DEVICE_ACTIVE.update(device_keys)
            acquired = True
        try:
            yield
        finally:
            if acquired:
                with _ACCOUNT_TASK_CONDITION:
                    remaining = max(0, _ACCOUNT_TASK_ACTIVE.get(account_id, 1) - 1)
                    if remaining:
                        _ACCOUNT_TASK_ACTIVE[account_id] = remaining
                    else:
                        _ACCOUNT_TASK_ACTIVE.pop(account_id, None)
                    for key in device_keys:
                        _ACCOUNT_DEVICE_ACTIVE.discard(key)
                    _ACCOUNT_TASK_CONDITION.notify_all()

    def _server_check(
        self,
        *,
        lease: dict[str, Any],
        phone_device_ids: list[str],
        operation: str,
        session: dict[str, Any],
    ) -> dict[str, Any]:
        newapi = session.get("newApi") if isinstance(session.get("newApi"), dict) else {}
        base_url = str(newapi.get("baseUrl") or "").strip().rstrip("/")
        token = str(session.get("memberToken") or "").strip()
        if not base_url or not token:
            raise AccountEntitlementError(
                "本机账号会话不完整，无法在线领取手机席位。",
                code="entitlement_online_claim_required",
                action="relogin",
            )
        parsed = urllib.parse.urlparse(base_url)
        if parsed.scheme != "https":
            raise AccountEntitlementError(
                "权益服务必须使用 HTTPS。",
                code="entitlement_endpoint_insecure",
                action="relogin",
            )
        request = urllib.request.Request(
            f"{base_url}/api/openclaw/entitlements/check",
            data=json.dumps(
                {
                    "entitlementLease": lease,
                    "operation": operation,
                    "phoneDeviceIds": phone_device_ids,
                },
                ensure_ascii=False,
            ).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "LOOM-Desktop/entitlements-v1",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=8) as response:
                payload = json.loads(response.read().decode("utf-8", errors="replace") or "{}")
        except urllib.error.HTTPError as error:
            try:
                payload = json.loads(error.read().decode("utf-8", errors="replace") or "{}")
            except Exception:
                payload = {}
            raise AccountEntitlementError(
                str(payload.get("message") or payload.get("error") or f"http_{error.code}"),
                code=str(payload.get("code") or "entitlement_check_failed"),
                action=str(payload.get("action") or "retry"),
                details=payload.get("details") if isinstance(payload.get("details"), dict) else {},
                status_code=int(error.code),
            ) from None
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as error:
            raise AccountEntitlementError(
                f"权益服务暂时不可达：{error}",
                code="entitlement_service_unreachable",
                action="retry",
                status_code=503,
            ) from None
        if not isinstance(payload, dict) or payload.get("success") is False:
            raise AccountEntitlementError(
                str(payload.get("message") or payload.get("error") or "权益校验失败"),
                code=str(payload.get("code") or "entitlement_check_failed"),
                action=str(payload.get("action") or "retry"),
                details=payload.get("details") if isinstance(payload.get("details"), dict) else {},
            )
        return payload

    def authorize_phone_devices(
        self,
        phone_device_ids: list[str],
        operation: str,
        *,
        session: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        current = self.current_state("matrix.devices")
        if not current.get("authorized"):
            raise AccountEntitlementError(
                str(current.get("message") or "当前账号未获得矩阵权益。"),
                code=str(current.get("code") or "entitlement_required"),
                action=str(current.get("action") or "relogin"),
                details=current.get("details") if isinstance(current.get("details"), dict) else {},
            )
        if current.get("source") == "legacy_license":
            raise AccountEntitlementError(
                "手机矩阵商业权限必须绑定模型账号。",
                code="account_entitlement_required",
                action="login_and_bind_authorization_code",
            )

        normalized = sorted({str(value).strip() for value in phone_device_ids if str(value).strip()})
        if not normalized:
            raise AccountEntitlementError(
                "请选择至少一台手机。",
                code="phone_device_required",
                action="select_phone_device",
                status_code=400,
            )
        state = self._state()
        active_session = session if isinstance(session, dict) else None
        if active_session:
            state = self._retry_pending_phone_device_releases(
                current=current,
                state=state,
                session=active_session,
            )
        verified_seats = self._verified_phone_seat_lease(current["lease"])
        claimed = set(
            verified_seats.get("phoneDeviceIds") if isinstance(verified_seats, dict) else []
        )
        limits = current.get("limits") if isinstance(current.get("limits"), dict) else {}
        limit = max(1, int(limits.get("devices") or 1))
        unlimited_devices = limits.get("unlimitedDevices") is True
        if (
            operation != "matrix.device.release"
            and not unlimited_devices
            and len(claimed.union(normalized)) > limit
        ):
            raise AccountEntitlementError(
                "当前账号绑定的手机数量超过系统安全上限，请联系技术支持。",
                code="device_limit_exceeded",
                action="contact_support",
                details={"limit": limit, "used": len(claimed), "phoneDeviceIds": normalized},
            )

        needs_online = operation == "matrix.device.release" or bool(set(normalized).difference(claimed))
        if not active_session and needs_online:
            raise AccountEntitlementError(
                "新增或更换手机需要联网校验账号权益。",
                code="entitlement_online_claim_required",
                action="refresh_entitlement",
                status_code=503,
            )

        payload: dict[str, Any] | None = None
        if active_session:
            try:
                payload = self._server_check(
                    lease=current["lease"],
                    phone_device_ids=normalized,
                    operation=operation,
                    session=active_session,
                )
            except AccountEntitlementError as error:
                if error.code in PERMANENT_ONLINE_ENTITLEMENT_ERROR_CODES:
                    self.clear_active()
                if error.code != "entitlement_service_unreachable" or needs_online:
                    raise
        if payload is None:
            return {
                "authorized": True,
                "source": "account_entitlement",
                "offline": True,
                "accountId": str(current["lease"]["accountId"]),
                "lease": current["lease"],
                "claimedPhoneDeviceIds": normalized,
                "limits": current["limits"],
            }

        seat_lease = payload.get("phoneSeatLease") if isinstance(payload, dict) else None
        try:
            verified_seats = self.verify_phone_seat_lease(
                seat_lease,
                entitlement_lease=current["lease"],
            )
        except AccountEntitlementError as error:
            raise AccountEntitlementError(
                f"权益服务未返回可信的手机席位凭证：{error}",
                code="phone_seat_lease_invalid",
                action="retry",
                status_code=503,
            ) from error
        write_json(self.paths.account_phone_seat_lease_file, seat_lease)
        claimed = set(verified_seats["phoneDeviceIds"])
        anchor = self._verified_anchor(state, current["lease"], required=True)
        effective_state = {
            **state,
            "lastSeenAt": max(
                int(state.get("lastSeenAt") or 0),
                int((anchor or {}).get("lastSeenAt") or 0),
            ),
        }
        last_seen_at = self._effective_now(effective_state)
        uptime_ms = max(0, int(self._uptime_ms()))
        previous_uptime_ms = max(
            int(state.get("uptimeMs") or 0),
            int((anchor or {}).get("uptimeMs") or 0),
        )
        same_boot = previous_uptime_ms > 0 and uptime_ms >= previous_uptime_ms
        boot_marker = (
            int(
                (anchor or {}).get("bootMarker")
                or state.get("bootMarker")
                or 0
            )
            if same_boot
            else 0
        ) or max(1, last_seen_at - uptime_ms // 1000)
        next_state = {
            **state,
            "accountLeaseSeen": True,
            "accountId": current["lease"]["accountId"],
            "entitlementVersion": current["entitlementVersion"],
            "keyId": current["lease"]["keyId"],
            "lastSeenAt": last_seen_at,
            "uptimeMs": uptime_ms,
            "bootMarker": boot_marker,
            "claimedPhoneDeviceIds": sorted(claimed),
        }
        self._anchor_writer(
            {
                **(anchor or {}),
                "lastSeenAt": last_seen_at,
                "uptimeMs": uptime_ms,
                "bootMarker": boot_marker,
            }
        )
        write_json(self.paths.account_entitlement_state_file, next_state)
        return {
            "authorized": True,
            "source": "account_entitlement",
            "offline": False,
            "accountId": str(current["lease"]["accountId"]),
            "lease": current["lease"],
            "claimedPhoneDeviceIds": sorted(claimed),
            "limits": current["limits"],
            "server": payload,
        }
