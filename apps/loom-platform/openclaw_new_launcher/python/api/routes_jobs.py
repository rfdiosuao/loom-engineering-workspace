"""Long-running launcher job routes."""

from __future__ import annotations

from fastapi import Request


def register_job_routes(app, ctx) -> None:
    @app.api_route("/api/jobs/list", methods=["GET", "POST"])
    async def jobs_list(request: Request):
        if error := ctx.auth_error(request):
            return error
        try:
            limit = int(request.query_params.get("limit", "30") or "30")
        except ValueError:
            limit = 30
        return ctx.fastapi_json({"jobs": ctx.get_job_mgr().list(limit)})

    @app.api_route("/api/jobs/{job_id}", methods=["GET", "POST"])
    async def jobs_get(job_id: str, request: Request):
        if error := ctx.auth_error(request):
            return error
        job = ctx.get_job_mgr().get(job_id)
        if not job:
            return ctx.fastapi_json({"error": "任务不存在"}, 404)
        return ctx.fastapi_json({"job": job})
