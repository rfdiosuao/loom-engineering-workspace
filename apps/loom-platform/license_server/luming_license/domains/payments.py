from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import sqlite3
from collections.abc import Callable, Collection, Mapping
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

from .. import audit
from ..timeutils import utc_now
from .account_entitlements import ACTIVATED_PHONE_DEVICE_LIMIT, normalize_account_id


ConnectFn = Callable[[], sqlite3.Connection]
UtcNowFn = Callable[[], str]
TokenFn = Callable[[int], str]
ALLOWED_PAYMENT_TYPES = frozenset({"alipay", "wxpay"})
SUCCESS_TRADE_STATUS = "TRADE_SUCCESS"
_SAFE_ID = re.compile(r"[^A-Za-z0-9_-]+")
_MONEY = re.compile(r"^(?:0|[1-9][0-9]*)(?:\.[0-9]{1,2})?$")


class PaymentError(RuntimeError):
    def __init__(self, message: str, status: int, code: str, *, retryable: bool = False):
        super().__init__(message)
        self.status = int(status)
        self.code = str(code)
        self.retryable = bool(retryable)


class PaymentProvider(Protocol):
    name: str

    def create_payment(self, request: dict[str, object]) -> dict[str, object]: ...

    def query_payment(self, request: dict[str, object]) -> dict[str, object]: ...


def _text(value: Any) -> str:
    return str(value if value is not None else "").strip()


def canonical_signing_text(fields: Mapping[str, Any], merchant_key: str) -> str:
    """Return the provider's raw logical UTF-8 signing string.

    Transport encoding is deliberately a later step. Empty values and signature
    metadata are excluded, while the logical value ``0`` is retained.
    """

    parts: list[str] = []
    for key in sorted(str(item) for item in fields):
        if key in {"sign", "sign_type"}:
            continue
        value = fields.get(key)
        if value is None:
            continue
        logical = str(value)
        if logical == "":
            continue
        parts.append(f"{key}={logical}")
    return "&".join(parts) + str(merchant_key)


def sign_md5(fields: Mapping[str, Any], merchant_key: str) -> str:
    canonical = canonical_signing_text(fields, merchant_key)
    return hashlib.md5(canonical.encode("utf-8"), usedforsecurity=False).hexdigest()


def verify_md5(fields: Mapping[str, Any], merchant_key: str) -> bool:
    provided = _text(fields.get("sign")).lower()
    if not provided or not re.fullmatch(r"[0-9a-f]{32}", provided):
        return False
    expected = sign_md5(fields, merchant_key)
    return hmac.compare_digest(provided, expected)


def money_text(amount_minor: int) -> str:
    if isinstance(amount_minor, bool) or int(amount_minor) < 0:
        raise PaymentError("支付金额无效。", 500, "PAYMENT_AMOUNT_INVALID")
    return f"{Decimal(int(amount_minor)) / Decimal(100):.2f}"


def money_minor(value: Any) -> int:
    text = _text(value)
    if not _MONEY.fullmatch(text):
        raise PaymentError("支付回调金额格式无效。", 400, "PAYMENT_AMOUNT_INVALID")
    try:
        amount = Decimal(text)
        minor = amount * Decimal(100)
        if minor != minor.to_integral_exact():
            raise InvalidOperation
        parsed = int(minor)
    except (InvalidOperation, ValueError) as error:
        raise PaymentError(
            "支付回调金额格式无效。", 400, "PAYMENT_AMOUNT_INVALID"
        ) from error
    if parsed < 0:
        raise PaymentError("支付回调金额格式无效。", 400, "PAYMENT_AMOUNT_INVALID")
    return parsed


def _load_json(value: Any, fallback: Any) -> Any:
    try:
        parsed = json.loads(str(value if value is not None else ""))
    except (TypeError, json.JSONDecodeError):
        return fallback
    return parsed


