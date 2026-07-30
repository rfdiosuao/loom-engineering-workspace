"""Long-running launcher job routes."""

from __future__ import annotations

from fastapi import Request

from core.job_ownership import (
    current_account_job_identity,
    job_visible_to_account,
    public_job_snapshot,
)


def register_job_routes(app, ctx) -> None:
    @app.api_route("/api/jobs/list", methods=["GET", "POST"])
    async def jobs_list(request: Request):
        if error := ctx.auth_error(request):
            return error
        try:
            limit = int(request.query_params.get("limit", "30") or "30")
        except ValueError:
            limit = 30
        account_id, owner_binding = current_account_job_identity(ctx)
        visible_jobs = [
            public_job_snapshot(job)
            for job in ctx.get_job_mgr().list(limit)
            if job_visible_to_account(
                job,
                account_id=account_id,
                owner_binding=owner_binding,
            )
        ]
        return ctx.fastapi_json({"jobs": visible_jobs})

    @app.api_route("/api/jobs/{job_id}", methods=["GET", "POST"])
    async def jobs_get(job_id: str, request: Request):
        if error := ctx.auth_error(request):
            return error
        job = ctx.get_job_mgr().get(job_id)
        account_id, owner_binding = current_account_job_identity(ctx)
        if not job or not job_visible_to_account(
            job,
            account_id=account_id,
            owner_binding=owner_binding,
        ):
            return ctx.fastapi_json({"error": "任务不存在"}, 404)
        return ctx.fastapi_json({"job": public_job_snapshot(job)})
