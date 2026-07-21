"""Read-only admin HTTP route implementations."""

from __future__ import annotations


def get_admin_api_beta_config(handler, parsed):
    api = handler.facade
    if not handler.require_admin():
        return
    handler.send_json(200, {"ok": True, "data": api.get_beta_config()})


def get_admin_api_templates(handler, parsed):
    api = handler.facade
    if not handler.require_admin():
        return
    kind = str(api.parse_qs(parsed.query).get("kind", [""])[0]).strip().lower()
    handler.send_json(200, {"ok": True, "data": api.list_templates(kind)})


def get_admin_api_accounts(handler, parsed):
    api = handler.facade
    if not handler.require_admin(api.ACCOUNT_ROLE_SUPER_ADMIN):
        return
    handler.send_json(200, {"accounts": api.list_account_rows()})


def get_admin_api_invites(handler, parsed):
    api = handler.facade
    if not handler.require_admin(api.ACCOUNT_ROLE_SUPER_ADMIN):
        return
    handler.send_json(200, {"invites": api.list_invite_rows()})


def get_admin_api_codes(handler, parsed):
    api = handler.facade
    if not handler.require_admin():
        return
    handler.send_json(200, {"codes": api.get_code_rows(handler.admin_context())})


def get_admin_api_activations(handler, parsed):
    api = handler.facade
    if not handler.require_admin():
        return
    handler.send_json(
        200, {"activations": api.get_all_activation_rows(handler.admin_context())}
    )


def get_admin_api_plans(handler, parsed):
    api = handler.facade
    if not handler.require_admin():
        return
    handler.send_json(200, {"plans": api.get_plan_rows(include_disabled=True)})


def get_admin_api_account_gateway(handler, parsed):
    api = handler.facade
    if not handler.require_admin():
        return
    account_id = api.context_account_id(handler.admin_context())
    handler.send_json(
        200,
        {
            "settings": api.get_account_gateway_settings(
                account_id, include_secrets=False
            )
        },
    )


def get_admin_api_codes_activations(handler, parsed):
    api = handler.facade
    if not handler.require_admin():
        return
    query = api.parse_qs(parsed.query)
    code_hash_value = str((query.get("codeHash") or [""])[0]).strip()
    try:
        handler.send_json(
            200,
            {
                "activations": api.get_activation_rows(
                    code_hash_value, handler.admin_context()
                )
            },
        )
    except api.ActivationError as error:
        handler.send_json(error.status, {"error": str(error)})


def get_admin_api_audit_logs(handler, parsed):
    api = handler.facade
    if not handler.require_admin(api.ACCOUNT_ROLE_SUPER_ADMIN):
        return
    query = api.parse_qs(parsed.query)
    limit = int((query.get("limit") or ["100"])[0] or "100")
    handler.send_json(200, {"logs": api.get_audit_rows(limit)})


def get_admin_api_public_settings(handler, parsed):
    api = handler.facade
    if not handler.require_admin(api.ACCOUNT_ROLE_SUPER_ADMIN):
        return
    handler.send_json(
        200,
        {"settings": api.public_settings(), "clientConfig": api.client_public_config()},
    )


__all__ = [
    "get_admin_api_beta_config",
    "get_admin_api_templates",
    "get_admin_api_accounts",
    "get_admin_api_invites",
    "get_admin_api_codes",
    "get_admin_api_activations",
    "get_admin_api_plans",
    "get_admin_api_account_gateway",
    "get_admin_api_codes_activations",
    "get_admin_api_audit_logs",
    "get_admin_api_public_settings",
]
