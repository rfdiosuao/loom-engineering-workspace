from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON_DIR = ROOT / "python"
if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))

from core.matrix_soak import run_matrix_soak
from core.release_smoke import write_report


def main() -> int:
    parser = argparse.ArgumentParser(description="运行 LOOM 多机矩阵只读稳定性门禁。")
    parser.add_argument("--duration-sec", type=float, default=300)
    parser.add_argument("--interval-sec", type=float, default=5)
    parser.add_argument("--min-devices", type=int, default=2)
    parser.add_argument("--max-failure-rate", type=float, default=0.05)
    parser.add_argument("--max-p95-ms", type=float, default=30000)
    parser.add_argument("--timeout-sec", type=int, default=45)
    parser.add_argument("--iterations", type=int)
    parser.add_argument("--no-screens", action="store_true")
    parser.add_argument("--report", default=str(ROOT / "artifacts" / "matrix-soak.json"))
    args = parser.parse_args()

    session = _bridge_session()
    call = _http_call(session["url"], session.get("token", ""))
    report = run_matrix_soak(
        call,
        duration_sec=max(1, args.duration_sec),
        interval_sec=max(0, args.interval_sec),
        min_devices=max(1, args.min_devices),
        capture_screens=not args.no_screens,
        max_failure_rate=max(0.0, min(1.0, args.max_failure_rate)),
        max_p95_ms=max(1.0, args.max_p95_ms),
        timeout_sec=max(5, args.timeout_sec),
        max_iterations=max(1, args.iterations) if args.iterations is not None else None,
    )
    report_path = write_report(args.report, report)
    print(json.dumps({**report, "reportPath": report_path}, ensure_ascii=False))
    return 0 if report["passed"] else 1


def _bridge_session() -> dict[str, str]:
    url = os.environ.get("LOOM_BRIDGE_URL", "").strip().rstrip("/")
    token = os.environ.get("LOOM_BRIDGE_TOKEN", "").strip()
    candidates = []
    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    if local_app_data:
        candidates.append(Path(local_app_data) / "LOOM" / "bridge-session.json")
    candidates.extend([
        Path.home() / "Library" / "Application Support" / "LOOM" / "bridge-session.json",
        Path.home() / ".local" / "share" / "loom" / "bridge-session.json",
    ])
    if not url:
        for path in candidates:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if payload.get("schema") != "loom.bridge_session.v1":
                continue
            url = str(payload.get("url") or "").strip().rstrip("/")
            token = token or str(payload.get("token") or "").strip()
            if not url and isinstance(payload.get("port"), int):
                url = f"http://127.0.0.1:{payload['port']}"
            break
    if not url.startswith("http://127.0.0.1:"):
        raise SystemExit("未找到安全的本机 LOOM Bridge 会话。请先启动麓鸣，或设置 LOOM_BRIDGE_URL。")
    return {"url": url, "token": token}


def _http_call(base_url: str, token: str):
    def call(method: str, path: str, body: dict | None, timeout_sec: int) -> dict:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
        headers = {"Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        if token:
            headers["X-Bridge-Token"] = token
        request = urllib.request.Request(base_url + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=timeout_sec) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("Bridge 返回了无效 JSON。")
        return payload

    return call


if __name__ == "__main__":
    raise SystemExit(main())
