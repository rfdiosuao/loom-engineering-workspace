"""Runtime wire contract for account-to-local configuration sync."""

from __future__ import annotations

import copy
import hashlib
import ipaddress
import json
import os
import re
import tempfile
import threading
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

from core.agent_session_retention import (
    SessionRetentionError,
    assert_agent_sessions_preserved,
    capture_agent_session_inventory,
)
from core.openclaw_model_sync import sync_openclaw_models_from_gateway_profile
from core.paths import AppPaths
from core.secret_store import protect_secret, unprotect_secret
from core.storage import read_json, write_json


WIRE_MANAGED_BY = "heang_account"
WIRE_PROVIDER = "heang"
WIRE_CUSTOM_MANAGED_BY = "custom_provider"
DEFAULT_TEXT_MODEL = "glm-5.2-coding"
DEFAULT_PHONE_MODEL = "qwen3.7-plus"
TEXT_MODEL_PRIORITY = (
    "glm-5.2-coding",
    "qwen3.7-plus",
    "qwen3.6-plus",
    "qwen3.5-plus",
    "glm-4-flash",
    "kimi-k2.5",
    "MiniMax-M2.5",
)
PHONE_MODEL_IDS = {"agnes-2.0-flash"}
IMAGE_MODEL_MARKERS = (
    "image",
    "dall-e",
    "gpt-image",
    "flux",
    "midjourney",
    "sd-",
    "imagen",
    "seedream",
)
VIDEO_MODEL_MARKERS = (
    "video",
    "veo",
    "sora",
    "seedance",
    "kling",
    "wan",
    "hailuo",
    "runway",
    "pika",
    "luma",
)
MANAGED_ACCOUNT_SOURCES = {"newapi_account", WIRE_MANAGED_BY, WIRE_CUSTOM_MANAGED_BY}
AGENT_ENV_KEYS = ("LOOM_OPENCODE_API_KEY", "LOOM_CODEX_API_KEY", "LOOM_CLAUDE_API_KEY")
AGENT_STALE_MODEL_ENV_KEYS = ("OPENAI_MODEL", "ANTHROPIC_MODEL", "CLAUDE_CODE_MODEL", "OPENCODE_MODEL", "OPENCODE_PROVIDER")
CODEX_TRANSACTION_LOCK_TIMEOUT_SECONDS = 8.0
CODEX_REMOTE_PROBE_TIMEOUT_SECONDS = 12.0
CODEX_TRANSACTION_ACTIVE_STATES = {"applying", "verifying", "rolling_back", "disabling", "recovery_required"}
_CODEX_LOCKS_GUARD = threading.Lock()
_CODEX_LOCKS: dict[str, threading.Lock] = {}
AGENT_MODEL_CONFIGS = {
    "codex-desktop": {
        "target": "codex",
        "name": "Codex",
        "configDir": ".codex",
        "configFile": "config.toml",
    },
    "claude-code": {
        "target": "claude",
        "name": "Claude Code",
        "configDir": ".claude",
        "configFile": "settings.json",
    },
    "openclaw-companion": {
        "target": "openclaw",
        "name": "OpenClaw",
        "configDir": ".openclaw",
        "configFile": "openclaw.json",
    },
}

SECRET_TEXT_PATTERNS = (
    re.compile(r"(?i)\b(api[_-]?key|access[_-]?token|session[_-]?cookie|password|secret|token)(\s*[:=]\s*)([^\s,;]+)"),
    re.compile(r"(?i)\b(bearer\s+)([a-z0-9._~+/=-]{8,})"),
    re.compile(r"\b(sk-[A-Za-z0-9._-]+|sess-[A-Za-z0-9._-]+|eyJ[A-Za-z0-9._=-]+)"),
)


class WireConfigError(RuntimeError):
    """Raised when runtime wire sync cannot be completed safely."""