def _features(value: Any) -> list[str]:
    raw = _load_json(value, [])
    if not isinstance(raw, list):
        raw = []
    result = list(
        dict.fromkeys(
            _text(item)
            for item in raw
            if isinstance(item, str) and _text(item)
        )
    )
    for required in ("matrix.devices", "matrix.tasks", "matrix.diagnostics"):
        if required not in result:
            result.append(required)
    return result


def _quotas(value: Any) -> dict[str, Any]:
    raw = _load_json(value, {})
    return raw if isinstance(raw, dict) else {}


def _benefits(value: Any) -> list[str]:
    raw = _load_json(value, [])
    if not isinstance(raw, list):
        return []
    return [_text(item)[:120] for item in raw if isinstance(item, str) and _text(item)]


def _public_plan(row: sqlite3.Row) -> dict[str, Any]:
    amount_minor = int(row["price_minor"] or 0)
    return {
        "planKey": _text(row["plan_key"]),
        "displayName": _text(row["display_name"]),
        "description": _text(row["payment_description"]),
        "durationDays": int(row["duration_days"] or 0),
        "amountMinor": amount_minor,
        "amount": money_text(amount_minor),
        "currency": _text(row["currency"]).upper(),
        "benefits": _benefits(row["payment_benefits_json"]),
        "features": _features(row["features_json"]),
    }


def list_payment_plans(*, connect_fn: ConnectFn) -> list[dict[str, Any]]:
    with connect_fn() as connection:
        rows = connection.execute(
            """
            select * from plans
            where disabled = 0 and payment_enabled = 1 and price_minor > 0
            order by payment_sort asc, price_minor asc, plan_key asc
            """
        ).fetchall()
    return [_public_plan(row) for row in rows]


def _payment_plan(connection: sqlite3.Connection, plan_key: str) -> sqlite3.Row:
    row = connection.execute(
        """
        select * from plans
        where plan_key = ? and disabled = 0 and payment_enabled = 1 and price_minor > 0
        """,
        (plan_key,),
    ).fetchone()
    if row is None:
        raise PaymentError("所选套餐当前不可购买。", 404, "PAYMENT_PLAN_UNAVAILABLE")
    currency = _text(row["currency"]).upper()
    if currency != "CNY":
        raise PaymentError("当前支付通道仅支持人民币套餐。", 409, "PAYMENT_CURRENCY_UNSUPPORTED")
    return row


def _token(token_fn: TokenFn, size: int) -> str:
    value = _SAFE_ID.sub("", _text(token_fn(size)))
    if not value:
        raise PaymentError("无法生成安全订单标识。", 500, "PAYMENT_RANDOM_UNAVAILABLE")
    return value[:96]


def _order_snapshot(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "orderId": _text(row["order_id"]),
        "outTradeNo": _text(row["out_trade_no"]),
        "planKey": _text(row["plan_key"]),
        "displayName": _text(row["product_name"]),
        "paymentType": _text(row["payment_type"]),
        "amountMinor": int(row["amount_minor"]),
        "amount": money_text(int(row["amount_minor"])),
        "currency": _text(row["currency"]),
        "status": _text(row["status"]),
        "providerOrderReference": _text(row["provider_order_reference"]),
        "providerTransactionId": _text(row["provider_transaction_id"]),
        "qrcode": _text(row["qrcode"]),
        "payUrl": _text(row["pay_url"]),
        "expiresAt": _text(row["expires_at"]),
        "paidAt": _text(row["paid_at"]),
        "createdAt": _text(row["created_at"]),
        "updatedAt": _text(row["updated_at"]),
    }


def _get_order_by_request(
    connection: sqlite3.Connection, account_id: str, request_id: str
) -> sqlite3.Row | None:
    return connection.execute(
        "select * from payment_orders where account_id = ? and request_id = ?",
        (account_id, request_id),
    ).fetchone()


