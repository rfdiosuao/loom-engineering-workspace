"""Admin account, invite, template, and gateway mutation routes."""

from __future__ import annotations


def post_admin_api_beta_config(handler, parsed):
    api = handler.facade
    if not handler.require_admin():
        return
    try:
        body = handler.read_json()
        before = api.get_beta_config()
        api._begin_audit_transaction()
        cfg = api.set_beta_config(body)
        handler.audit_admin_change(
            "beta.config.update",
            target_type="beta_config",
            target_id=api.templates.BETA_CONFIG_KEY,
            before=before,
            after=cfg,
        )
        handler.send_json(200, {"ok": True, "data": cfg})
    except Exception as error:
        handler.send_json(400, {"ok": False, "error": str(error)})


def post_admin_api_templates(handler, parsed):
    api = handler.facade
    if not handler.require_admin():
        return
    try:
        body = handler.read_json()
        raw_template_id = body.get("id", 0)
        template_id = (
            int(raw_template_id) if str(raw_template_id or "").strip().isdigit() else 0
        )
        before = next(
            (
                template
                for template in api.list_templates()
                if template["id"] == template_id
            ),
            {},
        )
        api._begin_audit_transaction()
        tpl = api.save_template(body)
        handler.audit_admin_change(
            "templates.save",
            target_type="template",
            target_id=str(tpl["id"]),
            before=before,
            after=tpl,
        )
        handler.send_json(200, {"ok": True, "data": tpl})
    except api.ActivationError as error:
        handler.send_json(error.status, {"ok": False, "error": str(error)})
    except Exception as error:
        handler.send_json(400, {"ok": False, "error": str(error)})


def post_admin_api_templates_delete(handler, parsed):
    api = handler.facade
    if not handler.require_admin():
        return
    try:
        body = handler.read_json()
        api.require_confirmation(body, "DELETE")
        template_id = int(body.get("id", 0) or 0)
        before = next(
            (
                template
                for template in api.list_templates()
                if template["id"] == template_id
            ),
            {},
        )
        api._begin_audit_transaction()
        api.delete_template(template_id)
        handler.audit_admin_change(
            "templates.delete",
            target_type="template",
            target_id=str(template_id),
            before=before,
            after={},
        )
        handler.send_json(200, {"ok": True})
    except Exception as error:
        handler.send_json(400, {"ok": False, "error": str(error)})


def post_admin_api_accounts(handler, parsed):
    api = handler.facade
    if not handler.require_admin(api.ACCOUNT_ROLE_SUPER_ADMIN):
        return
    try:
        body = handler.read_json()
        account_id = int(body.get("accountId") or 0)
        current = handler.admin_context()
        if account_id:
            before_row = api.get_account_by_id(account_id)
            if not before_row:
                handler.send_json(404, {"error": "\u8d26\u53f7\u4e0d\u5b58\u5728"})
                return
            next_role = (
                api.normalize_account_role(body.get("role"))
                if body.get("role") is not None
                else str(before_row["role"])
            )
            next_status = (
                api.normalize_account_status(body.get("status"))
                if body.get("status") is not None
                else str(before_row["status"])
            )
            removing_active_super = (
                before_row["role"] == api.ACCOUNT_ROLE_SUPER_ADMIN
                and before_row["status"] == api.ACCOUNT_STATUS_ACTIVE
                and (
                    next_role != api.ACCOUNT_ROLE_SUPER_ADMIN
                    or next_status != api.ACCOUNT_STATUS_ACTIVE
                )
            )
            if removing_active_super and api.count_active_super_admins() <= 1:
                handler.send_json(
                    409,
                    {
                        "error": "\u81f3\u5c11\u9700\u8981\u4fdd\u7559\u4e00\u4e2a\u542f\u7528\u4e2d\u7684\u8d85\u7ea7\u7ba1\u7406\u5458\u8d26\u53f7"
                    },
                )
                return
            before = api.account_row_public(before_row)
            backup_path = api.make_audited_backup("accounts-update")
            after = api.update_account_record(
                account_id=account_id,
                display_name=body.get("displayName"),
                role=body.get("role"),
                status=body.get("status"),
                password=body.get("password"),
                note=body.get("note"),
            )
            handler.audit_admin_change(
                "accounts.update",
                target_type="account",
                target_id=str(account_id),
                before=before,
                after=after,
                backup_path=backup_path,
            )
            handler.send_json(200, {"ok": True, "account": after})
        else:
            account_password = str(body.get("password") or "").strip()
            if not account_password:
                raise api.ActivationError(
                    "\u65b0\u5efa\u8d26\u53f7\u5fc5\u987b\u8bbe\u7f6e\u5bc6\u7801", 400
                )
            backup_path = api.make_audited_backup("accounts-create")
            account, _ = api.create_account_record(
                username=str(body.get("username") or "").strip(),
                display_name=str(
                    body.get("displayName") or body.get("display_name") or ""
                ).strip(),
                password=account_password,
                role=body.get("role") or api.ACCOUNT_ROLE_MERCHANT,
                status=body.get("status") or api.ACCOUNT_STATUS_ACTIVE,
                note=str(body.get("note") or "").strip(),
                created_by=int(current.get("accountId") or 0) if current else 0,
            )
            handler.audit_admin_change(
                "accounts.create",
                target_type="account",
                target_id=str(account.get("accountId") or ""),
                before={},
                after=account,
                backup_path=backup_path,
            )
            handler.send_json(200, {"ok": True, "account": account})
    except api.ActivationError as error:
        handler.send_json(error.status, {"error": str(error)})
    except Exception as error:
        handler.send_json(400, {"error": str(error)})