class WireService:
    def __init__(self, paths: AppPaths, append_log=None):
        self.paths = paths
        self.append_log = append_log or (lambda _text: None)
        self._recover_interrupted_codex_transaction()

    def current(self) -> dict[str, Any] | None:
        wire = _read_json_if_exists(self.paths.wire_current)
        if not isinstance(wire, dict):
            return None
        return _unprotect_wire(wire)

    def current_public(self) -> dict[str, Any]:
        return _public_wire(self.current())

    def sync_from_session(
        self,
        session: dict[str, Any],
        *,
        targets: tuple[str, ...] = ("openclaw", "opencode", "codex", "claude", "image", "desktop", "phone"),
    ) -> dict[str, Any]:
        wire = build_wire_from_session(session)
        current = _read_json_if_exists(self.paths.wire_current)
        if isinstance(current, dict):
            write_json(self.paths.wire_last_good, current)

        write_json(self.paths.wire_current, _protected_wire(wire))
        results = self.apply_wire(wire, targets=targets)
        return {
            "wire": _public_wire(wire),
            "syncResults": results,
        }

    def sync_custom_provider(
        self,
        *,
        provider: str,
        base_url: str,
        api_key: str,
        text_model: str,
        image_model: str = "",
        phone_model: str = "",
        video_model: str = "",
        targets: tuple[str, ...] = ("openclaw", "opencode", "codex", "claude", "image", "desktop", "phone"),
    ) -> dict[str, Any]:
        provider = _pick_text(provider, "自定义 Provider")
        base_url = _normalize_base_url(base_url)
        api_key = _pick_text(api_key)
        text_model = _pick_text(text_model)
        image_model = _pick_text(image_model)
        phone_model = _pick_text(phone_model, DEFAULT_PHONE_MODEL)
        video_model = _pick_text(video_model)
        if not base_url:
            raise WireConfigError("请输入第三方 Provider URL")
        if not api_key:
            raise WireConfigError("请输入第三方 API Key")
        if not text_model:
            raise WireConfigError("请输入默认文本模型")
        if _looks_like_non_text_model(text_model):
            raise WireConfigError("默认文本模型不能使用手机/图像/视频模型")

        wire = {
            "schemaVersion": 1,
            "managedBy": WIRE_CUSTOM_MANAGED_BY,
            "accountId": "",
            "account": "第三方 Provider",
            "provider": provider,
            "baseUrl": base_url,
            "apiKey": api_key,
            "tokenMasked": _mask_secret(api_key),
            "models": {
                "text": text_model,
                "phone": phone_model,
                "image": image_model,
                "video": video_model,
            },
            "modelLists": {
                "text": [text_model],
                "image": [image_model] if image_model else [],
                "video": [video_model] if video_model else [],
            },
            "targets": {
                "openclaw": True,
                "phone": True,
                "desktopRpa": True,
                "imageGateway": bool(image_model),
                "videoGateway": False,
                "opencode": True,
                "codex": True,
                "claude": True,
            },
            "updatedAt": _iso_now(),
        }
        current = _read_json_if_exists(self.paths.wire_current)
        if isinstance(current, dict):
            write_json(self.paths.wire_last_good, current)
        write_json(self.paths.wire_current, _protected_wire(wire))
        results = self.apply_wire(wire, targets=targets)
        return {
            "wire": _public_wire(wire),
            "syncResults": results,
        }

    def sync_custom_agent_model_config(
        self,
        component_id: str,
        *,
        provider: str,
        base_url: str,
        api_key: str,
        model: str,
    ) -> dict[str, Any]:
        current_snapshot = _snapshot_text_file(self.paths.wire_current)
        last_good_snapshot = _snapshot_text_file(self.paths.wire_last_good)
        try:
            self.sync_custom_provider(
                provider=provider,
                base_url=base_url,
                api_key=api_key,
                text_model=model,
                targets=(),
            )
            wire = self.current()
            if not wire:
                raise WireConfigError("custom_wire_not_persisted")
            return self.sync_agent_model_config(
                component_id,
                model=model,
                wire=wire,
                validate_remote=component_id == "codex-desktop",
            )
        except Exception:
            _restore_text_file_snapshot(current_snapshot)
            _restore_text_file_snapshot(last_good_snapshot)
            raise

    def apply_wire(self, wire: dict[str, Any], *, targets: tuple[str, ...]) -> list[dict[str, Any]]:
        actions = {
            "openclaw": self._sync_openclaw,
            "opencode": self._sync_opencode,
            "codex": self._sync_codex,
            "claude": self._sync_claude,
            "image": self._sync_image,
            "desktop": self._sync_desktop,
            "phone": self._sync_phone,
            "video": self._clear_video,
        }
        results: list[dict[str, Any]] = []
        for target in targets:
            action = actions.get(target)
            if action is None:
                results.append({"target": target, "ok": False, "error": "unknown_target"})
                continue
            try:
                action(wire)
                results.append({"target": target, "ok": True})
            except Exception as exc:
                safe_error = _redact_secret_text(str(exc))
                self.append_log(f"[Wire] sync target {target} failed: {safe_error}\n")
                results.append({"target": target, "ok": False, "error": safe_error})
        return results

    def verify(self) -> dict[str, Any]:
        wire = self.current()
        if not wire:
            return {
                "ok": False,
                "error": "wire_not_configured",
                "targets": {},
            }
        targets = {
            "token": {"ok": bool(_pick_text(wire.get("apiKey")))},
            "openclaw": {"ok": bool(read_json(self.paths.openclaw_config, {}))},
            "opencode": {"ok": bool(read_json(os.path.join(self.paths.data_dir, ".opencode", "opencode.json"), {}))},
            "codex": {"ok": self.agent_model_config_status("codex-desktop")["configured"]},
            "claude": {"ok": self.agent_model_config_status("claude-code")["configured"]},
            "phone": {"ok": bool(read_json(os.path.join(self.paths.launcher_dir, "phone-agent.json"), {}))},
            "desktop": {"ok": bool(read_json(os.path.join(self.paths.launcher_dir, "desktop-agent.json"), {}))},
            "image": {"ok": bool(read_json(self.paths.image_config, {}))},
            "video": {"ok": not bool(read_json(self.paths.video_config, {})) and not bool(read_json(self.paths.videoapi_config, {}))},
        }
        ok = all(bool(item.get("ok")) for item in targets.values())
        return {
            "ok": ok,
            "wire": _public_wire(wire),
            "targets": targets,
        }

    def verify_candidate(
        self,
        *,
        provider: str,
        base_url: str,
        api_key: str,
        text_model: str,
    ) -> dict[str, Any]:
        provider = _pick_text(provider, "自定义 Provider")
        base = _validate_provider_url(base_url)
        api_key = _pick_text(api_key)
        text_model = _pick_text(text_model)
        if not api_key:
            raise WireConfigError("请输入第三方 API Key")
        if not text_model:
            raise WireConfigError("请输入默认文本模型")
        if _looks_like_non_text_model(text_model):
            raise WireConfigError("默认文本模型不能使用手机/图像/视频模型")

        candidates = [base]
        if not base.endswith("/v1"):
            candidates.append(f"{base}/v1")
        errors: list[str] = []
        for candidate in candidates:
            try:
                payload = _provider_json_request(
                    f"{candidate}/models",
                    api_key,
                    method="GET",
                )
                model_ids = _extract_remote_model_ids(payload)
                if not model_ids:
                    raise WireConfigError("provider_models_empty")
                if text_model not in model_ids:
                    raise WireConfigError("selected_model_not_listed")
                return {
                    "ok": True,
                    "provider": provider,
                    "baseUrl": candidate,
                    "model": text_model,
                    "modelsVerified": True,
                    "availableModelCount": len(model_ids),
                    "verifiedAt": _iso_now(),
                }
            except WireConfigError as exc:
                errors.append(f"{candidate}/models: {exc}")
        safe = _redact_secret_text("; ".join(errors[-2:]))
        raise WireConfigError(f"provider_models_probe_failed: {safe}")

    def rollback(self) -> dict[str, Any]:
        previous = _read_json_if_exists(self.paths.wire_last_good)
        if not isinstance(previous, dict):
            raise WireConfigError("没有可回滚的模型同步快照")
        write_json(self.paths.wire_current, previous)
        wire = _unprotect_wire(previous)
        results = self.apply_wire(wire, targets=("openclaw", "opencode", "codex", "claude", "image", "desktop", "phone"))
        return {
            "wire": _public_wire(wire),
            "syncResults": results,
        }

    def agent_model_config_status(self, component_id: str) -> dict[str, Any]:
        component_id = str(component_id or "").strip()
        target = AGENT_MODEL_CONFIGS.get(component_id)
        if not target:
            return {
                "componentId": component_id,
                "supported": False,
                "configured": False,
                "status": "unsupported",
                "message": "该组件暂不支持模型配置",
                "availableModels": [],
            }

        wire = self.current()
        config_path = self._agent_config_path(component_id)
        metadata = self._agent_config_metadata(component_id)
        transaction_journal = (
            read_json(self._codex_transaction_journal_path(), {})
            if component_id == "codex-desktop"
            else {}
        )
        if not isinstance(transaction_journal, dict):
            transaction_journal = {}
        journal_state = _pick_text(transaction_journal.get("state"))
        official_channel = component_id == "codex-desktop" and journal_state == "official"
        model_lists = wire.get("modelLists") if isinstance(wire, dict) and isinstance(wire.get("modelLists"), dict) else {}
        text_models = _desktop_text_models(_list_values(model_lists.get("text")))
        current_model = _desktop_text_model(_model_value(wire, "text", "")) if isinstance(wire, dict) else ""
        if current_model and not text_models:
            text_models = [current_model, *text_models]
        metadata_model = _desktop_text_model(metadata.get("model"))
        expected_model = metadata_model or current_model
        actual_raw_model = _agent_config_model(component_id, config_path)
        actual_model = _desktop_text_model(actual_raw_model)
        user_config_path = _user_codex_config_path(self.paths) if component_id == "codex-desktop" else ""
        user_actual_raw_model = _agent_config_model(component_id, user_config_path) if user_config_path else ""
        user_actual_model = _desktop_text_model(user_actual_raw_model)
        actual_profile = (
            _codex_config_profile(_read_text(config_path))
            if component_id == "codex-desktop" and os.path.isfile(config_path)
            else {}
        )
        user_profile = (
            _codex_config_profile(_read_text(user_config_path))
            if component_id == "codex-desktop" and user_config_path and os.path.isfile(user_config_path)
            else {"channelMode": "official", "providerId": "", "provider": {}}
        )
        invalid_actual_model = bool(actual_raw_model and not actual_model)
        invalid_user_model = bool(user_actual_raw_model and not user_actual_model)
        invalid_model = actual_raw_model if invalid_actual_model else ""
        expected_provider_id = (
            _codex_provider_id(_pick_text(metadata.get("provider")), _pick_text(metadata.get("managedBy")))
            if component_id == "codex-desktop" and metadata.get("configured")
            else ""
        )
        expected_base_url = _pick_text(metadata.get("baseUrl")).rstrip("/")
        actual_provider = actual_profile.get("provider") if isinstance(actual_profile.get("provider"), dict) else {}
        user_provider = user_profile.get("provider") if isinstance(user_profile.get("provider"), dict) else {}
        config_matches = not invalid_actual_model and (not actual_model or not expected_model or actual_model == expected_model)
        user_config_matches = not invalid_user_model and (not user_actual_model or not expected_model or user_actual_model == expected_model)
        if component_id == "codex-desktop" and expected_provider_id:
            config_matches = bool(
                config_matches
                and actual_profile.get("providerId") == expected_provider_id
                and _pick_text(actual_provider.get("base_url")).rstrip("/") == expected_base_url
                and actual_provider.get("env_key") == "LOOM_CODEX_API_KEY"
                and actual_provider.get("wire_api") == "responses"
            )
            user_config_matches = bool(
                user_config_matches
                and user_profile.get("providerId") == expected_provider_id
                and _pick_text(user_provider.get("base_url")).rstrip("/") == expected_base_url
                and user_provider.get("env_key") == "LOOM_CODEX_API_KEY"
                and user_provider.get("wire_api") == "responses"
            )
        user_config_warning = _pick_text(metadata.get("userConfigWarning"))
        if component_id == "codex-desktop" and not user_config_warning:
            if invalid_user_model:
                user_config_warning = "用户 Codex 配置包含非文本模型；LOOM 专用配置仍可正常使用"
            elif user_actual_model and expected_model and user_actual_model != expected_model:
                user_config_warning = "用户 Codex 配置与 LOOM 专用配置不一致；LOOM 启动不受影响"
            elif expected_provider_id and not user_config_matches:
                user_config_warning = "用户 Codex 渠道已被修改，请重新写入或恢复官方渠道"
            elif user_config_path and not os.path.isfile(user_config_path):
                user_config_warning = "用户 Codex 配置未同步；LOOM 专用配置仍可正常使用"
        user_config_synchronized = component_id != "codex-desktop" or (not user_config_warning and user_config_matches)
        environment_warning = _pick_text(metadata.get("environmentWarning"))
        environment_synchronized = component_id != "codex-desktop" or not environment_warning
        if component_id == "codex-desktop" and metadata.get("configured"):
            expected_key = _pick_text(wire.get("apiKey")) if isinstance(wire, dict) else ""
            process_key_matches = bool(expected_key and os.environ.get("LOOM_CODEX_API_KEY") == expected_key)
            registry_key_matches = True
            if _should_persist_user_env(self.paths):
                registry_key_matches = _read_user_env_var("LOOM_CODEX_API_KEY") == expected_key
            dotenv_key_matches = _read_dotenv_value(
                _user_codex_env_path(self.paths),
                "LOOM_CODEX_API_KEY",
            ) == expected_key
            environment_synchronized = bool(
                process_key_matches
                and registry_key_matches
                and dotenv_key_matches
            )
            if not environment_synchronized:
                environment_warning = "Codex 模型环境变量已变化，请重新写入配置"
        optional_warnings = [warning for warning in (user_config_warning, environment_warning) if warning]
        optional_warning_message = "；".join(optional_warnings)
        files_configured = bool(
            os.path.isfile(config_path)
            and metadata.get("configured")
            and expected_model
            and config_matches
        )
        remote_verified = bool(metadata.get("remoteVerified"))
        configured = files_configured
        if component_id == "codex-desktop":
            transaction_committed = journal_state == "committed"
            remote_verified = bool(remote_verified and transaction_committed)
            configured = bool(
                files_configured
                and user_config_synchronized
                and environment_synchronized
                and remote_verified
                and transaction_committed
            )
        actual_channel_mode = _pick_text(user_profile.get("channelMode"), "official")
        official_channel = bool(official_channel and actual_channel_mode == "official")
        if official_channel:
            status = "official"
            message = "已恢复 OpenAI 官方渠道"
        elif component_id == "codex-desktop" and journal_state == "recovery_required":
            status = "failed"
            message = "Codex 模型配置恢复失败，请重新写入配置"
        elif component_id == "codex-desktop" and journal_state in {"applying", "verifying", "rolling_back"}:
            status = "configuring"
            message = "Codex 模型配置正在处理"
        elif not wire:
            status = "no_wire"
            message = "请先登录模型账号或应用第三方模型配置"
        elif invalid_model:
            status = "unconfigured"
            message = "检测到手机/图像/视频模型被写入桌面 Agent，请重新写入文本模型配置"
        elif component_id == "codex-desktop" and (not user_config_synchronized or not environment_synchronized):
            status = "unconfigured"
            message = optional_warning_message
        elif component_id == "codex-desktop" and files_configured and not remote_verified:
            status = "unverified"
            message = "配置已写入，点击写入配置完成模型连通性验证"
        elif configured:
            status = "configured"
            message = "模型配置已写入"
        else:
            status = "unconfigured"
            message = "可写入 LOOM 管理配置"
        effective_managed_by = (
            ""
            if official_channel or actual_channel_mode == "custom"
            else (_wire_managed_by(wire) if isinstance(wire, dict) else "")
        )
        wire_managed_by = _wire_managed_by(wire) if isinstance(wire, dict) else ""
        effective_provider = "" if official_channel else (_pick_text(wire.get("provider")) if isinstance(wire, dict) else "")
        effective_base_url = "" if official_channel else (_pick_text(wire.get("baseUrl")) if isinstance(wire, dict) else "")
        channel_mode = (
            "official"
            if official_channel
            else "custom"
            if actual_channel_mode == "custom" or effective_managed_by == WIRE_CUSTOM_MANAGED_BY
            else "managed"
            if configured
            else "unconfigured"
        )
        session_preservation = self._agent_session_preservation_status(
            component_id,
            metadata,
            user_config_path=user_config_path,
        )
        return {
            "componentId": component_id,
            "supported": True,
            "configured": configured,
            "status": status,
            "message": message,
            "model": user_actual_raw_model if official_channel else (actual_raw_model or metadata_model or current_model),
            "expectedModel": expected_model,
            "actualModel": actual_raw_model,
            "userActualModel": user_actual_raw_model,
            "invalidModel": invalid_model,
            "userInvalidModel": user_actual_raw_model if invalid_user_model else "",
            "userConfigSynchronized": user_config_synchronized,
            "userConfigWarning": user_config_warning,
            "environmentSynchronized": environment_synchronized,
            "environmentWarning": environment_warning,
            "provider": effective_provider,
            "baseUrl": effective_base_url,
            "managedBy": effective_managed_by,
            "wireManagedBy": wire_managed_by,
            "channelMode": channel_mode,
            "availableModels": text_models,
            "configPath": config_path,
            "userConfigPath": user_config_path,
            "backupAvailable": bool(
                journal_state == "committed"
                or (metadata.get("backupPath") and os.path.exists(str(metadata.get("backupPath"))))
            ),
            "rollbackAvailable": bool(journal_state == "committed"),
            "transactionId": transaction_journal.get("transactionId") or metadata.get("transactionId") or "",
            "transactionState": journal_state or metadata.get("transactionState") or "",
            "remoteVerified": remote_verified,
            "remoteValidation": metadata.get("remoteValidation") if isinstance(metadata.get("remoteValidation"), dict) else {},
            "officialAuthUnchanged": metadata.get("officialAuthUnchanged") is True,
            "sessionPreservation": session_preservation,
            "updatedAt": metadata.get("updatedAt") or "",
        }

    def sync_agent_model_config(
        self,
        component_id: str,
        *,
        model: str = "",
        wire: dict[str, Any] | None = None,
        validate_remote: bool = False,
    ) -> dict[str, Any]:
        component_id = str(component_id or "").strip()
        if component_id not in AGENT_MODEL_CONFIGS:
            raise WireConfigError("该组件暂不支持模型配置")
        wire = wire or self.current()
        if not wire:
            raise WireConfigError("请先登录模型账号或应用第三方模型配置")
        base_url = _pick_text(wire.get("baseUrl")).rstrip("/")
        api_key = _pick_text(wire.get("apiKey"))
        if _looks_like_non_text_model(model):
            raise WireConfigError("手机/图像/视频模型不能写入 Codex / Claude Code，请选择文本模型。")
        selected_model = _pick_agent_model(wire, model)
        if not selected_model:
            raise WireConfigError("没有可用文本模型，请同步/购买/换模型")
        if not base_url or not api_key:
            raise WireConfigError("托管模型配置不完整，请先同步模型")
        if component_id == "codex-desktop":
            return self._sync_codex_model_config_transaction(
                wire,
                selected_model,
                validate_remote=validate_remote,
            )
        if component_id == "openclaw-companion":
            _clear_stale_agent_model_env_keys(self.paths, broadcast=False)
            return self._sync_openclaw_agent_model_config(component_id, wire, selected_model)
        if component_id == "claude-code":
            return self._sync_claude_model_config_transaction(wire, selected_model)
        raise WireConfigError("该组件暂不支持模型配置")

    def _sync_claude_model_config_transaction(
        self,
        wire: dict[str, Any],
        selected_model: str,
    ) -> dict[str, Any]:
        component_id = "claude-code"
        config_path = self._agent_config_path(component_id)
        metadata_path = self._agent_config_metadata_path(component_id)
        config_snapshot = _snapshot_text_file(config_path)
        metadata_snapshot = _snapshot_text_file(metadata_path)
        environment_names = (*AGENT_STALE_MODEL_ENV_KEYS, "LOOM_CLAUDE_API_KEY")
        environment = {
            name: _snapshot_environment_value(self.paths, name)
            for name in environment_names
        }
        session_before = capture_agent_session_inventory(component_id)
        environment_changed = False
        try:
            environment_changed = _clear_stale_agent_model_env_keys(
                self.paths,
                broadcast=False,
            )
            config_text = self._agent_config_text(component_id, wire, selected_model)
            backup_path = _write_text_with_backup(config_path, config_text)
            environment_changed = _persist_agent_env_key(
                self.paths,
                "LOOM_CLAUDE_API_KEY",
                _pick_text(wire.get("apiKey")),
                broadcast=False,
            ) or environment_changed
            session_after = capture_agent_session_inventory(component_id)
            assert_agent_sessions_preserved(session_before, session_after)
            metadata = {
                "componentId": component_id,
                "configured": True,
                "managedBy": _wire_managed_by(wire),
                "provider": _pick_text(wire.get("provider")),
                "baseUrl": _pick_text(wire.get("baseUrl")).rstrip("/"),
                "model": selected_model,
                "configPath": config_path,
                "userConfigPath": "",
                "backupPath": (
                    backup_path
                    or self._agent_config_metadata(component_id).get("backupPath")
                    or ""
                ),
                "userBackupPath": "",
                "userConfigSynchronized": True,
                "userConfigWarning": "",
                "environmentSynchronized": True,
                "environmentWarning": "",
                "sessionInventoryBefore": session_before,
                "sessionInventoryAfter": session_after,
                "sessionVerifiedAt": _iso_now(),
                "updatedAt": _iso_now(),
            }
            _atomic_write_text(
                metadata_path,
                json.dumps(metadata, indent=2, ensure_ascii=False) + "\n",
            )
            if environment_changed:
                _broadcast_user_env_change()
            return self.agent_model_config_status(component_id)
        except Exception as exc:
            try:
                _restore_text_file_snapshot(config_snapshot)
                _restore_text_file_snapshot(metadata_snapshot)
                for name, snapshot in environment.items():
                    _restore_environment_snapshot(name, snapshot)
                _broadcast_user_env_change()
            except Exception as rollback_error:
                safe_error = _redact_secret_text(str(exc)) or "claude_config_transaction_failed"
                safe_rollback = (
                    _redact_secret_text(str(rollback_error))
                    or "claude_config_rollback_failed"
                )
                raise WireConfigError(
                    f"claude_config_recovery_required: {safe_error}; "
                    f"rollback={safe_rollback}"
                ) from exc
            if isinstance(exc, SessionRetentionError):
                raise WireConfigError(
                    f"claude_session_preservation_failed: {exc}"
                ) from exc
            if isinstance(exc, WireConfigError):
                raise
            raise WireConfigError(
                _redact_secret_text(str(exc)) or "claude_config_transaction_failed"
            ) from exc

    def _sync_codex_model_config_transaction(
        self,
        wire: dict[str, Any],
        selected_model: str,
        *,
        validate_remote: bool,
    ) -> dict[str, Any]:
        source_fingerprint = _codex_wire_fingerprint(wire, selected_model)
        base_url = _pick_text(wire.get("baseUrl")).rstrip("/")
        api_key = _pick_text(wire.get("apiKey"))
        provider = _pick_text(wire.get("provider"), "LOOM")
        managed_by = _wire_managed_by(wire)
        remote_validation: dict[str, Any] = {}
        if validate_remote:
            remote_validation = _probe_codex_provider(base_url, api_key, selected_model)
            base_url = _pick_text(remote_validation.get("baseUrl"), base_url).rstrip("/")

        with _exclusive_codex_config_lock(
            self.paths,
            timeout_seconds=CODEX_TRANSACTION_LOCK_TIMEOUT_SECONDS,
        ):
            self._recover_interrupted_codex_transaction(lock_held=True)
            previous_journal = read_json(self._codex_transaction_journal_path(), {})
            if not isinstance(previous_journal, dict):
                previous_journal = {}
            current_wire = self.current()
            if not current_wire or _codex_wire_fingerprint(current_wire, selected_model) != source_fingerprint:
                raise WireConfigError("codex_wire_changed_during_validation")
            transaction_id = uuid.uuid4().hex

            config_path = self._agent_config_path("codex-desktop")
            user_config_path = _user_codex_config_path(self.paths)
            user_env_path = _user_codex_env_path(self.paths)
            metadata_path = self._agent_config_metadata_path("codex-desktop")
            auth_path = os.path.join(os.path.dirname(user_config_path), "auth.json")
            session_home = os.path.dirname(user_config_path)
            session_before = capture_agent_session_inventory(
                "codex-desktop",
                home_path=session_home,
            )
            existing_user_config = _read_text(user_config_path) if os.path.isfile(user_config_path) else ""
            managed_text = _codex_config_text(base_url, provider, selected_model, managed_by)
            user_text = _codex_user_config_text(
                existing_user_config,
                base_url,
                provider,
                selected_model,
                managed_by,
            )
            provider_id = _codex_provider_id(provider, managed_by)
            _validate_codex_config_text(managed_text, provider_id, base_url, selected_model)
            _validate_codex_config_text(user_text, provider_id, base_url, selected_model)

            snapshots = {
                "managedConfig": _snapshot_text_file(config_path),
                "userConfig": _snapshot_text_file(user_config_path),
                "userEnv": _snapshot_text_file(user_env_path),
                "metadata": _snapshot_text_file(metadata_path),
            }
            environment_names = (*AGENT_STALE_MODEL_ENV_KEYS, "LOOM_CODEX_API_KEY")
            environment = {
                name: _snapshot_environment_value(self.paths, name)
                for name in environment_names
            }
            previous_committed_journal = (
                {
                    key: copy.deepcopy(value)
                    for key, value in previous_journal.items()
                    if key != "previousCommittedJournal"
                }
                if previous_journal.get("state") == "committed"
                else {}
            )
            official_baseline = (
                copy.deepcopy(previous_journal.get("officialBaseline"))
                if previous_journal.get("state") == "committed"
                and isinstance(previous_journal.get("officialBaseline"), dict)
                else {
                    "snapshots": copy.deepcopy(snapshots),
                    "environment": copy.deepcopy(environment),
                }
            )
            auth_before = _sha256_file(auth_path)
            journal = {
                "schemaVersion": 1,
                "transactionId": transaction_id,
                "componentId": "codex-desktop",
                "state": "applying",
                "startedAt": _iso_now(),
                "snapshots": snapshots,
                "environment": environment,
                "officialBaseline": official_baseline,
                "previousCommittedJournal": previous_committed_journal,
                "officialAuthPath": auth_path,
                "officialAuthSha256": auth_before,
                "remoteValidation": remote_validation,
                "sessionInventoryBefore": session_before,
            }
            self._write_codex_transaction_journal(journal)
            environment_changed = False
            try:
                _atomic_write_text(config_path, managed_text)
                _atomic_write_text(user_config_path, user_text)
                existing_user_env = _read_text(user_env_path) if os.path.isfile(user_env_path) else ""
                _atomic_write_text(
                    user_env_path,
                    _upsert_dotenv_value(
                        existing_user_env,
                        "LOOM_CODEX_API_KEY",
                        api_key,
                    ),
                )
                environment_changed = _clear_stale_agent_model_env_keys(
                    self.paths,
                    broadcast=False,
                )
                environment_changed = _persist_agent_env_key(
                    self.paths,
                    "LOOM_CODEX_API_KEY",
                    api_key,
                    broadcast=False,
                ) or environment_changed
                journal["appliedEnvironment"] = {
                    name: _snapshot_environment_value(self.paths, name)
                    for name in environment_names
                }
                journal["state"] = "verifying"
                self._write_codex_transaction_journal(journal)

                _validate_codex_config_file(config_path, provider_id, base_url, selected_model)
                _validate_codex_config_file(user_config_path, provider_id, base_url, selected_model)
                if os.environ.get("LOOM_CODEX_API_KEY") != api_key:
                    raise WireConfigError("codex_api_key_process_environment_mismatch")
                if _should_persist_user_env(self.paths):
                    persisted_key = _read_user_env_var("LOOM_CODEX_API_KEY")
                    if persisted_key != api_key:
                        raise WireConfigError("codex_api_key_user_environment_mismatch")
                if _read_dotenv_value(user_env_path, "LOOM_CODEX_API_KEY") != api_key:
                    raise WireConfigError("codex_api_key_dotenv_mismatch")
                if _sha256_file(auth_path) != auth_before:
                    raise WireConfigError("official_codex_auth_changed")
                session_after = capture_agent_session_inventory(
                    "codex-desktop",
                    home_path=session_home,
                )
                try:
                    assert_agent_sessions_preserved(session_before, session_after)
                except SessionRetentionError as exc:
                    raise WireConfigError(f"codex_session_preservation_failed: {exc}") from exc
                journal["sessionInventoryAfter"] = session_after
                journal["sessionVerifiedAt"] = _iso_now()

                metadata = {
                    "componentId": "codex-desktop",
                    "configured": True,
                    "managedBy": managed_by,
                    "provider": provider,
                    "baseUrl": base_url,
                    "model": selected_model,
                    "configPath": config_path,
                    "userConfigPath": user_config_path,
                    "userEnvPath": user_env_path,
                    "backupPath": "",
                    "userBackupPath": "",
                    "userConfigSynchronized": True,
                    "userConfigWarning": "",
                    "environmentSynchronized": True,
                    "environmentWarning": "",
                    "transactionId": transaction_id,
                    "transactionState": "committed",
                    "remoteVerified": bool(validate_remote),
                    "remoteValidation": remote_validation,
                    "officialAuthUnchanged": True,
                    "sessionInventoryBefore": session_before,
                    "sessionInventoryAfter": session_after,
                    "sessionVerifiedAt": journal["sessionVerifiedAt"],
                    "rollbackAvailable": True,
                    "updatedAt": _iso_now(),
                }
                _atomic_write_text(metadata_path, json.dumps(metadata, indent=2, ensure_ascii=False) + "\n")
                journal["state"] = "committed"
                journal["committedAt"] = _iso_now()
                self._write_codex_transaction_journal(journal)
                if environment_changed:
                    _broadcast_user_env_change()
                return self.agent_model_config_status("codex-desktop")
            except Exception as exc:
                safe_error = _redact_secret_text(str(exc)) or "codex_config_transaction_failed"
                journal["state"] = "rolling_back"
                journal["error"] = safe_error
                self._write_codex_transaction_journal(journal)
                try:
                    _restore_codex_transaction_snapshot(journal)
                    if previous_committed_journal:
                        previous_committed_journal["lastFailedAt"] = _iso_now()
                        previous_committed_journal["lastFailure"] = safe_error
                        self._write_codex_transaction_journal(previous_committed_journal)
                    else:
                        journal["state"] = "rolled_back"
                        journal["rolledBackAt"] = _iso_now()
                        self._write_codex_transaction_journal(journal)
                    _broadcast_user_env_change()
                except Exception as rollback_error:
                    journal["state"] = "recovery_required"
                    journal["rollbackError"] = _redact_secret_text(str(rollback_error))
                    self._write_codex_transaction_journal(journal)
                    raise WireConfigError(
                        f"codex_config_recovery_required: {safe_error}; "
                        f"rollback={journal['rollbackError']}"
                    ) from exc
                if isinstance(exc, WireConfigError):
                    raise
                raise WireConfigError(safe_error) from exc

    def _agent_session_preservation_status(
        self,
        component_id: str,
        metadata: dict[str, Any],
        *,
        user_config_path: str = "",
    ) -> dict[str, Any]:
        if component_id not in {"codex-desktop", "claude-code"}:
            return {
                "supported": False,
                "protected": False,
                "status": "not_applicable",
                "message": "该组件不使用本机会话保留护栏",
            }

        home_path = (
            os.path.dirname(user_config_path)
            if component_id == "codex-desktop" and user_config_path
            else None
        )
        current = capture_agent_session_inventory(component_id, home_path=home_path)
        baseline = (
            metadata.get("sessionInventoryBefore")
            if isinstance(metadata.get("sessionInventoryBefore"), dict)
            else current
        )
        protected = True
        detail = ""
        try:
            assert_agent_sessions_preserved(baseline, current)
        except SessionRetentionError as exc:
            protected = False
            detail = str(exc)
        total_threads = int(current.get("totalThreads") or 0)
        baseline_threads = int(baseline.get("totalThreads") or 0)
        if protected and metadata.get("sessionVerifiedAt"):
            status = "protected"
            message = f"原有会话已保护，已识别 {total_threads} 个会话"
        elif protected:
            status = "ready"
            message = f"已识别 {total_threads} 个原有会话，配置时将自动保护"
        else:
            status = "attention"
            message = "会话目录状态发生变化，请先停止配置并检查原有会话目录"
        return {
            "supported": True,
            "protected": protected,
            "status": status,
            "message": message,
            "componentId": component_id,
            "homePath": current.get("homePath") or "",
            "homeSource": current.get("homeSource") or "",
            "homeExists": current.get("homeExists") is True,
            "totalThreads": total_threads,
            "baselineThreads": baseline_threads,
            "lastVerifiedAt": metadata.get("sessionVerifiedAt") or "",
            "detail": detail,
        }

    def _codex_transaction_journal_path(self) -> str:
        return os.path.join(
            self.paths.launcher_dir,
            "agent-model-transactions",
            "codex-desktop.json",
        )

    def _write_codex_transaction_journal(self, journal: dict[str, Any]) -> None:
        try:
            _atomic_write_text(
                self._codex_transaction_journal_path(),
                json.dumps(journal, indent=2, ensure_ascii=False) + "\n",
            )
        except WireConfigError:
            raise
        except Exception as exc:
            raise WireConfigError(
                f"codex_transaction_journal_write_failed: {_redact_secret_text(exc)}"
            ) from exc

    def _recover_interrupted_codex_transaction(self, *, lock_held: bool = False) -> None:
        journal_path = self._codex_transaction_journal_path()
        journal = read_json(journal_path, {})
        if not isinstance(journal, dict) or journal.get("state") not in CODEX_TRANSACTION_ACTIVE_STATES:
            return

        def recover() -> bool:
            current = read_json(journal_path, {})
            if not isinstance(current, dict) or current.get("state") not in CODEX_TRANSACTION_ACTIVE_STATES:
                return True
            try:
                _restore_codex_transaction_snapshot(current)
                previous_committed = current.get("previousCommittedJournal")
                if isinstance(previous_committed, dict) and previous_committed.get("state") == "committed":
                    previous_committed["recoveredAfterRestart"] = True
                    previous_committed["recoveredAt"] = _iso_now()
                    self._write_codex_transaction_journal(previous_committed)
                else:
                    current["state"] = "rolled_back"
                    current["rolledBackAt"] = _iso_now()
                    current["recoveredAfterRestart"] = True
                    self._write_codex_transaction_journal(current)
                _broadcast_user_env_change()
                return True
            except Exception as exc:
                current["state"] = "recovery_required"
                current["rollbackError"] = _redact_secret_text(str(exc))
                self._write_codex_transaction_journal(current)
                return False

        if lock_held:
            if not recover():
                raise WireConfigError("codex_config_recovery_required")
            return
        try:
            with _exclusive_codex_config_lock(self.paths, timeout_seconds=0.05):
                recover()
        except WireConfigError:
            return

    def rollback_agent_model_config(self, component_id: str) -> dict[str, Any]:
        component_id = str(component_id or "").strip()
        if component_id not in AGENT_MODEL_CONFIGS:
            raise WireConfigError("该组件暂不支持模型配置回滚")
        if component_id == "codex-desktop":
            with _exclusive_codex_config_lock(
                self.paths,
                timeout_seconds=CODEX_TRANSACTION_LOCK_TIMEOUT_SECONDS,
            ):
                journal = read_json(self._codex_transaction_journal_path(), {})
                if not isinstance(journal, dict) or journal.get("state") != "committed":
                    raise WireConfigError("codex_config_rollback_snapshot_missing")
                journal["state"] = "rolling_back"
                journal["manualRollback"] = True
                self._write_codex_transaction_journal(journal)
                try:
                    _restore_codex_transaction_snapshot(journal)
                    journal["state"] = "manually_rolled_back"
                    journal["rolledBackAt"] = _iso_now()
                    self._write_codex_transaction_journal(journal)
                    _broadcast_user_env_change()
                except Exception as exc:
                    journal["state"] = "recovery_required"
                    journal["rollbackError"] = _redact_secret_text(str(exc))
                    self._write_codex_transaction_journal(journal)
                    raise WireConfigError("codex_config_recovery_required") from exc
                return self.agent_model_config_status(component_id)
        metadata = self._agent_config_metadata(component_id)
        backup_path = str(metadata.get("backupPath") or "")
        config_path = self._agent_config_path(component_id)
        if not backup_path or not os.path.isfile(backup_path):
            raise WireConfigError("没有可回滚的模型配置备份")
        _atomic_write_text(config_path, _read_text(backup_path))
        metadata["configured"] = True
        metadata["updatedAt"] = _iso_now()
        write_json(self._agent_config_metadata_path(component_id), metadata)
        return self.agent_model_config_status(component_id)

    def disable_agent_model_config(self, component_id: str) -> dict[str, Any]:
        component_id = str(component_id or "").strip()
        if component_id != "codex-desktop":
            raise WireConfigError("当前仅支持恢复 Codex 官方渠道")
        with _exclusive_codex_config_lock(
            self.paths,
            timeout_seconds=CODEX_TRANSACTION_LOCK_TIMEOUT_SECONDS,
        ):
            managed_path = self._agent_config_path(component_id)
            user_path = _user_codex_config_path(self.paths)
            user_env_path = _user_codex_env_path(self.paths)
            metadata_path = self._agent_config_metadata_path(component_id)
            auth_path = os.path.join(os.path.dirname(user_path), "auth.json")
            managed_text = _read_text(managed_path) if os.path.isfile(managed_path) else ""
            user_text = _read_text(user_path) if os.path.isfile(user_path) else ""
            user_env_text = _read_text(user_env_path) if os.path.isfile(user_env_path) else ""
            journal = read_json(self._codex_transaction_journal_path(), {})
            if not isinstance(journal, dict):
                journal = {}
            previous_committed = copy.deepcopy(journal) if journal.get("state") == "committed" else {}
            baseline = journal.get("officialBaseline") if isinstance(journal.get("officialBaseline"), dict) else {}
            baseline_snapshots = baseline.get("snapshots") if isinstance(baseline.get("snapshots"), dict) else {}
            baseline_environment = baseline.get("environment") if isinstance(baseline.get("environment"), dict) else {}

            cleaned_managed, managed_changed = _remove_loom_codex_provider(managed_text)
            if managed_text and not managed_changed:
                raise WireConfigError("codex_official_restore_unmanaged_config")
            user_profile = _codex_config_profile(user_text)
            if user_profile.get("channelMode") in {"custom", "invalid"}:
                raise WireConfigError("codex_official_restore_unmanaged_config")

            if previous_committed:
                baseline_user_text = _snapshot_text(baseline_snapshots.get("userConfig"))
                restored_user_text = _restore_codex_user_config_from_baseline(user_text, baseline_user_text)
                user_changed = restored_user_text != user_text
            else:
                restored_user_text, user_changed = _remove_loom_codex_provider(user_text)

            environment_names = (*AGENT_STALE_MODEL_ENV_KEYS, "LOOM_CODEX_API_KEY")
            current_wire = self.current() or {}
            expected_key = _pick_text(current_wire.get("apiKey"))
            baseline_user_env_text = _snapshot_text(baseline_snapshots.get("userEnv"))
            restored_user_env_text = _restore_dotenv_key_if_unchanged(
                user_env_text,
                baseline_user_env_text,
                "LOOM_CODEX_API_KEY",
                expected_key,
            )
            user_env_changed = restored_user_env_text != user_env_text
            applied_environment = journal.get("appliedEnvironment") if isinstance(journal.get("appliedEnvironment"), dict) else {}
            if previous_committed and not applied_environment:
                persist_registry = _should_persist_user_env(self.paths)
                applied_environment = {
                    name: {
                        "processExists": name == "LOOM_CODEX_API_KEY" and bool(expected_key),
                        "processValue": protect_secret(expected_key) if name == "LOOM_CODEX_API_KEY" and expected_key else "",
                        "registryCaptured": persist_registry,
                        "registryValue": protect_secret(expected_key) if name == "LOOM_CODEX_API_KEY" and expected_key and persist_registry else None,
                        "registryKind": None,
                    }
                    for name in environment_names
                }

            disable_journal = {
                "schemaVersion": 1,
                "transactionId": uuid.uuid4().hex,
                "componentId": component_id,
                "transactionType": "disable",
                "state": "disabling",
                "officialChannelRestore": True,
                "startedAt": _iso_now(),
                "snapshots": {
                    "managedConfig": _snapshot_text_file(managed_path),
                    "userConfig": _snapshot_text_file(user_path),
                    "userEnv": _snapshot_text_file(user_env_path),
                    "metadata": _snapshot_text_file(metadata_path),
                },
                "environment": {name: _snapshot_environment_value(self.paths, name) for name in environment_names},
                "previousCommittedJournal": previous_committed,
                "officialBaseline": copy.deepcopy(baseline),
                "officialAuthPath": auth_path,
                "officialAuthSha256": _sha256_file(auth_path),
            }
            self._write_codex_transaction_journal(disable_journal)
            try:
                if os.path.isfile(managed_path) and _sha256_file(managed_path) != hashlib.sha256(managed_text.encode("utf-8")).hexdigest():
                    raise WireConfigError("codex_config_busy")
                if os.path.isfile(user_path) and _sha256_file(user_path) != hashlib.sha256(user_text.encode("utf-8")).hexdigest():
                    raise WireConfigError("codex_config_busy")
                if os.path.isfile(user_env_path) and _sha256_file(user_env_path) != hashlib.sha256(user_env_text.encode("utf-8")).hexdigest():
                    raise WireConfigError("codex_config_busy")
                if managed_changed:
                    if cleaned_managed.strip():
                        _atomic_write_text(managed_path, cleaned_managed)
                    elif os.path.exists(managed_path):
                        os.remove(managed_path)
                if user_changed:
                    if restored_user_text.strip():
                        _atomic_write_text(user_path, restored_user_text)
                    elif os.path.exists(user_path):
                        os.remove(user_path)
                if user_env_changed:
                    if restored_user_env_text.strip():
                        _atomic_write_text(user_env_path, restored_user_env_text)
                    elif os.path.exists(user_env_path):
                        os.remove(user_env_path)
                environment_changed = False
                if previous_committed:
                    for name, original in baseline_environment.items():
                        expected = applied_environment.get(name)
                        if isinstance(original, dict) and isinstance(expected, dict):
                            environment_changed = _restore_environment_snapshot_if_unchanged(
                                self.paths,
                                str(name),
                                original,
                                expected,
                            ) or environment_changed
                elif managed_changed or user_changed:
                    os.environ.pop("LOOM_CODEX_API_KEY", None)
                    if _should_persist_user_env(self.paths):
                        environment_changed = _delete_user_env_var("LOOM_CODEX_API_KEY", broadcast=False)
                _atomic_write_text(metadata_path, json.dumps({
                    "componentId": component_id,
                    "configured": False,
                    "managedBy": "",
                    "provider": "",
                    "baseUrl": "",
                    "model": "",
                    "transactionId": disable_journal["transactionId"],
                    "transactionState": "official",
                    "remoteVerified": False,
                    "officialAuthUnchanged": True,
                    "rollbackAvailable": False,
                    "updatedAt": _iso_now(),
                }, indent=2, ensure_ascii=False) + "\n")
                disable_journal["state"] = "official"
                disable_journal["restoredAt"] = _iso_now()
                disable_journal.pop("previousCommittedJournal", None)
                self._write_codex_transaction_journal(disable_journal)
                if environment_changed:
                    _broadcast_user_env_change()
            except Exception as exc:
                try:
                    _restore_codex_transaction_snapshot(disable_journal)
                    if previous_committed:
                        previous_committed["lastDisableFailure"] = _redact_secret_text(str(exc))
                        previous_committed["lastDisableFailedAt"] = _iso_now()
                        self._write_codex_transaction_journal(previous_committed)
                    else:
                        disable_journal["state"] = "rolled_back"
                        disable_journal["rolledBackAt"] = _iso_now()
                        self._write_codex_transaction_journal(disable_journal)
                    _broadcast_user_env_change()
                except Exception as rollback_error:
                    disable_journal["state"] = "recovery_required"
                    disable_journal["rollbackError"] = _redact_secret_text(str(rollback_error))
                    self._write_codex_transaction_journal(disable_journal)
                    raise WireConfigError("codex_config_recovery_required") from exc
                if isinstance(exc, WireConfigError):
                    raise
                raise WireConfigError(_redact_secret_text(str(exc))) from exc
            return self.agent_model_config_status(component_id)

    def _sync_openclaw_agent_model_config(self, component_id: str, wire: dict[str, Any], selected_model: str) -> dict[str, Any]:
        config_path = self._agent_config_path(component_id)
        backup_path = _backup_text_file(config_path)
        models = wire.get("modelLists") if isinstance(wire.get("modelLists"), dict) else {}
        text_models = _desktop_text_models(_list_values(models.get("text")))
        if selected_model and selected_model not in text_models:
            text_models = [selected_model, *text_models]
        managed_by = _wire_managed_by(wire)
        try:
            ok = sync_openclaw_models_from_gateway_profile(
                self.paths,
                {
                    "source": managed_by,
                    "managedBy": managed_by,
                    "profileKey": "custom_provider" if managed_by == WIRE_CUSTOM_MANAGED_BY else "member_gateway",
                    "name": _pick_text(wire.get("provider"), "LOOM"),
                    "authMode": "custom" if managed_by == WIRE_CUSTOM_MANAGED_BY else "member",
                    "baseUrl": _pick_text(wire.get("baseUrl")),
                    "apiKey": _pick_text(wire.get("apiKey")),
                    "defaultModel": selected_model,
                    "imageModel": _model_value(wire, "image", ""),
                    "models": text_models or [selected_model],
                },
            )
            if not ok:
                raise WireConfigError("OpenClaw 模型配置写入失败，请先同步托管模型")
        except Exception as exc:
            if backup_path and os.path.isfile(backup_path):
                _restore_text(config_path, _read_text(backup_path))
            if isinstance(exc, WireConfigError):
                raise
            raise WireConfigError(f"OpenClaw 模型配置写入失败：{exc}") from exc

        metadata = {
            "componentId": component_id,
            "configured": True,
            "managedBy": managed_by,
            "provider": _pick_text(wire.get("provider")),
            "baseUrl": _pick_text(wire.get("baseUrl")).rstrip("/"),
            "model": selected_model,
            "configPath": config_path,
            "backupPath": backup_path or self._agent_config_metadata(component_id).get("backupPath") or "",
            "updatedAt": _iso_now(),
        }
        write_json(self._agent_config_metadata_path(component_id), metadata)
        return self.agent_model_config_status(component_id)

    def _sync_openclaw(self, wire: dict[str, Any]) -> None:
        models = wire.get("modelLists") if isinstance(wire.get("modelLists"), dict) else {}
        text_models = _desktop_text_models(models.get("text") if isinstance(models.get("text"), list) else [])
        default_model = _desktop_text_model(_model_value(wire, "text", ""))
        if not default_model and text_models:
            default_model = text_models[0]
        managed_by = _wire_managed_by(wire)
        if not default_model:
            raise WireConfigError("没有可用文本模型，请同步/购买/换模型")
        ok = sync_openclaw_models_from_gateway_profile(
            self.paths,
            {
                "source": managed_by,
                "managedBy": managed_by,
                "profileKey": "custom_provider" if managed_by == WIRE_CUSTOM_MANAGED_BY else "member_gateway",
                "name": _pick_text(wire.get("provider"), "Member Gateway"),
                "authMode": "custom" if managed_by == WIRE_CUSTOM_MANAGED_BY else "member",
                "baseUrl": _pick_text(wire.get("baseUrl")),
                "apiKey": _pick_text(wire.get("apiKey")),
                "defaultModel": default_model,
                "imageModel": _model_value(wire, "image", ""),
                "models": text_models or [default_model],
            },
        )
        if not ok:
            raise WireConfigError("OpenClaw 模型配置写入失败，请先同步托管模型")

    def _sync_opencode(self, wire: dict[str, Any]) -> None:
        base_url = _pick_text(wire.get("baseUrl")).rstrip("/")
        api_key = _pick_text(wire.get("apiKey"))
        default_model = _desktop_text_model(_model_value(wire, "text", ""))
        model_lists = wire.get("modelLists") if isinstance(wire.get("modelLists"), dict) else {}
        text_models = _desktop_text_models(_list_values(model_lists.get("text")))
        if default_model and default_model not in text_models:
            text_models = [default_model, *text_models]
        text_models = [model for model in text_models if model]
        if not default_model and text_models:
            default_model = text_models[0]
        if not text_models and default_model:
            text_models = [default_model]
        if not default_model:
            raise WireConfigError("没有可用文本模型，请同步/购买/换模型")
        if not base_url or not api_key:
            raise WireConfigError("opencode 缺少托管模型配置")

        _clear_stale_agent_model_env_keys(self.paths)
        provider_id = "loom"
        config_dir = os.path.join(self.paths.data_dir, ".opencode")
        os.makedirs(config_dir, exist_ok=True)
        config_path = os.path.join(config_dir, "opencode.json")
        config = read_json(config_path, {})
        if not isinstance(config, dict):
            config = {}
        config["$schema"] = "https://opencode.ai/config.json"
        config["model"] = f"{provider_id}/{default_model}"
        provider = config.get("provider") if isinstance(config.get("provider"), dict) else {}
        provider[provider_id] = {
            "name": "LOOM 模型服务",
            "npm": "@ai-sdk/openai-compatible",
            "options": {
                "baseURL": base_url,
                "apiKey": "{env:LOOM_OPENCODE_API_KEY}",
            },
            "models": {model: {"name": model} for model in text_models},
        }
        config["provider"] = provider
        write_json(config_path, config)
        _persist_agent_env_key(self.paths, "LOOM_OPENCODE_API_KEY", api_key)

    def _sync_codex(self, wire: dict[str, Any]) -> None:
        self.sync_agent_model_config("codex-desktop", wire=wire)

    def _sync_claude(self, wire: dict[str, Any]) -> None:
        self.sync_agent_model_config("claude-code", wire=wire)

    def _sync_image(self, wire: dict[str, Any]) -> None:
        image_model = _model_value(wire, "image", "")
        if not image_model:
            return
        current = read_json(self.paths.image_config, {})
        if not isinstance(current, dict):
            current = {}
        if current.get("lockedByUser") is True:
            return
        managed_by = _wire_managed_by(wire)
        current.update({
            "gatewayMode": "member",
            "managedBy": managed_by,
            "baseUrl": _pick_text(wire.get("baseUrl")),
            "apiKey": _pick_text(wire.get("apiKey")),
            "model": image_model,
        })
        write_json(self.paths.image_config, current)

    def _sync_desktop(self, wire: dict[str, Any]) -> None:
        model = _desktop_text_model(_model_value(wire, "text", ""))
        if not model:
            model_lists = wire.get("modelLists") if isinstance(wire.get("modelLists"), dict) else {}
            text_models = _desktop_text_models(_list_values(model_lists.get("text")))
            model = text_models[0] if text_models else ""
        if not model:
            raise WireConfigError("没有可用文本模型，请同步/购买/换模型")
        managed_by = _wire_managed_by(wire)
        provider = {
            "managedBy": managed_by,
            "apiKey": _pick_text(wire.get("apiKey")),
            "baseUrl": _pick_text(wire.get("baseUrl")),
            "baseURL": _pick_text(wire.get("baseUrl")),
            "model": model,
        }
        path = os.path.join(self.paths.launcher_dir, "desktop-agent.json")
        current = read_json(path, {})
        if not isinstance(current, dict):
            current = {}
        current.setdefault("provider", {})
        current.setdefault("llm", {})
        current.setdefault("chatProvider", {})
        current["chatProvider"].setdefault("config", {})
        current["provider"].update(provider)
        current["llm"].update(provider)
        current["chatProvider"]["config"].update(provider)
        write_json(path, current)

    def _sync_phone(self, wire: dict[str, Any]) -> None:
        path = os.path.join(self.paths.launcher_dir, "phone-agent.json")
        current = read_json(path, {})
        if not isinstance(current, dict):
            current = {}
        current.setdefault("llm", {})
        managed_by = _wire_managed_by(wire)
        current["llm"].update({
            "managedBy": managed_by,
            "baseUrl": _pick_text(wire.get("baseUrl")),
            "apiKey": _pick_text(wire.get("apiKey")),
            "model": _model_value(wire, "phone", DEFAULT_PHONE_MODEL),
        })
        write_json(path, current)

    def _clear_video(self, _wire: dict[str, Any]) -> None:
        for path in (self.paths.video_config, self.paths.videoapi_config):
            current = read_json(path, {})
            if not isinstance(current, dict) or current.get("lockedByUser") is True:
                continue
            if current.get("managedBy") in MANAGED_ACCOUNT_SOURCES or current.get("gatewayMode") == "member":
                write_json(path, {})

    def _agent_config_path(self, component_id: str) -> str:
        target = AGENT_MODEL_CONFIGS[component_id]
        return os.path.join(self.paths.data_dir, str(target["configDir"]), str(target["configFile"]))

    def _agent_config_metadata_path(self, component_id: str) -> str:
        return os.path.join(self.paths.launcher_dir, "agent-model-configs", f"{component_id}.json")

    def _agent_config_metadata(self, component_id: str) -> dict[str, Any]:
        metadata = read_json(self._agent_config_metadata_path(component_id), {})
        return metadata if isinstance(metadata, dict) else {}

    def _agent_config_text(self, component_id: str, wire: dict[str, Any], model: str) -> str:
        base_url = _pick_text(wire.get("baseUrl")).rstrip("/")
        provider = _pick_text(wire.get("provider"), "LOOM")
        if component_id == "codex-desktop":
            return _codex_config_text(base_url, provider, model, _wire_managed_by(wire))
        if component_id == "claude-code":
            return _claude_settings_text(base_url, provider, model)
        raise WireConfigError("该组件暂不支持模型配置")


