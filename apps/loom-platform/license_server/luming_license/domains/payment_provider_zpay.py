from __future__ import annotations

import ipaddress
import json
import os
import secrets
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
QueryRequester = Callable[[str, dict[str, str], dict[str, str], int], bytes]


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


def _payment_channels(value: Any) -> tuple[str, ...]:
    if isinstance(value, (list, tuple)):
        raw = value
    else:
        raw = str(value if value is not None else "").split(",")
    normalized = (
        str(item if item is not None else "").strip().lower() for item in raw
    )
    return tuple(dict.fromkeys(item for item in normalized if item))


@dataclass(frozen=True)
class ZPayConfig:
    enabled: bool
    base_url: str
    merchant_id: str
    merchant_key: str
    create_path: str
    notify_url: str
    return_url: str
    channels: tuple[str, ...]
    order_ttl_seconds: int = 600
    query_enabled: bool = False
    query_path: str = "/api.php"

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
            channels=_payment_channels(
                os.environ.get("LICENSE_ZPAY_CHANNELS", "")
            ),
            order_ttl_seconds=_bounded_int(
                os.environ.get("LICENSE_ZPAY_ORDER_TTL_SECONDS", "600"),
                600,
                60,
                3600,
            ),
            query_enabled=_enabled(
                os.environ.get("LICENSE_ZPAY_QUERY_ENABLED", "")
            ),
            query_path=str(
                os.environ.get("LICENSE_ZPAY_QUERY_PATH", "/api.php") or ""
            ).strip(),
        )

    def _provider_url(self, path_value: str, invalid_code: str) -> str:
        if not self.enabled or not all(
            (self.base_url, self.merchant_id, self.merchant_key, path_value)
        ):
            raise PaymentError(
                "支付服务尚未配置。", 503, "PAYMENT_PROVIDER_NOT_CONFIGURED"
            )
        base = urllib.parse.urlsplit(self.base_url)
        if (
            base.scheme != "https"
            or not base.hostname
            or base.username
            or base.password
            or base.path not in {"", "/"}
            or base.query
            or base.fragment
        ):
            raise PaymentError(
                "支付服务必须使用 HTTPS。", 503, "PAYMENT_PROVIDER_INSECURE"
            )
        path = urllib.parse.urlsplit(path_value)
        if (
            not path_value.startswith("/")
            or path.scheme
            or path.netloc
            or path.query
            or path.fragment
            or ".." in urllib.parse.unquote(path.path).split("/")
        ):
            raise PaymentError("支付服务路径配置无效。", 503, invalid_code)
        return urllib.parse.urlunsplit((base.scheme, base.netloc, path.path, "", ""))

    def enabled_channels(self) -> tuple[str, ...]:
        channels = _payment_channels(self.channels)
        if not channels or any(
            channel not in ALLOWED_PAYMENT_TYPES for channel in channels
        ):
            raise PaymentError(
                "支付渠道配置无效。",
                503,
                "PAYMENT_CHANNELS_INVALID",
            )
        return channels

    def create_url(self) -> str:
        if not self.notify_url or not self.return_url:
            raise PaymentError(
                "支付服务尚未配置。", 503, "PAYMENT_PROVIDER_NOT_CONFIGURED"
            )
        for callback in (self.notify_url, self.return_url):
            parsed = urllib.parse.urlsplit(callback)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.password
            ):
                raise PaymentError(
                    "支付回调必须使用 HTTPS。", 503, "PAYMENT_CALLBACK_INSECURE"
                )
        provider_url = self._provider_url(
            self.create_path, "PAYMENT_PROVIDER_PATH_INVALID"
        )
        self.enabled_channels()
        return provider_url

    def query_url(self) -> str:
        if not self.query_enabled:
            raise PaymentError(
                "支付平台主动查单尚未启用。",
                503,
                "PAYMENT_RECONCILIATION_NOT_CONFIGURED",
            )
        return self._provider_url(
            self.query_path, "PAYMENT_RECONCILIATION_PATH_INVALID"
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


def _default_query_requester(
    url: str, params: dict[str, str], headers: dict[str, str], timeout: int
) -> bytes:
    # This provider's current order-query contract is GET-only. Keep the secret
    # out of the caller-visible URL and never propagate urllib exceptions whose
    # repr may contain the full query string.
    target = f"{url}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(target, headers=headers, method="GET")

    class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *_args: Any, **_kwargs: Any) -> None:
            return None

    try:
        opener = urllib.request.build_opener(NoRedirectHandler())
        with opener.open(request, timeout=timeout) as response:
            payload = response.read(131073)
    except urllib.error.HTTPError as error:
        raise PaymentError(
            "支付平台查单暂时不可用。",
            502,
            "PAYMENT_RECONCILIATION_HTTP_ERROR",
            retryable=500 <= int(error.code) < 600,
        ) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise PaymentError(
            "暂时无法连接支付平台查单。",
            503,
            "PAYMENT_RECONCILIATION_UNAVAILABLE",
            retryable=True,
        ) from None
    if len(payload) > 131072:
        raise PaymentError(
            "支付平台查单响应过大。",
            502,
            "PAYMENT_RECONCILIATION_INVALID_RESPONSE",
        )
    return payload


