from __future__ import annotations

from typing import Any, Callable


Route = Callable[[Any, Any], None]


def get_root(handler, parsed):
    api = handler.facade
    handler.send_html(200, api.render_public_html())


def get_health(handler, parsed):
    api = handler.facade
    handler.send_json(200, {"ok": True, "time": api.utc_now()})


def get_api_beta_status(handler, parsed):
    api = handler.facade
    handler.send_json(200, {"ok": True, "data": api.beta_status_snapshot()})


def get_api_templates(handler, parsed):
    api = handler.facade
    kind = str(api.parse_qs(parsed.query).get("kind", [""])[0]).strip().lower()
    handler.send_json(
        200, {"ok": True, "data": api.list_templates(kind, only_enabled=True)}
    )


def get_public_key(handler, parsed):
    api = handler.facade
    handler.send_json(200, {"publicKey": api.public_key_b64()})


def get_admin(handler, parsed):
    api = handler.facade
    handler.send_html(200, api.ADMIN_HTML)


def get_logo_ico(handler, parsed):
    api = handler.facade
    handler.send_file(200, api.LOGO_FILE, "image/x-icon")


def get_api_client_config(handler, parsed):
    api = handler.facade
    handler.send_json(200, api.client_public_config())


def post_api_beta_claim(handler, parsed):
    api = handler.facade
    try:
        ip = handler.request_ip()
        api.rate_limit_consume(
            "beta-claim", ip, limit=20, window_seconds=3600, lockout_seconds=600
        )
        handler.send_json(200, {"ok": True, "data": api.beta_claim_code(ip)})
    except api.ActivationError as error:
        handler.send_json(error.status, {"ok": False, "error": str(error)})
    except Exception:
        handler.send_json(500, {"ok": False, "error": "Internal server error"})


def post_api_member_current(handler, parsed):
    api = handler.facade
    try:
        body = handler.read_json()
        license_data = api.find_member_license(body)
        if not license_data:
            handler.send_json(
                404,
                {
                    "error": "\u4f1a\u5458\u4f1a\u8bdd\u4e0d\u5b58\u5728\u6216\u5df2\u5931\u6548"
                },
            )
            return
        handler.send_json(200, api.member_response(license_data))
    except Exception as error:
        handler.send_json(500, {"error": f"server error: {error}"})


def post_api_member_usage(handler, parsed):
    api = handler.facade
    try:
        body = handler.read_json()
        license_data = api.find_member_license(body)
        if not license_data:
            handler.send_json(
                404,
                {
                    "error": "\u4f1a\u5458\u4f1a\u8bdd\u4e0d\u5b58\u5728\u6216\u5df2\u5931\u6548"
                },
            )
            return
        handler.send_json(
            200,
            {
                "usage": license_data.get("usage") or {},
                "quotas": license_data.get("quotas") or {},
            },
        )
    except Exception as error:
        handler.send_json(500, {"error": f"server error: {error}"})


def post_api_member_activate(handler, parsed):
    api = handler.facade
    try:
        body = handler.read_json()
        license_data = api.activate_code(body)
        handler.send_json(200, api.member_response(license_data))
    except api.ActivationError as error:
        handler.send_json(error.status, {"error": str(error), "code": error.code})
    except Exception as error:
        handler.send_json(500, {"error": f"server error: {error}"})


def post_activate(handler, parsed):
    api = handler.facade
    try:
        body = handler.read_json()
        license_data = api.activate_code(body)
        handler.send_json(200, {"license": license_data})
    except api.ActivationError as error:
        handler.send_json(error.status, {"error": str(error), "code": error.code})
    except Exception as error:
        handler.send_json(500, {"error": f"server error: {error}"})


def head_root(handler, parsed):
    api = handler.facade
    handler.send_html(200, api.render_public_html(), write_body=False)


def head_health(handler, parsed):
    api = handler.facade
    handler.send_json(200, {"ok": True, "time": api.utc_now()}, write_body=False)


def head_admin(handler, parsed):
    api = handler.facade
    handler.send_html(200, api.ADMIN_HTML, write_body=False)


def head_logo_ico(handler, parsed):
    api = handler.facade
    handler.send_file(200, api.LOGO_FILE, "image/x-icon", write_body=False)


def head_api_client_config(handler, parsed):
    api = handler.facade
    handler.send_json(200, api.client_public_config(), write_body=False)


def head_public_key(handler, parsed):
    api = handler.facade
    handler.send_json(200, {"publicKey": api.public_key_b64()}, write_body=False)


GET_ROUTES: dict[str, Route] = {
    "/": get_root,
    "/health": get_health,
    "/api/beta/status": get_api_beta_status,
    "/api/templates": get_api_templates,
    "/public-key": get_public_key,
    "/admin": get_admin,
    "/admin/": get_admin,
    "/logo.ico": get_logo_ico,
    "/admin/logo.ico": get_logo_ico,
    "/api/client/config": get_api_client_config,
    "/api/public/config": get_api_client_config,
    "/client/config": get_api_client_config,
}


POST_ROUTES: dict[str, Route] = {
    "/api/beta/claim": post_api_beta_claim,
    "/api/member/current": post_api_member_current,
    "/member/current": post_api_member_current,
    "/api/v1/member/current": post_api_member_current,
    "/api/member/refresh": post_api_member_current,
    "/member/refresh": post_api_member_current,
    "/api/v1/member/refresh": post_api_member_current,
    "/api/member/usage": post_api_member_usage,
    "/member/usage": post_api_member_usage,
    "/api/v1/member/usage": post_api_member_usage,
    "/api/member/activate": post_api_member_activate,
    "/member/activate": post_api_member_activate,
    "/api/v1/member/activate": post_api_member_activate,
    "/activate": post_activate,
}


HEAD_ROUTES: dict[str, Route] = {
    "/": head_root,
    "/health": head_health,
    "/admin": head_admin,
    "/admin/": head_admin,
    "/logo.ico": head_logo_ico,
    "/admin/logo.ico": head_logo_ico,
    "/api/client/config": head_api_client_config,
    "/api/public/config": head_api_client_config,
    "/client/config": head_api_client_config,
    "/public-key": head_public_key,
}
