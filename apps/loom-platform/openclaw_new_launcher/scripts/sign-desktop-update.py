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

from desktop_update_signing import (
    load_private_key,
    load_public_key,
    read_private_key,
    read_public_key,
)


VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


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
    parser.add_argument("--product", default="LOOM")
    parser.add_argument("--channel", default="stable")
    parser.add_argument("--channel-id", default="loom-stable")
    parser.add_argument("--file-prefix", default="LOOM")
    parser.add_argument("--download-url", default="")
    parser.add_argument("--public-key", required=True)
    args = parser.parse_args()

    version = str(args.version).strip()
    if not VERSION_RE.fullmatch(version):
        raise ValueError(f"version must use MAJOR.MINOR.PATCH format: {version}")
    installer = os.path.abspath(args.installer)
    if not os.path.isfile(installer):
        raise ValueError(f"installer does not exist: {installer}")
    filename = os.path.basename(installer)
    product = str(args.product).strip()
    channel = str(args.channel).strip()
    channel_id = str(args.channel_id).strip()
    file_prefix = str(args.file_prefix).strip()
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9-]{2,63}", file_prefix):
        raise ValueError(f"file prefix is invalid: {file_prefix}")
    if not product or not channel or not channel_id:
        raise ValueError("product, channel, and channel-id are required")
    expected_filename = f"{file_prefix}-{version}-setup.exe"
    if filename != expected_filename:
        raise ValueError(f"installer filename must be {expected_filename}")

    manifest: dict[str, object] = {
        "schemaVersion": 1,
        "product": product,
        "channel": channel,
        "channelId": channel_id,
        "version": version,
        "filename": filename,
        "size": os.path.getsize(installer),
        "sha256": _sha256(installer),
        "publishedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    download_url = str(args.download_url).strip()
    if download_url:
        if not download_url.startswith("https://"):
            raise ValueError("download-url must use HTTPS")
        manifest["downloadUrl"] = download_url
    private_key = load_private_key(read_private_key())
    expected_public_key = load_public_key(read_public_key(args.public_key))
    actual_public_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    expected_public_bytes = expected_public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    if actual_public_bytes != expected_public_bytes:
        raise ValueError(
            "desktop update private key does not match the public key bundled with the client"
        )
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
