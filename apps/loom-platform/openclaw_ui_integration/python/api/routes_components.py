"""Installable component routes for the launcher bridge."""

from __future__ import annotations

from fastapi import Request

from core.component_catalog import ComponentCatalog, default_component_state_path, default_manifest_path
from core.component_installer import ComponentInstallError, ComponentInstaller
from core.component_state import ComponentStateStore
from core.release_manifest import load_release_manifest_file


RUNNING_JOB_STATUSES = {"queued", "running"}


def register_component_routes(app, ctx) -> None:
    @app.api_route("/api/components/status", methods=["GET", "POST"])
    async def components_status(request: Request):
        if error := ctx.auth_error(request):
            return error
        return ctx.fastapi_json(_component_catalog(ctx).status())

    @app.post("/api/components/install")
    async def components_install(request: Request):
        if error := ctx.auth_error(request):
            return error
        body = await ctx.body(request)
        component_id = str(body.get("componentId") or body.get("id") or "").strip()
        if not component_id:
            return ctx.fastapi_json({"error": "componentId is required"}, 400)

        manifest_path = default_manifest_path(ctx.paths.base_path)
        state_store = _component_state_store(ctx)
        existing_state = state_store.load().get(component_id)
        if existing_state and existing_state.job_id:
            existing_job = ctx.get_job_mgr().get(existing_state.job_id)
            if existing_job and str(existing_job.get("status") or "").lower() in RUNNING_JOB_STATUSES:
                return ctx.fastapi_json({
                    "jobId": existing_state.job_id,
                    "job": existing_job,
                    "state": existing_state.to_json(),
                    "catalog": _component_catalog(ctx).status(),
                }, 202)

        try:
            manifest = load_release_manifest_file(manifest_path)
            component = manifest.component_by_id(component_id)
            if component is None:
                return ctx.fastapi_json({"error": f"Unknown component: {component_id}"}, 404)

            state_store.mark(component.component_id, "resolving_manifest", version=component.version)
            job_mgr = ctx.get_job_mgr()

            def run(job_id: str) -> dict:
                def on_progress(message: str, tone: str = "neutral") -> None:
                    job_mgr.progress(job_id, message, tone, componentId=component.component_id)
                    ctx.append_log(f"[Components] {component.component_id}: {message}\n")

                installer = _component_installer(ctx)
                state = installer.install(component, job_id=job_id, on_progress=on_progress)
                return {
                    "success": True,
                    "state": state.to_json(),
                    "catalog": _component_catalog(ctx).status(),
                }

            job = job_mgr.submit_progress("component.install", f"Install {component.name}", run)
            current_state = state_store.load().get(component.component_id)
            if current_state and current_state.status == "resolving_manifest":
                current_state = state_store.mark(component.component_id, "resolving_manifest", version=component.version, job_id=str(job.get("id") or ""))
            return ctx.fastapi_json({
                "jobId": job.get("id"),
                "job": job,
                "state": current_state.to_json() if current_state else None,
                "catalog": _component_catalog(ctx).status(),
            }, 202)
        except ComponentInstallError as exc:
            return ctx.fastapi_json({"error": str(exc), "catalog": _component_catalog(ctx).status()}, 500)
        except Exception as exc:
            ctx.append_log(f"[Components] install failed: {exc}\n")
            return ctx.fastapi_json({"error": str(exc)}, 500)

    @app.post("/api/components/rollback")
    async def components_rollback(request: Request):
        if error := ctx.auth_error(request):
            return error
        body = await ctx.body(request)
        component_id = str(body.get("componentId") or body.get("id") or "").strip()
        if not component_id:
            return ctx.fastapi_json({"error": "componentId is required"}, 400)

        try:
            state = _component_installer(ctx).rollback(component_id)
            return ctx.fastapi_json({
                "state": state.to_json(),
                "catalog": _component_catalog(ctx).status(),
            })
        except ComponentInstallError as exc:
            return ctx.fastapi_json({"error": str(exc), "catalog": _component_catalog(ctx).status()}, 500)


def _component_catalog(ctx) -> ComponentCatalog:
    return ComponentCatalog(
        manifest_path=default_manifest_path(ctx.paths.base_path),
        state_store=_component_state_store(ctx),
    )


def _component_installer(ctx) -> ComponentInstaller:
    return ComponentInstaller(
        base_path=ctx.paths.base_path,
        state_store=_component_state_store(ctx),
    )


def _component_state_store(ctx) -> ComponentStateStore:
    return ComponentStateStore(default_component_state_path(ctx.paths.base_path))
