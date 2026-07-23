"""Capability discovery and bounded execution for the central agent."""

from __future__ import annotations

import inspect
import json
import re
import threading
import time
from dataclasses import dataclass, field, replace
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from core.agent_runtime import redact_sensitive


Json = dict[str, Any]
Executor = Callable[..., Any]


DEFAULT_CANCELLATION_GRACE_SEC = 0.05
VALID_TARGET_SCOPES = frozenset(
    {
        "none",
        "optional-device-write",
        "single-device-read",
        "single-device-write",
        "matrix-write",
        "campaign-write",
    }
)

MEDIA_IMAGE_INPUT_SCHEMA: Json = {
    "type": "object",
    "required": ["prompt"],
    "properties": {
        "prompt": {"type": "string", "minLength": 1},
        "count": {"type": "integer", "minimum": 1, "maximum": 9},
        "ratio": {"type": "string"},
        "size": {"type": "string"},
        "model": {"type": "string"},
        "editImagePath": {"type": "string"},
        "deviceIds": {
            "type": "array",
            "minItems": 1,
            "items": {"type": "string", "minLength": 1},
        },
        "groups": {
            "type": "array",
            "minItems": 1,
            "items": {"type": "string", "minLength": 1},
        },
        "allOnline": {"type": "boolean", "enum": [True]},
    },
}

MEDIA_VIDEO_INPUT_SCHEMA: Json = {
    "type": "object",
    "required": ["prompt"],
    "properties": {
        "prompt": {"type": "string", "minLength": 1},
        "model": {"type": "string"},
        "duration": {"type": "integer"},
        "ratio": {"type": "string"},
        "imagePath": {"type": "string"},
        "deviceIds": {
            "type": "array",
            "minItems": 1,
            "items": {"type": "string", "minLength": 1},
        },
        "groups": {
            "type": "array",
            "minItems": 1,
            "items": {"type": "string", "minLength": 1},
        },
        "allOnline": {"type": "boolean"},
    },
}

PHONE_PUBLISH_INPUT_SCHEMA: Json = {
    "type": "object",
    "required": ["platform", "title", "body", "mediaPaths", "deviceId"],
    "properties": {
        "platform": {
            "type": "string",
            "enum": ["douyin", "xiaohongshu", "wechat", "x", "custom"],
        },
        "title": {
            "type": "string",
            "minLength": 1,
            "description": "内容标题；用户提供标题时必须放在此字段，不得合并到 body 或 notes。",
        },
        "body": {
            "type": "string",
            "minLength": 1,
            "description": "面向平台用户的发布正文或视频文案；不得把标题或内部执行说明放入此字段。",
        },
        "hashtags": {"type": "string"},
        "notes": {
            "type": "string",
            "description": "仅供手机执行智能体参考的内部备注；不得代替 title 或发布正文。",
        },
        "mediaPaths": {
            "type": "array",
            "minItems": 1,
            "maxItems": 20,
            "items": {"type": "string", "minLength": 1},
        },
        "deviceId": {"type": "string", "minLength": 1},
        "draftOnly": {"type": "boolean"},
    },
}

MATRIX_TARGET_SCHEMA: Json = {
    "type": "object",
    "properties": {
        "deviceIds": {
            "type": "array",
            "minItems": 1,
            "items": {"type": "string", "minLength": 1},
        },
        "groups": {
            "type": "array",
            "minItems": 1,
            "items": {"type": "string", "minLength": 1},
        },
        "allOnline": {"type": "boolean", "enum": [True]},
    },
    "oneOf": [
        {"required": ["deviceIds"]},
        {"required": ["groups"]},
        {"required": ["allOnline"]},
    ],
    "additionalProperties": False,
}

MEDIA_ASSET_LIST_INPUT_SCHEMA: Json = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": ["image", "video"]},
        "cursor": {"type": "string"},
        "limit": {"type": "integer", "minimum": 1, "maximum": 50},
    },
    "additionalProperties": False,
}

MEDIA_ASSET_LIST_OUTPUT_SCHEMA: Json = {
    "type": "object",
    "required": ["items", "nextCursor", "hasMore"],
    "properties": {
        "items": {"type": "array", "items": {"type": "object"}},
        "nextCursor": {"type": "string"},
        "hasMore": {"type": "boolean"},
    },
}

MEDIA_ASSET_TRANSFER_INPUT_SCHEMA: Json = {
    "type": "object",
    "required": ["assetId", "targets"],
    "properties": {
        "assetId": {"type": "string", "minLength": 1},
        "targets": MATRIX_TARGET_SCHEMA,
    },
    "additionalProperties": False,
}

MATRIX_DISPATCH_INPUT_SCHEMA: Json = {
    "type": "object",
    "required": ["prompt"],
    "properties": {
        "prompt": {"type": "string", "minLength": 1},
        "deviceId": {"type": "string", "minLength": 1},
        "group": {"type": "string", "minLength": 1},
        "targets": MATRIX_TARGET_SCHEMA,
        "mode": {"type": "string", "enum": ["observe", "safe", "full", "deep"]},
    },
    "oneOf": [
        {"required": ["deviceId"]},
        {"required": ["group"]},
        {"required": ["targets"]},
    ],
    "additionalProperties": False,
}

MATRIX_SCREENSHOT_INPUT_SCHEMA: Json = {
    "type": "object",
    "required": ["deviceId"],
    "properties": {"deviceId": {"type": "string", "minLength": 1}},
    "additionalProperties": False,
}

MATRIX_CAMPAIGN_INPUT_SCHEMA: Json = {
    "type": "object",
    "required": ["campaignId"],
    "properties": {"campaignId": {"type": "string", "minLength": 1}},
    "additionalProperties": False,
}

MEDIA_JOB_OUTPUT_SCHEMA: Json = {
    "type": "object",
    "required": ["jobId", "kind", "status"],
    "properties": {
        "jobId": {"type": "string"},
        "kind": {"type": "string"},
        "status": {"type": "string"},
    },
}


class CapabilityError(RuntimeError):
    def __init__(self, code: str, message: str, *, recoverable: bool = True):
        super().__init__(message)
        self.code = code
        self.recoverable = recoverable


class CapabilityInputError(CapabilityError):
    def __init__(self, message: str):
        super().__init__("capability_invalid_input", message, recoverable=False)


class CapabilityExecutionError(CapabilityError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        recoverable: bool = True,
        outcome_indeterminate: bool = False,
        execution_may_continue: bool = False,
    ):
        super().__init__(code, message, recoverable=recoverable)
        self.outcome_indeterminate = outcome_indeterminate
        self.execution_may_continue = execution_may_continue


