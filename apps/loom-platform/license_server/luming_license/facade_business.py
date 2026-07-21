"""Template, plan, audit, inventory, and activation facade adapter blueprints."""

from __future__ import annotations

# Functions in this module are rebound to an owning facade namespace before use.
# ruff: noqa: F821


def beta_today() -> str:
    return templates.beta_today()


def get_beta_config() -> dict[str, Any]:
    return templates.get_beta_config(connect_fn=connect)


def set_beta_config(patch: dict[str, Any]) -> dict[str, Any]:
    return templates.set_beta_config(
        patch,
        connect_fn=connect,
        get_beta_config_fn=get_beta_config,
        normalize_plan_key_fn=normalize_plan_key,
        utc_now_fn=utc_now,
    )


def beta_owner_account_id() -> int:
    return templates.beta_owner_account_id(
        connect_fn=connect,
        account_role_super_admin=ACCOUNT_ROLE_SUPER_ADMIN,
        account_status_active=ACCOUNT_STATUS_ACTIVE,
    )


def beta_claims_count_today() -> int:
    return templates.beta_claims_count_today(
        connect_fn=connect, beta_today_fn=beta_today
    )


def beta_status_snapshot() -> dict[str, Any]:
    return templates.beta_status_snapshot(
        get_beta_config_fn=get_beta_config,
        beta_claims_count_today_fn=beta_claims_count_today,
    )


def beta_claim_code(ip: str) -> dict[str, Any]:
    def claim() -> dict[str, Any]:
        return templates.beta_claim_code(
            ip,
            connect_fn=connect,
            get_beta_config_fn=get_beta_config,
            beta_today_fn=beta_today,
            beta_claims_count_today_fn=beta_claims_count_today,
            beta_owner_account_id_fn=beta_owner_account_id,
            normalize_plan_key_fn=normalize_plan_key,
            get_plan_row_fn=get_plan_row,
            apply_account_gateway_defaults_fn=apply_account_gateway_defaults,
            create_code_records_fn=create_code_records,
            load_json_value_fn=load_json_value,
            default_features=DEFAULT_FEATURES,
            add_days_date_fn=add_days_date,
            utc_now_fn=utc_now,
        )

    try:
        return _run_request_transaction(claim, timeout=1.0)
    except sqlite3.OperationalError as error:
        detail = str(error).lower()
        if "locked" in detail or "busy" in detail:
            raise ActivationError("Service temporarily unavailable", status=503) from None
        raise


def template_public(row: sqlite3.Row) -> dict[str, Any]:
    return templates.template_public(row, load_json_value_fn=load_json_value)


def seed_default_templates() -> None:
    templates.seed_default_templates(connect_fn=connect, utc_now_fn=utc_now)


def list_templates(
    kind: str = "", *, only_enabled: bool = False
) -> list[dict[str, Any]]:
    return templates.list_templates(
        kind,
        only_enabled=only_enabled,
        connect_fn=connect,
        template_public_fn=template_public,
    )


def save_template(body: dict[str, Any]) -> dict[str, Any]:
    return templates.save_template(
        body,
        connect_fn=connect,
        parse_json_object_fn=parse_json_object,
        template_public_fn=template_public,
        utc_now_fn=utc_now,
    )


def delete_template(template_id: int) -> None:
    templates.delete_template(template_id, connect_fn=connect)


def update_code_record(
    body: dict[str, Any], current_account: dict[str, Any] | None = None
) -> None:
    licenses.update_code_record(
        body,
        current_account,
        connect_fn=connect,
        normalize_code_expires_fn=normalize_code_expires,
        parse_features_fn=parse_features,
        parse_models_fn=parse_models,
        parse_json_object_fn=parse_json_object,
        code_row_owned_by_context_fn=code_row_owned_by_context,
        default_features=DEFAULT_FEATURES,
    )


def bulk_update_code_records(
    body: dict[str, Any], current_account: dict[str, Any] | None = None
) -> int:
    return licenses.bulk_update_code_records(
        body,
        current_account,
        connect_fn=connect,
        normalize_code_hashes_fn=normalize_code_hashes,
        code_row_owned_by_context_fn=code_row_owned_by_context,
        update_code_record_fn=update_code_record,
        load_json_value_fn=load_json_value,
        default_features=DEFAULT_FEATURES,
    )


def normalize_plan_key(value: Any) -> str:
    return plans.normalize_plan_key(value)


def plan_row_public(row: sqlite3.Row) -> dict[str, Any]:
    return plans.plan_row_public(
        row, default_features=DEFAULT_FEATURES, load_json_value_fn=load_json_value
    )


def get_plan_rows(include_disabled: bool = False) -> list[dict[str, Any]]:
    return plans.get_plan_rows(
        include_disabled, connect_fn=connect, plan_row_public_fn=plan_row_public
    )


def get_plan_row(plan_key: str) -> sqlite3.Row | None:
    return plans.get_plan_row(plan_key, connect_fn=connect)


def public_settings() -> dict[str, Any]:
    return plans.public_settings(
        connect_fn=connect,
        default_public_settings=DEFAULT_PUBLIC_SETTINGS,
        public_support_url=PUBLIC_SUPPORT_URL,
        load_json_value_fn=load_json_value,
    )


