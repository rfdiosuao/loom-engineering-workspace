#!/usr/bin/env python3
"""Create a byte-for-byte reproducible stored ZIP archive."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from zipfile import ZIP_STORED, ZipFile, ZipInfo


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--entries", required=True)
    parser.add_argument("--output", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    entries = json.loads(Path(args.entries).read_text(encoding="utf-8"))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    with ZipFile(output, mode="x", compression=ZIP_STORED, allowZip64=True) as archive:
        archive.comment = b""
        for item in sorted(entries, key=lambda value: str(value["entry"]).encode("utf-8")):
            timestamp = datetime.strptime(item["timestamp"], "%Y-%m-%dT%H:%M:%S")
            info = ZipInfo(str(item["entry"]), timestamp.timetuple()[:6])
            info.compress_type = ZIP_STORED
            info.create_system = 0
            info.create_version = 20
            info.extract_version = 20
            info.external_attr = 0
            info.internal_attr = 0
            info.extra = b""
            info.comment = b""
            archive.writestr(info, Path(item["source"]).read_bytes(), compress_type=ZIP_STORED)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
