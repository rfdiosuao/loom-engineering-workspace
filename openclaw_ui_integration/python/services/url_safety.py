"""HTTP URL validation helpers for outbound media requests."""

from __future__ import annotations

import ipaddress
import os
import socket
import urllib.parse


class UnsafeUrlError(ValueError):
    pass


def assert_public_http_url(value: str, label: str = "URL") -> str:
    text = str(value or "").strip()
    parsed = urllib.parse.urlparse(text)
    if parsed.scheme not in ("http", "https"):
        raise UnsafeUrlError(f"{label} 只支持 http/https")
    if not parsed.hostname:
        raise UnsafeUrlError(f"{label} 缺少主机名")
    if parsed.username or parsed.password:
        raise UnsafeUrlError(f"{label} 不能包含用户名或密码")
    if _allow_private_urls():
        return text
    host = parsed.hostname
    try:
        addresses = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
    except socket.gaierror as error:
        raise UnsafeUrlError(f"{label} 主机无法解析: {host}") from error
    for item in addresses:
        ip = ipaddress.ip_address(item[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified:
            raise UnsafeUrlError(f"{label} 指向受限网络地址: {host}")
    return text


def _allow_private_urls() -> bool:
    return str(os.environ.get("OPENCLAW_ALLOW_PRIVATE_MEDIA_URLS", "")).strip().lower() in {"1", "true", "yes", "on"}