class CapabilityCancellationToken:
    """Read-only signal passed to executors declaring a ``cancellation_token`` keyword."""

    def __init__(self) -> None:
        self._event = threading.Event()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def wait(self, timeout: float | None = None) -> bool:
        return self._event.wait(timeout)

    def _cancel(self) -> None:
        self._event.set()


@dataclass
class _ExecutionState:
    done: threading.Event = field(default_factory=threading.Event)
    lock: threading.Lock = field(default_factory=threading.Lock)
    invocation_started: bool = False
    result: Any = None
    error: BaseException | None = None


@dataclass(frozen=True)
class Capability:
    name: str
    source: str
    permission: str
    risk: str
    timeout_sec: float
    input_schema: Json = field(default_factory=lambda: {"type": "object"})
    output_schema: Json = field(default_factory=lambda: {"type": "object"})
    display_name: str = ""
    description: str = ""
    domain: str = "general"
    target_scope: str = "none"
    executor: Executor | None = field(default=None, compare=False, repr=False)

    def to_dict(self) -> Json:
        return {
            "name": self.name,
            "displayName": self.display_name or _fallback_display_name(self.name),
            "description": self.description,
            "domain": self.domain,
            "targetScope": self.target_scope,
            "source": self.source,
            "permission": self.permission,
            "risk": self.risk,
            "timeoutSec": self.timeout_sec,
            "inputSchema": dict(self.input_schema),
            "outputSchema": dict(self.output_schema),
            "available": self.executor is not None,
        }


DEFAULT_CLI_ALLOWLIST = frozenset(
    {
        "status",
        "models",
        "logs tail",
        "jobs list",
        "jobs get",
        "phone status",
        "phone screenshot",
        "phone read",
        "phone quick-task",
        "matrix status",
        "matrix dispatch",
        "matrix watch",
        "matrix cancel",
        "matrix retry",
        "template run",
        "experience report",
        "media image",
        "media video",
    }
)

SEMANTIC_CAPABILITY_GROUPS = (
    ("loom.capabilities.list", "loom.mcp.loom.loom_cli_commands"),
    ("loom.logs.tail", "loom.cli.logs.tail", "loom.mcp.loom.loom_logs_tail"),
    ("loom.matrix.status", "loom.cli.matrix.status", "loom.mcp.loom.loom_matrix_status"),
    ("loom.matrix.dispatch", "loom.cli.matrix.dispatch", "loom.mcp.loom.loom_matrix_dispatch"),
    ("loom.matrix.cancel", "loom.cli.matrix.cancel", "loom.mcp.loom.loom_matrix_cancel"),
    ("loom.matrix.retry", "loom.cli.matrix.retry", "loom.mcp.loom.loom_matrix_retry"),
    ("loom.matrix.screenshot", "loom.cli.phone.screenshot", "loom.mcp.loom.loom_phone_screenshot"),
    ("loom.media.image.generate", "loom.cli.media.image", "loom.mcp.loom.loom_media_generate_image"),
    ("loom.media.video.generate", "loom.cli.media.video", "loom.mcp.loom.loom_media_generate_video"),
    ("loom.cli.status", "loom.mcp.loom.loom_status"),
    ("loom.cli.models", "loom.mcp.loom.loom_models"),
    ("loom.cli.jobs.list", "loom.mcp.loom.loom_job_list"),
    ("loom.cli.jobs.get", "loom.mcp.loom.loom_job_get"),
    ("loom.cli.phone.status", "loom.mcp.loom.loom_phone_status"),
    ("loom.cli.phone.read", "loom.mcp.loom.loom_phone_read"),
    ("loom.cli.phone.quick-task", "loom.mcp.loom.loom_phone_quick_task"),
    ("loom.cli.matrix.watch", "loom.mcp.loom.loom_matrix_watch"),
    ("loom.cli.template.run", "loom.mcp.loom.loom_template_run"),
    ("loom.cli.experience.report", "loom.mcp.loom.loom_experience_report"),
)

CAPABILITY_OPERATION_KEYS = {
    capability_name: group[0]
    for group in SEMANTIC_CAPABILITY_GROUPS
    for capability_name in group
}

CAPABILITY_SOURCE_PRIORITY = {
    "internal": 0,
    "cli": 1,
    "mcp": 2,
    "skill": 3,
}

CLI_DISPLAY_NAMES = {
    "status": "查看麓鸣状态",
    "models": "查看模型配置",
    "logs tail": "查看运行日志",
    "jobs list": "查看任务列表",
    "jobs get": "查看任务详情",
    "phone status": "查看手机状态",
    "phone screenshot": "获取手机截图",
    "phone read": "读取手机屏幕",
    "phone quick-task": "执行手机任务",
    "matrix status": "查看矩阵状态",
    "matrix dispatch": "下发矩阵任务",
    "matrix watch": "查看矩阵进度",
    "matrix cancel": "取消矩阵任务",
    "matrix retry": "重试矩阵任务",
    "template run": "执行任务模板",
    "experience report": "查看运行经验",
    "media image": "生成图片",
    "media video": "生成视频",
}

