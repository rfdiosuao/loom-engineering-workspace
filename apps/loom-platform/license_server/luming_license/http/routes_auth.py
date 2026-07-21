from __future__ import annotations

from typing import Any, Callable


Route = Callable[[Any, Any], None]


def get_admin_api_auth_status(handler, parsed):
    api = handler.facade
    handler.send_json(200, api.auth_status_snapshot())


def get_admin_api_me(handler, parsed):
    api = handler.facade
    if not handler.require_admin():
        return
    context = handler.admin_context()
    account = (
        api.account_summary_row(api.context_account_id(context))
        if context and api.context_account_id(context)
        else None
    )
    payload = {
        "account": account or (context or {}),
        "session": {
            "authType": context.get("authType") if context else "",
            "role": context.get("role") if context else "",
        },
        "authStatus": api.auth_status_snapshot(),
    }
    handler.send_json(200, payload)


def post_admin_api_auth_status(handler, parsed):
    handler.send_json(405, {"error": "method not allowed"})


def post_admin_api_auth_login(handler, parsed):
    api = handler.facade
    try:
        body = handler.read_json()
        username = api.normalize_username(body.get("username"))
        password = str(body.get("password") or "").strip()
        login_rate_key = f"{handler.request_ip()}:{username or '-'}"
        api.rate_limit_check("admin-login", login_rate_key)
        account = api.get_account_by_username(username)
        if (
            not account
            or account["status"] != api.ACCOUNT_STATUS_ACTIVE
            or (not api.verify_password(password, account["password_hash"]))
        ):
            api.rate_limit_record_failure(
                "admin-login",
                login_rate_key,
                limit=api.LOGIN_RATE_LIMIT_ATTEMPTS,
                window_seconds=api.LOGIN_RATE_LIMIT_WINDOW_SECONDS,
                lockout_seconds=api.LOGIN_RATE_LIMIT_LOCKOUT_SECONDS,
            )
            handler.send_json(
                401, {"error": "\u7528\u6237\u540d\u6216\u5bc6\u7801\u9519\u8bef"}
            )
            return
        api.rate_limit_clear("admin-login", login_rate_key)
        session_token, expires_at = api.create_admin_session(
            int(account["id"]),
            request_ip=handler.request_ip(),
            user_agent=str(handler.headers.get("User-Agent", "") or ""),
        )
        api.update_account_last_login(int(account["id"]), handler.request_ip())
        account = api.get_account_by_id(int(account["id"]))
        handler.send_json(
            200,
            {
                "ok": True,
                "sessionToken": session_token,
                "expiresAt": expires_at,
                "account": api.account_row_public(account),
                "authStatus": api.auth_status_snapshot(),
            },
            headers={"Set-Cookie": api.admin_session_cookie(session_token)},
        )
    except api.ActivationError as error:
        handler.send_json(error.status, {"error": str(error)})
    except Exception as error:
        handler.send_json(400, {"error": str(error)})


def post_admin_api_auth_register(handler, parsed):
    api = handler.facade
    try:
        api.rate_limit_consume(
            "admin-register",
            handler.request_ip(),
            limit=api.REGISTER_RATE_LIMIT_ATTEMPTS,
            window_seconds=api.REGISTER_RATE_LIMIT_WINDOW_SECONDS,
            lockout_seconds=api.REGISTER_RATE_LIMIT_LOCKOUT_SECONDS,
        )
        body = handler.read_json()
        api._begin_audit_transaction()
        account, invite_code, _ = api.register_account_with_invite(
            invite_code=str(body.get("inviteCode") or body.get("invite_code") or ""),
            username=str(body.get("username") or ""),
            display_name=str(body.get("displayName") or body.get("display_name") or ""),
            password=str(body.get("password") or ""),
            request_ip=handler.request_ip(),
            user_agent=str(handler.headers.get("User-Agent", "") or ""),
        )
        account_id = int(account.get("accountId") or 0)
        session_token, expires_at = api.create_admin_session(
            account_id,
            request_ip=handler.request_ip(),
            user_agent=str(handler.headers.get("User-Agent", "") or ""),
        )
        api.update_account_last_login(account_id, handler.request_ip())
        account = api.get_account_by_id(account_id)
        public_account = api.account_row_public(account)
        api._audit_registered_account(
            account=public_account,
            invite_code=invite_code,
            request_ip=handler.request_ip(),
        )
        handler.send_json(
            200,
            {
                "ok": True,
                "inviteCode": invite_code,
                "sessionToken": session_token,
                "expiresAt": expires_at,
                "account": public_account,
                "authStatus": api.auth_status_snapshot(),
            },
            headers={"Set-Cookie": api.admin_session_cookie(session_token)},
        )
    except api.ActivationError as error:
        handler.send_json(error.status, {"error": str(error)})
    except Exception as error:
        handler.send_json(400, {"error": str(error)})


