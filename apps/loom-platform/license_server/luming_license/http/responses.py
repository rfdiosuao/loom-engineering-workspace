from __future__ import annotations

from typing import Any


class ResponseMixin:
    facade: Any
    path: str
    headers: Any
    wfile: Any

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        data = self.rfile.read(length)
        return self.facade.json.loads(data.decode("utf-8-sig"))

    def send_cors_headers(self) -> None:
        origin = str(self.headers.get("Origin") or "").strip()
        if self.facade.is_admin_request_path(self.path):
            if origin and self.facade.admin_cors_origin_allowed(origin):
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
        else:
            self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header(
            "Access-Control-Allow-Headers",
            "Content-Type, Authorization, X-OpenClaw-Relay-Token, X-Admin-Token, X-Admin-Session",
        )

    def send_security_headers(self, *, cache_control: str | None = None) -> None:
        path = self.facade.urlparse(self.path).path
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self' 'unsafe-inline' https://static.cloudflareinsights.com; "
            "style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self' https://cloudflareinsights.com; "
            "font-src 'self' data:; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'self'",
        )
        self.send_header(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.send_header(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
        )
        self.send_header(
            "Cache-Control",
            cache_control or ("no-store" if path.startswith("/admin") else "no-cache"),
        )

    def _send_bytes(
        self,
        status: int,
        data: bytes,
        content_type: str,
        headers: dict[str, str] | None,
        *,
        write_body: bool,
        cache_control: str | None = None,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_cors_headers()
        self.send_security_headers(cache_control=cache_control)
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        if write_body:
            self.wfile.write(data)

    def send_json(
        self,
        status: int,
        payload: dict[str, Any],
        headers: dict[str, str] | None = None,
        *,
        write_body: bool = True,
    ) -> None:
        data = self.facade.json.dumps(payload, ensure_ascii=False).encode("utf-8")
        finalize = getattr(self.facade, "_finalize_audit_response", None)
        if finalize is None:
            active_transaction = getattr(
                self.facade, "_active_audit_transaction", lambda: None
            )
            transaction = active_transaction()
            if transaction and transaction.audit_written and 200 <= status < 300:
                transaction.response_sent = True
        elif not finalize(status):
            status = 500
            headers = None
            data = self.facade.json.dumps(
                {"ok": False, "error": "Internal server error"}, ensure_ascii=False
            ).encode("utf-8")
        self._send_bytes(
            status,
            data,
            "application/json; charset=utf-8",
            headers,
            write_body=write_body,
        )

    def send_html(self, status: int, html: str, *, write_body: bool = True) -> None:
        self._send_bytes(
            status,
            html.encode("utf-8"),
            "text/html; charset=utf-8",
            None,
            write_body=write_body,
        )

    def send_file(
        self, status: int, path: str, content_type: str, *, write_body: bool = True
    ) -> None:
        file_error = getattr(self.facade, "OSError", OSError)
        try:
            file_open = getattr(self.facade, "open", open)
            with file_open(path, "rb") as file:
                data = file.read()
        except file_error:
            self.send_json(404, {"error": "file not found"}, write_body=write_body)
            return
        self._send_bytes(
            status,
            data,
            content_type,
            None,
            write_body=write_body,
            cache_control="public, max-age=3600",
        )
