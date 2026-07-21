from __future__ import annotations

import base64
import os
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from .config import Settings
from .serialization import canonical


def load_private_key(*, private_key_file: str | None = None) -> Ed25519PrivateKey:
    key_text = os.environ.get("LICENSE_PRIVATE_KEY_B64")
    if not key_text:
        key_path = private_key_file or Settings.from_env().private_key_file
        with open(key_path, "r", encoding="utf-8") as file:
            key_text = file.read().strip()
    raw = base64.b64decode(key_text)
    return Ed25519PrivateKey.from_private_bytes(raw)


def public_key_b64(*, private_key_file: str | None = None) -> str:
    public = load_private_key(private_key_file=private_key_file).public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return base64.b64encode(public).decode("ascii")


def sign_license(payload: dict[str, Any], *, private_key_file: str | None = None) -> dict[str, Any]:
    private_key = load_private_key(private_key_file=private_key_file)
    signature = private_key.sign(canonical(payload))
    license_data = dict(payload)
    license_data["signature"] = base64.b64encode(signature).decode("ascii")
    return license_data
