"""Admin code, plan, activation, and public-settings mutation routes."""

from __future__ import annotations


def post_admin_api_codes(handler, parsed):
    api = handler.facade
    if not handler.require_admin():
        return
    try:
        current = handler.admin_context()
        raw_body = handler.read_json()
        body = (
            api.apply_plan_template(raw_body)
            if api.is_super_admin_context(current)
            else raw_body
        )
        owner_account_id = api.context_account_id(current)
        if current and api.is_super_admin_context(current):
            owner_account_id = int(
                body.get("ownerAccountId")
                or body.get("owner_account_id")
                or owner_account_id
                or 0
            )
        body = api.apply_account_gateway_defaults(
            body, owner_account_id, explicit_body=raw_body
        )
        features = api.parse_features(
            str(body.get("features", ",".join(api.DEFAULT_FEATURES)))
        )
        backup_path = api.make_audited_backup("codes-create")
        if owner_account_id:
            owner = api.get_account_by_id(owner_account_id)
            if not owner or owner["status"] != api.ACCOUNT_STATUS_ACTIVE:
                raise api.ActivationError(
                    "\u5f52\u5c5e\u8d26\u53f7\u4e0d\u5b58\u5728\u6216\u5df2\u505c\u7528"
                )
        codes = api.create_code_records(
            count=int(body.get("count", 1)),
            licensee=str(body.get("licensee", "\u5ba2\u6237")).strip()
            or "\u5ba2\u6237",
            edition=str(body.get("edition", "pro")).strip() or "pro",
            features=features,
            expires=str(body.get("expires", "2027-05-01")).strip() or "2027-05-01",
            max_activations=int(body.get("maxActivations", 1)),
            member_mode=bool(body.get("memberMode")),
            plan=str(body.get("plan", "")).strip(),
            gateway_base_url=str(body.get("gatewayBaseUrl", "")).strip(),
            gateway_image_base_url=str(
                body.get("gatewayImageBaseUrl")
                or body.get("gateway_image_base_url")
                or ""
            ).strip(),
            gateway_video_base_url=str(
                body.get("gatewayVideoBaseUrl")
                or body.get("gateway_video_base_url")
                or ""
            ).strip(),
            gateway_token=str(body.get("gatewayToken", "")).strip(),
            gateway_image_token=str(
                body.get("gatewayImageToken") or body.get("gateway_image_token") or ""
            ).strip(),
            gateway_video_token=str(
                body.get("gatewayVideoToken") or body.get("gateway_video_token") or ""
            ).strip(),
            gateway_default_model=str(body.get("gatewayDefaultModel", "")).strip(),
            gateway_image_model=str(
                body.get("gatewayImageModel") or body.get("gateway_image_model") or ""
            ).strip(),
            gateway_video_model=str(
                body.get("gatewayVideoModel") or body.get("gateway_video_model") or ""
            ).strip(),
            gateway_models=api.parse_models(body.get("gatewayModels", "")),
            quotas=api.parse_json_object(body.get("quotas", "")),
            owner_account_id=owner_account_id,
        )
        handler.audit_admin_change(
            "codes.create",
            target_type="codes",
            target_id=f"count:{len(codes)}",
            before={},
            after={
                "count": len(codes),
                "codeLabels": [code[-9:] for code in codes],
                "licensee": str(body.get("licensee", "\u5ba2\u6237")).strip()
                or "\u5ba2\u6237",
                "memberMode": bool(body.get("memberMode")),
                "plan": str(body.get("plan", "")).strip(),
                "ownerAccountId": owner_account_id,
            },
            backup_path=backup_path,
        )
        handler.send_json(200, {"codes": codes})
    except Exception as error:
        handler.send_json(400, {"error": str(error)})


def post_admin_api_codes_update(handler, parsed):
    api = handler.facade
    if not handler.require_admin():
        return
    try:
        current = handler.admin_context()
        raw_body = handler.read_json()
        body = (
            api.apply_plan_template(raw_body)
            if api.is_super_admin_context(current)
            else raw_body
        )
        code_hash_value = str(body.get("codeHash", "")).strip()
        before = api.get_code_snapshot(code_hash_value, current)
        backup_path = api.make_audited_backup("codes-update")
        api.update_code_record(body, current_account=current)
        after = api.get_code_snapshot(code_hash_value, current)
        handler.audit_admin_change(
            "codes.update",
            target_type="code",
            target_id=code_hash_value,
            before=before,
            after=after,
            backup_path=backup_path,
        )
        handler.send_json(200, {"ok": True})
    except api.ActivationError as error:
        handler.send_json(error.status, {"error": str(error)})
    except Exception as error:
        handler.send_json(400, {"error": str(error)})


