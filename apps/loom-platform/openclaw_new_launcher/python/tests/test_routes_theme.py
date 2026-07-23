from __future__ import annotations

import os
import sys
import unittest
from types import SimpleNamespace


PYTHON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)


from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from api.routes_theme import register_theme_routes


class ThemeRouteTests(unittest.TestCase):
    def test_post_current_persists_selected_theme(self) -> None:
        app = FastAPI()
        saved = []
        selected_theme = {
            "name": "Dark",
            "colors": {"app_bg": "#111111"},
        }
        manager = SimpleNamespace(
            get_current=lambda _license: {"name": "Current"},
            get_by_merchant=lambda theme_id: (
                selected_theme if theme_id == "dark" else None
            ),
            save_theme=lambda theme: saved.append(theme),
        )
        register_theme_routes(app, _ctx(manager))
        client = TestClient(app)

        response = client.post("/api/theme/current", json={"theme": "dark"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(saved, [selected_theme])
        self.assertEqual(response.json()["theme"], selected_theme)
        self.assertEqual(response.json()["themeId"], "dark")

    def test_post_current_rejects_unknown_theme(self) -> None:
        app = FastAPI()
        manager = SimpleNamespace(
            get_current=lambda _license: {"name": "Current"},
            get_by_merchant=lambda _theme_id: None,
            save_theme=lambda _theme: self.fail("unknown theme must not be saved"),
        )
        register_theme_routes(app, _ctx(manager))
        client = TestClient(app)

        response = client.post("/api/theme/current", json={"theme": "missing"})

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "theme_not_found")


def _ctx(manager):
    async def body(request):
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        return payload if isinstance(payload, dict) else {}

    def fastapi_json(data: dict, status_code: int = 200):
        payload = dict(data)
        payload["_meta"] = {
            "ok": 200 <= status_code < 400 and "error" not in payload,
            "status": status_code,
        }
        return JSONResponse(status_code=status_code, content=payload)

    return SimpleNamespace(
        auth_error=lambda _request: None,
        body=body,
        fastapi_json=fastapi_json,
        get_license_mgr=lambda: SimpleNamespace(current_license=lambda: {}),
        get_theme_mgr=lambda: manager,
    )


if __name__ == "__main__":
    unittest.main()