LOOM_MCP_DISPLAY_NAMES = {
    "loom_status": "查看麓鸣状态",
    "loom_doctor": "检查麓鸣运行环境",
    "loom_cli_commands": "查看能力目录",
    "loom_models": "查看模型配置",
    "loom_agent_list": "查看智能体安装状态",
    "loom_agent_start": "启动智能体",
    "loom_agent_install": "安装智能体",
    "loom_agent_detect": "检测智能体安装",
    "loom_agent_uninstall": "卸载智能体",
    "loom_agent_rollback": "回滚智能体安装",
    "loom_agent_model_status": "查看智能体模型状态",
    "loom_agent_model_apply": "应用智能体模型配置",
    "loom_agent_model_rollback": "回滚智能体模型配置",
    "loom_account_current": "查看当前账户",
    "loom_account_send_code": "发送登录验证码",
    "loom_account_login_code": "使用验证码登录",
    "loom_account_login_password": "使用密码登录",
    "loom_account_sync": "同步账户与模型",
    "loom_account_subscription": "查看账户订阅",
    "loom_account_select_models": "选择默认模型",
    "loom_account_logout": "退出当前账户",
    "loom_wire_current": "查看模型接线配置",
    "loom_wire_sync": "同步模型接线配置",
    "loom_wire_custom": "配置自定义模型接口",
    "loom_wire_verify": "验证模型接口",
    "loom_wire_rollback": "回滚模型接线配置",
    "loom_media_config": "查看媒体生成配置",
    "loom_media_save_image_config": "保存图片生成配置",
    "loom_media_save_video_config": "保存视频生成配置",
    "loom_media_test_image": "测试图片生成配置",
    "loom_media_test_video": "测试视频生成配置",
    "loom_media_generate_image": "生成图片",
    "loom_media_generate_video": "生成视频",
    "loom_phone_status": "查看手机状态",
    "loom_phone_screenshot": "获取手机截图",
    "loom_phone_read": "读取手机屏幕",
    "loom_phone_quick_task": "执行手机任务",
    "loom_phone_template_task": "执行手机模板任务",
    "loom_phone_adb_doctor": "修复手机连接",
    "loom_phone_events_start": "启动手机事件同步",
    "loom_phone_events_status": "查看手机事件同步",
    "loom_phone_events_stop": "停止手机事件同步",
    "loom_acquisition_agent_run": "启动获客智能体任务",
    "loom_acquisition_agent_result": "记录获客智能体结果",
    "loom_feishu_doctor": "检查飞书集成环境",
    "loom_feishu_status": "查看飞书集成状态",
    "loom_feishu_install": "安装飞书集成",
    "loom_feishu_login": "登录飞书集成",
    "loom_feishu_bind_table": "绑定飞书线索表",
    "loom_feishu_create_table": "创建飞书线索表",
    "loom_feishu_test_write": "测试写入飞书",
    "loom_feishu_retry_sync": "重试飞书同步",
    "loom_feishu_reconcile": "核对飞书同步状态",
    "loom_schedule_list": "查看定时任务",
    "loom_schedule_add": "添加定时任务",
    "loom_schedule_run": "立即执行定时任务",
    "loom_schedule_cancel": "取消定时任务",
    "loom_logs_tail": "查看运行日志",
    "loom_matrix_status": "查看矩阵状态",
    "loom_matrix_dispatch": "下发矩阵任务",
    "loom_matrix_watch": "查看矩阵进度",
    "loom_matrix_cancel": "取消矩阵任务",
    "loom_matrix_retry": "重试矩阵任务",
    "loom_lead_list": "查看合规线索",
    "loom_lead_record": "记录合规线索",
    "loom_template_run": "执行任务模板",
    "loom_experience_report": "查看运行经验",
    "loom_job_list": "查看任务列表",
    "loom_job_get": "查看任务详情",
    "loom_settings_theme": "设置界面主题",
    "loom_settings_theme_list": "查看界面主题",
    "loom_settings_update_check": "检查麓鸣更新",
    "loom_settings_update_install": "安装麓鸣更新",
    "loom_diagnostics_run": "运行系统诊断",
    "loom_diagnostics_repair": "执行诊断修复",
    "loom_diagnostics_export": "导出诊断包",
    "loom_license_current": "查看授权状态",
    "loom_license_activate": "激活授权码",
    "loom_license_authorized": "检查授权有效性",
}

UNSAFE_CLI_GLOBAL_OPTIONS = frozenset(
    {
        "--bridge-token",
        "--bridge-url",
        "--dry-run",
        "--json",
        "--permission",
    }
)

PRE_EXECUTION_ERROR_CODES = frozenset(
    {
        "approval_already_resolved",
        "approval_conflict",
        "approval_expired",
        "approval_rejected",
        "approval_scope_mismatch",
        "bridge_not_configured",
        "capability_invalid_input",
        "capability_not_found",
        "capability_unavailable",
        "critical_target_required",
        "invalid_action_body_json",
        "invalid_actual_model",
        "invalid_codex_toml",
        "invalid_control",
        "invalid_dispatch",
        "invalid_input",
        "invalid_json",
        "invalid_lease",
        "invalid_media_file",
        "invalid_media_kind",
        "invalid_model",
        "invalid_option",
        "invalid_permission",
        "invalid_phone_mode",
        "invalid_phone_profile",
        "invalid_phone_token",
        "invalid_phone_url",
        "invalid_provider_url",
        "invalid_runtime",
        "invalid_schedule_command",
        "invalid_target",
        "invalid_task_transition",
        "invalid_user_model",
        "matrix_campaign_scope_required",
        "matrix_campaign_scope_violation",
        "matrix_target_scope_required",
        "media_asset_not_found",
        "missing_action",
        "missing_action_body_json",
        "missing_adb",
        "missing_agent_result_json",
        "missing_api_token",
        "missing_campaign",
        "missing_check_id",
        "missing_component",
        "missing_config_path",
        "missing_config_write_fields",
        "missing_email",
        "missing_email_code",
        "missing_feishu_table",
        "missing_helper_script",
        "missing_ids",
        "missing_job_id",
        "missing_lead_summary",
        "missing_license_code",
        "missing_local_phone_model_config",
        "missing_login_identity",
        "missing_merchant_id",
        "missing_model",
        "missing_option_value",
        "missing_packages",
        "missing_password",
        "missing_phone_llm_config",
        "missing_phone_token",
        "missing_phone_url",
        "missing_prompt",
        "missing_register_fields",
        "missing_schedule_command",
        "missing_schedule_time",
        "missing_target",
        "missing_task_id",
        "missing_template_id",
        "missing_ticket",
        "missing_wire_custom_fields",
        "permission_denied",
        "phone_single_target_required",
        "phone_target_not_found",
        "phone_target_scope_required",
        "phone_target_unavailable",
        "publish_media_missing",
        "safety_confirmation_required",
        "unknown_command",
        "unknown_tool",
        "unsupported_command",
    }
)


