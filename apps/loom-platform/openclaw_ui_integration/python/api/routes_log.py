"""Service log FastAPI routes."""

from __future__ import annotations

import os

from fastapi import Request

DEFAULT_MAX_BYTES = 200_000
MAX_LOG_BYTES = 2_000_000


def _query_int(request: Request, key: str, default: int) -> int:
    try:
        return int(request.query_params.get(key, str(default)) or str(default))
    except ValueError:
        return default


def _query_bool(request: Request, key: str) -> bool:
    value = str(request.query_params.get(key, "") or "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _read_persisted_log(path: str, offset: int, max_bytes: int, tail: bool) -> tuple[str, int, bool, bool]:
    if not os.path.exists(path):
        return "", 0, False, False
    try:
        with open(path, "rb") as file:
            file.seek(0, os.SEEK_END)
            total = file.tell()
            reset = offset > total
            if tail or reset:
                start = max(0, total - max_bytes)
            else:
                start = offset
            file.seek(start)
            text = file.read(max_bytes).decode("utf-8", errors="replace")
            return text, total, start > 0, reset
    except OSError:
        return "", 0, False, False


def register_log_routes(app, ctx) -> None:
    @app.api_route("/api/log/get", methods=["GET", "POST"])
    async def log_get(request: Request):
        if error := ctx.auth_error(request):
            return error
        offset = max(0, _query_int(request, "offset", 0))
        max_bytes = max(1, min(_query_int(request, "maxBytes", DEFAULT_MAX_BYTES), MAX_LOG_BYTES))
        tail = _query_bool(request, "tail") or offset == 0

        with ctx.log_lock:
            text = "".join(ctx.log_buffer)
        total = len(text)
        truncated = False
        if not text:
            persisted_log = os.path.join(ctx.paths.data_dir, "logs", "bridge-service.log")
            text, total, truncated, reset = _read_persisted_log(persisted_log, offset, max_bytes, tail)
            offset = 0
        else:
            reset = offset > len(text)
            if reset:
                offset = 0

        if tail and len(text) > max_bytes:
            text = text[-max_bytes:]
            offset = 0
            truncated = True
        return ctx.fastapi_json({
            "log": text[offset:],
            "offset": total,
            "total": total,
            "reset": reset,
            "truncated": truncated,
        })

    @app.post("/api/log/clear")
    async def log_clear(request: Request):
        if error := ctx.auth_error(request):
            return error
        with ctx.log_lock:
            ctx.log_buffer.clear()
        persisted_log = os.path.join(ctx.paths.data_dir, "logs", "bridge-service.log")
        try:
            if os.path.exists(persisted_log):
                open(persisted_log, "w", encoding="utf-8").close()
        except Exception:
            pass
        return ctx.fastapi_json({"status": "cleared"})
