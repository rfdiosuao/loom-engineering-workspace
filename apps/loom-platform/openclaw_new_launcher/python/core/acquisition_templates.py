"""Acquisition template library with optional cloud upload."""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
import uuid
from typing import Any, Callable, Dict

from core.paths import AppPaths


Json = Dict[str, Any]
TemplateUploader = Callable[[str, str, Json, int], Json]

SENSITIVE_KEY_MARKERS = ("token", "secret", "password", "credential", "api_key", "apikey", "authorization")
DEFAULT_TEMPLATE_SERVER_URL = "https://api.heang.top/api/loom/templates"


class TemplateError(RuntimeError):
    """Safe, user-facing template library error."""


class TemplateNotFound(TemplateError):
    pass


class TemplateDisabled(TemplateError):
    pass


class TemplateVersionConflict(TemplateError):
    pass


class AcquisitionTemplateLibrary:
    def __init__(self, paths: AppPaths, *, uploader: TemplateUploader | None = None):
        self.paths = paths
        self.uploader = uploader or _post_template

    @property
    def state_path(self) -> str:
        return os.path.join(self.paths.launcher_dir, "acquisition-templates.json")

    def status(self) -> Json:
        state = self._load_state()
        templates = [item for item in state.get("templates", []) if isinstance(item, dict)]
        cloud = self._cloud_config(state)
        return _redact_json(
            {
                "schema": "loom.acquisition_template_library.v1",
                "updatedAt": state.get("updatedAt") or _now_iso(),
                "cloud": {
                    "configured": bool(cloud["url"]),
                    "serverUrl": cloud["url"],
                    "tokenConfigured": bool(cloud["token"]),
                    "consentGranted": bool(cloud["consentGranted"]),
                    "uploadEnabled": bool(cloud["url"] and cloud["consentGranted"]),
                },
                "stats": {
                    "total": len(templates),
                    "enabled": sum(1 for item in templates if item.get("enabled") is not False),
                    "pendingUpload": sum(1 for item in templates if item.get("uploadStatus") in {"pending_upload", "upload_failed"}),
                    "uploaded": sum(1 for item in templates if item.get("uploadStatus") == "uploaded"),
                },
                "templates": templates[-100:],
            }
        )

    def set_cloud_consent(self, enabled: bool) -> Json:
        state = self._load_state()
        state["cloudConsent"] = {
            "enabled": bool(enabled),
            "updatedAt": _now_iso(),
            "source": "explicit_user_action",
        }
        state["updatedAt"] = _now_iso()
        self._write_state(state)
        return self.status()

    def save_from_acquisition(self, raw: Json) -> Json:
        state = self._load_state()
        templates = [item for item in state.get("templates", []) if isinstance(item, dict)]
        proposed_id = _template_id(raw.get("templateId") or f"{raw.get('industry') or raw.get('category') or raw.get('topic') or '通用获客'}-{raw.get('name') or raw.get('topic') or '获客打法模板'}")
        existing = next((item for item in templates if item.get("templateId") == proposed_id), None)
        expected_version = _optional_int(raw.get("expectedVersion")) if "expectedVersion" in raw else None
        if existing:
            current_version = max(1, _int(existing.get("version"), 1))
            if expected_version is not None and expected_version != current_version:
                raise TemplateVersionConflict(
                    f"模板已更新（当前版本 {current_version}），请刷新后重试"
                )
            source = {**existing, **raw, "templateId": proposed_id}
            template = self._build_template(source)
            template["version"] = current_version + 1
            template["createdAt"] = existing.get("createdAt") or template["createdAt"]
            template["enabled"] = raw.get("enabled") is not False if "enabled" in raw else existing.get("enabled") is not False
        else:
            if expected_version not in {None, 0}:
                raise TemplateVersionConflict("模板不存在或已被删除，请刷新后重试")
            template = self._build_template({**raw, "templateId": proposed_id})
        templates = [item for item in templates if item.get("templateId") != template["templateId"]]
        templates.append(template)
        state["templates"] = templates[-500:]
        state["updatedAt"] = _now_iso()
        self._write_state(state)
        upload = self.upload_template(template["templateId"])
        state = self._load_state()
        current = next((item for item in state.get("templates", []) if item.get("templateId") == template["templateId"]), template)
        return _redact_json({"template": current, "upload": upload, "status": self.status()})

    def resolve_template(
        self,
        template_id: str,
        *,
        expected_version: int | None = None,
        require_enabled: bool = True,
    ) -> Json:
        safe_id = _template_id(template_id)
        state = self._load_state()
        templates = [item for item in state.get("templates", []) if isinstance(item, dict)]
        template = next((item for item in templates if item.get("templateId") == safe_id), None)
        if not template:
            raise TemplateNotFound("未找到共享模板")
        current_version = max(1, _int(template.get("version"), 1))
        if expected_version is not None and expected_version != current_version:
            raise TemplateVersionConflict(
                f"模板版本不一致（请求 {expected_version}，当前 {current_version}），请刷新后重试"
            )
        if require_enabled and template.get("enabled") is False:
            raise TemplateDisabled("共享模板已停用，请启用后再执行")
        return _redact_json(dict(template))

    def materialize_request(self, raw: Json) -> Json:
        materialized = dict(raw) if isinstance(raw, dict) else {}
        template_id = str(materialized.get("templateId") or "").strip()
        if not template_id:
            return _redact_json(materialized)
        expected_version = _optional_int(
            materialized.get("templateVersion")
            if "templateVersion" in materialized
            else materialized.get("expectedVersion")
        )
        template = self.resolve_template(
            template_id,
            expected_version=expected_version,
            require_enabled=True,
        )
        version = max(1, _int(template.get("version"), 1))
        platforms = _string_list(template.get("platforms"), ["manual"])
        platform = platforms[0] if platforms else "manual"
        materialized.setdefault("topic", template.get("name") or "获客打法模板")
        materialized.setdefault("platform", platform)
        materialized.setdefault("target", template.get("targetCustomer") or "潜在客户")
        materialized.setdefault("targetCustomer", template.get("targetCustomer") or "潜在客户")
        materialized.setdefault("knowledge", template.get("replyStyle") or "自然、不强推、先确认需求")
        materialized["templateId"] = str(template.get("templateId") or template_id)
        materialized["templateVersion"] = version
        materialized["templateName"] = str(template.get("name") or "获客打法模板")
        materialized["sharedTemplate"] = {
            "templateId": materialized["templateId"],
            "version": version,
            "name": materialized["templateName"],
            "industry": template.get("industry") or "通用获客",
            "platforms": platforms,
            "targetCustomer": template.get("targetCustomer") or "潜在客户",
            "keywords": _string_list(template.get("keywords"), []),
            "leadRules": _string_list(template.get("leadRules"), []),
            "replyStyle": template.get("replyStyle") or "自然、不强推、先确认需求",
            "safetyPolicy": template.get("safetyPolicy") if isinstance(template.get("safetyPolicy"), dict) else {},
            "feishuMapping": template.get("feishuMapping") if isinstance(template.get("feishuMapping"), dict) else {},
        }
        if not str(materialized.get("prompt") or "").strip():
            keywords = "、".join(materialized["sharedTemplate"]["keywords"]) or "未指定"
            lead_rules = "；".join(materialized["sharedTemplate"]["leadRules"]) or "按公开意向信号判断"
            materialized["prompt"] = _clip(
                f"使用共享模板 {materialized['templateName']}（{materialized['templateId']}@v{version}）执行获客任务。"
                f"平台：{platform}；目标客户：{materialized['targetCustomer']}；关键词：{keywords}；"
                f"线索规则：{lead_rules}；回复风格：{materialized['knowledge']}。"
                "只读取公开可见内容，只生成线索与待人工确认草稿；禁止执行任何对外发送、互动、添加联系人或发布动作。",
                2000,
            )
        return _redact_json(materialized)

    def set_enabled(self, template_id: str, enabled: bool, *, expected_version: int | None = None) -> Json:
        state = self._load_state()
        templates = [item for item in state.get("templates", []) if isinstance(item, dict)]
        template = next((item for item in templates if item.get("templateId") == template_id), None)
        if not template:
            raise TemplateNotFound("未找到共享模板")
        current_version = max(1, _int(template.get("version"), 1))
        if expected_version is not None and expected_version != current_version:
            raise TemplateVersionConflict(
                f"模板已更新（当前版本 {current_version}），请刷新后重试"
            )
        template = {**template}
        template["enabled"] = bool(enabled)
        template["version"] = current_version + 1
        template["updatedAt"] = _now_iso()
        template["uploadStatus"] = "pending_upload"
        template["uploadError"] = ""
        template["remote"] = {}
        self._replace_template(state, template)
        return _redact_json({"template": template, "status": self.status()})

    def delete_template(self, template_id: str, *, expected_version: int | None = None) -> Json:
        state = self._load_state()
        templates = [item for item in state.get("templates", []) if isinstance(item, dict)]
        template = next((item for item in templates if item.get("templateId") == template_id), None)
        if not template:
            raise TemplateNotFound("未找到共享模板")
        current_version = max(1, _int(template.get("version"), 1))
        if expected_version is not None and expected_version != current_version:
            raise TemplateVersionConflict(
                f"模板已更新（当前版本 {current_version}），请刷新后重试"
            )
        state["templates"] = [item for item in templates if item.get("templateId") != template_id]
        state["updatedAt"] = _now_iso()
        self._write_state(state)
        return _redact_json({"status": "deleted", "templateId": template_id, "version": current_version})

    def upload_template(self, template_id: str) -> Json:
        state = self._load_state()
        templates = [item for item in state.get("templates", []) if isinstance(item, dict)]
        template = next((item for item in templates if item.get("templateId") == template_id), None)
        if not template:
            return {"status": "not_found", "templateId": _clip(template_id, 120)}
        cloud = self._cloud_config(state)
        now = _now_iso()
        if not cloud["url"]:
            template["uploadStatus"] = "pending_upload"
            template["uploadError"] = "template server is not configured"
            template["updatedAt"] = now
            self._replace_template(state, template)
            return _redact_json({"status": "pending_config", "templateId": template["templateId"], "configured": False})
        if not cloud["consentGranted"]:
            template["uploadStatus"] = "pending_upload"
            template["uploadError"] = "cloud upload consent is required"
            template["updatedAt"] = now
            self._replace_template(state, template)
            return _redact_json(
                {
                    "status": "pending_consent",
                    "templateId": template["templateId"],
                    "configured": bool(cloud["url"]),
                    "consentGranted": False,
                }
            )
        try:
            response = self.uploader(cloud["url"], cloud["token"], _public_template_payload(template), 20)
        except (OSError, urllib.error.URLError, TimeoutError, RuntimeError) as exc:
            template["uploadStatus"] = "upload_failed"
            template["uploadError"] = _redact(str(exc))[:240]
            template["updatedAt"] = now
            self._replace_template(state, template)
            return _redact_json({"status": "upload_failed", "templateId": template["templateId"], "error": template["uploadError"]})
        remote = {
            "templateId": _clip(response.get("templateId") or response.get("id") or template["templateId"], 160),
            "version": _int(response.get("version"), _int(template.get("version"), 1)),
            "url": _redact_url(str(response.get("url") or response.get("htmlUrl") or "")),
            "uploadedAt": now,
            "serverUrl": cloud["url"],
        }
        template["uploadStatus"] = "uploaded"
        template["uploadError"] = ""
        template["remote"] = remote
        template["updatedAt"] = now
        self._replace_template(state, template)
        return _redact_json({"status": "uploaded", "templateId": template["templateId"], "remote": remote})

    def retry_pending(self) -> Json:
        state = self._load_state()
        templates = [item for item in state.get("templates", []) if isinstance(item, dict)]
        pending = [
            item.get("templateId")
            for item in templates
            if item.get("templateId") and item.get("uploadStatus") in {"pending_upload", "upload_failed"}
        ]
        results = [self.upload_template(str(template_id)) for template_id in pending]
        return _redact_json({"retried": len(results), "results": results, "status": self.status()})

    def _build_template(self, raw: Json) -> Json:
        now = _now_iso()
        name = _clip(raw.get("name") or raw.get("topic") or "获客打法模板", 120)
        industry = _clip(raw.get("industry") or raw.get("category") or raw.get("topic") or "通用获客", 80)
        platforms = _string_list(raw.get("platforms") if raw.get("platforms") is not None else raw.get("platform"), ["manual"])
        target_customer = _clip(raw.get("targetCustomer") or raw.get("target") or "潜在客户", 220)
        keywords = _string_list(raw.get("keywords"), [])
        lead_rules = _string_list(raw.get("leadRules"), [])
        reply_style = _clip(raw.get("replyStyle") or raw.get("knowledge") or "自然、不强推、先确认需求", 260)
        template_id = _template_id(raw.get("templateId") or f"{industry}-{name}")
        return {
            "schema": "loom.acquisition_template.v1",
            "templateId": template_id,
            "version": 1,
            "enabled": raw.get("enabled") is not False,
            "name": name,
            "industry": industry,
            "platforms": platforms,
            "targetCustomer": target_customer,
            "keywords": keywords,
            "leadRules": lead_rules or ["询价", "问地址", "表达预约意向", "要求方案"],
            "replyStyle": reply_style,
            "safetyPolicy": {
                "sendMode": "draft_only",
                "manualConfirm": True,
                "whitelist": True,
                "frequencyCap": True,
                "auditLog": True,
            },
            "feishuMapping": {
                "客户昵称": "lead.title",
                "需求": "lead.summary",
                "意向等级": "lead.intentLevel",
                "跟进话术": "draft.body",
            },
            "createdFromTask": {
                "topic": _clip(raw.get("topic") or name, 160),
                "source": _clip(raw.get("source") or "acquisition_workbench", 80),
            },
            "uploadStatus": "pending_upload",
            "uploadError": "",
            "remote": {},
            "createdAt": now,
            "updatedAt": now,
        }

    def _cloud_config(self, state: Json | None = None) -> Json:
        if str(os.environ.get("LOOM_TEMPLATE_DISABLE_DEFAULT_CLOUD") or "").strip().lower() in {"1", "true", "yes"}:
            default_url = ""
        else:
            default_url = DEFAULT_TEMPLATE_SERVER_URL
        env_consent = str(os.environ.get("LOOM_TEMPLATE_CLOUD_AUTO_UPLOAD") or "").strip().lower() in {
            "1",
            "true",
            "yes",
        }
        consent = (state or {}).get("cloudConsent")
        state_consent = bool(consent.get("enabled")) if isinstance(consent, dict) else False
        return {
            "url": _clip(os.environ.get("LOOM_TEMPLATE_SERVER_URL") or os.environ.get("LOOM_TEMPLATE_CLOUD_URL") or default_url, 300),
            "token": str(os.environ.get("LOOM_TEMPLATE_SERVER_TOKEN") or os.environ.get("LOOM_TEMPLATE_CLOUD_TOKEN") or "").strip(),
            "consentGranted": bool(env_consent or state_consent),
        }

    def _load_state(self) -> Json:
        if not os.path.exists(self.state_path):
            return {"schema": "loom.acquisition_template_library.v1", "updatedAt": "", "templates": []}
        try:
            with open(self.state_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            if not isinstance(data, dict):
                return {"schema": "loom.acquisition_template_library.v1", "updatedAt": "", "templates": []}
            data.setdefault("templates", [])
            data.setdefault("cloudConsent", {"enabled": False, "updatedAt": "", "source": ""})
            data["schema"] = "loom.acquisition_template_library.v1"
            return data
        except (OSError, json.JSONDecodeError):
            return {"schema": "loom.acquisition_template_library.v1", "updatedAt": "", "templates": []}

    def _write_state(self, state: Json) -> None:
        os.makedirs(os.path.dirname(self.state_path), exist_ok=True)
        state["schema"] = "loom.acquisition_template_library.v1"
        tmp = f"{self.state_path}.tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(_redact_json(state), handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(tmp, self.state_path)

    def _replace_template(self, state: Json, template: Json) -> None:
        templates = [item for item in state.get("templates", []) if isinstance(item, dict)]
        state["templates"] = [item for item in templates if item.get("templateId") != template.get("templateId")]
        state["templates"].append(template)
        state["updatedAt"] = _now_iso()
        self._write_state(state)


def _post_template(url: str, token: str, payload: Json, timeout: int = 20) -> Json:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "User-Agent": "LOOM-Acquisition-Template/1.0",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        url,
        data=data,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            text = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {_redact(body[:240])}") from exc
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {"ok": True}
    except json.JSONDecodeError:
        return {"ok": True, "raw": _redact(text[:240])}


def _public_template_payload(template: Json) -> Json:
    payload = {key: value for key, value in template.items() if key not in {"uploadError", "remote"}}
    payload["schema"] = "loom.acquisition_template.v1"
    return _redact_json(payload)


def _string_list(value: Any, default: list[str]) -> list[str]:
    if isinstance(value, list):
        rows = value
    elif value is None or value == "":
        rows = default
    else:
        rows = [value]
    safe = []
    for item in rows:
        text = _clip(item, 120)
        if text and text not in safe:
            safe.append(text)
    return safe[:20]


def _template_id(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", text, flags=re.I).strip("-")
    if not text:
        text = f"template-{uuid.uuid4().hex[:10]}"
    return _clip(text, 100)


def _clip(value: Any, limit: int) -> str:
    return _redact(str(value or "").strip())[:limit]


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _redact_json(value: Any) -> Any:
    if isinstance(value, dict):
        safe: Json = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if any(marker in lowered for marker in SENSITIVE_KEY_MARKERS):
                continue
            safe[key] = _redact_json(item)
        return safe
    if isinstance(value, list):
        return [_redact_json(item) for item in value]
    if isinstance(value, str):
        return _redact(value)
    return value


def _redact_url(value: str) -> str:
    text = _redact(value)
    return re.sub(r"([?&](?:token|secret|key|password)=)[^&]+", r"\1***", text, flags=re.I)


def _redact(text: Any) -> str:
    value = str(text or "")
    value = re.sub(r"Bearer\s+[A-Za-z0-9._\-]+", "Bearer ***", value, flags=re.I)
    value = re.sub(r"\b1[3-9]\d{9}\b", "[手机号已隐藏]", value)
    value = re.sub(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", "[邮箱已隐藏]", value)
    value = re.sub(r"(secret|token|password|credential)[-_:= ]+[A-Za-z0-9._\-]+", r"\1=***", value, flags=re.I)
    return value


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")
