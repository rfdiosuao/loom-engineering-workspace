"""Structured, cancellable runtime adapter for installed LOOM agent runtimes."""

from __future__ import annotations

import json
import os
import queue
import re
import shutil
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol


Json = dict[str, Any]
EmitCallback = Callable[[Json], None]


class AgentRuntimeAdapter(Protocol):
    def status(self, profile_id: str | None = None) -> Json: ...

    def start(
        self,
        request: Mapping[str, Any],
        emit: EmitCallback,
        cancel: threading.Event,
        *,
        timeout_sec: float | None = None,
    ) -> Json: ...


class RuntimeExecutionError(RuntimeError):
    def __init__(self, code: str, message: str, *, recoverable: bool = True):
        super().__init__(redact_text(message))
        self.code = code
        self.recoverable = recoverable

    def to_dict(self) -> Json:
        return {"code": self.code, "message": str(self), "recoverable": self.recoverable}


class LoomCliRuntimeAdapter:
    """Run a selected CLI runtime through stdin/stdout JSON contracts."""

    def __init__(
        self,
        *,
        profile_resolver: Callable[[str | None], Mapping[str, Any] | None] | None = None,
        profiles_path: str | None = None,
        default_profile_id: str = "default",
        default_timeout_sec: float = 300.0,
        process_factory: Callable[..., Any] = subprocess.Popen,
    ):
        self.profiles_path = profiles_path or os.environ.get("LOOM_AGENT_RUNTIME_PROFILES", "").strip()
        self.default_profile_id = default_profile_id
        self.default_timeout_sec = max(0.01, float(default_timeout_sec))
        self._profile_resolver = profile_resolver or self._resolve_file_profile
        self._process_factory = process_factory

    def status(self, profile_id: str | None = None) -> Json:
        try:
            profile = self._resolve_profile(profile_id)
        except RuntimeExecutionError as exc:
            return {"available": False, "error": exc.to_dict()}
        command = _profile_command(profile)
        executable = command[0]
        installed = os.path.isfile(executable) or shutil.which(executable) is not None
        if not installed:
            return {
                "available": False,
                "profileId": str(profile.get("profileId") or profile_id or self.default_profile_id),
                "runtime": str(profile.get("runtime") or "unknown"),
                "error": {
                    "code": "agent_runtime_unavailable",
                    "message": "Configured agent runtime is not installed.",
                    "recoverable": True,
                },
            }
        return {
            "available": True,
            "profileId": str(profile.get("profileId") or profile_id or self.default_profile_id),
            "runtime": str(profile.get("runtime") or "compatible-cli"),
            "executable": os.path.basename(executable),
        }

    def start(
        self,
        request: Mapping[str, Any],
        emit: EmitCallback,
        cancel: threading.Event,
        *,
        timeout_sec: float | None = None,
    ) -> Json:
        if cancel.is_set():
            raise RuntimeExecutionError("agent_runtime_cancelled", "Agent runtime was cancelled.")

        profile_id = str(request.get("runtimeProfileId") or self.default_profile_id)
        profile = self._resolve_profile(profile_id)
        provider = str(profile.get("adapter") or "").strip().lower()
        if provider in {"codex", "claude"}:
            return self._start_provider(
                provider,
                profile,
                request,
                emit,
                cancel,
                timeout_sec=timeout_sec,
            )
        command = _profile_command(profile)
        environment = os.environ.copy()
        raw_env = profile.get("env")
        if isinstance(raw_env, Mapping):
            environment.update({str(key): str(value) for key, value in raw_env.items()})
        cwd = profile.get("cwd")
        if cwd is not None and not isinstance(cwd, str):
            raise RuntimeExecutionError("agent_runtime_invalid_profile", "Runtime cwd must be a string.")

        try:
            process = self._process_factory(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=cwd or None,
                env=environment,
                shell=False,
            )
        except (OSError, ValueError) as exc:
            raise RuntimeExecutionError(
                "agent_runtime_unavailable",
                f"Unable to launch configured agent runtime: {exc}",
            ) from exc

        try:
            assert process.stdin is not None
            process.stdin.write(json.dumps(dict(request), ensure_ascii=False, separators=(",", ":")) + "\n")
            process.stdin.flush()
            process.stdin.close()
        except (BrokenPipeError, OSError, ValueError) as exc:
            _terminate_process(process)
            raise RuntimeExecutionError(
                "agent_runtime_exited",
                f"Agent runtime closed before accepting its request: {exc}",
            ) from exc

        output_queue: queue.Queue[tuple[str, str | None]] = queue.Queue()
        readers = [
            threading.Thread(target=_read_stream, args=("stdout", process.stdout, output_queue), daemon=True),
            threading.Thread(target=_read_stream, args=("stderr", process.stderr, output_queue), daemon=True),
        ]
        for reader in readers:
            reader.start()

        deadline = time.monotonic() + (self.default_timeout_sec if timeout_sec is None else max(0.01, float(timeout_sec)))
        stdout_lines: list[str] = []
        stderr_lines: list[str] = []
        parsed_items: list[Json] = []
        result: Json | None = None
        streams_done: set[str] = set()

        while len(streams_done) < 2 or process.poll() is None:
            if cancel.is_set():
                _terminate_process(process)
                raise RuntimeExecutionError("agent_runtime_cancelled", "Agent runtime was cancelled.")
            if time.monotonic() >= deadline:
                _terminate_process(process)
                raise RuntimeExecutionError("agent_runtime_timeout", "Agent runtime exceeded its time limit.")
            try:
                stream_name, line = output_queue.get(timeout=0.02)
            except queue.Empty:
                continue
            if line is None:
                streams_done.add(stream_name)
                continue
            if stream_name == "stderr":
                stderr_lines.append(line)
                continue
            stdout_lines.append(line)
            item = _parse_json_object(line)
            if item is None:
                continue
            parsed_items.append(item)
            if item.get("type") == "result":
                result = _result_data(item)
            else:
                emit(redact_sensitive(item))

        for reader in readers:
            reader.join(timeout=0.1)
        return_code = process.wait(timeout=0.2)
        _close_process_streams(process)
        raw_stdout = "".join(stdout_lines).strip()
        if not parsed_items and raw_stdout:
            item = _parse_json_object(raw_stdout)
            if item is not None:
                parsed_items.append(item)
                if item.get("type") == "result":
                    result = _result_data(item)
                else:
                    emit(redact_sensitive(item))

        invalid_lines = [line for line in stdout_lines if line.strip() and _parse_json_object(line) is None]
        if parsed_items and invalid_lines and _parse_json_object(raw_stdout) is None:
            raise RuntimeExecutionError(
                "agent_runtime_invalid_output",
                "Agent runtime returned output outside the JSON/JSONL contract.",
            )
        if not parsed_items:
            detail = redact_text("".join(stderr_lines + stdout_lines))[:300]
            if return_code != 0:
                raise RuntimeExecutionError(
                    "agent_runtime_exited",
                    f"Agent runtime exited with code {return_code}. {detail}",
                )
            if raw_stdout:
                raise RuntimeExecutionError(
                    "agent_runtime_invalid_output",
                    f"Agent runtime returned invalid structured output. {detail}",
                )
            raise RuntimeExecutionError("agent_runtime_empty_output", "Agent runtime returned no structured output.")
        if return_code != 0:
            detail = redact_text("".join(stderr_lines))[:300]
            raise RuntimeExecutionError(
                "agent_runtime_exited",
                f"Agent runtime exited with code {return_code}. {detail}",
            )
        return redact_sensitive(result if result is not None else {"status": "completed"})

    def _start_provider(
        self,
        provider: str,
        profile: Mapping[str, Any],
        request: Mapping[str, Any],
        emit: EmitCallback,
        cancel: threading.Event,
        *,
        timeout_sec: float | None,
    ) -> Json:
        command = _profile_command(profile)
        environment = os.environ.copy()
        raw_env = profile.get("env")
        if isinstance(raw_env, Mapping):
            environment.update({str(key): str(value) for key, value in raw_env.items()})
        cwd = profile.get("cwd")
        if cwd is not None and not isinstance(cwd, str):
            raise RuntimeExecutionError("agent_runtime_invalid_profile", "Runtime cwd must be a string.")
        prompt = _provider_prompt(request)
        deadline_sec = self.default_timeout_sec if timeout_sec is None else max(0.01, float(timeout_sec))

        with tempfile.TemporaryDirectory(prefix="loom-agent-runtime-") as temp_dir:
            schema_path = os.path.join(temp_dir, "response-schema.json")
            output_path = os.path.join(temp_dir, "last-message.json")
            with open(schema_path, "w", encoding="utf-8") as handle:
                json.dump(AGENT_PROVIDER_RESPONSE_SCHEMA, handle, ensure_ascii=False, separators=(",", ":"))

            provider_command = _provider_command(
                provider,
                command,
                profile,
                schema_path=schema_path,
                output_path=output_path,
            )
            stdout, stderr = self._capture_provider(
                provider_command,
                prompt,
                cancel,
                timeout_sec=deadline_sec,
                cwd=cwd or None,
                environment=environment,
            )
            raw_result = ""
            if provider == "codex":
                try:
                    with open(output_path, "r", encoding="utf-8-sig") as handle:
                        raw_result = handle.read()
                except OSError as exc:
                    raise RuntimeExecutionError(
                        "agent_runtime_invalid_output",
                        f"Codex did not produce its structured result file: {exc}",
                    ) from exc
            else:
                raw_result = stdout

        result = _parse_provider_result(provider, raw_result)
        plan = result.get("plan")
        if isinstance(plan, list) and plan:
            emit({"type": "plan.updated", "data": {"steps": plan}})
        return redact_sensitive({
            "toolCalls": result.get("toolCalls", []),
            **({"final": result["final"]} if result.get("final") is not None else {}),
        })

    def _capture_provider(
        self,
        command: Sequence[str],
        prompt: str,
        cancel: threading.Event,
        *,
        timeout_sec: float,
        cwd: str | None,
        environment: Mapping[str, str],
    ) -> tuple[str, str]:
        try:
            process = self._process_factory(
                list(command),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=cwd,
                env=dict(environment),
                shell=False,
            )
        except (OSError, ValueError) as exc:
            raise RuntimeExecutionError(
                "agent_runtime_unavailable",
                f"Unable to launch {os.path.basename(str(command[0]))}: {exc}",
            ) from exc
        try:
            assert process.stdin is not None
            process.stdin.write(prompt)
            process.stdin.flush()
            process.stdin.close()
        except (BrokenPipeError, OSError, ValueError) as exc:
            _terminate_process(process)
            raise RuntimeExecutionError(
                "agent_runtime_exited",
                f"AI runtime closed before accepting its request: {exc}",
            ) from exc

        output_queue: queue.Queue[tuple[str, str | None]] = queue.Queue()
        readers = [
            threading.Thread(target=_read_stream, args=("stdout", process.stdout, output_queue), daemon=True),
            threading.Thread(target=_read_stream, args=("stderr", process.stderr, output_queue), daemon=True),
        ]
        for reader in readers:
            reader.start()
        deadline = time.monotonic() + timeout_sec
        streams_done: set[str] = set()
        chunks: dict[str, list[str]] = {"stdout": [], "stderr": []}
        output_size = 0
        while len(streams_done) < 2 or process.poll() is None:
            if cancel.is_set():
                _terminate_process(process)
                raise RuntimeExecutionError("agent_runtime_cancelled", "Agent runtime was cancelled.")
            if time.monotonic() >= deadline:
                _terminate_process(process)
                raise RuntimeExecutionError("agent_runtime_timeout", "Agent runtime exceeded its time limit.")
            try:
                stream_name, line = output_queue.get(timeout=0.02)
            except queue.Empty:
                continue
            if line is None:
                streams_done.add(stream_name)
                continue
            output_size += len(line.encode("utf-8", errors="replace"))
            if output_size > 2_000_000:
                _terminate_process(process)
                raise RuntimeExecutionError("agent_runtime_output_too_large", "Agent runtime output exceeded 2 MB.")
            chunks[stream_name].append(line)
        for reader in readers:
            reader.join(timeout=0.1)
        return_code = process.wait(timeout=0.2)
        _close_process_streams(process)
        stdout = "".join(chunks["stdout"]).strip()
        stderr = "".join(chunks["stderr"]).strip()
        if return_code != 0:
            detail = redact_text(stderr or stdout)[:300]
            raise RuntimeExecutionError(
                "agent_runtime_exited",
                f"Agent runtime exited with code {return_code}. {detail}",
            )
        return stdout, stderr

    def _resolve_profile(self, profile_id: str | None) -> Mapping[str, Any]:
        try:
            profile = self._profile_resolver(profile_id or self.default_profile_id)
        except RuntimeExecutionError:
            raise
        except Exception as exc:
            raise RuntimeExecutionError(
                "agent_runtime_unavailable",
                f"Unable to resolve the configured agent runtime: {exc}",
            ) from exc
        if not isinstance(profile, Mapping):
            raise RuntimeExecutionError("agent_runtime_unavailable", "No configured agent runtime was found.")
        return profile

    def _resolve_file_profile(self, profile_id: str | None) -> Mapping[str, Any] | None:
        path = self.profiles_path
        if not path or not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8-sig") as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeExecutionError("agent_runtime_invalid_profile", f"Runtime profile file is invalid: {exc}") from exc
        profiles = payload.get("profiles") if isinstance(payload, Mapping) else None
        wanted = profile_id or (payload.get("defaultProfileId") if isinstance(payload, Mapping) else None) or self.default_profile_id
        if isinstance(profiles, Mapping):
            profile = profiles.get(wanted)
            if isinstance(profile, Mapping):
                return {"profileId": wanted, **profile}
        if isinstance(profiles, Sequence) and not isinstance(profiles, (str, bytes)):
            for profile in profiles:
                if isinstance(profile, Mapping) and profile.get("profileId") == wanted:
                    return profile
        return None