DEFAULT_INTERNAL_SPECS: dict[str, Json] = {
    "loom.capabilities.list": {
        "displayName": "查看能力目录",
        "description": "查看麓鸣智能体当前真实连接且可执行的完整能力目录。",
        "domain": "agent",
        "targetScope": "none",
        "permission": "read",
        "risk": "read",
        "timeoutSec": 15,
        "inputSchema": {"type": "object", "additionalProperties": False},
    },
    "loom.matrix.status": {
        "displayName": "查看矩阵状态",
        "description": "查看手机矩阵任务与设备执行状态。",
        "domain": "matrix",
        "targetScope": "none",
        "permission": "read",
        "risk": "read",
        "timeoutSec": 15,
    },
    "loom.matrix.dispatch": {
        "displayName": "下发矩阵任务",
        "description": "向选定手机或设备组下发矩阵任务。",
        "domain": "matrix",
        "targetScope": "matrix-write",
        "permission": "control",
        "risk": "control_safe",
        "timeoutSec": 120,
        "inputSchema": MATRIX_DISPATCH_INPUT_SCHEMA,
    },
    "loom.matrix.screenshot": {
        "displayName": "获取矩阵截图",
        "description": "获取指定手机的当前屏幕截图。",
        "domain": "matrix",
        "targetScope": "single-device-read",
        "permission": "read",
        "risk": "read",
        "timeoutSec": 60,
        "inputSchema": MATRIX_SCREENSHOT_INPUT_SCHEMA,
    },
    "loom.matrix.cancel": {
        "displayName": "取消矩阵任务",
        "description": "取消正在执行的矩阵任务。",
        "domain": "matrix",
        "targetScope": "campaign-write",
        "permission": "control",
        "risk": "control_safe",
        "timeoutSec": 30,
        "inputSchema": MATRIX_CAMPAIGN_INPUT_SCHEMA,
    },
    "loom.matrix.retry": {
        "displayName": "重试矩阵任务",
        "description": "重试失败或需要人工处理的矩阵任务。",
        "domain": "matrix",
        "targetScope": "campaign-write",
        "permission": "control",
        "risk": "control_safe",
        "timeoutSec": 120,
        "inputSchema": MATRIX_CAMPAIGN_INPUT_SCHEMA,
    },
    "loom.media.image.generate": {
        "displayName": "生成图片",
        "description": "根据提示词生成图片并保存到媒体库。",
        "domain": "media",
        "targetScope": "optional-device-write",
        "permission": "control",
        "risk": "control_safe",
        "timeoutSec": 300,
        "inputSchema": MEDIA_IMAGE_INPUT_SCHEMA,
        "outputSchema": MEDIA_JOB_OUTPUT_SCHEMA,
    },
    "loom.media.video.generate": {
        "displayName": "生成视频",
        "description": "根据提示词或参考素材生成视频并保存到媒体库。",
        "domain": "media",
        "targetScope": "optional-device-write",
        "permission": "control",
        "risk": "control_safe",
        "timeoutSec": 900,
        "inputSchema": MEDIA_VIDEO_INPUT_SCHEMA,
        "outputSchema": MEDIA_JOB_OUTPUT_SCHEMA,
    },
    "loom.logs.tail": {
        "displayName": "查看运行日志",
        "description": "查看麓鸣最近的运行日志用于诊断。",
        "domain": "diagnostics",
        "targetScope": "none",
        "permission": "read",
        "risk": "read",
        "timeoutSec": 15,
    },
}