def post_admin_api_auth_bootstrap(handler, parsed):
    api = handler.facade
    try:
        if api.count_accounts() > 0:
            handler.send_json(
                409, {"error": "\u7cfb\u7edf\u5df2\u7ecf\u521d\u59cb\u5316"}
            )
            return
        provided = str(
            handler.headers.get("X-Admin-Token")
            or handler.headers.get("Authorization", "")
            or ""
        ).strip()
        if provided.lower().startswith("bearer "):
            provided = provided.split(" ", 1)[1].strip()
        expected = api.load_admin_token()
        if (
            not expected
            or not provided
            or (not api.secrets.compare_digest(provided, expected))
        ):
            handler.send_json(
                401, {"error": "\u521d\u59cb\u5316\u53e3\u4ee4\u9519\u8bef"}
            )
            return
        body = handler.read_json()
        bootstrap_password = str(body.get("password") or "").strip()
        if not bootstrap_password:
            raise api.ActivationError(
                "\u9996\u6b21\u521d\u59cb\u5316\u5fc5\u987b\u8bbe\u7f6e\u5bc6\u7801",
                400,
            )
        api._begin_audit_transaction()
        account, _ = api.create_account_record(
            username=str(body.get("username") or "admin").strip(),
            display_name=str(
                body.get("displayName")
                or body.get("display_name")
                or "\u8d85\u7ea7\u7ba1\u7406\u5458"
            ).strip(),
            password=bootstrap_password,
            role=api.ACCOUNT_ROLE_SUPER_ADMIN,
            status=api.ACCOUNT_STATUS_ACTIVE,
            note=str(body.get("note") or "").strip(),
            created_by=0,
        )
        session_token, expires_at = api.create_admin_session(
            int(account.get("accountId") or 0),
            request_ip=handler.request_ip(),
            user_agent=str(handler.headers.get("User-Agent", "") or ""),
        )
        api.add_audit_log(
            action="accounts.bootstrap",
            target_type="account",
            target_id=str(account["username"]),
            before={},
            after=account,
            actor="bootstrap",
            request_ip=handler.request_ip(),
            backup_path="",
        )
        handler.send_json(
            200,
            {
                "ok": True,
                "account": account,
                "sessionToken": session_token,
                "expiresAt": expires_at,
                "authStatus": api.auth_status_snapshot(),
            },
            headers={"Set-Cookie": api.admin_session_cookie(session_token)},
        )
    except api.ActivationError as error:
        handler.send_json(error.status, {"error": str(error)})
    except Exception as error:
        handler.send_json(400, {"error": str(error)})


def post_admin_api_auth_logout(handler, parsed):
    api = handler.facade
    if not handler.require_admin():
        return
    token = api.request_admin_token(handler.headers)
    revoked = api.revoke_admin_session(token)
    handler.send_json(
        200,
        {"ok": True, "revoked": revoked},
        headers={"Set-Cookie": api.admin_session_cookie("", max_age=0)},
    )


GET_ROUTES: dict[str, Route] = {
    "/admin/api/auth/status": get_admin_api_auth_status,
    "/admin/api/me": get_admin_api_me,
}


POST_ROUTES: dict[str, Route] = {
    "/admin/api/auth/status": post_admin_api_auth_status,
    "/admin/api/auth/login": post_admin_api_auth_login,
    "/admin/api/auth/register": post_admin_api_auth_register,
    "/admin/api/auth/bootstrap": post_admin_api_auth_bootstrap,
    "/admin/api/auth/logout": post_admin_api_auth_logout,
}
