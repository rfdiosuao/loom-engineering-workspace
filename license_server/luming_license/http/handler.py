from __future__ import annotations

from http.server import BaseHTTPRequestHandler
from typing import Any, Callable

from .responses import ResponseMixin
from . import routes_admin, routes_auth, routes_public, routes_relay


Route = Callable[[Any, Any], None]


def _merge_route_tables(*tables: dict[str, Route]) -> dict[str, Route]:
    merged: dict[str, Route] = {}
    for table in tables:
        overlap = set(merged).intersection(table)
        if overlap:
            raise RuntimeError(f"duplicate HTTP routes: {sorted(overlap)}")
        merged.update(table)
    return merged


GET_ROUTES = _merge_route_tables(
    routes_public.GET_ROUTES,
    routes_auth.GET_ROUTES,
    routes_admin.GET_ROUTES,
    routes_relay.GET_ROUTES,
)
POST_ROUTES = _merge_route_tables(
    routes_public.POST_ROUTES,
    routes_auth.POST_ROUTES,
    routes_admin.POST_ROUTES,
    routes_relay.POST_ROUTES,
)
HEAD_ROUTES = _merge_route_tables(routes_public.HEAD_ROUTES)
ROUTE_INVENTORY = frozenset(GET_ROUTES) | frozenset(POST_ROUTES)


def dispatch(handler: Handler, method: str) -> None:
    parsed = handler.facade.urlparse(handler.path)
    routes = {"GET": GET_ROUTES, "POST": POST_ROUTES, "HEAD": HEAD_ROUTES}[method]
    route = routes.get(parsed.path)
    if route is None:
        handler.send_json(404, {"error": "not found"}, write_body=method != "HEAD")
        return
    route(handler, parsed)


class Handler(ResponseMixin, BaseHTTPRequestHandler):
    server_version = "OpenClawLicense/1.0"
    facade: Any = None

    def admin_context(self, *, allow_legacy: bool = True) -> dict[str, Any] | None:
        context = getattr(self, "_admin_context", None)
        if context is not None:
            return context
        token = self.facade.request_admin_token(self.headers)
        context = self.facade.load_admin_context_from_session(token)
        if context is None and allow_legacy:
            context = self.facade.load_legacy_admin_context(token)
        self._admin_context = context
        return context

    def admin_actor(self) -> str:
        context = self.admin_context()
        if not context:
            return "admin"
        return str(context.get("actor") or "admin")

    def admin_role(self) -> str:
        context = self.admin_context()
        return str(context.get("role") or "") if context else ""

    def admin_account_id(self) -> int:
        context = self.admin_context()
        return self.facade.context_account_id(context)

    def request_ip(self) -> str:
        cf_ip = self.headers.get("CF-Connecting-IP", "").strip()
        if cf_ip:
            return cf_ip
        real_ip = self.headers.get("X-Real-IP", "").strip()
        if real_ip:
            return real_ip
        forwarded = self.headers.get("X-Forwarded-For", "")
        if forwarded:
            parts = [part.strip() for part in forwarded.split(",") if part.strip()]
            if parts:
                return parts[-1]
        return self.client_address[0] if self.client_address else ""

    def require_admin(
        self, role: str | None = None, *, allow_legacy: bool = True
    ) -> bool:
        context = self.admin_context(allow_legacy=allow_legacy)
        if not context:
            self.send_json(401, {"error": "\u8bf7\u5148\u767b\u5f55"})
            return False
        if role and self.facade.role_rank(
            str(context.get("role") or "")
        ) < self.facade.role_rank(role):
            self.send_json(403, {"error": "\u6743\u9650\u4e0d\u8db3"})
            return False
        return True

    def audit_admin_change(
        self,
        action: str,
        *,
        target_type: str = "",
        target_id: str = "",
        before: Any = None,
        after: Any = None,
        backup_path: str = "",
    ) -> None:
        self.facade.add_audit_log(
            action=action,
            target_type=target_type,
            target_id=target_id,
            before=before,
            after=after,
            actor=self.admin_actor(),
            request_ip=self.request_ip(),
            backup_path=backup_path,
        )

    def require_publish_relay_auth(self) -> bool:
        if not self.facade.publish_relay_configured():
            self.send_json(503, {"ok": False, "error": "Relay token is not configured"})
            return False
        if self.facade.publish_relay_token_valid(self.headers):
            return True
        self.send_json(
            401,
            {"ok": False, "error": "Relay auth required"},
            headers={"WWW-Authenticate": 'Bearer realm="openclaw-publish-relay"'},
        )
        return False

    def do_GET(self) -> None:
        dispatch(self, "GET")

    def do_POST(self) -> None:
        try:
            dispatch(self, "POST")
        finally:
            self.facade._finish_audit_transaction()

    def do_HEAD(self) -> None:
        dispatch(self, "HEAD")

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_cors_headers()
        self.send_security_headers()
        self.end_headers()

    def log_message(self, fmt: str, *args: Any) -> None:
        printer = getattr(self.facade, "print", print)
        printer(f"[{self.facade.utc_now()}] {self.address_string()} {fmt % args}")