class CapabilityRegistry:
    def __init__(
        self,
        *,
        internal_operations: Mapping[str, Any] | None = None,
        skill_provider: Callable[[], Any] | None = None,
        skill_executor: Callable[[str, Json], Any] | None = None,
        mcp_provider: Callable[[], Any] | None = None,
        mcp_executor: Callable[[str, str, Json], Any] | None = None,
        cli_catalog_provider: Callable[[], Any] | None = None,
        cli_executor: Callable[[str, Json], Any] | None = None,
        cli_allowlist: Sequence[str] = tuple(DEFAULT_CLI_ALLOWLIST),
        discovery_cache_ttl_sec: float = 5.0,
    ):
        self.internal_operations = dict(internal_operations or {})
        self.skill_provider = skill_provider or _default_skill_provider
        self.skill_executor = skill_executor
        self.mcp_provider = mcp_provider or _default_mcp_provider
        self._uses_default_mcp_executor = mcp_executor is None
        self.mcp_executor = _default_mcp_executor if self._uses_default_mcp_executor else mcp_executor
        self.cli_catalog_provider = cli_catalog_provider or _default_cli_catalog_provider
        self.cli_executor = cli_executor or _default_cli_executor
        self.cli_allowlist = {str(item).strip() for item in cli_allowlist if str(item).strip()}
        self.discovery_cache_ttl_sec = max(0.0, float(discovery_cache_ttl_sec or 0.0))
        self._discovery_lock = threading.RLock()
        self._discovery_cache: dict[str, Capability] | None = None
        self._discovery_cache_expires_at = 0.0

    def list_capabilities(self, *, available_only: bool = False) -> list[Json]:
        capabilities = list(self._capabilities(available_only=available_only).values())
        return [capability.to_dict() for capability in capabilities]

    def get(self, name: str) -> Capability:
        capabilities = self._all_capabilities()
        operation_key = CAPABILITY_OPERATION_KEYS.get(name, name)
        candidates = [
            capability
            for capability in capabilities.values()
            if CAPABILITY_OPERATION_KEYS.get(capability.name, capability.name) == operation_key
        ]
        if not candidates or (name not in capabilities and name not in CAPABILITY_OPERATION_KEYS):
            raise CapabilityExecutionError("capability_not_found", f"Unknown capability: {name}", recoverable=False)
        return _preferred_capability(candidates, prefer_available=True)

    def execute(self, name: str, payload: Mapping[str, Any] | None = None) -> Any:
        capability, data = self.validate_input(name, payload)
        if capability.executor is None:
            raise CapabilityExecutionError("capability_unavailable", f"Capability is not connected: {name}")
        if capability.permission != "read":
            self.invalidate_cache()
        token = CapabilityCancellationToken()
        state = _ExecutionState()
        supports_cancellation = _accepts_cancellation_token(capability.executor)

        def run() -> None:
            with state.lock:
                if token.cancelled:
                    state.done.set()
                    return
                state.invocation_started = True
            try:
                state.result = _invoke_executor(capability.executor, data, token, supports_cancellation)
            except BaseException as exc:
                state.error = exc
            finally:
                state.done.set()

        worker = threading.Thread(target=run, name="loom-capability", daemon=True)
        worker.start()
        if not state.done.wait(capability.timeout_sec):
            with state.lock:
                token._cancel()
                invocation_started = state.invocation_started
            if not invocation_started:
                raise CapabilityExecutionError("capability_timeout", f"Capability timed out before starting: {name}")

            settled = state.done.wait(DEFAULT_CANCELLATION_GRACE_SEC)
            if settled and supports_cancellation:
                detail = "acknowledged cancellation after the deadline"
            elif settled:
                detail = "settled after the deadline during the bounded cancellation grace period"
            elif supports_cancellation:
                detail = "was asked to cancel but is still running and may still complete"
            else:
                detail = "does not support cooperative cancellation, is still running, and may still complete"
            raise CapabilityExecutionError(
                "capability_timeout_indeterminate",
                f"Capability {detail}; side-effect outcome is indeterminate: {name}",
                recoverable=False,
                outcome_indeterminate=True,
                execution_may_continue=not settled,
            )

        if state.error is not None:
            if isinstance(state.error, CapabilityError):
                raise state.error
            if not isinstance(state.error, Exception):
                raise state.error
            detail = str(redact_sensitive(str(state.error)))[:500]
            if capability.permission == "read" and capability.risk == "read":
                raise CapabilityExecutionError(
                    "capability_failed",
                    f"Capability failed: {name}: {detail}",
                ) from state.error
            raise CapabilityExecutionError(
                "capability_execution_unknown",
                f"Capability execution outcome is unknown: {name}: {detail}",
                recoverable=False,
                outcome_indeterminate=True,
                execution_may_continue=False,
            ) from state.error
        result = state.result
        safe_result = redact_sensitive(result)
        try:
            _validate_schema(safe_result, capability.output_schema, path="output")
        except CapabilityInputError as exc:
            raise CapabilityExecutionError(
                "capability_invalid_output",
                str(exc),
                recoverable=False,
                outcome_indeterminate=True,
            ) from exc
        return safe_result

    def validate_input(
        self,
        name: str,
        payload: Mapping[str, Any] | None = None,
    ) -> tuple[Capability, Json]:
        capability = self.get(name)
        data = dict(payload or {})
        _validate_schema(data, capability.input_schema, path="input")
        return capability, data

    def _all_capabilities(self) -> dict[str, Capability]:
        now = time.monotonic()
        with self._discovery_lock:
            if (
                self._discovery_cache is not None
                and now < self._discovery_cache_expires_at
            ):
                return dict(self._discovery_cache)
            capabilities = self._internal_capabilities()
            for capability in self._skill_capabilities():
                capabilities[capability.name] = capability
            for capability in self._mcp_capabilities():
                capabilities[capability.name] = capability
            for capability in self._cli_capabilities():
                capabilities[capability.name] = capability
            discovered = dict(sorted(capabilities.items()))
            if self.discovery_cache_ttl_sec > 0:
                self._discovery_cache = discovered
                self._discovery_cache_expires_at = now + self.discovery_cache_ttl_sec
            return dict(discovered)

    def invalidate_cache(self) -> None:
        with self._discovery_lock:
            self._discovery_cache = None
            self._discovery_cache_expires_at = 0.0

    def _capabilities(self, *, available_only: bool = False) -> dict[str, Capability]:
        capabilities = list(self._all_capabilities().values())
        if available_only:
            capabilities = [capability for capability in capabilities if capability.executor is not None]
        grouped: dict[str, list[Capability]] = {}
        for capability in capabilities:
            operation_key = CAPABILITY_OPERATION_KEYS.get(capability.name, capability.name)
            grouped.setdefault(operation_key, []).append(capability)
        selected = {}
        for operation_key, candidates in grouped.items():
            capability = _preferred_capability(candidates, prefer_available=available_only)
            has_canonical_candidate = any(candidate.name == operation_key for candidate in candidates)
            canonical = (
                replace(capability, name=operation_key)
                if has_canonical_candidate and capability.name != operation_key
                else capability
            )
            selected[canonical.name] = canonical
        return dict(sorted(selected.items()))

    def _internal_capabilities(self) -> dict[str, Capability]:
        merged: dict[str, Any] = {name: dict(spec) for name, spec in DEFAULT_INTERNAL_SPECS.items()}
        for name, raw in self.internal_operations.items():
            spec = merged.setdefault(name, {})
            if callable(raw):
                spec["executor"] = raw
            elif isinstance(raw, Mapping):
                spec.update(raw)
        capabilities: dict[str, Capability] = {}
        for name, spec in merged.items():
            capabilities[name] = _capability_from_spec(name, "internal", spec)
        return capabilities

    def _skill_capabilities(self) -> list[Capability]:
        raw = _safe_provider_call(self.skill_provider)
        items = raw.get("skills", []) if isinstance(raw, Mapping) else raw
        capabilities: list[Capability] = []
        for item in items if isinstance(items, Sequence) and not isinstance(items, (str, bytes)) else []:
            if not isinstance(item, Mapping) or not item.get("installed", True) or not item.get("enabled", True):
                continue
            skill_id = _safe_name(item.get("id") or item.get("name"))
            if not skill_id:
                continue
            executor = item.get("executor") if callable(item.get("executor")) else None
            if executor is None and self.skill_executor is not None:
                skill_executor = self.skill_executor

                def executor(payload, *, cancellation_token, skill_id=skill_id, skill_executor=skill_executor):
                    return _invoke_with_optional_cancellation(
                        skill_executor,
                        skill_id,
                        payload,
                        cancellation_token=cancellation_token,
                    )
            permission, risk = _external_policy_metadata(item)
            capabilities.append(
                _capability_from_spec(
                    f"loom.skill.{skill_id}",
                    "skill",
                    {
                        **item,
                        "executor": executor,
                        "permission": permission,
                        "risk": risk,
                        "timeoutSec": item.get("timeoutSec", 300),
                    },
                )
            )
        return capabilities

    def _mcp_capabilities(self) -> list[Capability]:
        raw = _safe_provider_call(self.mcp_provider)
        items = raw.get("tools", []) if isinstance(raw, Mapping) else raw
        capabilities: list[Capability] = []
        for item in items if isinstance(items, Sequence) and not isinstance(items, (str, bytes)) else []:
            if not isinstance(item, Mapping):
                continue
            server = _safe_name(item.get("server") or "default")
            tool = _safe_name(item.get("name"))
            if not server or not tool:
                continue
            permission, risk = _external_policy_metadata(item)
            executor = item.get("executor") if callable(item.get("executor")) else None
            if (
                executor is None
                and self.mcp_executor is not None
                and (not self._uses_default_mcp_executor or server == "loom")
            ):
                mcp_executor = self.mcp_executor

                def executor(
                    payload,
                    *,
                    cancellation_token,
                    server=server,
                    tool=tool,
                    mcp_executor=mcp_executor,
                    permission=permission,
                    risk=risk,
                ):
                    result = _invoke_with_optional_cancellation(
                        mcp_executor,
                        server,
                        tool,
                        payload,
                        cancellation_token=cancellation_token,
                        permission=permission,
                    )
                    if isinstance(result, Mapping) and result.get("isError") is True:
                        raise _mcp_execution_error(
                            server,
                            tool,
                            result,
                            permission=permission,
                            risk=risk,
                        )
                    payload = _mcp_success_payload(result)
                    if (
                        server == "loom"
                        and isinstance(result, Mapping)
                        and "isError" in result
                        and payload is result
                    ):
                        raise _mcp_malformed_success_error(
                            server,
                            tool,
                            permission=permission,
                            risk=risk,
                        )
                    return payload
            localized = _external_capability_metadata("mcp", tool, server=server)
            capabilities.append(
                _capability_from_spec(
                    f"loom.mcp.{server}.{tool}",
                    "mcp",
                    {
                        **item,
                        **localized,
                        "executor": executor,
                        "permission": permission,
                        "risk": risk,
                        "timeoutSec": item.get("timeoutSec", 60),
                    },
                )
            )
        return capabilities

    def _cli_capabilities(self) -> list[Capability]:
        raw = _safe_provider_call(self.cli_catalog_provider)
        if isinstance(raw, Mapping) and isinstance(raw.get("data"), Mapping):
            raw = raw["data"]
        domains = raw.get("domains", []) if isinstance(raw, Mapping) else []
        capabilities: list[Capability] = []
        for domain in domains if isinstance(domains, Sequence) else []:
            commands = domain.get("commands", []) if isinstance(domain, Mapping) else []
            catalog_domain = str(domain.get("domain") or "general") if isinstance(domain, Mapping) else "general"
            for item in commands if isinstance(commands, Sequence) else []:
                if not isinstance(item, Mapping):
                    continue
                command = str(item.get("name") or "").strip()
                if command not in self.cli_allowlist:
                    continue
                permission, risk = _external_policy_metadata(item, derive_risk_from_permission=True)
                executor = None
                if self.cli_executor is not None:
                    cli_executor = self.cli_executor

                    def executor(
                        payload,
                        *,
                        cancellation_token,
                        command=command,
                        cli_executor=cli_executor,
                        permission=permission,
                    ):
                        return _invoke_with_optional_cancellation(
                            cli_executor,
                            command,
                            payload,
                            cancellation_token=cancellation_token,
                            permission=permission,
                        )
                localized = _external_capability_metadata("cli", command)
                capabilities.append(
                    _capability_from_spec(
                        f"loom.cli.{_safe_name(command.replace(' ', '.'))}",
                        "cli",
                        {
                            **item,
                            "domain": catalog_domain,
                            **localized,
                            "executor": executor,
                            "permission": permission,
                            "risk": risk,
                            "timeoutSec": item.get("timeoutSec", 120),
                        },
                    )
                )
        return capabilities