def build_wire_from_session(session: dict[str, Any]) -> dict[str, Any]:
    gateway = session.get("gateway") if isinstance(session.get("gateway"), dict) else {}
    newapi = session.get("newApi") if isinstance(session.get("newApi"), dict) else {}
    phone_agent = session.get("phoneAgent") if isinstance(session.get("phoneAgent"), dict) else {}
    classes = gateway.get("classifiedModels") if isinstance(gateway.get("classifiedModels"), dict) else newapi.get("modelClasses")
    if not isinstance(classes, dict):
        classes = _classify_models(session.get("gatewayModels") if isinstance(session.get("gatewayModels"), list) else [])

    text_model = _pick_text_model(
        _pick_text(session.get("gatewayDefaultModel"), gateway.get("defaultModel")),
        classes.get("text"),
        "",
    )
    image_model = _pick_model(_pick_text(session.get("gatewayImageModel"), gateway.get("imageModel")), classes.get("image"), "")
    video_model = _pick_model(
        _pick_text(session.get("gatewayVideoDraftModel"), gateway.get("videoDraftModel"), session.get("gatewayVideoModel")),
        classes.get("video"),
        "",
    )
    phone_model = _pick_text(phone_agent.get("model"), DEFAULT_PHONE_MODEL)
    api_key = _pick_text(phone_agent.get("apiKey"), session.get("memberToken"), gateway.get("accessToken"))
    base_url = _pick_text(phone_agent.get("baseUrl"), session.get("gatewayBaseUrl"), gateway.get("baseUrl"), "https://api.heang.top/v1")
    text_model_list = _desktop_text_models(_list_values(classes.get("text")))
    if text_model and text_model not in text_model_list:
        text_model_list = [text_model, *text_model_list]
    model_lists = {
        "text": text_model_list,
        "image": _list_values(classes.get("image")),
        "video": _list_values(classes.get("video")),
    }
    return {
        "schemaVersion": 1,
        "managedBy": WIRE_MANAGED_BY,
        "accountId": _pick_text(session.get("memberId"), newapi.get("userId")),
        "account": _pick_text(session.get("memberName"), newapi.get("account")),
        "provider": WIRE_PROVIDER,
        "baseUrl": base_url.rstrip("/"),
        "apiKey": api_key,
        "tokenMasked": _mask_secret(api_key),
        "models": {
            "text": text_model,
            "phone": phone_model,
            "image": image_model,
            "video": video_model,
        },
        "modelLists": model_lists,
            "targets": {
                "openclaw": True,
                "phone": True,
                "desktopRpa": True,
                "imageGateway": bool(image_model),
                "videoGateway": False,
                "opencode": True,
                "codex": True,
                "claude": True,
            },
        "updatedAt": _iso_now(),
    }