def post_admin_api_codes_bulk_update(handler, parsed):
    api = handler.facade
    if not handler.require_admin():
        return
    try:
        current = handler.admin_context()
        raw_body = handler.read_json()
        body = (
            api.apply_plan_template(raw_body)
            if api.is_super_admin_context(current)
            else dict(raw_body)
        )
        code_hashes = api.normalize_code_hashes(body.get("codeHashes"))
        body["codeHashes"] = code_hashes
        before = api.get_code_snapshots(code_hashes, current)
        backup_path = api.make_audited_backup("codes-bulk-update")
        updated = api.bulk_update_code_records(body, current_account=current)
        after = api.get_code_snapshots(code_hashes, current)
        handler.audit_admin_change(
            "codes.bulk_update",
            target_type="codes",
            target_id=f"count:{updated}",
            before=before,
            after=after,
            backup_path=backup_path,
        )
        handler.send_json(200, {"ok": True, "updated": updated})
    except api.ActivationError as error:
        handler.send_json(error.status, {"error": str(error)})
    except Exception as error:
        handler.send_json(400, {"error": str(error)})


def post_admin_api_plans_update(handler, parsed):
    api = handler.facade
    if not handler.require_admin(api.ACCOUNT_ROLE_SUPER_ADMIN):
        return
    try:
        body = handler.read_json()
        plan_key_value = str(
            body.get("planKey") or body.get("plan") or body.get("key") or ""
        ).strip()
        before_row = (
            api.get_plan_row(api.normalize_plan_key(plan_key_value))
            if plan_key_value
            else None
        )
        before = api.plan_row_public(before_row) if before_row else None
        backup_path = api.make_audited_backup("plans-update")
        plan = api.upsert_plan_record(body)
        handler.audit_admin_change(
            "plans.update",
            target_type="plan",
            target_id=plan["planKey"],
            before=before,
            after=plan,
            backup_path=backup_path,
        )
        handler.send_json(200, {"ok": True, "plan": plan})
    except api.ActivationError as error:
        handler.send_json(error.status, {"error": str(error)})
    except Exception as error:
        handler.send_json(400, {"error": str(error)})


def post_admin_api_plans_delete(handler, parsed):
    api = handler.facade
    if not handler.require_admin(api.ACCOUNT_ROLE_SUPER_ADMIN):
        return
    try:
        body = handler.read_json()
        api.require_confirmation(body, "DISABLE")
        plan_key_value = api.normalize_plan_key(body.get("planKey"))
        before_row = api.get_plan_row(plan_key_value)
        before = api.plan_row_public(before_row) if before_row else None
        if before is None:
            handler.send_json(
                404, {"error": "\u5957\u9910\u6a21\u677f\u4e0d\u5b58\u5728"}
            )
            return
        backup_path = api.make_audited_backup("plans-delete")
        after = api.disable_plan_record(plan_key_value)
        handler.audit_admin_change(
            "plans.delete",
            target_type="plan",
            target_id=plan_key_value,
            before=before,
            after=after,
            backup_path=backup_path,
        )
        handler.send_json(200, {"ok": True, "plan": after})
    except api.ActivationError as error:
        handler.send_json(error.status, {"error": str(error)})
    except Exception as error:
        handler.send_json(400, {"error": str(error)})


def post_admin_api_codes_toggle(handler, parsed):
    api = handler.facade
    if not handler.require_admin():
        return
    try:
        current = handler.admin_context()
        body = handler.read_json()
        code_hash_value = str(body.get("codeHash", ""))
        disabled = 1 if body.get("disabled") else 0
        before = api.get_code_snapshot(code_hash_value, current)
        backup_path = api.make_audited_backup("codes-toggle")
        with api.connect() as conn:
            if current and (not api.is_super_admin_context(current)):
                result = conn.execute(
                    "update codes set disabled = ? where code_hash = ? and owner_account_id = ?",
                    (disabled, code_hash_value, api.context_account_id(current)),
                )
            else:
                result = conn.execute(
                    "update codes set disabled = ? where code_hash = ?",
                    (disabled, code_hash_value),
                )
            conn.commit()
        if result.rowcount == 0:
            handler.send_json(404, {"error": "\u6388\u6743\u7801\u4e0d\u5b58\u5728"})
        else:
            after = api.get_code_snapshot(code_hash_value, current)
            handler.audit_admin_change(
                "codes.toggle",
                target_type="code",
                target_id=code_hash_value,
                before=before,
                after=after,
                backup_path=backup_path,
            )
            handler.send_json(200, {"ok": True})
    except Exception as error:
        handler.send_json(400, {"error": str(error)})


def post_admin_api_codes_clear(handler, parsed):
    api = handler.facade
    if not handler.require_admin(api.ACCOUNT_ROLE_SUPER_ADMIN):
        return
    try:
        body = handler.read_json()
        api.require_confirmation(body, "CLEAR")
        before = api.get_inventory_snapshot()
        backup_path = api.make_audited_backup("codes-clear")
        with api.connect() as conn:
            conn.execute("delete from activations")
            conn.execute("delete from codes")
            conn.commit()
        handler.audit_admin_change(
            "codes.clear",
            target_type="codes",
            target_id="all",
            before=before,
            after=api.get_inventory_snapshot(),
            backup_path=backup_path,
        )
        handler.send_json(200, {"ok": True})
    except Exception as error:
        handler.send_json(400, {"error": str(error)})


