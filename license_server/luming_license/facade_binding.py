from __future__ import annotations

import importlib.util
import itertools
import sys
from dataclasses import dataclass
from pathlib import Path
from types import FunctionType, ModuleType
from typing import Any, Callable

from . import facade_business, facade_identity, facade_relay
from .cli import bind_cli


# These tables are explicit because the facade's patch graph is a compatibility API.
# Adding an adapter or mutable dependency requires a conscious binding decision here.
_VALUE_NAMES = (
    "html_lib",
    "json",
    "logging",
    "os",
    "secrets",
    "sqlite3",
    "sys",
    "threading",
    "time",
    "datetime",
    "timedelta",
    "timezone",
    "ThreadingHTTPServer",
    "Any",
    "parse_qs",
    "urlparse",
    "audit",
    "db",
    "security",
    "license_serialization",
    "signing",
    "CONFIG_DEFAULT_ADMIN_CORS_ORIGINS",
    "Settings",
    "bounded_int_env",
    "ActivationError",
    "accounts",
    "activations",
    "licenses",
    "plans",
    "relay",
    "sessions",
    "templates",
    "HttpHandler",
    "add_days_date",
    "add_days_iso",
    "now_ms",
    "utc_filename_stamp",
    "utc_now",
    "LOGGER",
    "SETTINGS",
    "APPLICATION_DIR",
    "BASE_DIR",
    "DB_PATH",
    "BACKUP_DIR",
    "PRIVATE_KEY_FILE",
    "ADMIN_TOKEN_FILE",
    "LOGO_FILE",
    "HOST",
    "PORT",
    "COMMERCIAL_FEATURES",
    "DEFAULT_FEATURES",
    "VIP_DEFAULT_FEATURES",
    "_PLAN_DEFAULTS",
    "PUBLIC_COMMERCIAL_URL",
    "PUBLIC_SUPPORT_URL",
    "DEFAULT_GATEWAY_BASE_URL",
    "DEFAULT_GATEWAY_IMAGE_BASE_URL",
    "DEFAULT_GATEWAY_VIDEO_BASE_URL",
    "DEFAULT_GATEWAY_TOKEN",
    "DEFAULT_GATEWAY_IMAGE_TOKEN",
    "DEFAULT_GATEWAY_VIDEO_TOKEN",
    "DEFAULT_GATEWAY_DEFAULT_MODEL",
    "DEFAULT_GATEWAY_IMAGE_MODEL",
    "DEFAULT_GATEWAY_VIDEO_MODEL",
    "DEFAULT_GATEWAY_MODELS",
    "DEFAULT_PUBLIC_SETTINGS",
    "DB_DEFAULTS",
    "canonical",
    "parse_json_object",
    "load_json_value",
    "normalize_string",
    "clamp_int",
    "ClosingConnection",
    "ensure_column",
    "AUDIT_TRANSACTION_LOCAL",
    "PUBLISH_RELAY_TOKEN",
    "PUBLISH_RELAY_DEFAULT_LEASE_MS",
    "PUBLISH_RELAY_DEFAULT_WAIT_MS",
    "PUBLISH_RELAY_MAX_ATTEMPTS",
    "PUBLISH_RELAY_BACKOFF_MS",
    "PUBLISH_RELAY_MAX_BACKOFF_MS",
    "MAX_BULK_CODE_HASHES",
    "MAX_CODE_SECRET_EXPORT",
    "LOGIN_RATE_LIMIT_ATTEMPTS",
    "LOGIN_RATE_LIMIT_WINDOW_SECONDS",
    "LOGIN_RATE_LIMIT_LOCKOUT_SECONDS",
    "REGISTER_RATE_LIMIT_ATTEMPTS",
    "REGISTER_RATE_LIMIT_WINDOW_SECONDS",
    "REGISTER_RATE_LIMIT_LOCKOUT_SECONDS",
    "DEFAULT_ADMIN_CORS_ORIGINS",
    "ADMIN_CORS_ALLOWED_ORIGINS",
    "ADMIN_SESSION_COOKIE_NAME",
    "RATE_LIMIT_STATE",
    "RATE_LIMIT_LOCK",
    "RATE_LIMITS",
    "ADMIN_HTML_FALLBACK",
    "PUBLIC_HTML_FALLBACK",
    "ADMIN_HTML",
    "PUBLIC_HTML",
    "ADMIN_SESSION_TTL_DAYS",
    "ACCOUNT_ROLE_MERCHANT",
    "ACCOUNT_ROLE_SUPER_ADMIN",
    "ACCOUNT_STATUS_ACTIVE",
    "ACCOUNT_STATUS_DISABLED",
    "INVITE_CODE_STATUS_ACTIVE",
    "INVITE_CODE_STATUS_DISABLED",
    "INVITE_CODE_STATUS_USED",
    "INVITE_CODE_STATUS_EXPIRED",
    "INVITE_CODE_ALPHABET",
)

_CLASS_NAMES = ("_AuditTransactionConnection", "_AuditTransaction")