def _protected_wire(wire: dict[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(wire)
    if payload.get("apiKey"):
        payload["apiKey"] = protect_secret(payload.get("apiKey"))
    return payload


def _read_json_if_exists(path: str) -> Any | None:
    if not os.path.exists(path):
        return None
    return read_json(path, None)


def _unprotect_wire(wire: dict[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(wire)
    if "apiKey" in payload:
        payload["apiKey"] = unprotect_secret(payload.get("apiKey"))
    return payload


def _public_wire(wire: dict[str, Any] | None) -> dict[str, Any]:
    if not wire:
        return {
            "ok": False,
            "managedBy": "",
            "provider": "",
            "models": {"text": "", "phone": "", "image": "", "video": ""},
            "targets": {},
        }
    payload = copy.deepcopy(wire)
    payload.pop("apiKey", None)
    payload["ok"] = True
    payload["tokenMasked"] = _mask_secret(wire.get("apiKey") or wire.get("tokenMasked") or "")
    return payload


def _classify_models(models: list[Any]) -> dict[str, list[str]]:
    classified = {"text": [], "image": [], "video": []}
    for raw in models:
        model = _pick_text(raw.get("id") if isinstance(raw, dict) else raw)
        if not model:
            continue
        if _looks_like_video_model(model):
            classified["video"].append(model)
        elif _looks_like_image_model(model):
            classified["image"].append(model)
        elif _looks_like_phone_model(model):
            continue
        else:
            classified["text"].append(model)
    return classified


def _list_values(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    result: list[str] = []
    for value in values:
        text = _pick_text(value.get("id") if isinstance(value, dict) else value)
        if text and text not in result:
            result.append(text)
    return result


def _model_value(wire: dict[str, Any], key: str, fallback: str) -> str:
    models = wire.get("models") if isinstance(wire.get("models"), dict) else {}
    return _pick_text(models.get(key), fallback)


def _pick_agent_model(wire: dict[str, Any], preferred: str = "") -> str:
    model_lists = wire.get("modelLists") if isinstance(wire.get("modelLists"), dict) else {}
    text_models = _desktop_text_models(_list_values(model_lists.get("text")))
    preferred = _pick_text(preferred)
    if preferred:
        return _desktop_text_model(preferred)
    current = _desktop_text_model(_model_value(wire, "text", ""))
    if current and (not text_models or current in text_models):
        return current
    return text_models[0] if text_models else ""


def _pick_model(preferred: str, candidates: Any, fallback: str) -> str:
    values = _list_values(candidates)
    if preferred and (not values or preferred in values):
        return preferred
    return values[0] if values else fallback


def _pick_text_model(preferred: str, candidates: Any, fallback: str) -> str:
    values = _desktop_text_models(_list_values(candidates))
    preferred = _desktop_text_model(preferred)
    fallback = _desktop_text_model(fallback)
    if preferred and (not values or preferred in values):
        return preferred
    for model in TEXT_MODEL_PRIORITY:
        if model in values:
            return model
    return values[0] if values else fallback


def _looks_like_phone_model(model_id: Any) -> bool:
    text = _pick_text(model_id).lower()
    return bool(text) and text in PHONE_MODEL_IDS


def _looks_like_image_model(model_id: Any) -> bool:
    text = _pick_text(model_id).lower()
    return bool(text) and any(marker in text for marker in IMAGE_MODEL_MARKERS)


def _looks_like_video_model(model_id: Any) -> bool:
    text = _pick_text(model_id).lower()
    return bool(text) and any(marker in text for marker in VIDEO_MODEL_MARKERS)


def _looks_like_non_text_model(model_id: Any) -> bool:
    return _looks_like_phone_model(model_id) or _looks_like_image_model(model_id) or _looks_like_video_model(model_id)


def _desktop_text_model(model_id: Any) -> str:
    text = _pick_text(model_id)
    return "" if _looks_like_non_text_model(text) else text


def _desktop_text_models(models: list[str]) -> list[str]:
    result: list[str] = []
    for model in models:
        text = _desktop_text_model(model)
        if text and text not in result:
            result.append(text)
    return result


def _wire_managed_by(wire: dict[str, Any]) -> str:
    value = _pick_text(wire.get("managedBy"), WIRE_MANAGED_BY)
    return value if value in MANAGED_ACCOUNT_SOURCES else WIRE_MANAGED_BY


def _codex_wire_fingerprint(wire: dict[str, Any], model: str) -> str:
    payload = "\n".join([
        _pick_text(wire.get("baseUrl")).rstrip("/"),
        _pick_text(wire.get("apiKey")),
        _pick_text(wire.get("provider")),
        _wire_managed_by(wire),
        _pick_text(model),
    ])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@contextmanager
def _exclusive_codex_config_lock(paths: AppPaths, *, timeout_seconds: float):
    user_config_path = _user_codex_config_path(paths)
    lock_path = os.path.join(os.path.dirname(user_config_path), ".loom-codex-config.lock")
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    key = os.path.normcase(os.path.abspath(user_config_path))
    with _CODEX_LOCKS_GUARD:
        process_lock = _CODEX_LOCKS.setdefault(key, threading.Lock())
    if not process_lock.acquire(timeout=max(0.0, timeout_seconds)):
        raise WireConfigError("codex_config_busy")

    handle = None
    locked = False
    deadline = time.monotonic() + max(0.0, timeout_seconds)
    try:
        handle = open(lock_path, "a+b")
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        while True:
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise WireConfigError("codex_config_busy")
                time.sleep(0.02)
        yield
    finally:
        if handle is not None:
            if locked:
                try:
                    handle.seek(0)
                    if os.name == "nt":
                        import msvcrt

                        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl

                        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass
            handle.close()
        process_lock.release()


def _snapshot_text_file(path: str) -> dict[str, Any]:
    existed = os.path.isfile(path)
    content = _read_text(path) if existed else ""
    return {
        "path": path,
        "existed": existed,
        "content": protect_secret(content) if content else "",
    }


def _restore_text_file_snapshot(snapshot: dict[str, Any]) -> None:
    path = _pick_text(snapshot.get("path"))
    if not path:
        raise WireConfigError("codex_transaction_snapshot_path_missing")
    if snapshot.get("existed"):
        _atomic_write_text(path, unprotect_secret(snapshot.get("content")))
    elif os.path.exists(path):
        os.remove(path)


def _snapshot_environment_value(paths: AppPaths, name: str) -> dict[str, Any]:
    process_exists = name in os.environ
    process_value = os.environ.get(name, "")
    registry_captured = _should_persist_user_env(paths)
    registry_value = _read_user_env_var(name) if registry_captured else None
    registry_kind = _read_user_env_kind(name) if registry_captured else None
    return {
        "processExists": process_exists,
        "processValue": protect_secret(process_value) if process_exists else "",
        "registryCaptured": registry_captured,
        "registryValue": protect_secret(registry_value) if registry_value is not None else None,
        "registryKind": registry_kind,
    }


def _restore_environment_snapshot(name: str, snapshot: dict[str, Any]) -> None:
    if snapshot.get("processExists"):
        os.environ[name] = unprotect_secret(snapshot.get("processValue"))
    else:
        os.environ.pop(name, None)
    if snapshot.get("registryCaptured"):
        value = snapshot.get("registryValue")
        _restore_user_env_var(
            name,
            unprotect_secret(value) if value is not None else None,
            registry_kind=snapshot.get("registryKind"),
        )


def _environment_snapshot_matches_current(paths: AppPaths, name: str, expected: dict[str, Any]) -> bool:
    process_exists = name in os.environ
    expected_process_exists = bool(expected.get("processExists"))
    if process_exists != expected_process_exists:
        return False
    if process_exists and os.environ.get(name, "") != unprotect_secret(expected.get("processValue")):
        return False
    if expected.get("registryCaptured") and _should_persist_user_env(paths):
        current_registry = _read_user_env_var(name)
        expected_registry = expected.get("registryValue")
        expected_registry_value = unprotect_secret(expected_registry) if expected_registry is not None else None
        if current_registry != expected_registry_value:
            return False
    return True


def _restore_environment_snapshot_if_unchanged(
    paths: AppPaths,
    name: str,
    original: dict[str, Any],
    expected: dict[str, Any],
) -> bool:
    if not _environment_snapshot_matches_current(paths, name, expected):
        return False
    _restore_environment_snapshot(name, original)
    return True


def _restore_codex_transaction_snapshot(journal: dict[str, Any]) -> None:
    snapshots = journal.get("snapshots") if isinstance(journal.get("snapshots"), dict) else {}
    for key in ("managedConfig", "userConfig", "userEnv", "metadata"):
        snapshot = snapshots.get(key)
        if isinstance(snapshot, dict):
            _restore_text_file_snapshot(snapshot)
    environment = journal.get("environment") if isinstance(journal.get("environment"), dict) else {}
    for name, snapshot in environment.items():
        if isinstance(snapshot, dict):
            _restore_environment_snapshot(str(name), snapshot)


def _sha256_file(path: str) -> str:
    if not os.path.isfile(path):
        return ""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_codex_config_text(text: str, provider_id: str, base_url: str, model: str) -> None:
    try:
        parsed = tomllib.loads(text)
    except (tomllib.TOMLDecodeError, ValueError) as exc:
        raise WireConfigError(f"invalid_codex_toml: {exc}") from exc
    providers = parsed.get("model_providers") if isinstance(parsed.get("model_providers"), dict) else {}
    provider = providers.get(provider_id) if isinstance(providers, dict) else None
    if parsed.get("model") != model or parsed.get("model_provider") != provider_id:
        raise WireConfigError("codex_config_model_provider_mismatch")
    if not isinstance(provider, dict):
        raise WireConfigError("codex_config_provider_missing")
    if _pick_text(provider.get("base_url")).rstrip("/") != base_url.rstrip("/"):
        raise WireConfigError("codex_config_base_url_mismatch")
    if provider.get("env_key") != "LOOM_CODEX_API_KEY":
        raise WireConfigError("codex_config_env_key_mismatch")
    if provider.get("wire_api") != "responses":
        raise WireConfigError("codex_config_wire_api_mismatch")
    if "experimental_bearer_token" in provider:
        raise WireConfigError("codex_config_plaintext_bearer_forbidden")


def _validate_codex_config_file(path: str, provider_id: str, base_url: str, model: str) -> None:
    if not os.path.isfile(path):
        raise WireConfigError("codex_config_readback_missing")
    _validate_codex_config_text(_read_text(path), provider_id, base_url, model)


def _validate_provider_url(base_url: str) -> str:
    normalized = _normalize_base_url(base_url)
    parsed = urllib.parse.urlsplit(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise WireConfigError("invalid_provider_url")
    if parsed.username or parsed.password:
        raise WireConfigError("provider_url_userinfo_forbidden")
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        address = None
    if address is not None and (
        address.is_link_local
        or address.is_multicast
        or address.is_unspecified
        or (address.is_reserved and not address.is_loopback)
    ):
        raise WireConfigError("provider_url_address_forbidden")
    if parsed.scheme == "http" and parsed.hostname.lower() not in {"127.0.0.1", "localhost", "::1"}:
        raise WireConfigError("insecure_provider_url")
    return normalized.rstrip("/")


def _probe_codex_provider(base_url: str, api_key: str, model: str) -> dict[str, Any]:
    base = _validate_provider_url(base_url)
    candidates = [base]
    if not base.endswith("/v1"):
        candidates.append(f"{base}/v1")
    errors: list[str] = []
    for candidate in candidates:
        models_verified = False
        try:
            models_payload = _provider_json_request(
                f"{candidate}/models",
                api_key,
                method="GET",
            )
            model_ids = _extract_remote_model_ids(models_payload)
            if model_ids:
                models_verified = model in model_ids
                if not models_verified:
                    errors.append(f"{candidate}: selected_model_not_listed")
        except WireConfigError as exc:
            errors.append(f"{candidate}/models: {exc}")

        try:
            responses_payload = _provider_json_request(
                f"{candidate}/responses",
                api_key,
                method="POST",
                payload={
                    "model": model,
                    "input": (
                        "Call loom_capability_probe with probe='codex-tools'. "
                        "Do not answer with plain text."
                    ),
                    "tools": [
                        {
                            "type": "function",
                            "name": "loom_capability_probe",
                            "description": "Verify that this model returns native Responses API function calls.",
                            "parameters": {
                                "type": "object",
                                "properties": {"probe": {"type": "string"}},
                                "required": ["probe"],
                                "additionalProperties": False,
                            },
                            "strict": True,
                        }
                    ],
                    "tool_choice": {"type": "function", "name": "loom_capability_probe"},
                    "max_output_tokens": 128,
                },
            )
            if not isinstance(responses_payload, dict):
                raise WireConfigError("responses_api_invalid_success_payload")
            if responses_payload.get("error"):
                raise WireConfigError("responses_api_error_payload")
            response_id = _pick_text(responses_payload.get("id"))
            response_status = _pick_text(responses_payload.get("status")).lower()
            has_output = isinstance(responses_payload.get("output"), list) or isinstance(
                responses_payload.get("output_text"), str
            )
            if not response_id or not has_output:
                raise WireConfigError("responses_api_invalid_success_payload")
            if response_status and response_status != "completed":
                raise WireConfigError("responses_api_invalid_success_payload")
            if not _has_codex_probe_tool_call(responses_payload):
                raise WireConfigError("responses_tool_call_missing")
            return {
                "baseUrl": candidate,
                "endpoint": f"{candidate}/responses",
                "httpStatus": 200,
                "model": model,
                "modelsVerified": models_verified,
                "responsesVerified": True,
                "toolCallsVerified": True,
                "verifiedAt": _iso_now(),
            }
        except WireConfigError as exc:
            errors.append(f"{candidate}/responses: {exc}")
    safe = _redact_secret_text("; ".join(errors[-4:]))
    raise WireConfigError(f"remote_responses_probe_failed: {safe}")


def _has_codex_probe_tool_call(payload: dict[str, Any]) -> bool:
    output = payload.get("output")
    if not isinstance(output, list):
        return False
    for item in output:
        if not isinstance(item, dict) or item.get("type") != "function_call":
            continue
        if _pick_text(item.get("name")) != "loom_capability_probe":
            continue
        if not _pick_text(item.get("call_id")):
            continue
        arguments = item.get("arguments")
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except (TypeError, ValueError):
                continue
        if isinstance(arguments, dict) and arguments.get("probe") == "codex-tools":
            return True
    return False


def _provider_json_request(
    url: str,
    api_key: str,
    *,
    method: str,
    payload: dict[str, Any] | None = None,
) -> Any:
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "LOOM-Codex-Config-Probe/1.0",
        },
    )
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    try:
        opener = urllib.request.build_opener(NoRedirect())
        with opener.open(request, timeout=CODEX_REMOTE_PROBE_TIMEOUT_SECONDS) as response:
            status = int(getattr(response, "status", 200) or 200)
            raw = response.read(1024 * 1024)
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read(2048).decode("utf-8", errors="replace")
        except Exception:
            detail = ""
        if api_key:
            detail = detail.replace(api_key, "[redacted]")
        raise WireConfigError(f"http_{exc.code}: {_redact_secret_text(detail)[:320]}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise WireConfigError(f"network_error: {_redact_secret_text(exc)}") from exc
    if status >= 400:
        raise WireConfigError(f"http_{status}")
    if not raw:
        return {}
    try:
        return json.loads(raw.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WireConfigError("provider_response_not_json") from exc


def _extract_remote_model_ids(payload: Any) -> list[str]:
    if isinstance(payload, dict):
        for key in ("data", "models", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                payload = value
                break
    if not isinstance(payload, list):
        return []
    result: list[str] = []
    for item in payload:
        model_id = _pick_text(
            item.get("id") if isinstance(item, dict) else item,
            item.get("model") if isinstance(item, dict) else "",
            item.get("name") if isinstance(item, dict) else "",
        )
        if model_id and model_id not in result:
            result.append(model_id)
    return result


def _normalize_base_url(value: Any) -> str:
    text = _pick_text(value).rstrip("/")
    if not text:
        return ""
    if not text.startswith(("http://", "https://")):
        text = f"https://{text}"
    return text.rstrip("/")


def _pick_text(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text and text.lower() != "none":
            return text
    return ""


def _agent_config_model(component_id: str, path: str) -> str:
    if not path or not os.path.isfile(path):
        return ""
    try:
        if component_id == "codex-desktop":
            for line in _read_text(path).splitlines():
                stripped = line.strip()
                if stripped.startswith("model = "):
                    return _pick_text(stripped.split("=", 1)[1].strip().strip('"'))
        if component_id == "claude-code":
            payload = json.loads(_read_text(path))
            env = payload.get("env") if isinstance(payload, dict) else {}
            return _pick_text(env.get("ANTHROPIC_MODEL")) if isinstance(env, dict) else ""
    except Exception:
        return ""
    return ""


def _mask_secret(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) <= 8:
        return "****"
    return f"{text[:4]}****{text[-4:]}"


def _codex_provider_id(provider: str, managed_by: str = "") -> str:
    if managed_by == WIRE_MANAGED_BY and _pick_text(provider).lower() in {"", "loom", "luming", "麓鸣"}:
        provider = WIRE_PROVIDER
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", _pick_text(provider, WIRE_PROVIDER).lower()).strip("-_")
    if not slug or slug in {"openai", "ollama", "lmstudio"}:
        slug = "loom"
    return slug


def _codex_provider_block(base_url: str, provider: str, provider_id: str) -> list[str]:
    return [
        f"[model_providers.{provider_id}]",
        f'name = "{_toml_string(provider or "LOOM")}"',
        f'base_url = "{_toml_string(base_url)}"',
        'env_key = "LOOM_CODEX_API_KEY"',
        'wire_api = "responses"',
    ]


def _codex_config_text(base_url: str, provider: str, model: str, managed_by: str = "") -> str:
    provider_id = _codex_provider_id(provider, managed_by)
    return "\n".join([
        "# Managed by LOOM. The real token is injected at launch time.",
        "# Only model/provider fields are managed; personal Codex plugins and MCP stay in user config.",
        f'model = "{_toml_string(model)}"',
        f'model_provider = "{provider_id}"',
        "",
        *_codex_provider_block(base_url, provider, provider_id),
        "",
    ])


def _codex_user_config_text(existing_text: str, base_url: str, provider: str, model: str, managed_by: str = "") -> str:
    if not _pick_text(existing_text):
        return _codex_config_text(base_url, provider, model, managed_by)
    provider_id = _codex_provider_id(provider, managed_by)
    lines = existing_text.splitlines()
    lines = _upsert_top_level_toml_value(lines, "model", model)
    lines = _upsert_top_level_toml_value(lines, "model_provider", provider_id)
    lines = _remove_toml_table(lines, f"[model_providers.{provider_id}]")
    while lines and not lines[-1].strip():
        lines.pop()
    lines.extend(["", *_codex_provider_block(base_url, provider, provider_id), ""])
    return "\n".join(lines)


def _upsert_top_level_toml_value(lines: list[str], key: str, value: str) -> list[str]:
    result: list[str] = []
    replaced = False
    in_top_level = True
    assignment = f'{key} = "{_toml_string(value)}"'
    key_pattern = re.compile(rf"^{re.escape(key)}\s*=")
    for line in lines:
        stripped = line.strip()
        if in_top_level and stripped.startswith("[") and stripped.endswith("]"):
            if not replaced:
                result.append(assignment)
                replaced = True
            in_top_level = False
        if in_top_level and key_pattern.match(stripped):
            if not replaced:
                result.append(assignment)
                replaced = True
            continue
        result.append(line)
    if in_top_level and not replaced:
        result.append(assignment)
    return result


def _toml_table_path(header: str) -> tuple[str, ...] | None:
    stripped = header.strip()
    if not stripped.startswith("[") or not stripped.endswith("]") or stripped.startswith("[["):
        return None
    marker = "__loom_table_marker__"
    try:
        parsed = tomllib.loads(f"{stripped}\n{marker} = true\n")
    except tomllib.TOMLDecodeError:
        return None

    def find(value: Any, path: tuple[str, ...]) -> tuple[str, ...] | None:
        if not isinstance(value, dict):
            return None
        if value.get(marker) is True:
            return path
        for key, child in value.items():
            found = find(child, (*path, str(key)))
            if found is not None:
                return found
        return None

    return find(parsed, ())


def _remove_toml_table(lines: list[str], table_header: str) -> list[str]:
    result: list[str] = []
    skipping = False
    target_path = _toml_table_path(table_header)
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            current_path = _toml_table_path(stripped)
            is_target = bool(
                target_path is not None
                and current_path is not None
                and current_path == target_path
            ) or stripped == table_header
            is_target_child = bool(
                skipping
                and target_path is not None
                and current_path is not None
                and current_path[:len(target_path)] == target_path
            )
            if is_target or is_target_child:
                skipping = True
                continue
            if skipping:
                skipping = False
        if not skipping:
            result.append(line)
    return result


def _extract_toml_table(lines: list[str], table_header: str) -> list[str]:
    result: list[str] = []
    collecting = False
    target_path = _toml_table_path(table_header)
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            current_path = _toml_table_path(stripped)
            is_target = bool(
                target_path is not None
                and current_path is not None
                and current_path == target_path
            ) or stripped == table_header
            is_target_child = bool(
                collecting
                and target_path is not None
                and current_path is not None
                and current_path[:len(target_path)] == target_path
            )
            if is_target or is_target_child:
                collecting = True
            elif collecting:
                break
        if collecting:
            result.append(line)
    return result


def _codex_config_profile(text: str) -> dict[str, Any]:
    if not _pick_text(text):
        return {"model": "", "providerId": "", "provider": {}, "channelMode": "official"}
    try:
        parsed = tomllib.loads(text)
    except (tomllib.TOMLDecodeError, ValueError):
        return {"model": "", "providerId": "", "provider": {}, "channelMode": "invalid"}
    provider_id = _pick_text(parsed.get("model_provider"))
    providers = parsed.get("model_providers") if isinstance(parsed.get("model_providers"), dict) else {}
    provider = providers.get(provider_id) if provider_id and isinstance(providers, dict) else {}
    if not isinstance(provider, dict):
        provider = {}
    channel_mode = (
        "managed"
        if provider.get("env_key") == "LOOM_CODEX_API_KEY"
        else "custom"
        if provider_id and provider_id.lower() not in {"openai"}
        else "official"
    )
    return {
        "model": _pick_text(parsed.get("model")),
        "providerId": provider_id,
        "provider": provider,
        "channelMode": channel_mode,
    }


def _snapshot_text(snapshot: dict[str, Any] | None) -> str:
    if not isinstance(snapshot, dict) or not snapshot.get("existed"):
        return ""
    return unprotect_secret(snapshot.get("content"))


def _restore_codex_user_config_from_baseline(current_text: str, baseline_text: str) -> str:
    cleaned, changed = _remove_loom_codex_provider(current_text)
    if not changed:
        return current_text
    try:
        baseline = tomllib.loads(baseline_text) if _pick_text(baseline_text) else {}
    except (tomllib.TOMLDecodeError, ValueError) as exc:
        raise WireConfigError(f"codex_official_baseline_invalid: {exc}") from exc
    lines = cleaned.splitlines()
    baseline_model = baseline.get("model")
    baseline_provider_id = _pick_text(baseline.get("model_provider"))
    if isinstance(baseline_model, str) and baseline_model.strip():
        lines = _upsert_top_level_toml_value(lines, "model", baseline_model.strip())
    if baseline_provider_id:
        lines = _upsert_top_level_toml_value(lines, "model_provider", baseline_provider_id)
        lines = _remove_toml_table(lines, f'[model_providers."{baseline_provider_id}"]')
        provider_lines = _extract_toml_table(
            baseline_text.splitlines(),
            f'[model_providers."{baseline_provider_id}"]',
        )
        if provider_lines:
            while lines and not lines[-1].strip():
                lines.pop()
            lines.extend(["", *provider_lines])
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines) + ("\n" if lines else "")


def _remove_loom_codex_provider(text: str) -> tuple[str, bool]:
    if not _pick_text(text):
        return text, False
    try:
        parsed = tomllib.loads(text)
    except (tomllib.TOMLDecodeError, ValueError):
        return text, False
    provider_id = _pick_text(parsed.get("model_provider"))
    providers = parsed.get("model_providers") if isinstance(parsed.get("model_providers"), dict) else {}
    provider = providers.get(provider_id) if provider_id and isinstance(providers, dict) else None
    if not isinstance(provider, dict) or provider.get("env_key") != "LOOM_CODEX_API_KEY":
        return text, False

    lines = _remove_toml_table(text.splitlines(), f'[model_providers."{provider_id}"]')
    result: list[str] = []
    top_level = True
    root_keys = {"model", "model_provider"}
    for line in lines:
        stripped = line.strip()
        if top_level and stripped.startswith("[") and stripped.endswith("]"):
            top_level = False
        key = stripped.split("=", 1)[0].strip() if "=" in stripped else ""
        if top_level and key in root_keys:
            continue
        if stripped in {
            "# Managed by LOOM. The real token is injected at launch time.",
            "# Only model/provider fields are managed; personal Codex plugins and MCP stay in user config.",
        }:
            continue
        result.append(line)
    while result and not result[-1].strip():
        result.pop()
    cleaned = "\n".join(result)
    if cleaned:
        cleaned += "\n"
    return cleaned, True


def _user_codex_config_path(paths: AppPaths) -> str:
    override = _pick_text(os.environ.get("LOOM_CODEX_CONFIG_PATH"))
    if override:
        return os.path.abspath(os.path.expanduser(override))
    codex_home = _pick_text(os.environ.get("CODEX_HOME"))
    if codex_home:
        return os.path.join(os.path.abspath(os.path.expanduser(codex_home)), "config.toml")
    base_path = os.path.abspath(paths.base_path)
    temp_root = os.path.abspath(tempfile.gettempdir())
    if _path_is_within(base_path, temp_root):
        return os.path.join(paths.data_dir, ".codex-user", "config.toml")
    return os.path.join(os.path.expanduser("~"), ".codex", "config.toml")


def _user_codex_env_path(paths: AppPaths) -> str:
    return os.path.join(os.path.dirname(_user_codex_config_path(paths)), ".env")


def _dotenv_assignment_pattern(name: str) -> re.Pattern[str]:
    return re.compile(rf"^\s*(?:export\s+)?{re.escape(name)}\s*=", re.IGNORECASE)


def _dotenv_value_from_text(text: str, name: str) -> str | None:
    pattern = _dotenv_assignment_pattern(name)
    value: str | None = None
    for line in text.splitlines():
        if not pattern.match(line):
            continue
        raw = line.split("=", 1)[1].strip()
        if len(raw) >= 2 and raw[0] == raw[-1] == '"':
            try:
                parsed = json.loads(raw)
                value = parsed if isinstance(parsed, str) else str(parsed)
                continue
            except (json.JSONDecodeError, ValueError):
                pass
        if len(raw) >= 2 and raw[0] == raw[-1] == "'":
            value = raw[1:-1]
        else:
            value = raw
    return value


def _read_dotenv_value(path: str, name: str) -> str | None:
    if not os.path.isfile(path):
        return None
    return _dotenv_value_from_text(_read_text(path), name)


def _upsert_dotenv_value(text: str, name: str, value: str) -> str:
    pattern = _dotenv_assignment_pattern(name)
    marker = f"# Managed by LOOM for Codex desktop: {name}"
    lines = [line for line in text.splitlines() if not pattern.match(line) and line.strip() != marker]
    while lines and not lines[-1].strip():
        lines.pop()
    if lines:
        lines.append("")
    lines.extend((marker, f"{name}={json.dumps(value, ensure_ascii=False)}"))
    return "\n".join(lines) + "\n"


def _remove_dotenv_value(text: str, name: str) -> str:
    pattern = _dotenv_assignment_pattern(name)
    marker = f"# Managed by LOOM for Codex desktop: {name}"
    lines = [line for line in text.splitlines() if not pattern.match(line) and line.strip() != marker]
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines) + ("\n" if lines else "")


def _restore_dotenv_key_if_unchanged(
    current_text: str,
    baseline_text: str,
    name: str,
    expected_value: str,
) -> str:
    if _dotenv_value_from_text(current_text, name) != expected_value:
        return current_text
    baseline_value = _dotenv_value_from_text(baseline_text, name)
    if baseline_value is None:
        return _remove_dotenv_value(current_text, name)
    return _upsert_dotenv_value(current_text, name, baseline_value)


def _path_is_within(path: str, root: str) -> bool:
    try:
        return os.path.normcase(os.path.commonpath([path, root])) == os.path.normcase(os.path.abspath(root))
    except (OSError, ValueError):
        return False


def clear_agent_user_env_keys(paths: AppPaths) -> None:
    changed = False
    for name in AGENT_ENV_KEYS:
        os.environ.pop(name, None)
        if _should_persist_user_env(paths):
            changed = _delete_user_env_var(name, broadcast=False) or changed
    codex_env_path = _user_codex_env_path(paths)
    if os.path.isfile(codex_env_path):
        current_text = _read_text(codex_env_path)
        cleaned_text = _remove_dotenv_value(current_text, "LOOM_CODEX_API_KEY")
        if cleaned_text != current_text:
            if cleaned_text.strip():
                _atomic_write_text(codex_env_path, cleaned_text)
            else:
                os.remove(codex_env_path)
    if changed:
        _broadcast_user_env_change()


def _clear_stale_agent_model_env_keys(paths: AppPaths, *, broadcast: bool = True) -> bool:
    changed = False
    persist = _should_persist_user_env(paths)
    for name in AGENT_STALE_MODEL_ENV_KEYS:
        os.environ.pop(name, None)
        if persist:
            changed = _delete_user_env_var(name, broadcast=False) or changed
    if changed and broadcast:
        _broadcast_user_env_change()
    return changed


def _persist_agent_env_key(paths: AppPaths, name: str, value: str, *, broadcast: bool = True) -> bool:
    if name not in AGENT_ENV_KEYS or not value:
        return False
    os.environ[name] = value
    if _should_persist_user_env(paths):
        return _write_user_env_var(name, value, broadcast=broadcast)
    return False


def _should_persist_user_env(paths: AppPaths) -> bool:
    if str(os.environ.get("LOOM_DISABLE_USER_ENV_SYNC") or "").strip().lower() in {"1", "true", "yes"}:
        return False
    if str(os.environ.get("LOOM_FORCE_USER_ENV_SYNC") or "").strip().lower() in {"1", "true", "yes"}:
        return True
    try:
        base_path = os.path.abspath(paths.base_path)
        temp_root = os.path.abspath(tempfile.gettempdir())
        return not (base_path == temp_root or base_path.startswith(temp_root + os.sep))
    except Exception:
        return False


def _write_user_env_var(
    name: str,
    value: str,
    *,
    broadcast: bool = True,
    registry_kind: int | None = None,
) -> bool:
    if os.name != "nt":
        return False
    import winreg

    access = winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, "Environment", 0, access) as key:
        try:
            current, _kind = winreg.QueryValueEx(key, name)
        except FileNotFoundError:
            current = None
        if str(current or "") == value:
            return False
        value_kind = registry_kind if registry_kind in {winreg.REG_SZ, winreg.REG_EXPAND_SZ} else winreg.REG_SZ
        winreg.SetValueEx(key, name, 0, value_kind, value)
    if broadcast:
        _broadcast_user_env_change()
    return True


def _read_user_env_var(name: str) -> str | None:
    if os.name != "nt":
        return None
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_QUERY_VALUE) as key:
            value, _kind = winreg.QueryValueEx(key, name)
            return str(value)
    except FileNotFoundError:
        return None


def _read_user_env_kind(name: str) -> int | None:
    if os.name != "nt":
        return None
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_QUERY_VALUE) as key:
            _value, kind = winreg.QueryValueEx(key, name)
            return int(kind)
    except FileNotFoundError:
        return None


def _restore_user_env_var(name: str, value: str | None, *, registry_kind: int | None = None) -> None:
    if os.name != "nt":
        return
    if value is None:
        _delete_user_env_var(name, broadcast=False)
    else:
        _write_user_env_var(name, value, broadcast=False, registry_kind=registry_kind)


def _delete_user_env_var(name: str, *, broadcast: bool = True) -> bool:
    if os.name != "nt":
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, name)
    except FileNotFoundError:
        return False
    if broadcast:
        _broadcast_user_env_change()
    return True


def _broadcast_user_env_change() -> None:
    if os.name != "nt":
        return
    try:
        import ctypes

        HWND_BROADCAST = 0xFFFF
        WM_SETTINGCHANGE = 0x001A
        SMTO_ABORTIFHUNG = 0x0002
        ctypes.windll.user32.SendMessageTimeoutW(
            HWND_BROADCAST,
            WM_SETTINGCHANGE,
            0,
            "Environment",
            SMTO_ABORTIFHUNG,
            500,
            None,
        )
    except Exception:
        pass


def _anthropic_base_url(base_url: str) -> str:
    text = _pick_text(base_url).rstrip("/")
    if text.endswith("/v1"):
        return text[:-3].rstrip("/")
    return text


def _claude_settings_text(base_url: str, provider: str, model: str) -> str:
    return json.dumps({
        "managedBy": "LOOM",
        "provider": provider or "LOOM",
        "env": {
            "ANTHROPIC_BASE_URL": _anthropic_base_url(base_url),
            "ANTHROPIC_AUTH_TOKEN": "{env:LOOM_CLAUDE_API_KEY}",
            "ANTHROPIC_API_KEY": "{env:LOOM_CLAUDE_API_KEY}",
            "ANTHROPIC_MODEL": model,
        },
    }, indent=2, ensure_ascii=False) + "\n"


def _write_text_with_backup(path: str, text: str) -> str:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    if os.path.isfile(path) and _read_text(path) == text:
        return ""
    backup_path = _backup_text_file(path)
    try:
        _atomic_write_text(path, text)
    except Exception as exc:
        if backup_path and os.path.isfile(backup_path):
            _restore_text(path, _read_text(backup_path))
        raise WireConfigError(f"模型配置写入失败：{exc}") from exc
    return backup_path


def _backup_text_file(path: str) -> str:
    if not os.path.isfile(path):
        return ""
    backup_dir = os.path.join(os.path.dirname(path), ".loom-backups")
    os.makedirs(backup_dir, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = os.path.join(backup_dir, f"{os.path.basename(path)}.{stamp}.bak")
    _restore_text(backup_path, _read_text(path))
    return backup_path


def _atomic_write_text(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=".loom-", suffix=".tmp", dir=os.path.dirname(path) or ".")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        os.replace(temp_path, path)
    except Exception:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise


def _read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def _restore_text(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def _toml_string(value: Any) -> str:
    return str(value or "").replace("\\", "\\\\").replace('"', '\\"')


def _redact_secret_text(value: Any) -> str:
    text = str(value or "")
    for pattern in SECRET_TEXT_PATTERNS:
        if pattern.groups >= 3:
            text = pattern.sub(lambda match: f"{match.group(1)}{match.group(2)}[redacted]", text)
        elif pattern.groups == 2:
            text = pattern.sub(lambda match: f"{match.group(1)}[redacted]", text)
        else:
            text = pattern.sub("[redacted]", text)
    return text


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