def create_payment_order(
    body: dict[str, Any],
    *,
    connect_fn: ConnectFn,
    provider: PaymentProvider,
    now_fn: UtcNowFn = utc_now,
    token_fn: TokenFn = secrets.token_urlsafe,
    allowed_payment_types: Collection[str] | None = None,
) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise PaymentError("下单参数无效。", 400, "PAYMENT_INVALID_REQUEST")
    account_id = normalize_account_id(body.get("accountId"))
    plan_key = _text(body.get("planKey")).lower()
    request_id = _text(body.get("requestId"))
    payment_type = _text(body.get("paymentType")).lower()
    if not plan_key or len(plan_key) > 80:
        raise PaymentError("请选择套餐。", 400, "PAYMENT_PLAN_REQUIRED")
    if not request_id or len(request_id) > 128:
        raise PaymentError("本次下单标识无效，请重新选择套餐。", 400, "PAYMENT_REQUEST_ID_INVALID")
    enabled_types = (
        ALLOWED_PAYMENT_TYPES
        if allowed_payment_types is None
        else frozenset(
            _text(item).lower() for item in allowed_payment_types if _text(item)
        )
    )
    if (
        payment_type not in ALLOWED_PAYMENT_TYPES or payment_type not in enabled_types
    ):
        raise PaymentError("请选择支付宝或微信支付。", 400, "PAYMENT_CHANNEL_UNSUPPORTED")

    with connect_fn() as connection:
        existing = _get_order_by_request(connection, account_id, request_id)
        if existing is not None:
            if (
                _text(existing["plan_key"]) != plan_key
                or _text(existing["payment_type"]) != payment_type
            ):
                raise PaymentError(
                    "本次下单标识已用于其他套餐，请刷新后重试。",
                    409,
                    "PAYMENT_IDEMPOTENCY_CONFLICT",
                )
            return _order_snapshot(existing)
        plan = _payment_plan(connection, plan_key)
        now = now_fn()
        identity = _token(token_fn, 24)
        order_id = f"pay_{identity}"
        out_trade_no = f"LM{hashlib.sha256((identity + account_id).encode('utf-8')).hexdigest()[:28].upper()}"
        nonce = _token(token_fn, 32)
        nonce_hash = hashlib.sha256(nonce.encode("utf-8")).hexdigest()
        features = _features(plan["features_json"])
        quotas = _quotas(plan["quotas_json"])
        connection.execute(
            """
            insert into payment_orders (
                order_id, out_trade_no, account_id, request_id, product_id,
                product_name, plan_key, provider, payment_type, amount_minor,
                currency, duration_days, features_json, quotas_json, nonce_hash,
                status, created_at, updated_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
            """,
            (
                order_id,
                out_trade_no,
                account_id,
                request_id,
                plan_key,
                _text(plan["display_name"]),
                plan_key,
                _text(provider.name).lower(),
                payment_type,
                int(plan["price_minor"]),
                _text(plan["currency"]).upper(),
                int(plan["duration_days"]),
                json.dumps(features, ensure_ascii=False),
                json.dumps(quotas, ensure_ascii=False),
                nonce_hash,
                now,
                now,
            ),
        )
        connection.commit()
        provider_request: dict[str, object] = {
            "out_trade_no": out_trade_no,
            "type": payment_type,
            "name": _text(plan["display_name"]),
            "money": money_text(int(plan["price_minor"])),
            "param": nonce,
            "clientip": _text(body.get("clientIp")),
        }

    try:
        response = provider.create_payment(provider_request)
        if not isinstance(response, dict):
            raise PaymentError("支付服务返回格式无效。", 502, "PAYMENT_PROVIDER_INVALID_RESPONSE")
        reference = _text(response.get("providerOrderReference"))
        qrcode = _text(response.get("qrcode"))
        pay_url = _text(response.get("payUrl"))
        if not reference or not (qrcode or pay_url):
            raise PaymentError("支付服务未返回可用二维码。", 502, "PAYMENT_PROVIDER_INVALID_RESPONSE")
        with connect_fn() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                update payment_orders
                set provider_order_reference = ?, qrcode = ?, pay_url = ?,
                    expires_at = ?, updated_at = ?, last_error_code = ''
                where order_id = ? and status = 'pending'
                """,
                (
                    reference,
                    qrcode,
                    pay_url,
                    _text(response.get("expiresAt")),
                    now_fn(),
                    order_id,
                ),
            )
            row = connection.execute(
                "select * from payment_orders where order_id = ?", (order_id,)
            ).fetchone()
            connection.commit()
    except PaymentError as error:
        _mark_creation_uncertain(connect_fn, order_id, error.code, now_fn())
        raise
    except Exception as error:
        _mark_creation_uncertain(connect_fn, order_id, "PAYMENT_PROVIDER_UNAVAILABLE", now_fn())
        raise PaymentError(
            "暂时无法连接支付服务，请稍后查询订单状态。",
            503,
            "PAYMENT_PROVIDER_UNAVAILABLE",
            retryable=True,
        ) from error
    if row is None:
        raise PaymentError("支付订单保存失败。", 500, "PAYMENT_ORDER_LOST")
    return _order_snapshot(row)


def _mark_creation_uncertain(
    connect_fn: ConnectFn, order_id: str, error_code: str, updated_at: str
) -> None:
    with connect_fn() as connection:
        connection.execute(
            """
            update payment_orders
            set status = 'creation_uncertain', last_error_code = ?, updated_at = ?
            where order_id = ? and status = 'pending'
            """,
            (_text(error_code)[:80], updated_at, order_id),
        )
        connection.commit()


def payment_order_status(
    body: dict[str, Any], *, connect_fn: ConnectFn, now_fn: UtcNowFn = utc_now
) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise PaymentError("订单查询参数无效。", 400, "PAYMENT_INVALID_REQUEST")
    account_id = normalize_account_id(body.get("accountId"))
    order_id = _text(body.get("orderId"))
    if not order_id:
        raise PaymentError("缺少订单号。", 400, "PAYMENT_ORDER_REQUIRED")
    with connect_fn() as connection:
        row = connection.execute(
            "select * from payment_orders where order_id = ? and account_id = ?",
            (order_id, account_id),
        ).fetchone()
        if row is None:
            raise PaymentError("未找到该账号的支付订单。", 404, "PAYMENT_ORDER_NOT_FOUND")
        now_value = now_fn()
        if _text(row["status"]) == "pending" and _deadline_reached(
            row["expires_at"], now_value
        ):
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "select * from payment_orders where order_id = ? and account_id = ?",
                (order_id, account_id),
            ).fetchone()
            if row is None:
                raise PaymentError(
                    "未找到该账号的支付订单。",
                    404,
                    "PAYMENT_ORDER_NOT_FOUND",
                )
            if _text(row["status"]) == "pending" and _deadline_reached(
                row["expires_at"], now_value
            ):
                connection.execute(
                    """
                    update payment_orders
                    set status = 'expired', qrcode = '', pay_url = '', updated_at = ?
                    where order_id = ? and account_id = ? and status = 'pending'
                    """,
                    (now_value, order_id, account_id),
                )
            row = connection.execute(
                "select * from payment_orders where order_id = ? and account_id = ?",
                (order_id, account_id),
            ).fetchone()
            connection.commit()
    if row is None:
        raise PaymentError("支付订单状态读取失败。", 500, "PAYMENT_ORDER_LOST")
    return _order_snapshot(row)


def _parse_iso_datetime(value: Any) -> datetime | None:
    text = _text(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _deadline_reached(deadline: Any, now_value: Any) -> bool:
    parsed_deadline = _parse_iso_datetime(deadline)
    parsed_now = _parse_iso_datetime(now_value)
    return bool(parsed_deadline and parsed_now and parsed_now >= parsed_deadline)


def _expected_nonce(row: sqlite3.Row, callback_value: Any) -> bool:
    callback_hash = hashlib.sha256(_text(callback_value).encode("utf-8")).hexdigest()
    return hmac.compare_digest(callback_hash, _text(row["nonce_hash"]))


def _parse_iso_date(value: Any) -> date | None:
    text = _text(value)
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _today(now_value: str) -> date:
    text = _text(now_value)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).date()
    except ValueError:
        return datetime.now(timezone.utc).date()


def _entitlement_expiry(
    connection: sqlite3.Connection,
    *,
    account_id: str,
    plan_key: str,
    duration_days: int,
    today: date,
) -> date:
    rows = connection.execute(
        """
        select expires_at from account_entitlement_redemptions
        where account_id = ? and plan = ?
        """,
        (account_id, plan_key),
    ).fetchall()
    valid = [item for item in (_parse_iso_date(row["expires_at"]) for row in rows) if item]
    base = max([today, *valid])
    return base + timedelta(days=max(1, int(duration_days)))


def _write_paid_entitlement(
    connection: sqlite3.Connection,
    *,
    row: sqlite3.Row,
    paid_at: str,
) -> str:
    order_id = _text(row["order_id"])
    account_id = _text(row["account_id"])
    plan_key = _text(row["plan_key"])
    code_hash = hashlib.sha256(f"loom-payment-entitlement-v1\0{order_id}".encode("utf-8")).hexdigest()
    code_label = f"PAY-{order_id[-8:].upper()}"
    features = _features(row["features_json"])
    quotas = _quotas(row["quotas_json"])
    concurrent_tasks = quotas.get("concurrentTasks", quotas.get("concurrent_tasks", 1))
    if isinstance(concurrent_tasks, bool):
        concurrent_tasks = 1
    try:
        concurrent_tasks = max(1, min(int(concurrent_tasks), 100))
    except (TypeError, ValueError):
        concurrent_tasks = 1
    expires = _entitlement_expiry(
        connection,
        account_id=account_id,
        plan_key=plan_key,
        duration_days=int(row["duration_days"]),
        today=_today(paid_at),
    ).isoformat()
    connection.execute(
        """
        insert into codes (
            code_hash, code_label, full_code, licensee, edition, features_json,
            expires, max_activations, disabled, member_mode, plan, quotas_json,
            created_at
        ) values (?, ?, '', 'paid-account', ?, ?, ?, ?, 0, 1, ?, ?, ?)
        """,
        (
            code_hash,
            code_label,
            plan_key,
            json.dumps(features, ensure_ascii=False),
            expires,
            ACTIVATED_PHONE_DEVICE_LIMIT,
            plan_key,
            json.dumps(quotas, ensure_ascii=False),
            paid_at,
        ),
    )
    connection.execute(
        """
        insert into account_entitlement_redemptions (
            code_hash, account_id, plan, features_json, devices,
            concurrent_tasks, expires_at, code_label, redeemed_at
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            code_hash,
            account_id,
            plan_key,
            json.dumps(features, ensure_ascii=False),
            ACTIVATED_PHONE_DEVICE_LIMIT,
            concurrent_tasks,
            expires,
            code_label,
            paid_at,
        ),
    )
    return code_hash


