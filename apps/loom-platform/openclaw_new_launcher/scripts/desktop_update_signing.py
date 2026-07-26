"""Shared Ed25519 key loading for LOOM desktop update tooling."""

from __future__ import annotations

import base64
import json
import os

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


PRIVATE_KEY_ENV = "LOOM_DESKTOP_UPDATE_PRIVATE_KEY"
PRIVATE_KEY_PATH_ENV = "LOOM_DESKTOP_UPDATE_PRIVATE_KEY_PATH"


def read_private_key() -> str:
    value = str(os.environ.get(PRIVATE_KEY_ENV) or "").strip()
    if value:
        return value
    path = str(os.environ.get(PRIVATE_KEY_PATH_ENV) or "").strip()
    if path and os.path.isfile(path):
        with open(path, "r", encoding="utf-8-sig") as handle:
            value = handle.read().strip()
    if not value:
        raise ValueError(
            f"{PRIVATE_KEY_ENV} or {PRIVATE_KEY_PATH_ENV} is required to sign desktop updates"
        )
    return value


def load_private_key(value: str) -> Ed25519PrivateKey:
    text = value.strip()
    if text.startswith("-----BEGIN"):
        loaded = serialization.load_pem_private_key(text.encode("utf-8"), password=None)
        if not isinstance(loaded, Ed25519PrivateKey):
            raise ValueError("desktop update private key must use Ed25519")
        return loaded
    if text.lower().startswith("ed25519:"):
        text = text.split(":", 1)[1].strip()
    try:
        raw = base64.b64decode(text, validate=True)
    except Exception as error:
        raise ValueError("desktop update private key must be base64 or PEM") from error
    if len(raw) != 32:
        raise ValueError("desktop update private key must contain 32 raw Ed25519 bytes")
    return Ed25519PrivateKey.from_private_bytes(raw)


def read_public_key(path: str) -> str:
    resolved = os.path.abspath(str(path or "").strip())
    if not os.path.isfile(resolved):
        raise ValueError(f"desktop update public key does not exist: {resolved}")
    with open(resolved, "r", encoding="utf-8-sig") as handle:
        text = handle.read().strip()
    if text.startswith("{"):
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as error:
            raise ValueError("desktop update public key JSON is invalid") from error
        text = str(payload.get("publicKey") or "").strip()
    if not text:
        raise ValueError("desktop update public key is empty")
    return text


def load_public_key(value: str) -> Ed25519PublicKey:
    text = value.strip()
    if text.startswith("-----BEGIN"):
        loaded = serialization.load_pem_public_key(text.encode("utf-8"))
        if not isinstance(loaded, Ed25519PublicKey):
            raise ValueError("desktop update public key must use Ed25519")
        return loaded
    if text.lower().startswith("ed25519:"):
        text = text.split(":", 1)[1].strip()
    try:
        raw = base64.b64decode(text, validate=True)
    except Exception as error:
        raise ValueError("desktop update public key must be base64 or PEM") from error
    if len(raw) != 32:
        raise ValueError("desktop update public key must contain 32 raw Ed25519 bytes")
    return Ed25519PublicKey.from_public_bytes(raw)