_CORE_FUNCTION_NAMES = (
    "_active_audit_transaction",
    "_begin_audit_transaction",
    "_finish_audit_transaction",
    "_finalize_audit_response",
    "_run_request_transaction",
    "_commit_audit_connection",
    "_commit_registration_normalization",
    "parse_features",
    "parse_models",
    "parse_optional_models",
    "load_private_key",
    "public_key_b64",
    "sign_license",
    "connect",
    "init_db",
    "seed_default_settings",
    "seed_default_plans",
    "make_db_backup",
    "make_audited_backup",
    "load_admin_html",
    "load_public_html",
    "render_public_html",
    "code_hash",
    "load_admin_token",
)

_IDENTITY_FUNCTION_NAMES = (
    "normalize_username",
    "normalize_account_role",
    "normalize_account_status",
    "role_rank",
    "password_hash",
    "verify_password",
    "admin_session_token_hash",
    "generate_admin_session_token",
    "normalize_code_expires",
    "require_confirmation",
    "extract_bearer_token",
    "extract_admin_session_cookie",
    "request_admin_token",
    "admin_session_cookie",
    "account_row_public",
    "get_account_by_username",
    "get_account_by_id",
    "list_account_rows",
    "account_summary_row",
    "normalize_invite_code",
    "generate_invite_code",
    "invite_row_public",
    "count_invites",
    "list_invite_rows",
    "get_invite_by_code",
    "_create_account_record_on_connection",
    "create_invite_record",
    "toggle_invite_record",
    "register_account_with_invite",
    "_audit_registered_account",
    "create_account_record",
    "update_account_record",
    "admin_context_from_row",
    "load_admin_context_from_session",
    "load_legacy_admin_context",
    "create_admin_session",
    "update_account_last_login",
    "revoke_admin_session",
    "count_accounts",
    "count_active_super_admins",
    "auth_status_snapshot",
    "_rate_limit_state",
    "rate_limit_storage_key",
    "rate_limit_check",
    "rate_limit_record_failure",
    "rate_limit_clear",
    "rate_limit_consume",
    "admin_cors_origin_allowed",
    "is_admin_request_path",
    "normalize_code_hashes",
)

_RELAY_FUNCTION_NAMES = (
    "publish_relay_backoff_ms",
    "publish_relay_packet_id",
    "publish_relay_lease_id",
    "publish_relay_auth_required",
    "publish_relay_configured",
    "publish_relay_request_token",
    "publish_relay_token_valid",
    "publish_relay_record_from_row",
    "publish_relay_fetch",
    "publish_relay_enqueue",
    "publish_relay_claim",
    "publish_relay_wait_for_packet",
    "publish_relay_complete",
    "publish_relay_status",
    "publish_relay_stats",
    "make_code",
    "is_super_admin_context",
    "context_account_id",
    "code_row_owned_by_context",
    "create_code_records",
)

_BUSINESS_FUNCTION_NAMES = (
    "beta_today",
    "get_beta_config",
    "set_beta_config",
    "beta_owner_account_id",
    "beta_claims_count_today",
    "beta_status_snapshot",
    "beta_claim_code",
    "template_public",
    "seed_default_templates",
    "list_templates",
    "save_template",
    "delete_template",
    "update_code_record",
    "bulk_update_code_records",
    "normalize_plan_key",
    "plan_row_public",
    "get_plan_rows",
    "get_plan_row",
    "public_settings",
    "client_public_config",
    "validate_gateway_url",
    "update_public_settings",
    "default_account_gateway_settings",
    "account_gateway_settings_public",
    "get_account_gateway_settings",
    "upsert_account_gateway_settings",
    "has_explicit_gateway_value",
    "apply_account_gateway_defaults",
    "upsert_plan_record",
    "disable_plan_record",
    "apply_plan_template",
    "audit_json",
    "masked_code_label",
    "audit_public_value",
    "add_audit_log",
    "masked_secret",
    "code_row_snapshot",
    "get_code_snapshot",
    "get_code_snapshots",
    "get_inventory_snapshot",
    "get_audit_rows",
    "get_code_rows",
    "get_code_secret_rows",
    "activation_row_public",
    "get_activation_rows",
    "get_all_activation_rows",
    "get_activation_snapshot",
    "apply_member_fields",
    "build_signed_license",
    "member_response",
    "find_member_license",
    "activate_code",
)

_STATIC_FUNCTION_GROUPS = (
    (facade_identity, _IDENTITY_FUNCTION_NAMES),
    (facade_relay, _RELAY_FUNCTION_NAMES),
    (facade_business, _BUSINESS_FUNCTION_NAMES),
)

_INSTANCE_IDS = itertools.count()


