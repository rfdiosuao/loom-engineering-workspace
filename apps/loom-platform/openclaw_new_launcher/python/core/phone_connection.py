"""Deterministic phone transport candidate selection.

The phone reports every LAN-capable address. The desktop probes those candidates with its existing
signed identity check, then chooses a verified transport without changing the pairing identity.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse


_TRANSPORT_PRIORITY = {
    "usb-loopback": 0,
    "hotspot-host": 1,
    "wifi-client": 2,
    "ethernet": 3,
    "usb-tethering": 4,
    "lan": 5,
}
_CREDENTIAL_FAILURES = {
    "auth_failed",
    "device_identity_mismatch",
    "credential_invalid",
    "phone_pairing_credential_invalid",
    "signature_invalid",
    "unauthorized",
}


def _normalized_base_url(value: object, default_port: int = 9527) -> str:
    text = str(value or "").strip().rstrip("/")
    if not text:
        return ""
    if "://" not in text:
        text = f"http://{text}"
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return ""
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        return ""
    try:
        port = parsed.port or default_port
    except ValueError:
        return ""
    host = parsed.hostname
    host_part = f"[{host}]" if ":" in host and not host.startswith("[") else host
    return f"{parsed.scheme}://{host_part}:{port}"


def _transport_for_url(base_url: str, requested: object = "") -> str:
    requested_mode = str(requested or "").strip().lower()
    host = urlparse(base_url).hostname or ""
    if host in {"127.0.0.1", "localhost", "::1"}:
        return "usb-loopback"
    if requested_mode in _TRANSPORT_PRIORITY:
        return requested_mode
    return "lan"


def phone_connection_candidates(device: dict, status: dict | None = None) -> list[dict]:
    status = status if isinstance(status, dict) else {}
    raw: list[tuple[object, object, object]] = []
    raw.append((device.get("baseUrl"), device.get("activeTransport"), "saved"))
    if device.get("adbLocalPort"):
        raw.append((f"http://127.0.0.1:{device['adbLocalPort']}", "usb-loopback", "adb-forward"))
    raw.append((device.get("lanBaseUrl"), "lan", "saved-lan"))
    for value in device.get("lanBaseUrls", []) if isinstance(device.get("lanBaseUrls"), list) else []:
        raw.append((value, "lan", "saved-lan"))
    for item in status.get("networkCandidates", []) if isinstance(status.get("networkCandidates"), list) else []:
        if not isinstance(item, dict):
            continue
        base_url = item.get("baseUrl")
        if not base_url and item.get("address"):
            port = status.get("configServerPort") or status.get("serverPort") or 9527
            base_url = f"http://{item['address']}:{port}"
        raw.append((base_url, item.get("mode"), item.get("interface") or "phone-status"))

    by_url: dict[str, dict] = {}
    for value, mode, source in raw:
        base_url = _normalized_base_url(value)
        if not base_url:
            continue
        transport = _transport_for_url(base_url, mode)
        candidate = {
            "baseUrl": base_url,
            "transport": transport,
            "source": str(source or "").strip()[:80],
            "priority": _TRANSPORT_PRIORITY.get(transport, 99),
        }
        current = by_url.get(base_url)
        if current is None or candidate["priority"] < current["priority"]:
            by_url[base_url] = candidate
    candidates = list(by_url.values())
    return sorted(candidates, key=lambda item: (item["priority"], item["baseUrl"]))


def _probe_candidate(candidate: dict, probe) -> dict:
    try:
        raw = probe(candidate["baseUrl"])
        result = raw if isinstance(raw, dict) else {"ok": bool(raw)}
    except Exception as error:  # Probe implementations already sanitize transport details.
        result = {"ok": False, "status": "endpoint_unavailable", "message": type(error).__name__}
    return {
        **candidate,
        "ok": result.get("ok") is True,
        "status": str(result.get("status") or ("verified" if result.get("ok") is True else "endpoint_unavailable"))[:80],
        "deviceInstanceId": str(result.get("deviceInstanceId") or "")[:120],
    }


def select_phone_connection(device: dict, *, status: dict | None, probe, max_workers: int = 4) -> dict:
    """Probe candidates concurrently and return a stable, secret-free selection result."""

    status = status if isinstance(status, dict) else {}
    candidates = phone_connection_candidates(device, status)
    expected_mode = str(device.get("expectedNetworkMode") or "").strip().lower()
    has_hotspot = any(item["transport"] == "hotspot-host" for item in candidates)

    if status.get("configServerRunning") is False:
        return _failure("phone_connection_service_stopped", candidates)
    if expected_mode == "hotspot-host" and not has_hotspot:
        return _failure("phone_hotspot_not_enabled", candidates)
    if not candidates:
        return _failure("phone_port_unreachable", candidates)

    results: list[dict] = []
    worker_count = max(1, min(int(max_workers or 1), len(candidates), 8))
    with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="phone-transport-probe") as executor:
        future_map = {executor.submit(_probe_candidate, item, probe): item for item in candidates}
        for future in as_completed(future_map):
            results.append(future.result())

    results.sort(key=lambda item: (item["priority"], item["baseUrl"]))
    verified = next((item for item in results if item["ok"]), None)
    if verified:
        return {
            "ok": True,
            "baseUrl": verified["baseUrl"],
            "activeTransport": verified["transport"],
            "deviceInstanceId": verified.get("deviceInstanceId") or "",
            "candidates": results,
        }

    statuses = {item.get("status") for item in results}
    if statuses.intersection(_CREDENTIAL_FAILURES):
        return _failure("phone_pairing_credential_invalid", results)
    if has_hotspot:
        return _failure("phone_hotspot_client_disconnected", results)
    return _failure("phone_port_unreachable", results)


def _failure(code: str, candidates: list[dict]) -> dict:
    messages = {
        "phone_connection_service_stopped": "手机连接服务已关闭。",
        "phone_hotspot_not_enabled": "手机热点尚未开启。",
        "phone_hotspot_client_disconnected": "电脑未连接手机热点，或热点地址暂不可达。",
        "phone_pairing_credential_invalid": "手机配对身份无效，请重新配对。",
        "phone_port_unreachable": "手机连接端口不可达。",
    }
    return {
        "ok": False,
        "errorCode": code,
        "message": messages[code],
        "candidates": candidates,
    }
