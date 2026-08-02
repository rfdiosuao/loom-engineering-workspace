from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from ..timeutils import utc_now
from .payments import ALLOWED_PAYMENT_TYPES, PaymentError, sign_md5


Requester = Callable[[str, bytes, dict[str, str], int], bytes]


def _enabled(value: Any) -> bool:
    return str(value if value is not None else "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
        "enabled",
    }


def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))


@dataclass(frozen=True)
class ZPayConfig:
    enabled: bool
    base_url: str
    merchant_id: str
    merchant_key: str
    create_path: str
    notify_url: str
    return_url: str
    order_ttl_seconds: int = 600

    @classmethod
    def from_env(cls) -> "ZPayConfig":
        return cls(
            enabled=_enabled(os.environ.get("LICENSE_ZPAY_ENABLED", "")),
            base_url=str(os.environ.get("LICENSE_ZPAY_BASE_URL", "") or "").strip().rstrip("/"),
            merchant_id=str(os.environ.get("LICENSE_ZPAY_PID", "") or "").strip(),
            merchant_key=str(os.environ.get("LICENSE_ZPAY_KEY", "") or "").strip(),
            create_path=str(os.environ.get("LICENSE_ZPAY_CREATE_PATH", "/mapi.php") or "").strip(),
            notify_url=str(os.environ.get("LICENSE_ZPAY_NOTIFY_URL", "") or "").strip(),
            return_url=str(os.environ.get("LICENSE_ZPAY_RETURN_URL", "") or "").strip(),
            order_ttl_seconds=_bounded_int(
                os.environ.get("LICENSE_ZPAY_ORDER_TTL_SECONDS", "600"),
                600,
                60,
                3600,
            ),
        )

    def create_url(self) -> str:
        if not self.enabled or not all(
            (
                self.base_url,
                self.merchant_id,
                self.merchant_key,
                self.create_path,
                self.notify_url,
                self.return_url,
            )
        ):
            raise PaymentError(
                "支付服务尚未配置。", 503, "PAYMENT_PROVIDER_NOT_CONFIGURED"
            )
        base = urllib.parse.urlsplit(self.base_url)
        if base.scheme != "https" or not base.hostname or base.username or base.password:
            raise PaymentError(
                "支付服务必须使用 HTTPS。", 503, "PAYMENT_PROVIDER_INSECURE"
            )
        path = urllib.parse.urlsplit(self.create_path)
        if (
            not self.create_path.startswith("/")
            or path.scheme
            or path.netloc
            or path.query
            or path.fragment
            or ".." in path.path.split("/")
        ):
            raise PaymentError(
                "支付下单路径配置无效。", 503, "PAYMENT_PROVIDER_PATH_INVALID"
            )
        for callback in (self.notify_url, self.return_url):
            parsed = urllib.parse.urlsplit(callback)
            if parsed.scheme != "https" or not parsed.hostname:
                raise PaymentError(
                    "支付回调必须使用 HTTPS。", 503, "PAYMENT_CALLBACK_INSECURE"
                )
        return urllib.parse.urlunsplit(
            (base.scheme, base.netloc, path.path, "", "")
        )


def _default_requester(
    url: str, data: bytes, headers: dict[str, str], timeout: int
) -> bytes:
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read(131073)
    except urllib.error.HTTPError as error:
        raise PaymentError(
            "支付服务暂时不可用。",
            502,
            "PAYMENT_PROVIDER_HTTP_ERROR",
            retryable=500 <= int(error.code) < 600,
        ) from error
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise PaymentError(
            "暂时无法连接支付服务。",
            503,
            "PAYMENT_PROVIDER_UNAVAILABLE",
            retryable=True,
        ) from error
    if len(payload) > 131072:
        raise PaymentError(
            "支付服务响应过大。", 502, "PAYMENT_PROVIDER_INVALID_RESPONSE"
        )
    return payload


def _expiry(now_value: str, ttl_seconds: int) -> str:
    try:
        parsed = datetime.fromisoformat(str(now_value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        parsed = datetime.now(timezone.utc)
    return (
        parsed.astimezone(timezone.utc) + timedelta(seconds=ttl_seconds)
    ).isoformat(timespec="seconds").replace("+00:00", "Z")


class ZPayProvider:
    name = "zpay"

    def __init__(
        self,
        config: ZPayConfig,
        *,
        requester: Requester = _default_requester,
        now_fn: Callable[[], str] = utc_now,
    ) -> None:
        self.config = config
        self.requester = requester
        self.now_fn = now_fn

    def create_payment(self, request: dict[str, object]) -> dict[str, object]:
        url = self.config.create_url()
        fields = {
            "pid": self.config.merchant_id,
            "type": str(request.get("type") or "").strip().lower(),
            "out_trade_no": str(request.get("out_trade_no") or "").strip(),
            "notify_url": self.config.notify_url,
            "return_url": self.config.return_url,
            "name": str(request.get("name") or "").strip(),
            "money": str(request.get("money") or "").strip(),
            "param": str(request.get("param") or "").strip(),
        }
        if fields["type"] not in ALLOWED_PAYMENT_TYPES:
            raise PaymentError(
                "支付渠道不受支持。", 400, "PAYMENT_CHANNEL_UNSUPPORTED"
            )
        if not all(fields.values()):
            raise PaymentError(
                "支付下单参数不完整。", 400, "PAYMENT_PROVIDER_REQUEST_INVALID"
            )
        fields["sign"] = sign_md5(fields, self.config.merchant_key)
        fields["sign_type"] = "MD5"
        transport = urllib.parse.urlencode(fields).encode("utf-8")
        raw = self.requester(
            url,
            transport,
            {
                "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
                "Accept": "application/json",
                "User-Agent": "LOOM-Payment-Adapter/1.0",
            },
            12,
        )
        try:
            payload = json.loads(raw.decode("utf-8-sig"))
        except (AttributeError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise PaymentError(
                "支付服务响应格式无效。",
                502,
                "PAYMENT_PROVIDER_INVALID_RESPONSE",
            ) from error
        if not isinstance(payload, dict):
            raise PaymentError(
                "支付服务响应格式无效。", 502, "PAYMENT_PROVIDER_INVALID_RESPONSE"
            )
        success = payload.get("code") in {1, "1"} or payload.get("success") is True
        if not success:
            raise PaymentError(
                "支付服务拒绝创建订单。",
                502,
                "PAYMENT_PROVIDER_REJECTED",
            )
        reference = str(payload.get("trade_no") or "").strip()
        qrcode = str(payload.get("qrcode") or payload.get("qr_code") or "").strip()
        pay_url = str(payload.get("payurl") or payload.get("pay_url") or "").strip()
        if not reference or not (qrcode or pay_url):
            raise PaymentError(
                "支付服务未返回可用二维码。",
                502,
                "PAYMENT_PROVIDER_INVALID_RESPONSE",
            )
        return {
            "providerOrderReference": reference,
            "qrcode": qrcode,
            "payUrl": pay_url,
            "expiresAt": _expiry(self.now_fn(), self.config.order_ttl_seconds),
        }


__all__ = ["ZPayConfig", "ZPayProvider"]