def _preferred_capability(
    candidates: Sequence[Capability],
    *,
    prefer_available: bool,
) -> Capability:
    eligible = list(candidates)
    if prefer_available:
        available = [capability for capability in eligible if capability.executor is not None]
        if available:
            eligible = available
    return min(
        eligible,
        key=lambda capability: (
            0 if _preserves_structured_contract(capability, eligible) else 1,
            CAPABILITY_SOURCE_PRIORITY.get(capability.source, 99),
            capability.name,
        ),
    )


def _preserves_structured_contract(capability: Capability, candidates: Sequence[Capability]) -> bool:
    if any(candidate.source == "internal" for candidate in candidates):
        return capability.source == "internal"
    score = _structured_contract_score(capability.input_schema)
    return score == max(_structured_contract_score(candidate.input_schema) for candidate in candidates)


def _structured_contract_score(schema: Mapping[str, Any]) -> tuple[int, int, int]:
    properties = schema.get("properties")
    property_count = len(properties) if isinstance(properties, Mapping) else 0
    required = schema.get("required")
    required_count = len(required) if isinstance(required, Sequence) and not isinstance(required, (str, bytes)) else 0
    return (1 if property_count else 0, required_count, property_count)


def _accepts_cancellation_token(executor: Executor) -> bool:
    return _accepts_keyword(executor, "cancellation_token")


def _accepts_keyword(executor: Callable[..., Any], name: str) -> bool:
    try:
        parameters = inspect.signature(executor).parameters
    except (TypeError, ValueError):
        return False
    parameter = parameters.get(name)
    if parameter is not None and parameter.kind in {
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
        inspect.Parameter.KEYWORD_ONLY,
    }:
        return True
    return any(parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in parameters.values())


def _invoke_executor(
    executor: Executor,
    payload: Json,
    cancellation_token: CapabilityCancellationToken,
    supports_cancellation: bool,
) -> Any:
    if supports_cancellation:
        return executor(payload, cancellation_token=cancellation_token)
    return executor(payload)


def _invoke_with_optional_cancellation(
    executor: Callable[..., Any],
    *args: Any,
    cancellation_token: CapabilityCancellationToken,
    permission: str | None = None,
) -> Any:
    kwargs: dict[str, Any] = {}
    if _accepts_cancellation_token(executor):
        kwargs["cancellation_token"] = cancellation_token
    if permission is not None and _accepts_keyword(executor, "permission"):
        kwargs["permission"] = permission
    return executor(*args, **kwargs)


def _capability_from_spec(name: str, source: str, spec: Mapping[str, Any]) -> Capability:
    return Capability(
        name=name,
        source=source,
        permission=_normalize_permission(spec.get("permission")),
        risk=str(spec.get("risk") or "control_safe"),
        timeout_sec=max(0.001, float(spec.get("timeoutSec") or 60)),
        input_schema=_schema(spec.get("inputSchema")),
        output_schema=_schema(spec.get("outputSchema")),
        display_name=str(spec.get("displayName") or spec.get("display_name") or ""),
        description=str(spec.get("description") or spec.get("summary") or ""),
        domain=str(spec.get("domain") or "general"),
        target_scope=_normalize_target_scope(spec.get("targetScope") or spec.get("target_scope")),
        executor=spec.get("executor") if callable(spec.get("executor")) else None,
    )


def _schema(value: Any) -> Json:
    return dict(value) if isinstance(value, Mapping) else {"type": "object"}


def _fallback_display_name(name: str) -> str:
    label = str(name or "").rsplit(".", 1)[-1].replace("-", " ").replace("_", " ").strip()
    return label or str(name or "")


def _external_capability_metadata(source: str, identifier: str, *, server: str = "") -> Json:
    if source == "cli":
        display_name = CLI_DISPLAY_NAMES.get(identifier)
        domain = identifier.split(" ", 1)[0]
        domain = {"status": "system", "models": "models", "logs": "diagnostics"}.get(domain, domain)
    elif source == "mcp" and server == "loom":
        display_name = LOOM_MCP_DISPLAY_NAMES.get(identifier)
        domain = _loom_mcp_domain(identifier)
    else:
        return {}
    if not display_name:
        return {}
    return {
        "displayName": display_name,
        "description": f"在麓鸣工作台中{display_name}。",
        "domain": domain,
    }