def client_public_config() -> dict[str, Any]:
    return plans.client_public_config(
        public_settings_fn=public_settings,
        public_commercial_url=PUBLIC_COMMERCIAL_URL,
        public_support_url=PUBLIC_SUPPORT_URL,
    )


def validate_gateway_url(value: str, label: str) -> str:
    return plans.validate_gateway_url(value, label)


def update_public_settings(body: dict[str, Any]) -> dict[str, Any]:
    return plans.update_public_settings(
        body,
        connect_fn=connect,
        public_settings_fn=public_settings,
        validate_gateway_url_fn=validate_gateway_url,
        public_support_url=PUBLIC_SUPPORT_URL,
        utc_now_fn=utc_now,
    )


def default_account_gateway_settings(
    account_id: int = 0, *, include_secrets: bool = False
) -> dict[str, Any]:
    return plans.default_account_gateway_settings(
        account_id, include_secrets=include_secrets
    )


def account_gateway_settings_public(
    row: sqlite3.Row | None,
    *,
    account_id: int = 0,
    include_secrets: bool = False,
) -> dict[str, Any]:
    return plans.account_gateway_settings_public(
        row,
        account_id=account_id,
        include_secrets=include_secrets,
        default_account_gateway_settings_fn=default_account_gateway_settings,
        load_json_value_fn=load_json_value,
    )


def get_account_gateway_settings(
    account_id: int, *, include_secrets: bool = False
) -> dict[str, Any]:
    return plans.get_account_gateway_settings(
        account_id,
        include_secrets=include_secrets,
        connect_fn=connect,
        account_gateway_settings_public_fn=account_gateway_settings_public,
        default_account_gateway_settings_fn=default_account_gateway_settings,
    )


def upsert_account_gateway_settings(
    account_id: int, body: dict[str, Any]
) -> dict[str, Any]:
    return plans.upsert_account_gateway_settings(
        account_id,
        body,
        connect_fn=connect,
        get_account_by_id_fn=get_account_by_id,
        get_account_gateway_settings_fn=get_account_gateway_settings,
        validate_gateway_url_fn=validate_gateway_url,
        parse_optional_models_fn=parse_optional_models,
        utc_now_fn=utc_now,
        account_status_active=ACCOUNT_STATUS_ACTIVE,
    )


def has_explicit_gateway_value(body: dict[str, Any], *names: str) -> bool:
    return plans.has_explicit_gateway_value(body, *names)