def _paid_audit(connection: sqlite3.Connection, row: sqlite3.Row, paid_at: str) -> None:
    payload = audit.audit_public_value(
        {
            "orderId": _text(row["order_id"]),
            "accountId": _text(row["account_id"]),
            "planKey": _text(row["plan_key"]),
            "amountMinor": int(row["amount_minor"]),
            "currency": _text(row["currency"]),
            "status": "paid",
        }
    )
    connection.execute(
        """
        insert into audit_logs (
            actor, action, target_type, target_id, before_json, after_json,
            request_ip, backup_path, created_at
        ) values ('service:payments', 'payment.order.paid', 'payment_order', ?, ?, ?, '', '', ?)
        """,
        (
            _text(row["order_id"]),
            audit.audit_json({"status": _text(row["status"])}),
            audit.audit_json(payload),
            paid_at,
        ),
    )


def _fulfil_verified_payment(
    payload: Mapping[str, Any],
    *,
    connect_fn: ConnectFn,
    merchant_id: str,
    now_fn: UtcNowFn = utc_now,
) -> dict[str, Any]:
    if not merchant_id:
        raise PaymentError("支付回调服务尚未配置。", 503, "PAYMENT_PROVIDER_NOT_CONFIGURED")
    if _text(payload.get("pid")) != merchant_id:
        raise PaymentError("支付通知商户不匹配。", 400, "PAYMENT_MERCHANT_MISMATCH")
    if _text(payload.get("trade_status")).upper() != SUCCESS_TRADE_STATUS:
        raise PaymentError("支付尚未成功。", 409, "PAYMENT_NOT_SUCCESSFUL")
    out_trade_no = _text(payload.get("out_trade_no"))
    provider_transaction_id = _text(payload.get("trade_no"))
    if not out_trade_no or not provider_transaction_id:
        raise PaymentError("支付通知缺少订单流水。", 400, "PAYMENT_CALLBACK_INVALID")

    with connect_fn() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "select * from payment_orders where out_trade_no = ?", (out_trade_no,)
        ).fetchone()
        if row is None:
            raise PaymentError("支付订单不存在。", 404, "PAYMENT_ORDER_NOT_FOUND")
        if money_minor(payload.get("money")) != int(row["amount_minor"]):
            raise PaymentError("支付金额与订单不一致。", 409, "PAYMENT_AMOUNT_MISMATCH")
        callback_currency = _text(payload.get("currency")).upper()
        if callback_currency and callback_currency != _text(row["currency"]).upper():
            raise PaymentError("支付币种与订单不一致。", 409, "PAYMENT_CURRENCY_MISMATCH")
        if _text(payload.get("type")).lower() != _text(row["payment_type"]).lower():
            raise PaymentError("支付渠道与订单不一致。", 409, "PAYMENT_CHANNEL_MISMATCH")
        if not _expected_nonce(row, payload.get("param")):
            raise PaymentError("支付通知校验参数不匹配。", 409, "PAYMENT_NONCE_MISMATCH")
        callback_name = _text(payload.get("name"))
        if callback_name and callback_name != _text(row["product_name"]):
            raise PaymentError("支付商品与订单不一致。", 409, "PAYMENT_PRODUCT_MISMATCH")
        reused = connection.execute(
            """
            select order_id from payment_orders
            where provider_transaction_id = ? and order_id <> ?
            """,
            (provider_transaction_id, row["order_id"]),
        ).fetchone()
        if reused is not None:
            raise PaymentError("支付流水已用于其他订单。", 409, "PAYMENT_TRANSACTION_REUSED")
        if _text(row["status"]) == "paid":
            if _text(row["provider_transaction_id"]) != provider_transaction_id:
                raise PaymentError("订单已由其他支付流水完成。", 409, "PAYMENT_TRANSACTION_MISMATCH")
            if _text(row["qrcode"]) or _text(row["pay_url"]):
                connection.execute(
                    """
                    update payment_orders
                    set qrcode = '', pay_url = ''
                    where order_id = ?
                    """,
                    (row["order_id"],),
                )
                row = connection.execute(
                    "select * from payment_orders where order_id = ?",
                    (row["order_id"],),
                ).fetchone()
            connection.commit()
            result = _order_snapshot(row)
            result["duplicate"] = True
            return result
        if _text(row["status"]) not in {"pending", "creation_uncertain", "expired"}:
            raise PaymentError("订单当前状态不允许入账。", 409, "PAYMENT_ORDER_STATE_INVALID")

        paid_at = now_fn()
        code_hash = _write_paid_entitlement(connection, row=row, paid_at=paid_at)
        _paid_audit(connection, row, paid_at)
        connection.execute(
            """
            update payment_orders
            set status = 'paid', provider_transaction_id = ?, paid_at = ?,
                entitlement_code_hash = ?, qrcode = '', pay_url = '',
                updated_at = ?, last_error_code = ''
            where order_id = ?
            """,
            (provider_transaction_id, paid_at, code_hash, paid_at, row["order_id"]),
        )
        updated = connection.execute(
            "select * from payment_orders where order_id = ?", (row["order_id"],)
        ).fetchone()
        connection.commit()
    if updated is None:
        raise PaymentError("支付入账失败。", 500, "PAYMENT_FULFILMENT_FAILED")
    result = _order_snapshot(updated)
    result["duplicate"] = False
    return result


