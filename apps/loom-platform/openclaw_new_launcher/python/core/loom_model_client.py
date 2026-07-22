"""Managed gateway client for the native LOOM central agent."""

from __future__ import annotations

import hashlib
import json
import math
import random
import re
import socket
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from core.agent_system_prompt import build_agent_system_prompt


CONNECT_TIMEOUT_SEC = 10.0
FIRST_RESPONSE_TIMEOUT_SEC = 45.0
DEFAULT_TOTAL_ROUND_TIMEOUT_SEC = 120.0
MAX_RETRIES_BEFORE_CHUNK = 2
RETRY_BASE_DELAY_SEC = 0.25
RETRY_MAX_DELAY_SEC = 2.0
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
RETRYABLE_ERROR_CODES = frozenset({"AGENT_MODEL_NETWORK_ERROR", "AGENT_MODEL_TIMEOUT"})
RETRYABLE_HTTP_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504, 520, 521, 522, 523, 524})
SAFE_TOKEN_USAGE_FIELDS = frozenset({
    "acceptedpredictiontokens",
    "audiotokens",
    "cachedtokens",
    "completiontokens",
    "completiontokensdetails",
    "inputtokens",
    "maxtokens",
    "outputtokens",
    "prompttokens",
    "prompttokensdetails",
    "reasoningtokens",
    "rejectedpredictiontokens",
    "tokenbudget",
    "totaltokens",
})
TOOL_CALL_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
CAPABILITY_NAME_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9._:-]{0,127}\Z")
MODEL_TOOL_NAME_PATTERN = re.compile(r"[^A-Za-z0-9_-]+")
MODEL_TOOL_NAME_MAX_LENGTH = 64
SENSITIVE_HEADER_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_-])(?P<prefix>(?:authorization|proxy[-_ ]?authorization|cookie|set[-_ ]?cookie)[ \t]*:[ \t]*)[^\r\n]*",
    re.IGNORECASE | re.MULTILINE,
)
TEXT_ASSIGNMENT_PREFIX_PATTERN = re.compile(
    r"""
    (?P<prefix>
        (?<![A-Za-z0-9_])
        (?P<key_quote>["']?)
        (?P<key>[A-Za-z_][A-Za-z0-9_.-]*)
        (?P=key_quote)
        [ \t]*(?P<separator>[:=])[ \t]*
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

SYSTEM_CONTRACT = build_agent_system_prompt([])


@dataclass(frozen=True)
class LoomModelProfile:
    base_url: str
    access_token: str
    model: str


class ModelAccountManager(Protocol):
    def current(self) -> dict[str, Any] | None: ...
    def ensure_launcher_token(
        self,
        *,
        sync_runtime: bool = True,
        force_refresh: bool = False,
    ) -> dict[str, Any]: ...


class ModelGatewayTransport(Protocol):
    def stream(
        self,
        profile: LoomModelProfile,
        payload: Mapping[str, Any],
        cancel: threading.Event,
        *,
        timeout_sec: float,
    ) -> Iterator[dict[str, Any]]: ...


class ModelGatewayError(RuntimeError):
    def __init__(self, code: str, message: str, *, recoverable: bool = True, status_code: int | None = None):
        super().__init__(redact_text(message))
        self.code = code
        self.recoverable = recoverable
        self.status_code = status_code


def _model_account_error(error: Exception) -> ModelGatewayError:
    message = redact_text(error).strip().lower()
    status_code = getattr(error, "status_code", None)
    if message in {"not_logged_in", "managed_session_missing_api_token"}:
        return ModelGatewayError(
            "AGENT_ACCOUNT_LOGIN_REQUIRED",
            "Managed model login is required.",
            status_code=status_code,
        )
    if status_code in {401, 403} or any(marker in message for marker in (
        "requires re-login",
        "requires relogin",
        "permission_contract_invalid",
    )):
        return ModelGatewayError(
            "AGENT_ACCOUNT_RELOGIN_REQUIRED",
            "Managed model account must be signed in again.",
            status_code=status_code,
        )
    return ModelGatewayError(
        "AGENT_MODEL_CREDENTIAL_REFRESH_FAILED",
        "Managed model credentials could not be refreshed.",
        status_code=status_code,
    )


def redact_text(value: Any) -> str:
    text = str(value or "")
    text = SENSITIVE_HEADER_PATTERN.sub(r"\g<prefix>[REDACTED]", text)
    text = _redact_text_assignments(text)
    text = re.sub(r"(?i)Bearer\s+[A-Za-z0-9._~+/-]+", "Bearer [REDACTED]", text)
    text = re.sub(r"\bsk-[A-Za-z0-9._-]{4,}\b", "sk-[REDACTED]", text)
    return text


def _redact_text_assignments(text: str) -> str:
    replacements: list[tuple[int, int, str]] = []
    cursor = 0
    while match := TEXT_ASSIGNMENT_PREFIX_PATTERN.search(text, cursor):
        cursor = match.end()
        normalized = re.sub(r"[^a-z0-9]", "", match.group("key").lower())
        if not _is_sensitive_key(normalized):
            continue

        value_end, quote = _text_assignment_value_end(text, match.end())
        prefix = match.group("prefix")
        if match.group("separator") == ":" and quote:
            replacement = f"{prefix}{quote}[REDACTED]{quote}"
        else:
            replacement = f"{prefix}[REDACTED]"
        replacements.append((match.start(), value_end, replacement))
        cursor = value_end

    for start, end, replacement in reversed(replacements):
        text = f"{text[:start]}{replacement}{text[end:]}"
    return text


def _text_assignment_value_end(text: str, start: int) -> tuple[int, str | None]:
    if start < len(text) and text[start] in {'"', "'"}:
        quote = text[start]
        cursor = start + 1
        while cursor < len(text):
            if text[cursor] == "\\":
                cursor += 2
                continue
            if text[cursor] == quote:
                return cursor + 1, quote
            if text[cursor] in "\r\n":
                break
            cursor += 1
        return cursor, quote

    delimiter = re.search(r"[,;\r\n}]", text[start:])
    return (start + delimiter.start() if delimiter else len(text)), None


def redact_sensitive(value: Any) -> Any:
    if isinstance(value, Mapping):
        safe: dict[str, Any] = {}
        for key, item in value.items():
            name = str(key)
            normalized = re.sub(r"[^a-z0-9]", "", name.lower())
            if _is_sensitive_key(normalized):
                safe[name] = "[REDACTED]"
            else:
                safe[name] = redact_sensitive(item)
        return safe
    if isinstance(value, (list, tuple)):
        return [redact_sensitive(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def _is_sensitive_key(normalized: str) -> bool:
    if not normalized or normalized in SAFE_TOKEN_USAGE_FIELDS:
        return False
    if any(marker in normalized for marker in (
        "accesskey",
        "apikey",
        "authorization",
        "bearer",
        "cookie",
        "credential",
        "password",
        "privatekey",
        "secret",
        "signature",
        "token",
    )):
        return True
    if normalized == "auth" or any(marker in normalized for marker in (
        "authcredential",
        "authheader",
        "authkey",
        "authtoken",
        "authvalue",
    )):
        return True
    return False


def _sanitized_gateway_error(error: ModelGatewayError) -> ModelGatewayError:
    return ModelGatewayError(
        error.code,
        str(error),
        recoverable=error.recoverable,
        status_code=error.status_code,
    )


def _is_retryable_gateway_error(error: ModelGatewayError) -> bool:
    return error.recoverable and (
        error.code in RETRYABLE_ERROR_CODES or error.status_code in RETRYABLE_HTTP_STATUS_CODES
    )


def _is_safe_model_identifier(value: str, pattern: re.Pattern[str]) -> bool:
    return pattern.fullmatch(value) is not None and redact_text(value) == value


def _bounded_total_timeout(timeout_sec: Any) -> float:
    candidate = DEFAULT_TOTAL_ROUND_TIMEOUT_SEC if timeout_sec is None else timeout_sec
    if isinstance(candidate, bool):
        raise ModelGatewayError(
            "AGENT_MODEL_TIMEOUT",
            "Managed model timeout must be a finite positive number.",
            recoverable=False,
        )
    try:
        requested = float(candidate)
    except (TypeError, ValueError, OverflowError):
        raise ModelGatewayError(
            "AGENT_MODEL_TIMEOUT",
            "Managed model timeout must be a finite positive number.",
            recoverable=False,
        ) from None
    if not math.isfinite(requested) or requested <= 0:
        raise ModelGatewayError(
            "AGENT_MODEL_TIMEOUT",
            "Managed model timeout must be a finite positive number.",
            recoverable=False,
        )
    return min(requested, DEFAULT_TOTAL_ROUND_TIMEOUT_SEC)


def profile_from_session(
    session: Mapping[str, Any] | None,
    *,
    model_id: str = "",
) -> LoomModelProfile:
    if not isinstance(session, Mapping):
        raise ModelGatewayError("AGENT_ACCOUNT_LOGIN_REQUIRED", "Managed model login is required.")
    gateway = session.get("gateway") if isinstance(session.get("gateway"), Mapping) else {}
    profile = LoomModelProfile(
        base_url=str(session.get("gatewayBaseUrl") or gateway.get("baseUrl") or "").strip().rstrip("/"),
        access_token=str(session.get("memberToken") or gateway.get("accessToken") or "").strip(),
        model=str(model_id or session.get("gatewayDefaultModel") or gateway.get("defaultModel") or "").strip(),
    )
    if not profile.base_url or not profile.access_token or not profile.model:
        raise ModelGatewayError("AGENT_MODEL_CONFIG_INVALID", "Managed model gateway configuration is incomplete.")
    return profile


class UrlLibSseTransport:
    """OpenAI-compatible SSE transport with bounded reads and sanitized errors."""

    def __init__(self, opener: Callable[..., Any] | None = None) -> None:
        self._opener = opener or urllib.request.urlopen

    def stream(
        self,
        profile: LoomModelProfile,
        payload: Mapping[str, Any],
        cancel: threading.Event,
        *,
        timeout_sec: float,
    ) -> Iterator[dict[str, Any]]:
        if cancel.is_set():
            raise ModelGatewayError("AGENT_MODEL_CANCELLED", "Managed model request was cancelled.")
        if timeout_sec <= 0:
            raise ModelGatewayError("AGENT_MODEL_TIMEOUT", "Managed model request timed out.")

        request = urllib.request.Request(
            f"{profile.base_url}/chat/completions",
            data=json.dumps(dict(payload), ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {profile.access_token}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
            },
            method="POST",
        )
        started = time.monotonic()
        try:
            response = self._opener(request, timeout=min(CONNECT_TIMEOUT_SEC, timeout_sec))
        except urllib.error.HTTPError as exc:
            raise ModelGatewayError(
                "AGENT_MODEL_HTTP_ERROR",
                f"Managed gateway returned HTTP {exc.code}.",
                recoverable=exc.code in {401, 403} or exc.code in RETRYABLE_HTTP_STATUS_CODES,
                status_code=exc.code,
            ) from None
        except (urllib.error.URLError, socket.timeout, TimeoutError):
            raise ModelGatewayError("AGENT_MODEL_NETWORK_ERROR", "Managed gateway connection failed.") from None
        except OSError:
            raise ModelGatewayError("AGENT_MODEL_NETWORK_ERROR", "Managed gateway connection failed.") from None

        try:
            with response:
                self._set_first_response_timeout(response, timeout_sec)
                received = 0
                while True:
                    if cancel.is_set():
                        raise ModelGatewayError("AGENT_MODEL_CANCELLED", "Managed model request was cancelled.")
                    remaining = timeout_sec - (time.monotonic() - started)
                    if remaining <= 0:
                        raise ModelGatewayError("AGENT_MODEL_TIMEOUT", "Managed model request timed out.")
                    self._set_first_response_timeout(response, remaining)
                    try:
                        raw_line = response.readline(MAX_RESPONSE_BYTES - received + 1)
                    except (socket.timeout, TimeoutError):
                        raise ModelGatewayError("AGENT_MODEL_TIMEOUT", "Managed gateway response timed out.") from None
                    if cancel.is_set():
                        raise ModelGatewayError("AGENT_MODEL_CANCELLED", "Managed model request was cancelled.")
                    if not raw_line:
                        return
                    received += len(raw_line)
                    if received > MAX_RESPONSE_BYTES:
                        raise ModelGatewayError(
                            "AGENT_MODEL_OUTPUT_TOO_LARGE",
                            "Managed gateway response exceeded the size limit.",
                            recoverable=False,
                        )
                    try:
                        line = raw_line.decode("utf-8").strip()
                    except UnicodeDecodeError:
                        raise ModelGatewayError("AGENT_MODEL_PROTOCOL_INVALID", "Managed gateway returned non-UTF-8 SSE data.", recoverable=False) from None
                    if not line or line.startswith(":"):
                        continue
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        return
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        raise ModelGatewayError("AGENT_MODEL_PROTOCOL_INVALID", "Managed gateway returned malformed SSE JSON.", recoverable=False) from None
                    if not isinstance(chunk, dict):
                        raise ModelGatewayError("AGENT_MODEL_PROTOCOL_INVALID", "Managed gateway SSE event was not an object.", recoverable=False)
                    yield chunk
        except ModelGatewayError:
            raise
        except (urllib.error.URLError, OSError):
            raise ModelGatewayError("AGENT_MODEL_NETWORK_ERROR", "Managed gateway stream failed.") from None

    @staticmethod
    def _set_first_response_timeout(response: Any, total_timeout_sec: float) -> None:
        timeout = min(FIRST_RESPONSE_TIMEOUT_SEC, total_timeout_sec)
        raw = getattr(getattr(response, "fp", None), "raw", None)
        sock = getattr(raw, "_sock", None)
        if sock is not None and hasattr(sock, "settimeout"):
            sock.settimeout(timeout)


def _model_tool_alias_maps(capabilities: Any) -> tuple[dict[str, str], dict[str, str]]:
    canonical_to_alias: dict[str, str] = {}
    alias_to_canonical: dict[str, str] = {}
    if not isinstance(capabilities, list):
        return canonical_to_alias, alias_to_canonical
    for capability in capabilities:
        if not isinstance(capability, Mapping):
            continue
        canonical = str(capability.get("name") or "").strip()
        if not canonical:
            continue
        base_alias = MODEL_TOOL_NAME_PATTERN.sub("_", canonical)[:MODEL_TOOL_NAME_MAX_LENGTH]
        alias = base_alias
        collision_index = 0
        while alias in alias_to_canonical and alias_to_canonical[alias] != canonical:
            digest = hashlib.sha256(f"{canonical}:{collision_index}".encode("utf-8")).hexdigest()[:12]
            suffix = f"_{digest}"
            alias = f"{base_alias[:MODEL_TOOL_NAME_MAX_LENGTH - len(suffix)]}{suffix}"
            collision_index += 1
        canonical_to_alias[canonical] = alias
        alias_to_canonical[alias] = canonical
    return canonical_to_alias, alias_to_canonical


def extract_explicit_capability_hints(prompt: Any, capability_names: Any) -> list[str]:
    text = str(prompt or "")
    if not text.strip() or not isinstance(capability_names, (list, tuple, set)):
        return []
    matches: list[str] = []
    for raw_name in capability_names:
        name = str(raw_name or "").strip()
        if not name:
            continue
        pattern = re.compile(
            rf"(?i)(?:please\s+)?(?:use|call|invoke|run|调用|使用|执行)\s*"
            rf"(?:the\s+)?(?:tool|capability|工具|能力)?\s*[`\"']?"
            rf"(?<![A-Za-z0-9_.-]){re.escape(name)}(?![A-Za-z0-9_.-])"
        )
        for match in pattern.finditer(text):
            if _explicit_invocation_is_negated(text, match.start()):
                continue
            matches.append(name)
            break
    return list(dict.fromkeys(matches))


def _explicit_invocation_is_negated(text: str, invocation_start: int) -> bool:
    prefix = text[max(0, invocation_start - 96):invocation_start].casefold()
    chinese_negation = re.compile(
        r"(?:"
        r"(?:请\s*)?(?:不要|不准|不可|不能)\s*(?:再|再次|继续|去)?|"
        r"请勿|切勿|不得|严禁|禁止\s*(?:再|再次)?|"
        r"别\s*(?:再|继续)?|无需|不必"
        r")\s*$"
    )
    english_negation = re.compile(
        r"(?:"
        r"(?:please\s+)?(?:do|must|should|shall|need)\s+not(?:\s+ever)?|"
        r"(?:don't|never)(?:\s+ever)?"
        r")\s*$"
    )
    return bool(chinese_negation.search(prefix) or english_negation.search(prefix))


def _ordered_model_capabilities(capabilities: Any, hints: Any) -> list[Any]:
    if not isinstance(capabilities, list):
        return []
    requested = [str(item or "").strip() for item in hints] if isinstance(hints, list) else []
    ranks = {name: index for index, name in enumerate(dict.fromkeys(requested)) if name}
    indexed = list(enumerate(capabilities))
    indexed.sort(
        key=lambda item: (
            ranks.get(
                str(item[1].get("name") or "").strip() if isinstance(item[1], Mapping) else "",
                len(ranks),
            ),
            item[0],
        )
    )
    return [item for _index, item in indexed]


def _conversation_history_content(item: Mapping[str, Any]) -> str:
    content = item.get("content")
    if isinstance(content, str) and content.strip():
        return content.strip()
    blocks = item.get("blocks")
    if not isinstance(blocks, list):
        return ""
    text_blocks: list[str] = []
    for block in blocks:
        if not isinstance(block, Mapping) or block.get("type") != "text":
            continue
        data = block.get("data")
        block_text = data.get("text") if isinstance(data, Mapping) else None
        if isinstance(block_text, str) and block_text.strip():
            text_blocks.append(block_text.strip())
    return "\n\n".join(text_blocks)


def build_chat_payload(profile: LoomModelProfile, request: Mapping[str, Any]) -> dict[str, Any]:
    capabilities = request.get("capabilities")
    canonical_to_alias, _alias_to_canonical = _model_tool_alias_maps(capabilities)
    system_override = request.get("systemOverride")
    system_content = (
        system_override if isinstance(system_override, str) and system_override.strip()
        else build_agent_system_prompt(capabilities)
    )
    messages: list[dict[str, Any]] = [{"role": "system", "content": system_content}]
    # Session artifacts are a native-agent runtime concern; skip them when a
    # caller supplies its own system prompt (e.g. the nine-step storyboard flow).
    if not (isinstance(system_override, str) and system_override.strip()):
        raw_artifacts = request.get("sessionArtifacts")
        session_artifacts: list[dict[str, str]] = []
        if isinstance(raw_artifacts, list):
            for item in raw_artifacts[-20:]:
                if not isinstance(item, Mapping):
                    continue
                path = str(item.get("path") or "").strip()
                if not path:
                    continue
                session_artifacts.append({
                    "name": str(item.get("name") or "media")[:160],
                    "path": path[:2000],
                    "mime": str(item.get("mime") or "")[:120],
                    "kind": str(item.get("kind") or "")[:40],
                })
        if session_artifacts:
            artifact_context = json.dumps(session_artifacts, ensure_ascii=False, separators=(",", ":"))
            messages[0]["content"] += (
                "\n\nReusable LOOM session artifacts (trusted local tool results):\n"
                f"{artifact_context[:12000]}\n"
                "Do not regenerate media when an existing artifact satisfies the user's request. "
                "Reuse its exact path for downstream upload or publishing tools unless the user asks for a new version."
            )
    history = request.get("history")
    if isinstance(history, list):
        for item in history[-20:]:
            if not isinstance(item, Mapping):
                continue
            role = str(item.get("role") or "").strip()
            content = _conversation_history_content(item)
            if role not in {"user", "assistant"} or not content:
                continue
            messages.append({"role": role, "content": redact_text(content)[:12000]})

    prompt = request.get("prompt")
    if isinstance(prompt, str) and prompt.strip():
        messages.append({"role": "user", "content": redact_text(prompt)[:12000]})

    tool_results = request.get("toolResults")
    if isinstance(tool_results, list) and tool_results:
        fallback_results: list[Any] = []
        for item in tool_results[-20:]:
            if not isinstance(item, Mapping):
                fallback_results.append(item)
                continue
            tool_call_id = str(item.get("toolCallId") or "").strip()
            capability = str(item.get("capability") or "").strip()
            item_error = item.get("error")
            if (
                isinstance(item_error, Mapping)
                and str(item_error.get("code") or "") == "capability_not_found"
            ):
                available_names = list(canonical_to_alias)[:120]
                repair_context = json.dumps(
                    {"availableCapabilities": available_names},
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                messages.append({
                    "role": "user",
                    "content": (
                        "麓鸣执行层确认上一轮选择的能力不存在，工具尚未执行。"
                        "请只从本轮结构化工具中重新选择最匹配的能力；不要重复旧名称，"
                        "也不要把尚未执行写成已完成。\n"
                        f"{repair_context[:10000]}"
                    ),
                })
                continue
            if (
                isinstance(item_error, Mapping)
                and str(item_error.get("code") or "") == "capability_invalid_input"
            ):
                repair_context = {
                    "capability": capability,
                    "rejectedInput": redact_sensitive(
                        item.get("input") if isinstance(item.get("input"), Mapping) else {}
                    ),
                    "validationError": redact_sensitive(dict(item_error)),
                }
                repair_summary = json.dumps(
                    repair_context,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    default=str,
                )
                messages.append({
                    "role": "user",
                    "content": (
                        "麓鸣执行层拒绝了上一轮工具参数，工具尚未执行。"
                        "请根据原始用户请求和结构化 Schema 补齐字段，并立即重新调用同一工具；"
                        "不要改写为文字答复，也不要省略用户明确给出的值。\n"
                        f"{repair_summary[:10000]}"
                    ),
                })
                continue
            alias = canonical_to_alias.get(capability)
            if not alias or not TOOL_CALL_ID_PATTERN.fullmatch(tool_call_id):
                fallback_results.append(item)
                continue
            safe_input = redact_sensitive(item.get("input") if isinstance(item.get("input"), Mapping) else {})
            safe_result = {
                "status": str(item.get("status") or "completed"),
                "result": redact_sensitive(item.get("result")),
            }
            if item.get("error") is not None:
                safe_result["error"] = redact_sensitive(item.get("error"))
            messages.append({
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": tool_call_id,
                    "type": "function",
                    "function": {
                        "name": alias,
                        "arguments": json.dumps(safe_input, ensure_ascii=False, separators=(",", ":"), default=str)[:12000],
                    },
                }],
            })
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": json.dumps(safe_result, ensure_ascii=False, separators=(",", ":"), default=str)[:12000],
            })
        if fallback_results:
            summary = json.dumps(
                redact_sensitive(fallback_results),
                ensure_ascii=False,
                separators=(",", ":"),
                default=str,
            )
            messages.append({"role": "user", "content": f"Tool results from LOOM:\n{summary[:12000]}"})

    capability_names = [
        str(item.get("name") or "").strip()
        for item in capabilities
        if isinstance(item, Mapping) and str(item.get("name") or "").strip()
    ] if isinstance(capabilities, list) else []
    supplied_hints = request.get("capabilityHints")
    hints = [str(item or "").strip() for item in supplied_hints] if isinstance(supplied_hints, list) else []
    explicit_hints = extract_explicit_capability_hints(prompt, capability_names)
    hints = list(dict.fromkeys([*explicit_hints, *hints]))

    tools: list[dict[str, Any]] = []
    seen_capabilities: set[str] = set()
    if isinstance(capabilities, list):
        for capability in _ordered_model_capabilities(capabilities, hints):
            if not isinstance(capability, Mapping):
                continue
            name = str(capability.get("name") or "").strip()
            if not name or name in seen_capabilities or name not in canonical_to_alias:
                continue
            seen_capabilities.add(name)
            schema = capability.get("inputSchema")
            parameters = _sanitize_schema(schema) if isinstance(schema, Mapping) else {"type": "object"}
            tools.append({
                "type": "function",
                "function": {
                    "name": canonical_to_alias[name],
                    "description": redact_text(capability.get("description") or "")[:2000],
                    "parameters": parameters,
                },
            })

    run_id = redact_text(request.get("runId") or "")
    round_value = request.get("round")
    tool_choice: Any = "auto"
    tool_results = request.get("toolResults")
    routing = request.get("capabilityRouting")
    routing = routing if isinstance(routing, Mapping) else {}
    routing_forced_capability = str(routing.get("forcedCapability") or "").strip()
    routing_tool_choice = str(routing.get("toolChoice") or "").strip().lower()
    repair_capability = ""
    if isinstance(tool_results, list) and tool_results:
        latest_result = tool_results[-1]
        if isinstance(latest_result, Mapping):
            latest_error = latest_result.get("error")
            if (
                isinstance(latest_error, Mapping)
                and str(latest_error.get("code") or "") == "capability_invalid_input"
            ):
                repair_capability = str(latest_result.get("capability") or "").strip()
    forced_capability = repair_capability or routing_forced_capability or (
        explicit_hints[0]
        if len(explicit_hints) == 1 and not (isinstance(tool_results, list) and tool_results)
        else ""
    )
    if forced_capability:
        forced_alias = canonical_to_alias.get(forced_capability)
        if forced_alias:
            tool_choice = {"type": "function", "function": {"name": forced_alias}}
    elif routing_tool_choice == "none":
        tool_choice = "none"

    return {
        "model": profile.model,
        "messages": messages,
        "tools": tools,
        "tool_choice": tool_choice,
        "stream": True,
        "stream_options": {"include_usage": True},
        "temperature": 0.2,
        "metadata": {"idempotencyKey": f"{run_id}:{round_value}"},
    }


def _sanitize_schema(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _sanitize_schema(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_schema(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


@dataclass
class _ToolCallParts:
    tool_call_id: str = ""
    name: str = ""
    arguments: str = ""


@dataclass
class ChatAggregate:
    text_parts: list[str] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)
    tool_calls: dict[int, _ToolCallParts] = field(default_factory=dict)
    tool_name_map: dict[str, str] = field(default_factory=dict)

    def consume(self, chunk: Mapping[str, Any]) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        usage = chunk.get("usage")
        if isinstance(usage, Mapping):
            safe_usage = redact_sensitive(dict(usage))
            self.usage.update(safe_usage)
            events.append({"type": "model.usage", "data": safe_usage})
        choices = chunk.get("choices")
        if not isinstance(choices, list):
            return events
        for choice in choices:
            if not isinstance(choice, Mapping):
                continue
            delta = choice.get("delta")
            if not isinstance(delta, Mapping):
                continue
            content = delta.get("content")
            if isinstance(content, str) and content:
                safe_content = redact_text(content)
                self.text_parts.append(safe_content)
                events.append({"type": "model.text.delta", "data": {"text": safe_content}})
            raw_calls = delta.get("tool_calls")
            if not isinstance(raw_calls, list):
                continue
            for ordinal, raw_call in enumerate(raw_calls):
                if not isinstance(raw_call, Mapping):
                    raise ModelGatewayError("AGENT_MODEL_PROTOCOL_INVALID", "Managed gateway returned an invalid tool call.", recoverable=False)
                index = raw_call.get("index", ordinal)
                if not isinstance(index, int):
                    raise ModelGatewayError("AGENT_MODEL_PROTOCOL_INVALID", "Managed gateway tool call index was invalid.", recoverable=False)
                parts = self.tool_calls.setdefault(index, _ToolCallParts())
                tool_call_id_delta = ""
                name_delta = ""
                arguments_delta = ""
                if raw_call.get("id") is not None:
                    tool_call_id_delta = str(raw_call["id"])
                    parts.tool_call_id += tool_call_id_delta
                function = raw_call.get("function")
                if function is not None and not isinstance(function, Mapping):
                    raise ModelGatewayError("AGENT_MODEL_PROTOCOL_INVALID", "Managed gateway tool function was invalid.", recoverable=False)
                if isinstance(function, Mapping):
                    if function.get("name") is not None:
                        name_delta = str(function["name"])
                        parts.name += name_delta
                    if function.get("arguments") is not None:
                        arguments_delta = str(function["arguments"])
                        parts.arguments += arguments_delta
                if tool_call_id_delta or name_delta or arguments_delta:
                    events.append({
                        "type": "model.tool_call.delta",
                        "data": {
                            "index": index,
                            "toolCallIdDelta": tool_call_id_delta,
                            "nameDelta": name_delta,
                            "argumentsDelta": arguments_delta,
                        },
                    })
        return events

    def result(self, model: str) -> dict[str, Any]:
        normalized_calls: list[dict[str, Any]] = []
        for index in sorted(self.tool_calls):
            parts = self.tool_calls[index]
            tool_call_id = parts.tool_call_id
            raw_name = parts.name
            if (
                not _is_safe_model_identifier(tool_call_id, TOOL_CALL_ID_PATTERN)
                or not _is_safe_model_identifier(raw_name, CAPABILITY_NAME_PATTERN)
            ):
                raise ModelGatewayError("AGENT_MODEL_PROTOCOL_INVALID", "Managed gateway tool call fields were incomplete.", recoverable=False)
            name = self.tool_name_map.get(raw_name, raw_name)
            try:
                arguments = json.loads(parts.arguments or "{}")
            except json.JSONDecodeError:
                raise ModelGatewayError("AGENT_MODEL_PROTOCOL_INVALID", "Managed gateway tool arguments were malformed JSON.", recoverable=False) from None
            if not isinstance(arguments, Mapping):
                raise ModelGatewayError("AGENT_MODEL_PROTOCOL_INVALID", "Managed gateway tool arguments must be an object.", recoverable=False)
            normalized_calls.append({"toolCallId": tool_call_id, "name": name, "input": redact_sensitive(dict(arguments))})
        text = "".join(self.text_parts)
        if not text and not normalized_calls:
            raise ModelGatewayError("AGENT_MODEL_PROTOCOL_INVALID", "Managed gateway returned an empty response.", recoverable=False)
        return {"text": text, "toolCalls": normalized_calls, "usage": dict(self.usage), "model": model}


class LoomModelClient:
    def __init__(self, account: ModelAccountManager, *, transport: ModelGatewayTransport | None = None) -> None:
        self.account = account
        self.transport = transport or UrlLibSseTransport()

    def status(self) -> dict[str, Any]:
        try:
            profile = self._ensure_profile()
        except ModelGatewayError as exc:
            return {"available": False, "profileId": "loom-native", "error": {"code": exc.code, "message": str(exc)}}
        return {"available": True, "profileId": "loom-native", "model": profile.model}

    def complete(
        self,
        request: Mapping[str, Any],
        emit: Callable[[dict[str, Any]], None],
        cancel: threading.Event,
        *,
        timeout_sec: float | None = None,
    ) -> dict[str, Any]:
        try:
            if cancel.is_set():
                raise ModelGatewayError("AGENT_MODEL_CANCELLED", "Managed model request was cancelled.")
            model_id = str(request.get("modelId") or "").strip()
            profile = self._ensure_profile(model_id=model_id)
            total_timeout = _bounded_total_timeout(timeout_sec)
            payload = build_chat_payload(profile, request)
            _canonical_to_alias, alias_to_canonical = _model_tool_alias_maps(request.get("capabilities"))
            aggregate = ChatAggregate(tool_name_map=alias_to_canonical)
            active_profile = profile
            for active_profile, chunk in self._stream_with_retry(
                profile,
                payload,
                cancel,
                total_timeout,
                model_id=model_id,
            ):
                for event in aggregate.consume(chunk):
                    emit(redact_sensitive(event))
            result = aggregate.result(active_profile.model)
            emit(redact_sensitive({
                "type": "model.completed",
                "data": {
                    "model": result["model"],
                    "usage": result["usage"],
                    "toolCallCount": len(result["toolCalls"]),
                    "textLength": len(result["text"]),
                },
            }))
            return result
        except ModelGatewayError as exc:
            safe_error = _sanitized_gateway_error(exc)
            emit(redact_sensitive({
                "type": "model.failed",
                "data": {
                    "error": {
                        "code": safe_error.code,
                        "message": str(safe_error),
                        "recoverable": safe_error.recoverable,
                    },
                },
            }))
            raise safe_error from None

    def _ensure_profile(self, *, force_refresh: bool = False, model_id: str = "") -> LoomModelProfile:
        try:
            return profile_from_session(
                self.account.ensure_launcher_token(
                    sync_runtime=False,
                    force_refresh=force_refresh,
                ),
                model_id=model_id,
            )
        except ModelGatewayError as exc:
            raise _sanitized_gateway_error(exc) from None
        except Exception as exc:
            raise _model_account_error(exc) from None

    def _stream_with_retry(
        self,
        profile: LoomModelProfile,
        payload: Mapping[str, Any],
        cancel: threading.Event,
        total_timeout_sec: float,
        *,
        model_id: str = "",
    ) -> Iterator[tuple[LoomModelProfile, dict[str, Any]]]:
        deadline = time.monotonic() + total_timeout_sec
        active_profile = profile
        active_payload = dict(payload)
        network_retries = 0
        refreshed = False
        received_chunk = False
        first_attempt = True

        while True:
            if cancel.is_set():
                raise ModelGatewayError("AGENT_MODEL_CANCELLED", "Managed model request was cancelled.")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ModelGatewayError("AGENT_MODEL_TIMEOUT", "Managed model request timed out.")
            try:
                attempt_timeout = total_timeout_sec if first_attempt else remaining
                first_attempt = False
                for chunk in self.transport.stream(active_profile, active_payload, cancel, timeout_sec=attempt_timeout):
                    if cancel.is_set():
                        raise ModelGatewayError("AGENT_MODEL_CANCELLED", "Managed model request was cancelled.")
                    received_chunk = True
                    yield active_profile, chunk
                return
            except ModelGatewayError as exc:
                if cancel.is_set() or exc.code == "AGENT_MODEL_CANCELLED":
                    raise ModelGatewayError("AGENT_MODEL_CANCELLED", "Managed model request was cancelled.") from None
                if received_chunk:
                    raise _sanitized_gateway_error(exc) from None
                if exc.status_code in {401, 403} and not refreshed:
                    refreshed = True
                    active_profile = self._ensure_profile(force_refresh=True, model_id=model_id)
                    active_payload = {**active_payload, "model": active_profile.model}
                    continue
                if _is_retryable_gateway_error(exc) and network_retries < MAX_RETRIES_BEFORE_CHUNK:
                    network_retries += 1
                    self._wait_before_retry(cancel, deadline, network_retries)
                    continue
                raise _sanitized_gateway_error(exc) from None
            except Exception:
                if received_chunk:
                    raise ModelGatewayError("AGENT_MODEL_NETWORK_ERROR", "Managed gateway stream failed.") from None
                if network_retries < MAX_RETRIES_BEFORE_CHUNK:
                    network_retries += 1
                    self._wait_before_retry(cancel, deadline, network_retries)
                    continue
                raise ModelGatewayError("AGENT_MODEL_NETWORK_ERROR", "Managed gateway stream failed.") from None

    @staticmethod
    def _wait_before_retry(cancel: threading.Event, deadline: float, retry_number: int) -> None:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ModelGatewayError("AGENT_MODEL_TIMEOUT", "Managed model request timed out.")
        base_delay = min(RETRY_BASE_DELAY_SEC * (2 ** max(0, retry_number - 1)), RETRY_MAX_DELAY_SEC)
        max_delay = min(base_delay * 1.25, RETRY_MAX_DELAY_SEC)
        delay = min(random.uniform(base_delay, max_delay), remaining)
        if delay > 0 and cancel.wait(delay):
            raise ModelGatewayError("AGENT_MODEL_CANCELLED", "Managed model request was cancelled.")
