from __future__ import annotations

import argparse
import json
import os
import re
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse


Json = dict[str, Any]
SENSITIVE_KEY_MARKERS = ("token", "secret", "password", "credential", "api_key", "apikey", "authorization")


class TemplateStore:
    def __init__(self, path: str):
        self.path = path

    def list_templates(self) -> Json:
        state = self._read()
        templates = [item for item in state.get("templates", []) if isinstance(item, dict)]
        templates.sort(key=lambda item: str(item.get("updatedAt") or ""), reverse=True)
        return {
            "schema": "loom.template_cloud.v1",
            "updatedAt": state.get("updatedAt") or now_iso(),
            "stats": {
                "total": len(templates),
                "uploaded": len(templates),
                "industries": len({str(item.get("industry") or "") for item in templates if item.get("industry")}),
            },
            "templates": templates,
        }

    def upsert(self, payload: Json) -> Json:
        state = self._read()
        templates = [item for item in state.get("templates", []) if isinstance(item, dict)]
        template_id = template_id_from(payload.get("templateId") or payload.get("id") or payload.get("name"))
        existing = next((item for item in templates if item.get("templateId") == template_id), None)
        version = int(existing.get("version", 0)) + 1 if existing else int(payload.get("version") or 1)
        upload_count = int(existing.get("uploadCount", 0)) + 1 if existing else 1
        now = now_iso()
        template = redact_json(
            {
                **payload,
                "schema": "loom.acquisition_template.v1",
                "templateId": template_id,
                "version": version,
                "uploadCount": upload_count,
                "createdAt": existing.get("createdAt") if existing else payload.get("createdAt") or now,
                "updatedAt": now,
            }
        )
        state["templates"] = [item for item in templates if item.get("templateId") != template_id]
        state["templates"].append(template)
        state["updatedAt"] = now
        self._write(state)
        return template

    def _read(self) -> Json:
        if not os.path.exists(self.path):
            return {"schema": "loom.template_cloud.v1", "updatedAt": "", "templates": []}
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            if not isinstance(data, dict):
                raise ValueError("state must be an object")
            data.setdefault("templates", [])
            return data
        except (OSError, json.JSONDecodeError, ValueError):
            return {"schema": "loom.template_cloud.v1", "updatedAt": "", "templates": []}

    def _write(self, state: Json) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = f"{self.path}.tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(redact_json(state), handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(tmp, self.path)


def create_response(store: TemplateStore, payload: Json, *, public_base: str) -> Json:
    template = store.upsert(payload)
    base = public_base.rstrip("/")
    return {
        "ok": True,
        "templateId": template["templateId"],
        "version": template["version"],
        "url": f"{base}/template-admin/?templateId={template['templateId']}" if base else f"/template-admin/?templateId={template['templateId']}",
    }


def require_bearer(header: str, token: str) -> bool:
    if not token:
        return False
    prefix = "Bearer "
    return header.startswith(prefix) and header[len(prefix) :].strip() == token


def can_write_template(header: str, token: str, *, allow_public_upload: bool = False) -> bool:
    return allow_public_upload or require_bearer(header, token)


