"""FastAPI route registration for the launcher bridge."""

from __future__ import annotations

import traceback

from fastapi import Request

from api.routes_account import register_account_routes
from api.routes_components import register_component_routes
from api.routes_config import register_config_routes
from api.routes_desktop_agent import register_desktop_agent_routes
from api.routes_diagnostics import register_diagnostics_routes
from api.routes_license import register_license_routes
from api.routes_member import register_member_routes
from api.routes_jobs import register_job_routes
from api.routes_log import register_log_routes
from api.routes_media import register_media_routes
from api.routes_phone_automation import register_phone_automation_routes
from api.routes_process import register_process_routes
from api.routes_skills import register_skills_routes
from api.routes_system import register_system_routes
from api.routes_theme import register_theme_routes
from api.routes_update import register_update_routes


def register_fastapi_routes(app, ctx) -> None:
    """Register all native FastAPI endpoints."""

    @app.exception_handler(Exception)
    async def unhandled_exception(request: Request, exc: Exception):
        ctx.append_log(f"[Bridge Error] {request.url.path}: {exc}\n{traceback.format_exc()}\n")
        return ctx.fastapi_json({"error": str(exc)}, 500)

    register_system_routes(app, ctx)
    register_process_routes(app, ctx)
    register_log_routes(app, ctx)
    register_license_routes(app, ctx)
    register_member_routes(app, ctx)
    register_account_routes(app, ctx)
    register_component_routes(app, ctx)
    register_job_routes(app, ctx)
    register_media_routes(app, ctx)
    register_phone_automation_routes(app, ctx)
    register_theme_routes(app, ctx)
    register_config_routes(app, ctx)
    register_desktop_agent_routes(app, ctx)
    register_diagnostics_routes(app, ctx)
    register_update_routes(app, ctx)
    register_skills_routes(app, ctx)

    @app.api_route("/{path:path}", methods=["GET", "POST", "PUT"])
    async def route_all(path: str, _request: Request):
        return ctx.fastapi_json({"error": f"Not found: /{path}"}, 404)