def process_zpay_notification(
    payload: Mapping[str, Any],
    *,
    connect_fn: ConnectFn,
    merchant_id: str,
    merchant_key: str,
    now_fn: UtcNowFn = utc_now,
) -> dict[str, Any]:
    if not merchant_id or not merchant_key:
        raise PaymentError("支付回调服务尚未配置。", 503, "PAYMENT_PROVIDER_NOT_CONFIGURED")
    if not verify_md5(payload, merchant_key):
        raise PaymentError("支付通知签名无效。", 400, "PAYMENT_SIGNATURE_INVALID")
    return _fulfil_verified_payment(
        payload,
        connect_fn=connect_fn,
        merchant_id=merchant_id,
        now_fn=now_fn,
    )


def reconcile_payment_order(
    body: dict[str, Any],
    *,
    connect_fn: ConnectFn,
    provider: PaymentProvider,
    merchant_id: str,
    now_fn: UtcNowFn = utc_now,
) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise PaymentError("订单查单参数无效。", 400, "PAYMENT_INVALID_REQUEST")
    account_id = normalize_account_id(body.get("accountId"))
    order_id = _text(body.get("orderId"))
    if not order_id:
        raise PaymentError("缺少订单号。", 400, "PAYMENT_ORDER_REQUIRED")
    with connect_fn() as connection:
        row = connection.execute(
            "select * from payment_orders where order_id = ? and account_id = ?",
            (order_id, account_id),
        ).fetchone()
    if row is None:
        raise PaymentError("未找到该账号的支付订单。", 404, "PAYMENT_ORDER_NOT_FOUND")
    if _text(row["status"]) == "paid":
        result = _order_snapshot(row)
        result["duplicate"] = True
        result["reconciled"] = False
        return result
    if _text(row["provider"]).lower() != _text(provider.name).lower():
        raise PaymentError(
            "支付订单与查单服务不匹配。",
            409,
            "PAYMENT_PROVIDER_MISMATCH",
        )

    observed = provider.query_payment(
        {"out_trade_no": _text(row["out_trade_no"])}
    )
    if not isinstance(observed, dict):
        raise PaymentError(
            "支付平台查单响应格式无效。",
            502,
            "PAYMENT_RECONCILIATION_INVALID_RESPONSE",
        )
    observed_status = _text(observed.get("status")).lower()
    observed_out_trade_no = _text(observed.get("outTradeNo"))
    if observed_out_trade_no != _text(row["out_trade_no"]):
        raise PaymentError(
            "支付平台返回的订单号不匹配。",
            409,
            "PAYMENT_ORDER_MISMATCH",
        )
    if observed_status == "pending":
        result = payment_order_status(body, connect_fn=connect_fn, now_fn=now_fn)
        result["reconciled"] = True
        return result
    if observed_status != "paid":
        raise PaymentError(
            "支付平台查单状态无效。",
            502,
            "PAYMENT_RECONCILIATION_INVALID_RESPONSE",
        )
    result = _fulfil_verified_payment(
        {
            "pid": observed.get("merchantId"),
            "trade_no": observed.get("providerTransactionId"),
            "out_trade_no": observed_out_trade_no,
            "type": observed.get("paymentType"),
            "name": observed.get("productName"),
            "money": observed.get("money"),
            "currency": observed.get("currency"),
            "param": observed.get("param"),
            "trade_status": SUCCESS_TRADE_STATUS,
        },
        connect_fn=connect_fn,
        merchant_id=merchant_id,
        now_fn=now_fn,
    )
    result["reconciled"] = True
    return result


__all__ = [
    "ALLOWED_PAYMENT_TYPES",
    "PaymentError",
    "PaymentProvider",
    "SUCCESS_TRADE_STATUS",
    "canonical_signing_text",
    "create_payment_order",
    "list_payment_plans",
    "money_minor",
    "money_text",
    "payment_order_status",
    "process_zpay_notification",
    "reconcile_payment_order",
    "sign_md5",
    "verify_md5",
]