def _multipart_form(fields: dict[str, str]) -> tuple[bytes, str]:
    values = tuple(fields.values())
    while True:
        boundary = f"----LOOMPayment{secrets.token_hex(16)}"
        if all(boundary not in value for value in values):
            break
    chunks: list[bytes] = []
    for key, value in fields.items():
        chunks.extend(
            (
                f"--{boundary}\r\n".encode("ascii"),
                f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode(
                    "ascii"
                ),
                value.encode("utf-8"),
                b"\r\n",
            )
        )
    chunks.append(f"--{boundary}--\r\n".encode("ascii"))
    return b"".join(chunks), boundary


def _json_object(raw: bytes, invalid_code: str, message: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw.decode("utf-8-sig"))
    except (AttributeError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PaymentError(message, 502, invalid_code) from error
    if not isinstance(payload, dict):
        raise PaymentError(message, 502, invalid_code)
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
        query_requester: QueryRequester = _default_query_requester,
        now_fn: Callable[[], str] = utc_now,
    ) -> None:
        self.config = config
        self.requester = requester
        self.query_requester = query_requester
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
            "clientip": str(request.get("clientip") or "").strip(),
            "device": "pc",
        }
        if fields["type"] not in self.config.enabled_channels():
            raise PaymentError(
                "支付渠道不受支持。", 400, "PAYMENT_CHANNEL_UNSUPPORTED"
            )
        if not all(fields.values()):
            raise PaymentError(
                "支付下单参数不完整。", 400, "PAYMENT_PROVIDER_REQUEST_INVALID"
            )
        try:
            ipaddress.ip_address(fields["clientip"])
        except ValueError as error:
            raise PaymentError(
                "支付下单客户端地址无效。",
                400,
                "PAYMENT_CLIENT_IP_INVALID",
            ) from error
        fields["sign"] = sign_md5(fields, self.config.merchant_key)
        fields["sign_type"] = "MD5"
        transport, boundary = _multipart_form(fields)
        raw = self.requester(
            url,
            transport,
            {
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Accept": "application/json",
                "User-Agent": "LOOM-Payment-Adapter/1.0",
            },
            12,
        )
        payload = _json_object(
            raw,
            "PAYMENT_PROVIDER_INVALID_RESPONSE",
            "支付服务响应格式无效。",
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

    def query_payment(self, request: dict[str, object]) -> dict[str, object]:
        url = self.config.query_url()
        out_trade_no = str(request.get("out_trade_no") or "").strip()
        if not out_trade_no or len(out_trade_no) > 64:
            raise PaymentError(
                "支付查单参数无效。",
                400,
                "PAYMENT_RECONCILIATION_REQUEST_INVALID",
            )
        params = {
            "act": "order",
            "pid": self.config.merchant_id,
            "key": self.config.merchant_key,
            "out_trade_no": out_trade_no,
        }
        raw = self.query_requester(
            url,
            params,
            {
                "Accept": "application/json",
                "User-Agent": "LOOM-Payment-Adapter/1.0",
                "Cache-Control": "no-store",
            },
            12,
        )
        payload = _json_object(
            raw,
            "PAYMENT_RECONCILIATION_INVALID_RESPONSE",
            "支付平台查单响应格式无效。",
        )
        if payload.get("code") not in {1, "1"}:
            raise PaymentError(
                "支付平台暂未返回该订单。",
                502,
                "PAYMENT_RECONCILIATION_REJECTED",
                retryable=True,
            )
        provider_status = payload.get("status")
        if provider_status in {1, "1"}:
            status = "paid"
        elif provider_status in {0, "0"}:
            status = "pending"
        else:
            raise PaymentError(
                "支付平台查单状态无效。",
                502,
                "PAYMENT_RECONCILIATION_INVALID_RESPONSE",
            )
        return {
            "status": status,
            "merchantId": str(payload.get("pid") or "").strip(),
            "providerTransactionId": str(payload.get("trade_no") or "").strip(),
            "outTradeNo": str(payload.get("out_trade_no") or "").strip(),
            "paymentType": str(payload.get("type") or "").strip().lower(),
            "productName": str(payload.get("name") or "").strip(),
            "money": str(payload.get("money") or "").strip(),
            "currency": str(payload.get("currency") or "").strip().upper(),
            "param": str(payload.get("param") or "").strip(),
        }


__all__ = ["ZPayConfig", "ZPayProvider"]