def _loom_mcp_domain(identifier: str) -> str:
    prefixes = (
        ("loom_agent_", "agent"),
        ("loom_account_", "account"),
        ("loom_wire_", "models"),
        ("loom_media_", "media"),
        ("loom_phone_", "phone"),
        ("loom_acquisition_", "acquisition"),
        ("loom_feishu_", "integration"),
        ("loom_schedule_", "schedule"),
        ("loom_logs_", "diagnostics"),
        ("loom_matrix_", "matrix"),
        ("loom_lead_", "acquisition"),
        ("loom_template_", "matrix"),
        ("loom_experience_", "matrix"),
        ("loom_job_", "jobs"),
        ("loom_settings_", "settings"),
        ("loom_diagnostics_", "diagnostics"),
        ("loom_license_", "license"),
    )
    for prefix, domain in prefixes:
        if identifier.startswith(prefix):
            return domain
    if identifier == "loom_doctor":
        return "diagnostics"
    return "models" if identifier == "loom_models" else "system"


def _normalize_target_scope(value: Any) -> str:
    target_scope = str(value or "none").strip().lower()
    return target_scope if target_scope in VALID_TARGET_SCOPES else "none"


def _normalize_permission(value: Any) -> str:
    text = str(value or "read").lower()
    if "/" in text:
        text = text.rsplit("/", 1)[-1]
    return text if text in {"read", "control", "automation", "admin"} else "read"


def _external_policy_metadata(spec: Mapping[str, Any], *, derive_risk_from_permission: bool = False) -> tuple[str, str]:
    permission = str(spec.get("permission") or "").strip().lower()
    if "/" in permission:
        permission = permission.rsplit("/", 1)[-1]
    if permission not in {"read", "control", "automation", "admin"}:
        return "admin", "critical"

    risk = str(spec.get("risk") or "").strip().lower()
    if risk in {"read", "control_safe", "outbound", "critical"}:
        return permission, risk
    if not derive_risk_from_permission:
        return permission, "critical"
    if permission == "read":
        return permission, "read"
    if permission == "admin":
        return permission, "critical"
    return permission, "control_safe"


def _safe_name(value: Any) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value or "").strip()).strip(".-")[:160]


def _safe_provider_call(provider: Callable[[], Any]) -> Any:
    try:
        return provider()
    except Exception:
        return []


def _validate_schema(value: Any, schema: Mapping[str, Any], *, path: str) -> None:
    expected = schema.get("type")
    type_map = {
        "object": Mapping,
        "array": list,
        "string": str,
        "number": (int, float),
        "integer": int,
        "boolean": bool,
    }
    if expected in type_map and (not isinstance(value, type_map[expected]) or expected in {"number", "integer"} and isinstance(value, bool)):
        raise CapabilityInputError(f"{path} must be {expected}")
    allowed = schema.get("enum")
    if isinstance(allowed, Sequence) and not isinstance(allowed, (str, bytes)) and value not in allowed:
        raise CapabilityInputError(f"{path} must be one of: {', '.join(map(str, allowed))}")
    if expected == "string" and isinstance(value, str):
        minimum_length = schema.get("minLength")
        maximum_length = schema.get("maxLength")
        if isinstance(minimum_length, int) and len(value) < minimum_length:
            raise CapabilityInputError(f"{path} must contain at least {minimum_length} characters")
        if isinstance(maximum_length, int) and len(value) > maximum_length:
            raise CapabilityInputError(f"{path} must contain at most {maximum_length} characters")
    if expected == "array" and isinstance(value, list):
        minimum_items = schema.get("minItems")
        maximum_items = schema.get("maxItems")
        if isinstance(minimum_items, int) and len(value) < minimum_items:
            raise CapabilityInputError(f"{path} must contain at least {minimum_items} items")
        if isinstance(maximum_items, int) and len(value) > maximum_items:
            raise CapabilityInputError(f"{path} must contain at most {maximum_items} items")
        item_schema = schema.get("items")
        if isinstance(item_schema, Mapping):
            for index, item in enumerate(value):
                _validate_schema(item, item_schema, path=f"{path}[{index}]")
    if expected in {"number", "integer"} and isinstance(value, (int, float)) and not isinstance(value, bool):
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if isinstance(minimum, (int, float)) and value < minimum:
            raise CapabilityInputError(f"{path} must be at least {minimum}")
        if isinstance(maximum, (int, float)) and value > maximum:
            raise CapabilityInputError(f"{path} must be at most {maximum}")
    required = schema.get("required")
    properties = schema.get("properties")
    has_required_fields = isinstance(required, Sequence) and not isinstance(required, (str, bytes))
    has_object_constraints = (
        expected == "object"
        or isinstance(properties, Mapping)
        or has_required_fields
        or schema.get("additionalProperties") is False
    )
    if has_object_constraints:
        if not isinstance(value, Mapping):
            raise CapabilityInputError(f"{path} must be object")
        for key in required if has_required_fields else []:
            if key not in value:
                raise CapabilityInputError(f"{path}.{key} is required")
        if isinstance(properties, Mapping):
            for key, child_schema in properties.items():
                if key in value and isinstance(child_schema, Mapping):
                    _validate_schema(value[key], child_schema, path=f"{path}.{key}")
            if schema.get("additionalProperties") is False:
                unexpected = [str(key) for key in value if key not in properties]
                if unexpected:
                    raise CapabilityInputError(f"{path}.{sorted(unexpected)[0]} is not allowed")
    any_of = schema.get("anyOf")
    if isinstance(any_of, Sequence) and not isinstance(any_of, (str, bytes)) and any_of:
        for option in any_of:
            if not isinstance(option, Mapping):
                continue
            try:
                _validate_schema(value, option, path=path)
            except CapabilityInputError:
                continue
            break
        else:
            required_options = [
                "/".join(str(key) for key in option.get("required", []))
                for option in any_of
                if isinstance(option, Mapping)
                and isinstance(option.get("required"), Sequence)
                and not isinstance(option.get("required"), (str, bytes))
            ]
            detail = f": {' or '.join(required_options)}" if required_options else ""
            raise CapabilityInputError(f"{path} must satisfy one allowed parameter combination{detail}")
    one_of = schema.get("oneOf")
    if isinstance(one_of, Sequence) and not isinstance(one_of, (str, bytes)) and one_of:
        matches = 0
        for option in one_of:
            if not isinstance(option, Mapping):
                continue
            try:
                _validate_schema(value, option, path=path)
            except CapabilityInputError:
                continue
            matches += 1
        if matches != 1:
            required_options = [
                "/".join(str(key) for key in option.get("required", []))
                for option in one_of
                if isinstance(option, Mapping)
                and isinstance(option.get("required"), Sequence)
                and not isinstance(option.get("required"), (str, bytes))
            ]
            detail = f": {' or '.join(required_options)}" if required_options else ""
            raise CapabilityInputError(
                f"{path} must satisfy exactly one allowed parameter combination{detail}"
            )