def post_admin_api_accounts_toggle(handler, parsed):
    api = handler.facade
    if not handler.require_admin(api.ACCOUNT_ROLE_SUPER_ADMIN):
        return
    try:
        body = handler.read_json()
        account_id = int(body.get("accountId") or 0)
        if account_id <= 0:
            handler.send_json(400, {"error": "\u7f3a\u5c11\u8d26\u53f7 ID"})
            return
        before_row = api.get_account_by_id(account_id)
        if not before_row:
            handler.send_json(404, {"error": "\u8d26\u53f7\u4e0d\u5b58\u5728"})
            return
        before = api.account_row_public(before_row)
        next_status = (
            api.ACCOUNT_STATUS_DISABLED
            if before_row["status"] == api.ACCOUNT_STATUS_ACTIVE
            else api.ACCOUNT_STATUS_ACTIVE
        )
        if (
            before_row["role"] == api.ACCOUNT_ROLE_SUPER_ADMIN
            and before_row["status"] == api.ACCOUNT_STATUS_ACTIVE
            and (next_status == api.ACCOUNT_STATUS_DISABLED)
            and (api.count_active_super_admins() <= 1)
        ):
            handler.send_json(
                409,
                {
                    "error": "\u81f3\u5c11\u9700\u8981\u4fdd\u7559\u4e00\u4e2a\u542f\u7528\u4e2d\u7684\u8d85\u7ea7\u7ba1\u7406\u5458\u8d26\u53f7"
                },
            )
            return
        backup_path = api.make_audited_backup("accounts-toggle")
        after = api.update_account_record(account_id=account_id, status=next_status)
        handler.audit_admin_change(
            "accounts.toggle",
            target_type="account",
            target_id=str(account_id),
            before=before,
            after=after,
            backup_path=backup_path,
        )
        handler.send_json(200, {"ok": True, "account": after})
    except api.ActivationError as error:
        handler.send_json(error.status, {"error": str(error)})
    except Exception as error:
        handler.send_json(400, {"error": str(error)})


def post_admin_api_invites(handler, parsed):
    api = handler.facade
    if not handler.require_admin(api.ACCOUNT_ROLE_SUPER_ADMIN):
        return
    try:
        body = handler.read_json()
        current = handler.admin_context()
        backup_path = api.make_audited_backup("invites-create")
        invite, raw_code = api.create_invite_record(
            note=str(body.get("note") or "").strip(),
            max_uses=int(body.get("maxUses") or body.get("max_uses") or 1),
            expires_at=str(
                body.get("expiresAt") or body.get("expires_at") or ""
            ).strip(),
            created_by=int(current.get("accountId") or 0) if current else 0,
        )
        handler.audit_admin_change(
            "invites.create",
            target_type="invite",
            target_id=str(invite.get("inviteId") or invite.get("inviteCode") or ""),
            before={},
            after={**invite, "rawInviteCode": raw_code},
            backup_path=backup_path,
        )
        handler.send_json(200, {"ok": True, "invite": invite, "inviteCode": raw_code})
    except api.ActivationError as error:
        handler.send_json(error.status, {"error": str(error)})
    except Exception as error:
        handler.send_json(400, {"error": str(error)})


