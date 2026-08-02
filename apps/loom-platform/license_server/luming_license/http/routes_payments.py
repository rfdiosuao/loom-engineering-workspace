from __future__ import annotations

import json
from typing import Any, Callable
from urllib.parse import parse_qs

from ..domains.payment_provider_zpay import ZPayConfig, ZPayProvider
from ..domains.payments import (
    PaymentError,
    create_payment_order,
    list_payment_plans,
    payment_order_status,
    process_zpay_notification,
)


Route = Callable[[Any, Any], None]
RETURN_PAGE = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>麓鸣支付结果</title><style>body{font-family:system-ui,sans-serif;display:grid;place-items:center;min-height:100vh;margin:0;background:#071b22;color:#f4f1e8}main{max-width:520px;padding:32px;border:1px solid #1e5e61;border-radius:18px;background:#0a252d}h1{margin-top:0}p{line-height:1.7;color:#bdd3cf}</style></head>
<body><main><h1>支付结果正在确认</h1><p>同步返回页不会直接开通套餐。请回到麓鸣查看订单状态；服务端收到并验证支付通知后会自动更新权益。</p></main></body></html>"""


def _require_service_auth(handler: Any) -> bool:
    api = handler.facade
    if not api.account_redeem_service_configured():
        handler.send_json(
            503,
            {
                "ok": False,
                "error": "Payment service authentication is not configured",
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
        headers={"WWW-Authenticate": 'Bearer realm="loom-payments"'},
    )
    return False


def _payment_error(handler: Any, error: PaymentError) -> None:
    handler.send_json(
        error.status,
        {
            "ok": False,
            "error": str(error),
            "code": error.code,
            "retryable": error.retryable,
        },
    )


def post_payment_plans(handler: Any, parsed: Any) -> None:
    del parsed
    if not _require_service_auth(handler):
        return
    config = ZPayConfig.from_env()
    try:
        config.create_url()
        provider_configured = True
    except PaymentError:
        provider_configured = False
    handler.send_json(
        200,
        {
            "ok": True,
            "plans": list_payment_plans(connect_fn=handler.facade.connect),
            "payment": {
                "provider": "zpay",
                "configured": provider_configured,
                "channels": ["alipay", "wxpay"],
            },
        },
    )


def post_payment_order_create(handler: Any, parsed: Any) -> None:
    del parsed
    if not _require_service_auth(handler):
        return
    try:
        body = handler.read_json()
        order = create_payment_order(
            body,
            connect_fn=handler.facade.connect,
            provider=ZPayProvider(ZPayConfig.from_env()),
        )
        handler.send_json(200, {"ok": True, "order": order})
    except PaymentError as error:
        _payment_error(handler, error)
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
        _payment_error(
            handler,
            PaymentError("下单参数无效。", 400, "PAYMENT_INVALID_REQUEST"),
        )


def post_payment_order_status(handler: Any, parsed: Any) -> None:
    del parsed
    if not _require_service_auth(handler):
        return
    try:
        body = handler.read_json()
        order = payment_order_status(body, connect_fn=handler.facade.connect)
        handler.send_json(200, {"ok": True, "order": order})
    except PaymentError as error:
        _payment_error(handler, error)
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
        _payment_error(
            handler,
            PaymentError("订单查询参数无效。", 400, "PAYMENT_INVALID_REQUEST"),
        )


def _flatten(values: dict[str, list[str]]) -> dict[str, str]:
    return {key: items[-1] if items else "" for key, items in values.items()}


def _callback_fields(handler: Any, parsed: Any) -> dict[str, Any]:
    fields = _flatten(parse_qs(parsed.query, keep_blank_values=True))
    if str(getattr(handler, "command", "GET")).upper() != "POST":
        return fields
    length = int(handler.headers.get("Content-Length", "0") or 0)
    if length < 0 or length > 65536:
        raise PaymentError("支付通知过大。", 413, "PAYMENT_CALLBACK_TOO_LARGE")
    raw = handler.rfile.read(length) if length else b""
    if not raw:
        return fields
    content_type = str(handler.headers.get("Content-Type", "")).lower()
    try:
        if "application/json" in content_type:
            decoded = json.loads(raw.decode("utf-8-sig"))
            if not isinstance(decoded, dict):
                raise ValueError
            fields.update({str(key): value for key, value in decoded.items()})
        else:
            fields.update(
                _flatten(parse_qs(raw.decode("utf-8-sig"), keep_blank_values=True))
            )
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as error:
        raise PaymentError(
            "支付通知格式无效。", 400, "PAYMENT_CALLBACK_INVALID"
        ) from error
    return fields


def payment_notify(handler: Any, parsed: Any) -> None:
    try:
        config = ZPayConfig.from_env()
        fields = _callback_fields(handler, parsed)
        process_zpay_notification(
            fields,
            connect_fn=handler.facade.connect,
            merchant_id=config.merchant_id,
            merchant_key=config.merchant_key,
        )
        handler.send_text(200, "success")
    except PaymentError as error:
        status = 503 if error.retryable or error.status >= 500 else 400
        handler.send_text(status, "fail")
    except Exception:
        handler.send_text(503, "fail")


def payment_return(handler: Any, parsed: Any) -> None:
    del parsed
    handler.send_html(200, RETURN_PAGE)


GET_ROUTES: dict[str, Route] = {
    "/api/payments/zpay/notify": payment_notify,
    "/api/payments/zpay/return": payment_return,
}


POST_ROUTES: dict[str, Route] = {
    "/api/service/payments/plans": post_payment_plans,
    "/api/service/payments/orders/create": post_payment_order_create,
    "/api/service/payments/orders/status": post_payment_order_status,
    "/api/payments/zpay/notify": payment_notify,
}


__all__ = ["GET_ROUTES", "POST_ROUTES"]