def make_handler(store: TemplateStore, token: str, public_base: str, *, allow_public_upload: bool = False):
    class Handler(BaseHTTPRequestHandler):
        server_version = "LoomTemplateCloud/1.0"

        def do_OPTIONS(self) -> None:
            self.send_response(204)
            self._cors()
            self.end_headers()

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/health":
                self._json({"ok": True, "service": "loom-template-cloud", "time": now_iso()})
                return
            if parsed.path in {"/template-admin", "/template-admin/"}:
                self._html(admin_html(public_base))
                return
            if parsed.path == "/api/loom/templates":
                if not self._authorized():
                    self._json({"error": "unauthorized"}, 401)
                    return
                payload = store.list_templates()
                query = parse_qs(parsed.query)
                template_id = (query.get("templateId") or [""])[0]
                if template_id:
                    payload["templates"] = [item for item in payload["templates"] if item.get("templateId") == template_id]
                self._json(payload)
                return
            self._json({"error": "not_found"}, 404)

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path != "/api/loom/templates":
                self._json({"error": "not_found"}, 404)
                return
            if not self._can_write():
                self._json({"error": "unauthorized"}, 401)
                return
            try:
                length = int(self.headers.get("Content-Length") or "0")
                payload = decode_payload(self.rfile.read(min(length, 2_000_000)))
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
                self._json({"error": f"invalid_json: {exc}"}, 400)
                return
            self._json(create_response(store, payload, public_base=public_base), 201)

        def _authorized(self) -> bool:
            return require_bearer(self.headers.get("Authorization", ""), token)

        def _can_write(self) -> bool:
            return can_write_template(self.headers.get("Authorization", ""), token, allow_public_upload=allow_public_upload)

        def _json(self, payload: Json, status: int = 200) -> None:
            data = json.dumps(redact_json(payload), ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self._cors()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _html(self, html: str) -> None:
            data = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _cors(self) -> None:
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

        def log_message(self, fmt: str, *args: Any) -> None:
            print(f"{self.address_string()} - {fmt % args}")

    return Handler


def admin_html(public_base: str) -> str:
    api_base = public_base.rstrip("/")
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>麓鸣获客模板云后台</title>
  <style>
    body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #eef2f5; color: #16212c; }}
    main {{ max-width: 1120px; margin: 0 auto; padding: 32px 20px; }}
    header {{ display: flex; justify-content: space-between; gap: 16px; align-items: flex-end; margin-bottom: 20px; }}
    h1 {{ margin: 0; font-size: 32px; line-height: 1.15; }}
    .muted {{ color: #647181; font-size: 13px; }}
    .panel {{ background: #fff; border: 1px solid #d9e1e8; border-radius: 8px; padding: 16px; margin-bottom: 16px; }}
    .controls {{ display: grid; grid-template-columns: 1fr auto; gap: 10px; }}
    input {{ min-height: 38px; border: 1px solid #cbd5df; border-radius: 8px; padding: 0 12px; font-size: 14px; }}
    button {{ border: 0; border-radius: 8px; padding: 0 16px; min-height: 38px; background: #075e4f; color: #fff; font-weight: 800; cursor: pointer; }}
    .stats {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }}
    .stat {{ background: #f8fafc; border: 1px solid #e1e7ee; border-radius: 8px; padding: 12px; }}
    table {{ width: 100%; border-collapse: collapse; background: #fff; border-radius: 8px; overflow: hidden; }}
    th, td {{ border-bottom: 1px solid #e5ebf0; padding: 10px; text-align: left; font-size: 13px; vertical-align: top; }}
    th {{ background: #f8fafc; font-size: 12px; color: #475569; }}
    code {{ font-size: 12px; color: #0f766e; }}
    @media (max-width: 700px) {{ header, .controls {{ display: block; }} input, button {{ width: 100%; margin-top: 8px; }} .stats {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
  <main>
    <header>
      <div>
        <div class="muted">LOOM TEMPLATE CLOUD</div>
        <h1>麓鸣获客模板云后台</h1>
      </div>
      <div class="muted">API: <code>{api_base or ""}/api/loom/templates</code></div>
    </header>
    <section class="panel">
      <div class="controls">
        <input id="token" type="password" placeholder="输入后台 Token，保存在本浏览器 localStorage" />
        <button id="load">查看模板</button>
      </div>
      <div id="message" class="muted" style="margin-top:10px;">请输入服务器 Token 后查看。</div>
    </section>
    <section class="panel stats">
      <div class="stat"><div class="muted">模板总数</div><strong id="total">0</strong></div>
      <div class="stat"><div class="muted">已上传</div><strong id="uploaded">0</strong></div>
      <div class="stat"><div class="muted">行业数</div><strong id="industries">0</strong></div>
    </section>
    <section class="panel">
      <table>
        <thead><tr><th>模板</th><th>行业/平台</th><th>版本</th><th>更新时间</th><th>安全策略</th></tr></thead>
        <tbody id="rows"><tr><td colspan="5" class="muted">暂无数据</td></tr></tbody>
      </table>
    </section>
  </main>
  <script>
    const api = "{api_base}/api/loom/templates" || "/api/loom/templates";
    const tokenInput = document.getElementById("token");
    const message = document.getElementById("message");
    tokenInput.value = localStorage.getItem("loomTemplateCloudToken") || "";
    document.getElementById("load").onclick = async () => {{
      const token = tokenInput.value.trim();
      localStorage.setItem("loomTemplateCloudToken", token);
      message.textContent = "正在读取模板...";
      const resp = await fetch(api, {{ headers: {{ Authorization: "Bearer " + token }} }});
      if (!resp.ok) {{ message.textContent = "读取失败：" + resp.status; return; }}
      const data = await resp.json();
      document.getElementById("total").textContent = data.stats?.total || 0;
      document.getElementById("uploaded").textContent = data.stats?.uploaded || 0;
      document.getElementById("industries").textContent = data.stats?.industries || 0;
      const rows = document.getElementById("rows");
      rows.innerHTML = "";
      for (const item of data.templates || []) {{
        const tr = document.createElement("tr");
        tr.innerHTML = `<td><strong>${{escapeHtml(item.name || item.templateId)}}</strong><br><code>${{escapeHtml(item.templateId)}}</code></td><td>${{escapeHtml(item.industry || "")}}<br>${{escapeHtml((item.platforms || []).join(" / "))}}</td><td>v${{item.version || 1}}<br><span class="muted">${{item.uploadCount || 1}} 次</span></td><td>${{escapeHtml(item.updatedAt || "")}}</td><td>${{escapeHtml(item.safetyPolicy?.sendMode || "draft_only")}}<br>${{item.safetyPolicy?.manualConfirm === false ? "未声明人工确认" : "人工确认"}}</td>`;
        rows.appendChild(tr);
      }}
      if (!rows.children.length) rows.innerHTML = '<tr><td colspan="5" class="muted">暂无模板</td></tr>';
      message.textContent = "已加载";
    }};
    function escapeHtml(value) {{
      return String(value ?? "").replace(/[&<>"']/g, (ch) => ({{ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }}[ch]));
    }}
  </script>
</body>
</html>"""


def decode_payload(data: bytes) -> Json:
    payload = json.loads(data.decode("utf-8-sig")) if data else {}
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    return payload


def template_id_from(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", text, flags=re.I).strip("-")
    return text[:100] or f"template-{uuid.uuid4().hex[:10]}"


def redact_json(value: Any) -> Any:
    if isinstance(value, dict):
        safe: Json = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if any(marker in lowered for marker in SENSITIVE_KEY_MARKERS):
                continue
            safe[key] = redact_json(item)
        return safe
    if isinstance(value, list):
        return [redact_json(item) for item in value]
    if isinstance(value, str):
        return redact(value)
    return value


def redact(value: Any) -> str:
    text = str(value or "")
    text = re.sub(r"Bearer\s+[A-Za-z0-9._\-]+", "Bearer ***", text, flags=re.I)
    text = re.sub(r"\b1[3-9]\d{9}\b", "[phone-redacted]", text)
    text = re.sub(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", "[email-redacted]", text)
    text = re.sub(r"(secret|token|password|credential)[-_:= ]+[A-Za-z0-9._\-]+", r"\1=***", text, flags=re.I)
    return text


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def main() -> None:
    parser = argparse.ArgumentParser(description="LOOM acquisition template cloud server")
    parser.add_argument("command", nargs="?", default="serve", choices=["serve"])
    parser.add_argument("--host", default=os.environ.get("TEMPLATE_CLOUD_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("TEMPLATE_CLOUD_PORT", "18793")))
    parser.add_argument("--db", default=os.environ.get("TEMPLATE_CLOUD_DB", "/opt/loom-template-cloud/templates.json"))
    parser.add_argument("--token", default=os.environ.get("TEMPLATE_CLOUD_TOKEN", ""))
    parser.add_argument("--public-base", default=os.environ.get("TEMPLATE_CLOUD_PUBLIC_BASE", ""))
    parser.add_argument(
        "--allow-public-upload",
        action="store_true",
        default=str(os.environ.get("TEMPLATE_CLOUD_ALLOW_PUBLIC_UPLOAD", "")).strip().lower() in {"1", "true", "yes"},
    )
    args = parser.parse_args()
    if not args.token:
        raise SystemExit("TEMPLATE_CLOUD_TOKEN is required")
    store = TemplateStore(args.db)
    httpd = ThreadingHTTPServer(
        (args.host, args.port),
        make_handler(store, args.token, args.public_base, allow_public_upload=args.allow_public_upload),
    )
    print(f"loom-template-cloud listening on {args.host}:{args.port}")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
