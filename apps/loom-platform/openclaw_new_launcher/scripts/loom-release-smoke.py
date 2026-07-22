from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON_DIR = ROOT / "python"
if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))

from core.release_smoke import run_release_smoke, write_report


def main() -> int:
    parser = argparse.ArgumentParser(description="运行 LOOM 发布前冒烟门禁。")
    parser.add_argument("--cli", default=str(PYTHON_DIR / "loom_cli.py"))
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--report", default=str(ROOT / "artifacts" / "release-smoke.json"))
    parser.add_argument("--require-provider", action="store_true")
    parser.add_argument("--require-matrix", action="store_true")
    parser.add_argument("--require-phone-count", type=int, default=0)
    parser.add_argument("--timeout-sec", type=int, default=45)
    args = parser.parse_args()

    report = run_release_smoke(
        args.cli,
        python_executable=args.python,
        require_provider=args.require_provider,
        require_matrix=args.require_matrix,
        require_phone_count=max(0, args.require_phone_count),
        timeout_sec=max(5, args.timeout_sec),
    )
    report_path = write_report(args.report, report)
    print(json.dumps({**report, "reportPath": report_path}, ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
