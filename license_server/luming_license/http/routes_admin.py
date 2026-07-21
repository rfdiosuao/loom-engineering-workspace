from __future__ import annotations

from typing import Any, Callable

from .routes_admin_business import (
    post_admin_api_activations_delete,
    post_admin_api_codes,
    post_admin_api_codes_bulk_update,
    post_admin_api_codes_clear,
    post_admin_api_codes_delete,
    post_admin_api_codes_hash,
    post_admin_api_codes_toggle,
    post_admin_api_codes_update,
    post_admin_api_plans_delete,
    post_admin_api_plans_update,
    post_admin_api_public_settings,
)
from .routes_admin_mutations import (
    post_admin_api_account_gateway,
    post_admin_api_accounts,
    post_admin_api_accounts_toggle,
    post_admin_api_beta_config,
    post_admin_api_codes_export,
    post_admin_api_codes_reveal,
    post_admin_api_invites,
    post_admin_api_invites_toggle,
    post_admin_api_templates,
    post_admin_api_templates_delete,
)
from .routes_admin_read import (
    get_admin_api_account_gateway,
    get_admin_api_accounts,
    get_admin_api_activations,
    get_admin_api_audit_logs,
    get_admin_api_beta_config,
    get_admin_api_codes,
    get_admin_api_codes_activations,
    get_admin_api_invites,
    get_admin_api_plans,
    get_admin_api_public_settings,
    get_admin_api_templates,
)


Route = Callable[[Any, Any], None]


GET_ROUTES: dict[str, Route] = {
    "/admin/api/beta/config": get_admin_api_beta_config,
    "/admin/api/templates": get_admin_api_templates,
    "/admin/api/accounts": get_admin_api_accounts,
    "/admin/api/invites": get_admin_api_invites,
    "/admin/api/codes": get_admin_api_codes,
    "/admin/api/activations": get_admin_api_activations,
    "/admin/api/plans": get_admin_api_plans,
    "/admin/api/account-gateway": get_admin_api_account_gateway,
    "/admin/api/codes/activations": get_admin_api_codes_activations,
    "/admin/api/audit-logs": get_admin_api_audit_logs,
    "/admin/api/public-settings": get_admin_api_public_settings,
}


POST_ROUTES: dict[str, Route] = {
    "/admin/api/beta/config": post_admin_api_beta_config,
    "/admin/api/templates": post_admin_api_templates,
    "/admin/api/templates/delete": post_admin_api_templates_delete,
    "/admin/api/accounts": post_admin_api_accounts,
    "/admin/api/accounts/toggle": post_admin_api_accounts_toggle,
    "/admin/api/invites": post_admin_api_invites,
    "/admin/api/invites/toggle": post_admin_api_invites_toggle,
    "/admin/api/account-gateway": post_admin_api_account_gateway,
    "/admin/api/codes/reveal": post_admin_api_codes_reveal,
    "/admin/api/codes/export": post_admin_api_codes_export,
    "/admin/api/codes": post_admin_api_codes,
    "/admin/api/codes/update": post_admin_api_codes_update,
    "/admin/api/codes/bulk-update": post_admin_api_codes_bulk_update,
    "/admin/api/plans/update": post_admin_api_plans_update,
    "/admin/api/plans/delete": post_admin_api_plans_delete,
    "/admin/api/codes/toggle": post_admin_api_codes_toggle,
    "/admin/api/codes/clear": post_admin_api_codes_clear,
    "/admin/api/codes/hash": post_admin_api_codes_hash,
    "/admin/api/codes/delete": post_admin_api_codes_delete,
    "/admin/api/activations/delete": post_admin_api_activations_delete,
    "/admin/api/public-settings": post_admin_api_public_settings,
}


__all__ = ["GET_ROUTES", "POST_ROUTES"]