AGENT_PROVIDER_RESPONSE_SCHEMA: Json = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "plan": {"type": "array", "items": {"type": "string"}},
        "toolCalls": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "toolCallId": {"type": "string"},
                    "name": {"type": "string"},
                    "input": {"type": "object"},
                },
                "required": ["toolCallId", "name", "input"],
            },
        },
        "final": {
            "anyOf": [
                {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {"text": {"type": "string"}},
                    "required": ["text"],
                },
                {"type": "null"},
            ],
        },
    },
    "required": ["plan", "toolCalls", "final"],
}


def _provider_prompt(request: Mapping[str, Any]) -> str:
    safe_request = redact_sensitive(dict(request))
    payload = json.dumps(safe_request, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return (
        "You are the decision runtime inside the local LOOM central agent. "
        "Do not run shell commands, inspect files, browse, call MCP, or execute tools yourself. "
        "LOOM executes tools after policy and lease checks. Use only capability names present in the request. "
        "Return exactly one JSON object matching the supplied schema. "
        "plan is a short list of concrete steps. toolCalls contains the next bounded tool calls; use stable unique toolCallId values. "
        "When toolResults are sufficient, return an empty toolCalls array and final with a concise user-facing text. "
        "When tools are required, final must be null. Never include secrets or reusable credentials.\n\n"
        f"LOOM_REQUEST_JSON={payload}"
    )


def _provider_command(
    provider: str,
    base_command: Sequence[str],
    profile: Mapping[str, Any],
    *,
    schema_path: str,
    output_path: str,
) -> list[str]:
    extra = profile.get("providerArgs", [])
    if not isinstance(extra, Sequence) or isinstance(extra, (str, bytes)) or not all(isinstance(item, str) for item in extra):
        raise RuntimeExecutionError(
            "agent_runtime_invalid_profile",
            "Runtime providerArgs must be an argument array.",
            recoverable=False,
        )
    model = str(profile.get("model") or "").strip()
    command = [str(item) for item in base_command]
    if provider == "codex":
        command.extend([
            "exec",
            "--skip-git-repo-check",
            "--ephemeral",
            "--sandbox",
            "read-only",
            "--color",
            "never",
            "--output-schema",
            schema_path,
            "--output-last-message",
            output_path,
        ])
        if model:
            command.extend(["--model", model])
        command.extend(extra)
        command.append("-")
        return command
    command.extend([
        "--print",
        "--safe-mode",
        "--tools",
        "",
        "--permission-mode",
        "dontAsk",
        "--output-format",
        "json",
        "--json-schema",
        json.dumps(AGENT_PROVIDER_RESPONSE_SCHEMA, ensure_ascii=False, separators=(",", ":")),
        "--no-session-persistence",
    ])
    if model:
        command.extend(["--model", model])
    command.extend(extra)
    return command


def _parse_provider_result(provider: str, raw: str) -> Json:
    payload = _parse_json_object(raw.strip())
    if payload is None:
        raise RuntimeExecutionError(
            "agent_runtime_invalid_output",
            f"{provider.title()} returned invalid structured output.",
        )
    candidate: Any = payload
    if isinstance(payload.get("structured_output"), Mapping):
        candidate = payload["structured_output"]
    elif isinstance(payload.get("result"), Mapping):
        candidate = payload["result"]
    elif isinstance(payload.get("result"), str):
        candidate = _parse_json_object(str(payload["result"]).strip())
    if not isinstance(candidate, Mapping):
        raise RuntimeExecutionError("agent_runtime_invalid_output", "AI runtime result did not contain a JSON object.")
    plan = candidate.get("plan", [])
    tool_calls = candidate.get("toolCalls", [])
    final = candidate.get("final")
    if not isinstance(plan, list) or not all(isinstance(step, str) for step in plan):
        raise RuntimeExecutionError("agent_runtime_invalid_output", "AI runtime plan must be a string array.")
    if not isinstance(tool_calls, list):
        raise RuntimeExecutionError("agent_runtime_invalid_output", "AI runtime toolCalls must be an array.")
    normalized_calls: list[Json] = []
    for item in tool_calls:
        if not isinstance(item, Mapping):
            raise RuntimeExecutionError("agent_runtime_invalid_output", "AI runtime returned an invalid tool call.")
        tool_call_id = str(item.get("toolCallId") or "").strip()
        name = str(item.get("name") or "").strip()
        arguments = item.get("input")
        if not tool_call_id or not name or not isinstance(arguments, Mapping):
            raise RuntimeExecutionError("agent_runtime_invalid_output", "AI runtime tool call fields are incomplete.")
        normalized_calls.append({"toolCallId": tool_call_id, "name": name, "input": dict(arguments)})
    if isinstance(final, str):
        final = {"text": final}
    if final is not None and (not isinstance(final, Mapping) or not isinstance(final.get("text"), str)):
        raise RuntimeExecutionError("agent_runtime_invalid_output", "AI runtime final result is invalid.")
    if normalized_calls and final is not None:
        raise RuntimeExecutionError("agent_runtime_invalid_output", "AI runtime cannot return tools and a final answer together.")
    if not normalized_calls and final is None:
        raise RuntimeExecutionError("agent_runtime_invalid_output", "AI runtime returned neither tools nor a final answer.")
    return {"plan": plan, "toolCalls": normalized_calls, "final": dict(final) if isinstance(final, Mapping) else None}


def redact_sensitive(value: Any) -> Any:
    """Return a log/event-safe copy without reusable credentials or private bodies."""
    if isinstance(value, Mapping):
        safe: Json = {}
        for key, item in value.items():
            name = str(key)
            lowered = re.sub(r"[^a-z0-9]", "", name.lower())
            if _is_sensitive_key(lowered):
                safe[name] = "[REDACTED]"
            elif lowered in {"privatecontent", "privatebody", "contactlist", "addressbook", "filebody"}:
                safe[name] = "[PRIVATE CONTENT REDACTED]"
            else:
                safe[name] = redact_sensitive(item)
        return safe
    if isinstance(value, list):
        return [redact_sensitive(item) for item in value]
    if isinstance(value, tuple):
        return [redact_sensitive(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def redact_text(value: str) -> str:
    text = str(value)
    patterns = (
        (r"(?i)Bearer\s+[A-Za-z0-9._~+/-]+", "Bearer [REDACTED]"),
        (r"\bsk-[A-Za-z0-9_-]{4,}\b", "sk-[REDACTED]"),
        (r"(?i)(api[_-]?key|token|password|secret|cookie|authorization)(\s*[:=]\s*)[^\s,;]+", r"\1\2[REDACTED]"),
    )
    for pattern, replacement in patterns:
        text = re.sub(pattern, replacement, text)
    return text


def _is_sensitive_key(normalized_key: str) -> bool:
    return any(
        marker in normalized_key
        for marker in ("apikey", "token", "secret", "password", "cookie", "authorization", "credential")
    )


def _profile_command(profile: Mapping[str, Any]) -> list[str]:
    raw = profile.get("command")
    if isinstance(raw, str):
        raise RuntimeExecutionError(
            "agent_runtime_invalid_profile",
            "Runtime command must be an argument array, not a shell string.",
            recoverable=False,
        )
    if not isinstance(raw, Sequence) or isinstance(raw, (bytes, bytearray)):
        executable = profile.get("executable")
        args = profile.get("args", [])
        raw = [executable, *args] if executable and isinstance(args, Sequence) and not isinstance(args, str) else []
    command = [str(item) for item in raw if isinstance(item, (str, os.PathLike)) and str(item)]
    if not command or len(command) != len(raw):
        raise RuntimeExecutionError("agent_runtime_invalid_profile", "Runtime command contains invalid arguments.", recoverable=False)
    return command


def _read_stream(name: str, stream: Any, output: queue.Queue[tuple[str, str | None]]) -> None:
    try:
        if stream is not None:
            for line in iter(stream.readline, ""):
                output.put((name, line))
    finally:
        output.put((name, None))


def _parse_json_object(raw: str) -> Json | None:
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def _result_data(item: Mapping[str, Any]) -> Json:
    data = item.get("data", {})
    return dict(data) if isinstance(data, Mapping) else {"value": data}


def _terminate_process(process: Any) -> None:
    if process.poll() is not None:
        _close_process_streams(process)
        return
    try:
        process.terminate()
        process.wait(timeout=0.3)
    except Exception:
        try:
            process.kill()
            process.wait(timeout=0.3)
        except Exception:
            pass
    _close_process_streams(process)


def _close_process_streams(process: Any) -> None:
    for stream_name in ("stdin", "stdout", "stderr"):
        stream = getattr(process, stream_name, None)
        try:
            if stream is not None and not stream.closed:
                stream.close()
        except (OSError, ValueError):
            pass
