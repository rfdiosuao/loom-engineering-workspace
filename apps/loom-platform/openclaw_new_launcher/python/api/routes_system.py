"""System information FastAPI routes."""

from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import Request


API_CONTRACT_VERSION = "loom.bridge.api.v2"
BRIDGE_CAPABILITIES = (
    "system.contract.v1",
    "phone.config.v2",
    "phone.task.v2",
    "matrix.dispatch.v2",
    "acquisition.v1",
    "feishu.reconcile.v1",
    "media.library.v1",
)


def _launcher_version() -> str:
    runtime_version = str(os.environ.get("LOOM_APP_VERSION") or "").strip()
    if runtime_version:
        return runtime_version
    package_path = Path(__file__).resolve().parents[2] / "package.json"
    try:
        payload = json.loads(package_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "unknown"
    return str(payload.get("version") or "unknown")


def register_system_routes(app, ctx) -> None:
    @app.api_route("/api/system/info", methods=["GET", "POST"])
    async def system_info(request: Request):
        if error := ctx.auth_error(request):
            return error
        updater = ctx.get_updater()
        launcher_version = _launcher_version()
        capabilities = list(BRIDGE_CAPABILITIES)
        return ctx.fastapi_json({
            "node_path": ctx.paths.node_exe,
            "base_path": ctx.paths.base_path,
            "openclaw_version": updater.current_version(),
            "launcher_version": launcher_version,
            "api_contract_version": API_CONTRACT_VERSION,
            "capabilities": capabilities,
            "bridge": {
                "version": launcher_version,
                "apiContractVersion": API_CONTRACT_VERSION,
                "capabilities": capabilities,
            },
        })