def post_admin_api_codes_hash(handler, parsed):
    api = handler.facade
    if not handler.require_admin():
        return
    try:
        current = handler.admin_context()  # noqa: F841 - preserve the facade call
        body = handler.read_json()
        code = str(body.get("code", "")).strip().upper()
        h = api.code_hash(code)
        handler.send_json(200, {"codeHash": h})
    except Exception as error:
        handler.send_json(400, {"error": str(error)})


def post_admin_api_codes_delete(handler, parsed):
    api = handler.facade
    if not handler.require_admin():
        return
    try:
        current = handler.admin_context()
        body = handler.read_json()
        api.require_confirmation(body, "DELETE")
        code_hash_value = str(body.get("codeHash", ""))
        before = api.get_code_snapshot(code_hash_value, current)
        if not before:
            handler.send_json(
                404,
                {
                    "error": "\u6388\u6743\u7801\u4e0d\u5b58\u5728\u6216\u65e0\u6743\u8bbf\u95ee"
                },
            )
            return
        backup_path = api.make_audited_backup("codes-delete")
        with api.connect() as conn:
            if current and (not api.is_super_admin_context(current)):
                conn.execute(
                    "delete from activations where code_hash = ?", (code_hash_value,)
                )
                conn.execute(
                    "delete from codes where code_hash = ? and owner_account_id = ?",
                    (code_hash_value, api.context_account_id(current)),
                )
            else:
                conn.execute(
                    "delete from activations where code_hash = ?", (code_hash_value,)
                )
                conn.execute(
                    "delete from codes where code_hash = ?", (code_hash_value,)
                )
            conn.commit()
        handler.audit_admin_change(
            "codes.delete",
            target_type="code",
            target_id=code_hash_value,
            before=before,
            after={},
            backup_path=backup_path,
        )
        handler.send_json(200, {"ok": True})
    except Exception as error:
        handler.send_json(400, {"error": str(error)})


def post_admin_api_activations_delete(handler, parsed):
    api = handler.facade
    if not handler.require_admin():
        return
    try:
        current = handler.admin_context()
        body = handler.read_json()
        api.require_confirmation(body, "UNBIND")
        activation_id = int(body.get("id") or 0)
        before = api.get_activation_snapshot(activation_id, current)
        if before is None:
            handler.send_json(
                404,
                {
                    "error": "\u6fc0\u6d3b\u8bb0\u5f55\u4e0d\u5b58\u5728\u6216\u65e0\u6743\u8bbf\u95ee"
                },
            )
            return
        backup_path = api.make_audited_backup("activations-delete")
        with api.connect() as conn:
            if current and (not api.is_super_admin_context(current)):
                deleted = conn.execute(
                    "\n                            delete from activations\n                            where id = ?\n                              and code_hash in (\n                                  select code_hash from codes where owner_account_id = ?\n                              )\n                            ",
                    (activation_id, api.context_account_id(current)),
                )
            else:
                deleted = conn.execute(
                    "delete from activations where id = ?", (activation_id,)
                )
            if deleted.rowcount != 1:
                conn.rollback()
                handler.send_json(
                    404,
                    {
                        "error": "\u6fc0\u6d3b\u8bb0\u5f55\u4e0d\u5b58\u5728\u6216\u65e0\u6743\u8bbf\u95ee"
                    },
                )
                return
            conn.commit()
        handler.audit_admin_change(
            "activations.delete",
            target_type="activation",
            target_id=str(activation_id),
            before=before,
            after={},
            backup_path=backup_path,
        )
        handler.send_json(200, {"ok": True})
    except Exception as error:
        handler.send_json(400, {"error": str(error)})


def post_admin_api_public_settings(handler, parsed):
    api = handler.facade
    if not handler.require_admin(api.ACCOUNT_ROLE_SUPER_ADMIN):
        return
    try:
        before = api.public_settings()
        backup_path = api.make_audited_backup("public-settings-update")
        settings = api.update_public_settings(handler.read_json())
        handler.audit_admin_change(
            "settings.update",
            target_type="settings",
            target_id="public",
            before=before,
            after=settings,
            backup_path=backup_path,
        )
        handler.send_json(
            200,
            {
                "ok": True,
                "settings": settings,
                "clientConfig": api.client_public_config(),
            },
        )
    except api.ActivationError as error:
        handler.send_json(error.status, {"error": str(error)})
    except Exception as error:
        handler.send_json(400, {"error": str(error)})


__all__ = [
    "post_admin_api_codes",
    "post_admin_api_codes_update",
    "post_admin_api_codes_bulk_update",
    "post_admin_api_plans_update",
    "post_admin_api_plans_delete",
    "post_admin_api_codes_toggle",
    "post_admin_api_codes_clear",
    "post_admin_api_codes_hash",
    "post_admin_api_codes_delete",
    "post_admin_api_activations_delete",
    "post_admin_api_public_settings",
]