def apply_account_gateway_defaults(
    body: dict[str, Any],
    account_id: int,
    *,
    explicit_body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return plans.apply_account_gateway_defaults(
        body,
        account_id,
        explicit_body=explicit_body,
        get_account_gateway_settings_fn=get_account_gateway_settings,
        has_explicit_gateway_value_fn=has_explicit_gateway_value,
    )


def upsert_plan_record(body: dict[str, Any]) -> dict[str, Any]:
    return plans.upsert_plan_record(
        body,
        connect_fn=connect,
        normalize_plan_key_fn=normalize_plan_key,
        parse_features_fn=parse_features,
        parse_models_fn=parse_models,
        parse_json_object_fn=parse_json_object,
        get_plan_row_fn=get_plan_row,
        plan_row_public_fn=plan_row_public,
        default_features=DEFAULT_FEATURES,
        utc_now_fn=utc_now,
    )


def disable_plan_record(plan_key: str) -> dict[str, Any] | None:
    return plans.disable_plan_record(
        plan_key,
        connect_fn=connect,
        normalize_plan_key_fn=normalize_plan_key,
        get_plan_row_fn=get_plan_row,
        plan_row_public_fn=plan_row_public,
        utc_now_fn=utc_now,
    )


def apply_plan_template(body: dict[str, Any]) -> dict[str, Any]:
    return plans.apply_plan_template(
        body,
        normalize_plan_key_fn=normalize_plan_key,
        get_plan_row_fn=get_plan_row,
        default_features=DEFAULT_FEATURES,
        load_json_value_fn=load_json_value,
    )


def audit_json(value: Any) -> str:
    return audit.audit_json(value)


def masked_code_label(value: Any) -> str:
    return audit.masked_code_label(value)


def audit_public_value(value: Any, *, key: str = "") -> Any:
    return audit.audit_public_value(value, key=key)


def add_audit_log(
    *,
    action: str,
    target_type: str = "",
    target_id: str = "",
    before: Any = None,
    after: Any = None,
    actor: str = "",
    request_ip: str = "",
    backup_path: str = "",
) -> None:
    return audit.add_audit_log(
        action=action,
        target_type=target_type,
        target_id=target_id,
        before=before,
        after=after,
        actor=actor,
        request_ip=request_ip,
        backup_path=backup_path,
        connect_fn=connect,
        utc_now_fn=utc_now,
        audit_json_fn=audit_json,
        audit_public_value_fn=audit_public_value,
        commit_fn=_commit_audit_connection,
    )


def masked_secret(value: Any) -> str:
    return audit.masked_secret(value)


def code_row_snapshot(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return licenses.code_row_snapshot(
        row,
        load_json_value_fn=load_json_value,
        masked_secret_fn=masked_secret,
        default_features=DEFAULT_FEATURES,
    )


def get_code_snapshot(
    code_hash_value: str, current_account: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    return licenses.get_code_snapshot(
        code_hash_value,
        current_account,
        connect_fn=connect,
        code_row_owned_by_context_fn=code_row_owned_by_context,
        code_row_snapshot_fn=code_row_snapshot,
    )


def get_code_snapshots(
    code_hashes: list[Any], current_account: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    return licenses.get_code_snapshots(
        code_hashes,
        current_account,
        connect_fn=connect,
        code_row_snapshot_fn=code_row_snapshot,
        is_super_admin_context_fn=is_super_admin_context,
        context_account_id_fn=context_account_id,
    )


def get_inventory_snapshot() -> dict[str, Any]:
    return licenses.get_inventory_snapshot(connect_fn=connect)


def get_audit_rows(limit: int = 100) -> list[dict[str, Any]]:
    return audit.get_audit_rows(
        limit,
        connect_fn=connect,
        load_json_value_fn=load_json_value,
        audit_public_value_fn=audit_public_value,
    )


def get_code_rows(
    current_account: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    return licenses.get_code_rows(
        current_account,
        connect_fn=connect,
        is_super_admin_context_fn=is_super_admin_context,
        context_account_id_fn=context_account_id,
        masked_secret_fn=masked_secret,
    )


def get_code_secret_rows(
    code_hashes: list[Any],
    current_account: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    return licenses.get_code_secret_rows(
        code_hashes,
        current_account,
        connect_fn=connect,
        normalize_code_hashes_fn=normalize_code_hashes,
        code_row_owned_by_context_fn=code_row_owned_by_context,
        max_code_secret_export=MAX_CODE_SECRET_EXPORT,
    )


def activation_row_public(row: sqlite3.Row) -> dict[str, Any]:
    return activations.activation_row_public(row)


def get_activation_rows(
    code_hash_value: str, current_account: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    return activations.get_activation_rows(
        code_hash_value,
        current_account,
        connect_fn=connect,
        is_super_admin_context_fn=is_super_admin_context,
        context_account_id_fn=context_account_id,
        activation_row_public_fn=activation_row_public,
    )


def get_all_activation_rows(
    current_account: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    return activations.get_all_activation_rows(
        current_account,
        connect_fn=connect,
        is_super_admin_context_fn=is_super_admin_context,
        context_account_id_fn=context_account_id,
    )


def get_activation_snapshot(
    activation_id: int,
    current_account: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    return activations.get_activation_snapshot(
        activation_id,
        current_account,
        connect_fn=connect,
        is_super_admin_context_fn=is_super_admin_context,
        context_account_id_fn=context_account_id,
        activation_row_public_fn=activation_row_public,
    )


def apply_member_fields(
    payload: dict[str, Any], code_row: sqlite3.Row
) -> dict[str, Any]:
    return activations.apply_member_fields(
        payload,
        code_row,
        default_gateway_base_url=DEFAULT_GATEWAY_BASE_URL,
        default_gateway_image_base_url=DEFAULT_GATEWAY_IMAGE_BASE_URL,
        default_gateway_video_base_url=DEFAULT_GATEWAY_VIDEO_BASE_URL,
        default_gateway_token=DEFAULT_GATEWAY_TOKEN,
        default_gateway_image_token=DEFAULT_GATEWAY_IMAGE_TOKEN,
        default_gateway_video_token=DEFAULT_GATEWAY_VIDEO_TOKEN,
        default_gateway_default_model=DEFAULT_GATEWAY_DEFAULT_MODEL,
        default_gateway_image_model=DEFAULT_GATEWAY_IMAGE_MODEL,
        default_gateway_video_model=DEFAULT_GATEWAY_VIDEO_MODEL,
        default_gateway_models=DEFAULT_GATEWAY_MODELS,
        load_json_value_fn=load_json_value,
    )


def build_signed_license(
    code_row: sqlite3.Row,
    install_id: str,
    device_id: str,
    *,
    license_id: str | None = None,
    activated_at: str | None = None,
) -> dict[str, Any]:
    return activations.build_signed_license(
        code_row,
        install_id,
        device_id,
        license_id=license_id,
        activated_at=activated_at,
        apply_member_fields_fn=apply_member_fields,
        sign_license_fn=sign_license,
        utc_now_fn=utc_now,
    )


def member_response(license_data: dict[str, Any]) -> dict[str, Any]:
    return activations.member_response(license_data)


def find_member_license(body: dict[str, Any]) -> dict[str, Any] | None:
    return activations.find_member_license(
        body,
        connect_fn=connect,
        build_signed_license_fn=build_signed_license,
    )


def activate_code(body: dict[str, Any]) -> dict[str, Any]:
    return activations.activate_code(
        body,
        connect_fn=connect,
        code_hash_fn=code_hash,
        build_signed_license_fn=build_signed_license,
        utc_now_fn=utc_now,
    )


__all__ = [
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
]
