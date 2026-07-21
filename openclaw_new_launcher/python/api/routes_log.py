"""Service log FastAPI routes."""

from __future__ import annotations

import os

from fastapi import Request
from core.log_files import clear_text_log, read_text_tail


def register_log_routes(app, ctx) -> None:
    @app.api_route("/api/log/get", methods=["GET", "POST"])
    async def log_get(request: Request):
        if error := ctx.auth_error(request):
            return error
        try:
            offset = max(0, int(request.query_params.get("offset", "0") or "0"))
        except ValueError:
            offset = 0
        requested_generation = str(request.query_params.get("generation", "") or "")[:128]

        with ctx.log_lock:
            text = "".join(ctx.log_buffer)
        encoded = text.encode("utf-8")
        tail = {
            "text": text,
            "totalBytes": len(encoded),
            "windowStartBytes": 0,
            "windowBytes": len(encoded),
            "omittedBytes": 0,
            "truncated": False,
        }
        persisted_log = os.path.join(ctx.paths.data_dir, "logs", "bridge-service.log")
        persisted_tail = read_text_tail(persisted_log, max_bytes=512 * 1024)
        tail["generation"] = persisted_tail["generation"]
        if persisted_tail["exists"]:
            tail = persisted_tail
            text = str(tail["text"])

        window = text.encode("utf-8")
        total_bytes = int(tail["totalBytes"])
        window_start_bytes = int(tail["windowStartBytes"])
        generation = str(tail["generation"])
        generation_mismatch = bool(requested_generation and requested_generation != generation)
        reset = (
            generation_mismatch
            or offset > total_bytes
            or (offset > 0 and offset < window_start_bytes)
        )
        if offset == 0 or reset:
            delta = window
        else:
            relative_offset = max(0, min(len(window), offset - window_start_bytes))
            delta = window[relative_offset:]
        return ctx.fastapi_json({
            "log": delta.decode("utf-8", errors="ignore"),
            "offset": total_bytes,
            "total": total_bytes,
            "reset": reset,
            "generation": generation,
            "totalBytes": total_bytes,
            "windowStartBytes": window_start_bytes,
            "windowBytes": tail["windowBytes"],
            "omittedBytes": tail["omittedBytes"],
            "truncated": tail["truncated"],
        })

    @app.post("/api/log/clear")
    async def log_clear(request: Request):
        if error := ctx.auth_error(request):
            return error
        with ctx.log_lock:
            ctx.log_buffer.clear()
        persisted_log = os.path.join(ctx.paths.data_dir, "logs", "bridge-service.log")
        result = clear_text_log(persisted_log)
        return ctx.fastapi_json({
            "status": "cleared" if result["cleared"] else "clear_failed",
            "generation": result["generation"],
        })
