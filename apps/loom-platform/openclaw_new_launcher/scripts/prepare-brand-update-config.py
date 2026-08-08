"""Attach the public Ed25519 update key to a compiled OEM update config."""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import tempfile

from cryptography.hazmat.primitives import serialization

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from desktop_update_signing import load_private_key, read_private_key


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    args = parser.parse_args()

    config_path = os.path.abspath(args.config)
    with open(config_path, "r", encoding="utf-8-sig") as handle:
        config = json.load(handle)
    if not isinstance(config, dict):
        raise ValueError("desktop update brand config must be a JSON object")

    private_key = load_private_key(read_private_key())
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    config["publicKey"] = base64.b64encode(public_key).decode("ascii")

    descriptor, temporary = tempfile.mkstemp(
        prefix=os.path.basename(config_path) + ".",
        suffix=".tmp",
        dir=os.path.dirname(config_path),
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(config, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary, config_path)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)

    print(json.dumps({"ok": True, "config": config_path}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
