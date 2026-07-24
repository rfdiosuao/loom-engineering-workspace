"""Create a signed LOOM desktop update manifest."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


PRIVATE_KEY_ENV = "LOOM_DESKTOP_UPDATE_PRIVATE_KEY"
PRIVATE_KEY_PATH_ENV = "LOOM_DESKTOP_UPDATE_PRIVATE_KEY_PATH"
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


def _read_private_key() -> str:
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


def _load_private_key(value: str) -> Ed25519PrivateKey:
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


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_payload(manifest: dict[str, object]) -> bytes:
    return json.dumps(
        manifest,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--installer", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    version = str(args.version).strip()
    if not VERSION_RE.fullmatch(version):
        raise ValueError(f"version must use MAJOR.MINOR.PATCH format: {version}")
    installer = os.path.abspath(args.installer)
    if not os.path.isfile(installer):
        raise ValueError(f"installer does not exist: {installer}")
    filename = os.path.basename(installer)
    expected_filename = f"LOOM-{version}-setup.exe"
    if filename != expected_filename:
        raise ValueError(f"installer filename must be {expected_filename}")

    manifest: dict[str, object] = {
        "schemaVersion": 1,
        "product": "LOOM",
        "channel": "stable",
        "version": version,
        "filename": filename,
        "size": os.path.getsize(installer),
        "sha256": _sha256(installer),
        "publishedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    private_key = _load_private_key(_read_private_key())
    manifest["signature"] = {
        "algorithm": "ed25519",
        "value": base64.b64encode(private_key.sign(_canonical_payload(manifest))).decode("ascii"),
    }

    output = os.path.abspath(args.output)
    os.makedirs(os.path.dirname(output), exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=os.path.basename(output) + ".",
        suffix=".tmp",
        dir=os.path.dirname(output),
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(manifest, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary, output)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)

    print(
        json.dumps(
            {
                "ok": True,
                "manifest": output,
                "version": version,
                "filename": filename,
                "sha256": manifest["sha256"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
