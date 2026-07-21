"""Skill management FastAPI routes."""

from __future__ import annotations

from fastapi import Request

from services.skills import SkillError


def register_skills_routes(app, ctx) -> None:
    @app.api_route("/api/skills/list", methods=["GET", "POST"])
    async def skills_list(request: Request):
        if error := ctx.auth_error(request):
            return error
        return ctx.fastapi_json(ctx.get_skill_svc().list_skills())

    @app.post("/api/skills/install_zip")
    async def skills_install_zip(request: Request):
        if error := ctx.auth_error(request):
            return error
        body = await ctx.body(request)
        filename = body.get("filename", "skill.zip")
        data = body.get("data", "")
        if not data:
            return ctx.fastapi_json({"error": "Skill 包数据不能为空"}, 400)
        try:
            return ctx.fastapi_json(ctx.get_skill_svc().install_zip(filename, data))
        except SkillError as exc:
            return ctx.fastapi_json({"error": str(exc)}, 400)

    @app.post("/api/skills/enable")
    async def skills_enable(request: Request):
        if error := ctx.auth_error(request):
            return error
        body = await ctx.body(request)
        skill_id = body.get("id", "")
        if not skill_id:
            return ctx.fastapi_json({"error": "Skill ID 不能为空"}, 400)
        try:
            return ctx.fastapi_json(ctx.get_skill_svc().set_enabled(skill_id, bool(body.get("enabled"))))
        except SkillError as exc:
            return ctx.fastapi_json({"error": str(exc)}, 400)

    @app.post("/api/skills/uninstall")
    async def skills_uninstall(request: Request):
        if error := ctx.auth_error(request):
            return error
        body = await ctx.body(request)
        skill_id = body.get("id", "")
        if not skill_id:
            return ctx.fastapi_json({"error": "Skill ID 不能为空"}, 400)
        try:
            return ctx.fastapi_json(ctx.get_skill_svc().uninstall(skill_id))
        except SkillError as exc:
            return ctx.fastapi_json({"error": str(exc)}, 400)

    @app.post("/api/skills/readme")
    async def skills_readme(request: Request):
        if error := ctx.auth_error(request):
            return error
        body = await ctx.body(request)
        skill_id = body.get("id", "")
        if not skill_id:
            return ctx.fastapi_json({"error": "Skill ID 不能为空"}, 400)
        try:
            return ctx.fastapi_json(ctx.get_skill_svc().read_readme(skill_id))
        except SkillError as exc:
            return ctx.fastapi_json({"error": str(exc)}, 400)

    @app.api_route("/api/skills/paths", methods=["GET", "POST"])
    async def skills_paths(request: Request):
        if error := ctx.auth_error(request):
            return error
        return ctx.fastapi_json(ctx.get_skill_svc().paths_payload())