@dataclass(frozen=True)
class FacadeBindings:
    Handler: type
    ActivationError: type[Exception]
    connect: Callable[..., Any]
    init_db: Callable[..., Any]
    make_db_backup: Callable[..., Any]
    create_account_record: Callable[..., Any]
    create_admin_session: Callable[..., Any]
    create_code_records: Callable[..., Any]
    get_code_rows: Callable[..., Any]
    get_code_secret_rows: Callable[..., Any]
    get_activation_rows: Callable[..., Any]
    get_plan_rows: Callable[..., Any]
    client_public_config: Callable[..., Any]
    update_public_settings: Callable[..., Any]
    activate_code: Callable[..., Any]
    find_member_license: Callable[..., Any]
    publish_relay_enqueue: Callable[..., Any]
    publish_relay_claim: Callable[..., Any]
    publish_relay_complete: Callable[..., Any]
    publish_relay_status: Callable[..., Any]
    serve: Callable[..., Any]
    create_codes: Callable[..., Any]
    list_codes: Callable[..., Any]
    public_key: Callable[..., Any]
    build_parser: Callable[..., Any]
    main: Callable[..., Any]


def _load_core_blueprint() -> ModuleType:
    name = f"luming_license._facade_core_instance_{next(_INSTANCE_IDS)}"
    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).with_name("facade_core.py")
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load the license server facade blueprint")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(name, None)
    return module


def _bind_function(function: FunctionType, namespace: dict[str, Any]) -> FunctionType:
    if function.__closure__:
        raise RuntimeError(
            f"Facade function {function.__name__} unexpectedly closes over shared state"
        )
    bound = FunctionType(
        function.__code__, namespace, function.__name__, function.__defaults__
    )
    bound.__kwdefaults__ = (
        None if function.__kwdefaults__ is None else dict(function.__kwdefaults__)
    )
    bound.__annotations__ = dict(function.__annotations__)
    bound.__dict__.update(function.__dict__)
    bound.__doc__ = function.__doc__
    bound.__module__ = str(namespace["__name__"])
    bound.__qualname__ = function.__qualname__
    return bound


def _bind_class(source: type, namespace: dict[str, Any]) -> type:
    attributes: dict[str, Any] = {
        "__module__": namespace["__name__"],
        "__doc__": source.__doc__,
    }
    for name, value in source.__dict__.items():
        if name in {"__dict__", "__doc__", "__module__", "__weakref__"}:
            continue
        if isinstance(value, FunctionType):
            attributes[name] = _bind_function(value, namespace)
        elif isinstance(value, staticmethod):
            attributes[name] = staticmethod(_bind_function(value.__func__, namespace))
        elif isinstance(value, classmethod):
            attributes[name] = classmethod(_bind_function(value.__func__, namespace))
        else:
            attributes[name] = value
    return type(source.__name__, source.__bases__, attributes)


def bind_facade(target: ModuleType) -> FacadeBindings:
    """Install one isolated, late-bound compatibility graph on ``target``."""
    core_blueprint = _load_core_blueprint()
    namespace = target.__dict__

    # Assigning only audited names keeps the facade explicit while function globals point
    # at the target module, which is what makes server-level monkeypatches visible.
    for name in _VALUE_NAMES:
        namespace[name] = getattr(core_blueprint, name)
    for name in _CLASS_NAMES:
        namespace[name] = _bind_class(getattr(core_blueprint, name), namespace)
    for name in _CORE_FUNCTION_NAMES:
        namespace[name] = _bind_function(getattr(core_blueprint, name), namespace)
    for blueprint, function_names in _STATIC_FUNCTION_GROUPS:
        for name in function_names:
            namespace[name] = _bind_function(getattr(blueprint, name), namespace)

    handler = type(
        "Handler",
        (namespace["HttpHandler"],),
        {"__module__": target.__name__, "facade": target},
    )
    namespace["Handler"] = handler

    cli = bind_cli(target)
    namespace["serve"] = cli.serve
    namespace["create_codes"] = cli.create_codes
    namespace["list_codes"] = cli.list_codes
    namespace["public_key"] = cli.public_key
    namespace["build_parser"] = cli.build_parser
    namespace["main"] = cli.main

    return FacadeBindings(
        Handler=handler,
        ActivationError=namespace["ActivationError"],
        connect=namespace["connect"],
        init_db=namespace["init_db"],
        make_db_backup=namespace["make_db_backup"],
        create_account_record=namespace["create_account_record"],
        create_admin_session=namespace["create_admin_session"],
        create_code_records=namespace["create_code_records"],
        get_code_rows=namespace["get_code_rows"],
        get_code_secret_rows=namespace["get_code_secret_rows"],
        get_activation_rows=namespace["get_activation_rows"],
        get_plan_rows=namespace["get_plan_rows"],
        client_public_config=namespace["client_public_config"],
        update_public_settings=namespace["update_public_settings"],
        activate_code=namespace["activate_code"],
        find_member_license=namespace["find_member_license"],
        publish_relay_enqueue=namespace["publish_relay_enqueue"],
        publish_relay_claim=namespace["publish_relay_claim"],
        publish_relay_complete=namespace["publish_relay_complete"],
        publish_relay_status=namespace["publish_relay_status"],
        serve=cli.serve,
        create_codes=cli.create_codes,
        list_codes=cli.list_codes,
        public_key=cli.public_key,
        build_parser=cli.build_parser,
        main=cli.main,
    )


__all__ = ["FacadeBindings", "bind_facade"]