def _default_skill_provider() -> Any:
    from core.paths import AppPaths
    from services.skills import SkillService

    return SkillService(AppPaths.discover()).list_skills()


def _default_mcp_provider() -> Any:
    try:
        import loom_mcp

        return [{"server": "loom", **tool} for tool in loom_mcp.tool_definitions()]
    except Exception:
        return []


def _default_mcp_executor(server: str, tool: str, payload: Json, *, permission: str | None = None) -> Any:
    if server != "loom":
        raise CapabilityExecutionError("capability_unavailable", f"MCP server is not connected: {server}")
    import loom_mcp

    return loom_mcp.call_tool(tool, payload, permission=permission, trusted_internal=True)


def _mcp_execution_error(
    server: str,
    tool: str,
    result: Mapping[str, Any],
    *,
    permission: str = "read",
    risk: str = "read",
) -> CapabilityExecutionError:
    code = "mcp_tool_failed"
    message = f"MCP tool failed: {server}/{tool}"
    error_payload: Mapping[str, Any] = {}
    content = result.get("content")
    if isinstance(content, Sequence) and not isinstance(content, (str, bytes)):
        for item in content:
            if not isinstance(item, Mapping) or item.get("type") != "text":
                continue
            text = item.get("text")
            if not isinstance(text, str) or not text.strip():
                continue
            try:
                payload = json.loads(text)
            except (TypeError, ValueError):
                message = text.strip()
                break
            error = payload.get("error") if isinstance(payload, Mapping) else None
            if isinstance(error, Mapping):
                error_payload = error
                code = str(error.get("code") or code)
                message = str(error.get("message") or message)
            break
    outcome_indeterminate = error_payload.get("outcomeIndeterminate") is True
    execution_may_continue = error_payload.get("executionMayContinue") is True
    recoverable_value = error_payload.get("recoverable")
    if not isinstance(recoverable_value, bool):
        recoverable_value = error_payload.get("retryable")
    recoverable = recoverable_value if isinstance(recoverable_value, bool) else True
    if outcome_indeterminate or execution_may_continue:
        return CapabilityExecutionError(
            code,
            message,
            recoverable=False,
            outcome_indeterminate=outcome_indeterminate or execution_may_continue,
            execution_may_continue=execution_may_continue,
        )
    side_effecting = permission != "read" or risk != "read"
    if side_effecting and not _error_is_definitely_pre_execution(code):
        return CapabilityExecutionError(
            "capability_execution_unknown",
            f"MCP control outcome is unknown after {code}: {message}",
            recoverable=False,
            outcome_indeterminate=True,
            execution_may_continue=False,
        )
    return CapabilityExecutionError(code, message, recoverable=recoverable)


def _mcp_success_payload(result: Any) -> Any:
    if not isinstance(result, Mapping) or result.get("isError") is True:
        return result

    structured = result.get("structuredContent")
    if isinstance(structured, Mapping):
        return dict(structured)

    content = result.get("content")
    if not isinstance(content, Sequence) or isinstance(content, (str, bytes)):
        return result
    for item in content:
        if not isinstance(item, Mapping) or item.get("type") != "text":
            continue
        text = item.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        try:
            payload = json.loads(text)
        except (TypeError, ValueError):
            continue
        if isinstance(payload, Mapping):
            return dict(payload)
    return result


def _mcp_malformed_success_error(
    server: str,
    tool: str,
    *,
    permission: str = "read",
    risk: str = "read",
) -> CapabilityExecutionError:
    message = f"MCP tool returned a success response without a structured result: {server}/{tool}"
    if permission != "read" or risk != "read":
        return CapabilityExecutionError(
            "capability_execution_unknown",
            f"MCP control outcome is unknown because its success receipt was malformed: {server}/{tool}",
            recoverable=False,
            outcome_indeterminate=True,
            execution_may_continue=False,
        )
    return CapabilityExecutionError(
        "capability_invalid_output",
        message,
        recoverable=True,
    )


def _error_is_definitely_pre_execution(code: str) -> bool:
    normalized = str(code or "").strip().lower()
    return normalized in PRE_EXECUTION_ERROR_CODES


def _default_cli_catalog_provider() -> Any:
    try:
        import loom_cli

        return loom_cli._command_catalog()  # The CLI catalog is the local machine-readable contract.
    except Exception:
        return {"domains": []}


def _default_cli_executor(command: str, payload: Json, *, permission: str | None = None) -> Any:
    import loom_cli

    extra = payload.get("args", [])
    if not isinstance(extra, Sequence) or isinstance(extra, (str, bytes)) or not all(isinstance(item, str) for item in extra):
        raise CapabilityInputError("input.args must be an argument array")
    for item in extra:
        option = item.strip()
        if any(option == global_option or option.startswith(f"{global_option}=") for global_option in UNSAFE_CLI_GLOBAL_OPTIONS):
            raise CapabilityInputError(f"input.args contains forbidden global option: {option.split('=', 1)[0]}")
    extra = list(extra)
    if command == "phone quick-task":
        for key, option in (("prompt", "--prompt"), ("deviceId", "--device-id"), ("mode", "--mode")):
            value = payload.get(key)
            if value is not None:
                if not isinstance(value, str) or not value.strip():
                    raise CapabilityInputError(f"input.{key} must be a non-empty string")
                extra.extend([option, value])
    permission_args = ["--permission", permission] if permission else []
    code, result = loom_cli.dispatch([*command.split(), *extra, "--json", *permission_args], source="agent")
    if code != 0:
        error = result.get("error", {}) if isinstance(result, Mapping) else {}
        error_code = str(error.get("code") or "cli_failed")
        message = str(error.get("message") or "CLI command failed")
        if permission != "read" and not _error_is_definitely_pre_execution(error_code):
            raise CapabilityExecutionError(
                "capability_execution_unknown",
                f"CLI control outcome is unknown after {error_code}: {message}",
                recoverable=False,
                outcome_indeterminate=True,
                execution_may_continue=False,
            )
        raise CapabilityExecutionError(error_code, message)
    return result.get("data", result) if isinstance(result, Mapping) else result