def post_admin_api_invites_toggle(handler, parsed):
    api = handler.facade
    if not handler.require_admin(api.ACCOUNT_ROLE_SUPER_ADMIN):
        return
    try:
        body = handler.read_json()
        invite_id = int(body.get("inviteId") or body.get("invite_id") or 0)
        if invite_id <= 0:
            handler.send_json(400, {"error": "\u7f3a\u5c11\u9080\u8bf7\u7801 ID"})
            return
        with api.connect() as conn:
            before_row = conn.execute(
                "select * from invite_codes where id = ?", (invite_id,)
            ).fetchone()
        if not before_row:
            handler.send_json(404, {"error": "\u9080\u8bf7\u7801\u4e0d\u5b58\u5728"})
            return
        backup_path = api.make_audited_backup("invites-toggle")
        after = api.toggle_invite_record(invite_id)
        handler.audit_admin_change(
            "invites.toggle",
            target_type="invite",
            target_id=str(invite_id),
            before=api.invite_row_public(before_row),
            after=after,
            backup_path=backup_path,
        )
        handler.send_json(200, {"ok": True, "invite": after})
    except api.ActivationError as error:
        handler.send_json(error.status, {"error": str(error)})
    except Exception as error:
        handler.send_json(400, {"error": str(error)})


def post_admin_api_account_gateway(handler, parsed):
    api = handler.facade
    if not handler.require_admin():
        return
    try:
        account_id = api.context_account_id(handler.admin_context())
        if account_id <= 0:
            raise api.ActivationError(
                "\u8bf7\u5148\u4f7f\u7528\u8d26\u53f7\u767b\u5f55", 401
            )
        before = api.get_account_gateway_settings(account_id, include_secrets=False)
        backup_path = api.make_audited_backup("account-gateway-update")
        settings = api.upsert_account_gateway_settings(account_id, handler.read_json())
        handler.audit_admin_change(
            "account_gateway.update",
            target_type="account_gateway",
            target_id=str(account_id),
            before=before,
            after=settings,
            backup_path=backup_path,
        )
        handler.send_json(200, {"ok": True, "settings": settings})
    except api.ActivationError as error:
        handler.send_json(error.status, {"error": str(error)})
    except Exception as error:
        handler.send_json(400, {"error": str(error)})


def post_admin_api_codes_reveal(handler, parsed):
    api = handler.facade
    if not handler.require_admin():
        return
    try:
        body = handler.read_json()
        if str(body.get("confirmation") or "") != "REVEAL":
            raise api.ActivationError(
                "\u8bf7\u786e\u8ba4\u67e5\u770b\u5b8c\u6574\u6388\u6743\u7801", 400
            )
        api._begin_audit_transaction()
        rows = api.get_code_secret_rows(
            [body.get("codeHash")],
            handler.admin_context(),
        )
        row = rows[0]
        handler.audit_admin_change(
            "codes.reveal",
            target_type="code",
            target_id=row["codeHash"],
            after={"codeLabel": row["codeLabel"]},
        )
        handler.send_json(200, {"code": row["code"], "codeLabel": row["codeLabel"]})
    except api.ActivationError as error:
        handler.send_json(error.status, {"error": str(error)})
    except Exception:
        handler.send_json(500, {"error": "\u67e5\u770b\u6388\u6743\u7801\u5931\u8d25"})


def post_admin_api_codes_export(handler, parsed):
    api = handler.facade
    if not handler.require_admin():
        return
    try:
        body = handler.read_json()
        if str(body.get("confirmation") or "") != "EXPORT":
            raise api.ActivationError(
                "\u8bf7\u786e\u8ba4\u5bfc\u51fa\u5b8c\u6574\u6388\u6743\u7801", 400
            )
        api._begin_audit_transaction()
        rows = api.get_code_secret_rows(
            body.get("codeHashes"),
            handler.admin_context(),
        )
        handler.audit_admin_change(
            "codes.export",
            target_type="codes",
            target_id=f"count:{len(rows)}",
            after={
                "count": len(rows),
                "codeLabels": [row["codeLabel"] for row in rows],
            },
        )
        handler.send_json(200, {"codes": rows})
    except api.ActivationError as error:
        handler.send_json(error.status, {"error": str(error)})
    except Exception:
        handler.send_json(500, {"error": "\u5bfc\u51fa\u6388\u6743\u7801\u5931\u8d25"})


__all__ = [
    "post_admin_api_beta_config",
    "post_admin_api_templates",
    "post_admin_api_templates_delete",
    "post_admin_api_accounts",
    "post_admin_api_accounts_toggle",
    "post_admin_api_invites",
    "post_admin_api_invites_toggle",
    "post_admin_api_account_gateway",
    "post_admin_api_codes_reveal",
    "post_admin_api_codes_export",
]
