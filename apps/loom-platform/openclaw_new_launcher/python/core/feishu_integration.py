"""Feishu/Lark lead-table integration for the acquisition workbench."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from functools import wraps
from typing import Any, Callable, Dict

from core.paths import AppPaths


Json = Dict[str, Any]
LEAD_TABLE_FIELDS = [
    "来源平台",
    "来源任务",
    "客户昵称/账号",
    "主页或内容链接",
    "原始线索内容",
    "痛点/需求",
    "意向等级",
    "推荐跟进动作",
    "跟进话术草稿",
    "状态",
    "负责人",
    "创建时间",
    "更新时间",
    "任务日志 ID",
]
_FEISHU_STATE_LOCK = threading.RLock()


def _feishu_state_guard(method):
    @wraps(method)
    def guarded(*args, **kwargs):
        with _FEISHU_STATE_LOCK:
            return method(*args, **kwargs)

    return guarded


def _feishu_sync_guard(method):
    @wraps(method)
    def guarded(self, lead: Json):
        safe_lead = _lead_fields(lead)
        try:
            return method(self, safe_lead)
        except Exception as exc:
            return self._cache_pending(
                safe_lead,
                "sync_failed",
                f"飞书同步异常: {_redact(str(exc))}",
            )

    return guarded


class FeishuAcquisitionIntegration:
    def __init__(
        self,
        paths: AppPaths,
        *,
        command_resolver: Callable[[str], str | None] | None = None,
        runner: Callable[..., Json] | None = None,
    ):
        self.paths = paths
        self.command_resolver = command_resolver or shutil.which
        self.runner = runner or _run_command

    @property
    def state_path(self) -> str:
        return os.path.join(self.paths.launcher_dir, "feishu-acquisition.json")

    def doctor(self) -> Json:
        cli_path = self._cli_path()
        version = ""
        if cli_path:
            completed = self.runner(["lark-cli", "--version"], timeout=8)
            if _returncode(completed) == 0:
                version = _redact((completed.get("stdout") or "").strip())
        status = self.status()
        return {
            "schema": "loom.feishu_acquisition.doctor.v1",
            "cli": {
                "installed": bool(cli_path),
                "path": _redact_path(cli_path),
                "version": version,
                "installCommand": "npm install -g @larksuite/cli@latest",
                "requiresInstallConfirmation": not bool(cli_path),
            },
            "auth": status["auth"],
            "table": status["table"],
            "connected": status["connected"],
        }

    def install_cli(self, *, confirmed: bool = False) -> Json:
        if self._cli_path():
            return {"installed": True, "executed": False, "message": "lark-cli already available"}
        command = ["npm", "install", "-g", "@larksuite/cli@latest"]
        if not confirmed:
            return {"installed": False, "executed": False, "requiresConfirmation": True, "command": " ".join(command)}
        completed = self.runner(command, timeout=600)
        ok = _returncode(completed) == 0
        return {
            "installed": ok,
            "executed": True,
            "command": " ".join(command),
            "error": "" if ok else _redact(completed.get("stderr") or completed.get("stdout") or "install failed"),
        }

    def status(self) -> Json:
        state = self._load_state()
        auth = self._auth_status()
        table = state.get("table") if isinstance(state.get("table"), dict) else {}
        connected = bool(self._cli_path() and auth.get("loggedIn") and table.get("baseToken") and table.get("tableId"))
        return {
            "schema": "loom.feishu_acquisition.status.v1",
            "cliInstalled": bool(self._cli_path()),
            "auth": auth,
            "table": _redact_json(table),
            "connected": connected,
            "lastSync": _redact_json(state.get("lastSync") if isinstance(state.get("lastSync"), dict) else {}),
            "pendingCount": len(self.pending_syncs()),
            "pendingVerificationCount": len(self.pending_verifications()),
        }

    def start_login(self) -> Json:
        self._require_cli()
        completed = self.runner(["lark-cli", "auth", "login", "--recommend", "--no-wait", "--json"], timeout=30)
        if _returncode(completed) != 0:
            return {"ok": False, "error": _redact(completed.get("stderr") or completed.get("stdout") or "login failed")}
        payload = _json_loads(completed.get("stdout") or "{}")
        login_url = str(payload.get("verification_uri_complete") or payload.get("verification_url") or payload.get("verification_uri") or "")
        user_code = str(payload.get("user_code") or "")
        qr_ascii = ""
        if login_url:
            qr = self.runner(["lark-cli", "auth", "qrcode", login_url, "--ascii"], timeout=20)
            if _returncode(qr) == 0:
                qr_ascii = _redact(qr.get("stdout") or "")
        return {
            "ok": bool(login_url),
            "loginUrl": _redact_url(login_url),
            "verificationUrl": _redact_url(str(payload.get("verification_uri") or "")),
            "userCode": user_code,
            "qrAscii": qr_ascii,
            "message": "请用飞书扫码或打开登录链接完成授权。",
        }

    @_feishu_state_guard
    def bind_table(self, raw: Json) -> Json:
        state = self._load_state()
        table = {
            "url": _redact_url(str(raw.get("url") or "")),
            "baseToken": _clip(raw.get("baseToken") or _extract_base_token(raw.get("url")), 120),
            "tableId": _clip(raw.get("tableId") or _extract_table_id(raw.get("url")), 120),
            "name": _clip(raw.get("name") or "麓鸣获客线索表", 120),
            "boundAt": _now_iso(),
            "fields": LEAD_TABLE_FIELDS,
        }
        state["table"] = table
        state["updatedAt"] = _now_iso()
        self._write_state(state)
        return {"table": _redact_json(table), "status": self.status()}

    @_feishu_state_guard
    def create_table(self, *, confirmed: bool = False) -> Json:
        self._require_cli()
        if not confirmed:
            return {"requiresConfirmation": True, "executed": False, "name": "麓鸣获客线索表", "fields": LEAD_TABLE_FIELDS}
        fields = json.dumps([{"name": name, "type": "text"} for name in LEAD_TABLE_FIELDS], ensure_ascii=False)
        completed = self.runner(
            [
                "lark-cli",
                "base",
                "+base-create",
                "--name",
                "麓鸣获客线索表",
                "--table-name",
                "线索池",
                "--fields",
                fields,
                "--as",
                "user",
                "--format",
                "json",
            ],
            timeout=120,
        )
        ok = _returncode(completed) == 0
        payload = _json_loads(completed.get("stdout") or "{}")
        if ok:
            base_token = str(payload.get("app_token") or payload.get("base_token") or payload.get("token") or "")
            table_id = _first_table_id(payload)
            if base_token and table_id:
                self.bind_table({"baseToken": base_token, "tableId": table_id, "url": ""})
        return {"ok": ok, "result": _redact_json(payload), "error": "" if ok else _redact(completed.get("stderr") or "")}

    def test_write(self) -> Json:
        test_id = f"test_{int(time.time())}_{uuid.uuid4().hex[:12]}"
        lead = {
            "leadId": test_id,
            "platform": "dry-run",
            "sourceTask": "飞书测试写入",
            "title": "测试客户",
            "summary": "这是一条麓鸣获客线索表测试记录",
            "need": "验证字段和权限",
            "intentLevel": "测试",
            "recommendedAction": "确认表格能写入",
            "draft": "这是一条测试草稿，不会触达真实客户。",
            "status": "test",
            "owner": "麓鸣",
            "logId": test_id,
        }
        return self.sync_lead(lead)

    @_feishu_state_guard
    @_feishu_sync_guard
    def sync_lead(self, lead: Json) -> Json:
        safe_lead = _lead_fields(lead)
        state = self._load_state()
        table = state.get("table") if isinstance(state.get("table"), dict) else {}
        if not self._cli_path() or not table.get("baseToken") or not table.get("tableId"):
            return self._cache_pending(safe_lead, "pending_sync", "飞书未连接或未绑定线索表")
        lookup = self._lookup_remote_record(table, safe_lead)
        if not lookup.get("ok"):
            return self._cache_pending(safe_lead, "sync_failed", lookup.get("error") or "飞书业务键查询失败")
        if lookup.get("status") == "conflict":
            return self._cache_pending(safe_lead, "sync_conflict", "飞书存在重复业务键，请人工合并后重试")
        existing_record_id = str(lookup.get("recordId") or "")
        command = [
            "lark-cli",
            "base",
            "+record-upsert",
            "--base-token",
            str(table.get("baseToken")),
            "--table-id",
            str(table.get("tableId")),
        ]
        if existing_record_id:
            command.extend(["--record-id", existing_record_id])
        command.extend(
            [
                "--json",
                json.dumps(safe_lead["fields"], ensure_ascii=False),
                "--as",
                "user",
                "--format",
                "json",
            ]
        )
        completed = self.runner(command, timeout=60)
        ok = _returncode(completed) == 0
        payload = _json_loads(completed.get("stdout") or "{}")
        record_id = _record_id(payload) or existing_record_id
        if not record_id:
            recovered = self._lookup_remote_record(table, safe_lead)
            if recovered.get("status") == "conflict":
                return self._cache_pending(safe_lead, "sync_conflict", "飞书写入后发现重复业务键，请人工合并")
            if recovered.get("ok"):
                record_id = str(recovered.get("recordId") or "")
        if record_id:
            verification = self._verify_remote_record(table, record_id, safe_lead["fields"])
            verified = verification.get("verified") is True
            if not ok and not verified:
                error = _redact(completed.get("stderr") or completed.get("stdout") or "飞书写入失败且远端记录未确认")
                return self._cache_pending(safe_lead, "sync_failed", error)
            result = {
                "leadId": safe_lead["leadId"],
                "syncStatus": "synced" if verified else "sync_unverified",
                "recordId": record_id,
                "syncedAt": _now_iso(),
                "verificationStatus": "verified" if verified else "pending",
                "verificationError": "" if verified else _redact(verification.get("error") or "飞书记录回读未确认"),
            }
            pending_verification = state.get("pendingVerification")
            if not isinstance(pending_verification, list):
                pending_verification = []
            pending_verification = [
                item
                for item in pending_verification
                if not isinstance(item, dict) or str(item.get("recordId") or "") != record_id
            ]
            if not verified:
                pending_verification.append(
                    {
                        "leadId": safe_lead["leadId"],
                        "recordId": record_id,
                        "fields": safe_lead["fields"],
                        "verificationStatus": "pending",
                        "verificationError": result["verificationError"],
                        "updatedAt": _now_iso(),
                    }
                )
            state["pendingVerification"] = pending_verification[-500:]
            pending_sync = state.get("pendingSync")
            if isinstance(pending_sync, list):
                state["pendingSync"] = [
                    item
                    for item in pending_sync
                    if not isinstance(item, dict) or str(item.get("leadId") or "") != safe_lead["leadId"]
                ]
            state["lastSync"] = result
            self._write_state(state)
            return _redact_json(result)
        if ok:
            return self._cache_pending(safe_lead, "sync_failed", "飞书写入成功但按业务键无法确认远端记录")
        error = _redact(completed.get("stderr") or completed.get("stdout") or "飞书写入失败")
        return self._cache_pending(safe_lead, "sync_failed", error)

    def _lookup_remote_record(self, table: Json, safe_lead: Json) -> Json:
        business_key = str(safe_lead.get("businessKey") or safe_lead.get("leadId") or "").strip()
        if not business_key:
            return {"ok": False, "status": "error", "error": "飞书业务键为空"}
        filter_json = json.dumps(
            {"logic": "and", "conditions": [["任务日志 ID", "==", business_key]]},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        completed = self.runner(
            [
                "lark-cli",
                "base",
                "+record-list",
                "--base-token",
                str(table.get("baseToken")),
                "--table-id",
                str(table.get("tableId")),
                "--filter-json",
                filter_json,
                "--limit",
                "3",
                "--as",
                "user",
                "--format",
                "json",
            ],
            timeout=45,
        )
        if _returncode(completed) != 0:
            return {
                "ok": False,
                "status": "error",
                "error": _redact(completed.get("stderr") or completed.get("stdout") or "飞书业务键查询失败"),
            }
        records = _record_rows(_json_loads(completed.get("stdout") or "{}"))
        record_ids = list(dict.fromkeys(_record_id(row) for row in records if _record_id(row)))
        if not record_ids:
            return {"ok": True, "status": "missing", "recordId": ""}
        if len(record_ids) > 1:
            return {"ok": True, "status": "conflict", "recordIds": record_ids[:3]}
        return {"ok": True, "status": "found", "recordId": record_ids[0]}

    def pending_syncs(self) -> list[Json]:
        state = self._load_state()
        rows = state.get("pendingSync")
        return _redact_json(rows if isinstance(rows, list) else [])

    def pending_verifications(self) -> list[Json]:
        state = self._load_state()
        rows = state.get("pendingVerification")
        return _redact_json(rows if isinstance(rows, list) else [])

    @_feishu_state_guard
    def reconcile(self) -> Json:
        state = self._load_state()
        table = state.get("table") if isinstance(state.get("table"), dict) else {}
        rows = state.get("pendingVerification")
        if not isinstance(rows, list):
            rows = []
        verified_rows: list[Json] = []
        remaining: list[Json] = []
        for raw in rows:
            if not isinstance(raw, dict):
                continue
            record_id = str(raw.get("recordId") or "").strip()
            expected_fields = raw.get("fields") if isinstance(raw.get("fields"), dict) else {}
            verification = self._verify_remote_record(table, record_id, expected_fields)
            if verification.get("verified") is True:
                verified_rows.append({"leadId": raw.get("leadId"), "recordId": record_id, "verificationStatus": "verified"})
                continue
            remaining.append(
                {
                    **raw,
                    "verificationStatus": "pending",
                    "verificationError": _redact(verification.get("error") or "飞书记录回读未确认"),
                    "updatedAt": _now_iso(),
                }
            )
        state["pendingVerification"] = remaining[-500:]
        state["updatedAt"] = _now_iso()
        if verified_rows:
            state["lastSync"] = {**verified_rows[-1], "syncStatus": "synced", "syncedAt": _now_iso()}
        self._write_state(state)
        return _redact_json(
            {
                "checked": len(rows),
                "verified": len(verified_rows),
                "pending": len(remaining),
                "results": verified_rows,
                "status": self.status(),
            }
        )

    @_feishu_state_guard
    def retry_pending(self) -> Json:
        rows = self.pending_syncs()
        results: list[Json] = []
        for row in rows:
            try:
                results.append(self.sync_lead(row))
            except Exception as exc:
                safe_lead = _lead_fields(row)
                results.append(
                    self._cache_pending(
                        safe_lead,
                        "sync_failed",
                        f"飞书重试异常: {_redact(str(exc))}",
                    )
                )
        reconciliation = self.reconcile()
        return {"retried": len(rows), "results": results, "reconciliation": reconciliation, "status": self.status()}

    def _verify_remote_record(self, table: Json, record_id: str, expected_fields: Json) -> Json:
        if not self._cli_path() or not table.get("baseToken") or not table.get("tableId") or not record_id:
            return {"verified": False, "error": "飞书回读所需配置不完整"}
        completed = self.runner(
            [
                "lark-cli",
                "base",
                "+record-get",
                "--base-token",
                str(table.get("baseToken")),
                "--table-id",
                str(table.get("tableId")),
                "--record-id",
                record_id,
                "--as",
                "user",
                "--format",
                "json",
            ],
            timeout=45,
        )
        if _returncode(completed) != 0:
            return {"verified": False, "error": _redact(completed.get("stderr") or completed.get("stdout") or "飞书记录回读失败")}
        payload = _json_loads(completed.get("stdout") or "{}")
        remote_fields = _record_fields(payload)
        if not isinstance(remote_fields, dict):
            return {"verified": False, "error": "飞书回读结果缺少 fields"}
        mismatched = [key for key, value in expected_fields.items() if not _field_value_matches(value, remote_fields.get(key))]
        if mismatched:
            return {"verified": False, "error": f"飞书字段尚未一致: {', '.join(mismatched[:5])}"}
        return {"verified": True, "recordId": record_id}

    def _cache_pending(self, safe_lead: Json, status: str, error: str) -> Json:
        state = self._load_state()
        pending = state.get("pendingSync")
        if not isinstance(pending, list):
            pending = []
        row = {
            "leadId": safe_lead["leadId"],
            "businessKey": safe_lead.get("businessKey") or safe_lead["leadId"],
            "fields": safe_lead["fields"],
            "syncStatus": status,
            "syncError": _redact(error)[:240],
            "updatedAt": _now_iso(),
        }
        pending = [item for item in pending if not isinstance(item, dict) or item.get("leadId") != row["leadId"]]
        pending.append(row)
        state["pendingSync"] = pending[-500:]
        state["lastSync"] = row
        state["updatedAt"] = _now_iso()
        self._write_state(state)
        return _redact_json({"leadId": row["leadId"], "syncStatus": status, "syncError": row["syncError"]})

    def _auth_status(self) -> Json:
        if not self._cli_path():
            return {"loggedIn": False, "botReady": False, "message": "lark-cli 未安装"}
        try:
            completed = self.runner(["lark-cli", "auth", "status"], timeout=15)
        except (OSError, subprocess.SubprocessError) as exc:
            return {"loggedIn": False, "botReady": False, "message": _redact(exc)}
        text = (completed.get("stdout") or "").strip()
        data = _json_loads(text)
        user = data.get("identities", {}).get("user", {}) if isinstance(data.get("identities"), dict) else {}
        bot = data.get("identities", {}).get("bot", {}) if isinstance(data.get("identities"), dict) else {}
        return {
            "loggedIn": bool(user.get("available") and user.get("status") == "ready"),
            "botReady": bool(bot.get("available") and bot.get("status") == "ready"),
            "identity": str(data.get("identity") or ""),
            "userName": _clip(user.get("userName") or data.get("userName"), 80),
            "message": _redact(str(user.get("message") or data.get("note") or text[:160])),
        }

    def _require_cli(self) -> None:
        if not self._cli_path():
            raise RuntimeError("lark-cli is not installed")

    def _cli_path(self) -> str:
        return str(self.command_resolver("lark-cli") or "").strip()

    def _load_state(self) -> Json:
        if not os.path.exists(self.state_path):
            return {
                "schema": "loom.feishu_acquisition.v1",
                "updatedAt": "",
                "table": {},
                "pendingSync": [],
                "pendingVerification": [],
                "lastSync": {},
            }
        try:
            with open(self.state_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            if not isinstance(data, dict):
                return {}
            data.setdefault("pendingSync", [])
            data.setdefault("pendingVerification", [])
            data.setdefault("lastSync", {})
            return data
        except (OSError, json.JSONDecodeError):
            return {
                "schema": "loom.feishu_acquisition.v1",
                "updatedAt": "",
                "table": {},
                "pendingSync": [],
                "pendingVerification": [],
                "lastSync": {},
            }

    def _write_state(self, state: Json) -> None:
        os.makedirs(os.path.dirname(self.state_path), exist_ok=True)
        state["schema"] = "loom.feishu_acquisition.v1"
        tmp = f"{self.state_path}.tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(_redact_json(state), handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(tmp, self.state_path)


def _run_command(args: list[str], *, timeout: int = 30) -> Json:
    run_args = list(args)
    if args and args[0] == "lark-cli":
        resolved = shutil.which("lark-cli")
        if resolved:
            run_args[0] = resolved
    completed = subprocess.run(
        run_args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return {"returncode": completed.returncode, "stdout": completed.stdout or "", "stderr": completed.stderr or ""}


def _lead_fields(lead: Json) -> Json:
    now = _now_iso()
    lead_id = _clip(lead.get("leadId") or lead.get("id") or f"lead_{int(time.time())}", 80)
    existing_fields = lead.get("fields") if isinstance(lead.get("fields"), dict) else None
    existing_business_key = existing_fields.get("任务日志 ID") if existing_fields else ""
    business_key = _clip(
        lead.get("dedupeKey")
        or lead.get("businessKey")
        or existing_business_key
        or lead.get("logId")
        or lead.get("taskLogId")
        or lead_id,
        120,
    )
    if existing_fields is not None:
        fields = dict(existing_fields)
        fields["任务日志 ID"] = business_key
        return {"leadId": lead_id, "businessKey": business_key, "fields": _redact_json(fields)}
    fields = {
        "来源平台": _clip(lead.get("platform") or lead.get("sourcePlatform") or lead.get("source") or "manual", 120),
        "来源任务": _clip(lead.get("sourceTask") or lead.get("campaignId") or lead.get("title") or "", 180),
        "客户昵称/账号": _clip(lead.get("nickname") or lead.get("account") or lead.get("title") or "潜在线索", 160),
        "主页或内容链接": _redact_url(str(lead.get("profileUrl") or lead.get("contentUrl") or lead.get("url") or "")),
        "原始线索内容": _clip(lead.get("rawContent") or lead.get("summary") or lead.get("description") or "", 500),
        "痛点/需求": _clip(lead.get("need") or lead.get("painPoint") or lead.get("summary") or "", 300),
        "意向等级": _clip(lead.get("intentLevel") or "待判断", 80),
        "推荐跟进动作": _clip(lead.get("recommendedAction") or "生成草稿后人工确认", 240),
        "跟进话术草稿": _clip(lead.get("draft") or lead.get("draftBody") or "", 500),
        "状态": _clip(lead.get("status") or "new", 80),
        "负责人": _clip(lead.get("owner") or "", 80),
        "创建时间": _clip(lead.get("createdAt") or now, 80),
        "更新时间": _clip(lead.get("updatedAt") or now, 80),
        "任务日志 ID": business_key,
    }
    return {"leadId": lead_id, "businessKey": business_key, "fields": _redact_json(fields)}


def _json_loads(text: str) -> Json:
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def _record_candidates(payload: Json) -> list[Json]:
    candidates: list[Json] = [payload]
    data = payload.get("data")
    if isinstance(data, dict):
        candidates.append(data)
    for container in tuple(candidates):
        for key in ("record", "item"):
            value = container.get(key)
            if isinstance(value, dict):
                candidates.append(value)
        for key in ("records", "items"):
            value = container.get(key)
            if isinstance(value, list):
                candidates.extend(item for item in value if isinstance(item, dict))
    return candidates


def _record_rows(payload: Json) -> list[Json]:
    rows: list[Json] = []
    containers = [payload]
    data = payload.get("data")
    if isinstance(data, dict):
        containers.append(data)
    for container in containers:
        for key in ("records", "items"):
            value = container.get(key)
            if isinstance(value, list):
                rows.extend(item for item in value if isinstance(item, dict))
    return rows


def _record_id(payload: Json) -> str:
    for candidate in _record_candidates(payload):
        value = candidate.get("record_id") or candidate.get("recordId") or candidate.get("id")
        if value:
            return str(value)
    return ""


def _record_fields(payload: Json) -> Json | None:
    for candidate in _record_candidates(payload):
        fields = candidate.get("fields")
        if isinstance(fields, dict):
            return fields
    return None


def _field_value_matches(expected: Any, actual: Any) -> bool:
    if expected == actual:
        return True
    if expected is None and (actual is None or actual == ""):
        return True
    if isinstance(actual, list) and len(actual) == 1:
        return _field_value_matches(expected, actual[0])
    if isinstance(actual, dict):
        for key in ("text", "value", "name"):
            if key in actual and _field_value_matches(expected, actual.get(key)):
                return True
    return str(expected or "").strip() == str(actual or "").strip()


def _returncode(completed: Json) -> int:
    value = completed.get("returncode")
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        return 1


def _first_table_id(payload: Json) -> str:
    tables = payload.get("tables") if isinstance(payload.get("tables"), list) else []
    for item in tables:
        if isinstance(item, dict) and item.get("table_id"):
            return str(item.get("table_id"))
    table = payload.get("table") if isinstance(payload.get("table"), dict) else {}
    return str(table.get("table_id") or payload.get("table_id") or "")


def _extract_base_token(url: Any) -> str:
    match = re.search(r"/base/([A-Za-z0-9_]+)", str(url or ""))
    return match.group(1) if match else ""


def _extract_table_id(url: Any) -> str:
    match = re.search(r"(?:table=|[?&]table_id=)(tbl[A-Za-z0-9_]+)", str(url or ""))
    return match.group(1) if match else ""


def _clip(value: Any, limit: int) -> str:
    return _redact(str(value or "").strip())[:limit]


def _redact_json(value: Any) -> Any:
    if isinstance(value, dict):
        safe: Json = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if str(key) != "baseToken" and any(mark in lowered for mark in ("token", "secret", "password", "credential", "device_code", "refresh")):
                continue
            safe[key] = _redact_json(item)
        return safe
    if isinstance(value, list):
        return [_redact_json(item) for item in value]
    if isinstance(value, str):
        return _redact(value)
    return value


def _redact_path(path: str) -> str:
    return _redact(path)


def _redact_url(value: str) -> str:
    text = _redact(value)
    return re.sub(r"([?&](?:token|secret|key|device_code|refresh_token)=)[^&]+", r"\1***", text, flags=re.I)


def _redact(text: Any) -> str:
    value = str(text or "")
    value = re.sub(r"Bearer\s+[A-Za-z0-9._\-]+", "Bearer ***", value, flags=re.I)
    value = re.sub(r"\b1[3-9]\d{9}\b", "[手机号已隐藏]", value)
    value = re.sub(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", "[邮箱已隐藏]", value)
    value = re.sub(r"(secret|token|password|credential)[-_:= ]+[A-Za-z0-9._\-]+", r"\1=***", value, flags=re.I)
    return value


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")
