"""Local secret protection helpers for launcher-owned session files."""

from __future__ import annotations

import base64
import ctypes
import os
from typing import Any


SECRET_MARKER = "__loomSecret"
DPAPI_PROVIDER = "dpapi"


def protect_secret(value: Any) -> Any:
    text = str(value or "")
    if not text:
        return value
    if isinstance(value, dict) and value.get(SECRET_MARKER):
        return value
    if os.name != "nt":
        return value
    encrypted = _crypt_protect(text.encode("utf-8"))
    return {
        SECRET_MARKER: DPAPI_PROVIDER,
        "value": base64.b64encode(encrypted).decode("ascii"),
    }


def unprotect_secret(value: Any) -> str:
    if not isinstance(value, dict) or value.get(SECRET_MARKER) != DPAPI_PROVIDER:
        return str(value or "")
    raw = base64.b64decode(str(value.get("value") or ""))
    return _crypt_unprotect(raw).decode("utf-8", errors="replace")


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", ctypes.c_ulong),
        ("pbData", ctypes.POINTER(ctypes.c_byte)),
    ]


def _crypt_protect(data: bytes) -> bytes:
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    in_buffer = ctypes.create_string_buffer(data)
    in_blob = _DataBlob(len(data), ctypes.cast(in_buffer, ctypes.POINTER(ctypes.c_byte)))
    out_blob = _DataBlob()
    ok = crypt32.CryptProtectData(
        ctypes.byref(in_blob),
        "LOOM launcher secret",
        None,
        None,
        None,
        0x01,
        ctypes.byref(out_blob),
    )
    if not ok:
        raise ctypes.WinError()
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(out_blob.pbData)


def _crypt_unprotect(data: bytes) -> bytes:
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    in_buffer = ctypes.create_string_buffer(data)
    in_blob = _DataBlob(len(data), ctypes.cast(in_buffer, ctypes.POINTER(ctypes.c_byte)))
    out_blob = _DataBlob()
    ok = crypt32.CryptUnprotectData(
        ctypes.byref(in_blob),
        None,
        None,
        None,
        None,
        0x01,
        ctypes.byref(out_blob),
    )
    if not ok:
        raise ctypes.WinError()
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(out_blob.pbData)
