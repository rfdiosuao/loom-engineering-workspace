"""Native LOOM runtime adapter backed by the managed model gateway."""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from typing import Any

from core.agent_runtime import Json, RuntimeExecutionError
from core.loom_model_client import LoomModelClient, ModelGatewayError, redact_sensitive


class LoomNativeRuntimeAdapter:
    """Expose the managed LOOM model client through the agent runtime contract."""

    profile_id = "loom-native"

    def __init__(self, client: LoomModelClient) -> None:
        self.client = client

    def status(self, profile_id: str | None = None) -> Json:
        status = self.client.status()
        return {
            **redact_sensitive(status),
            "profileId": self.profile_id,
            "runtime": "麓鸣原生智能体",
        }

    def start(
        self,
        request: Mapping[str, Any],
        emit: Callable[[Json], None],
        cancel: threading.Event,
        *,
        timeout_sec: float | None = None,
    ) -> Json:
        if cancel.is_set():
            raise RuntimeExecutionError("AGENT_MODEL_CANCELLED", "Managed model request was cancelled.")

        run_id = str(request.get("runId") or "unknown")
        round_value = request.get("round")
        round_suffix = f"_round_{round_value}" if isinstance(round_value, int) and round_value > 0 else ""
        message_id = f"message_{run_id}{round_suffix}"

        def relay(event: Json) -> None:
            if event.get("type") == "model.text.delta":
                data = event.get("data") if isinstance(event.get("data"), Mapping) else {}
                delta = data.get("delta", data.get("text", ""))
                emit({
                    "type": "message.delta",
                    "data": {"messageId": message_id, "role": "assistant", "delta": str(delta or "")},
                })
                return
            emit(redact_sensitive(event))

        try:
            response = self.client.complete(request, relay, cancel, timeout_sec=timeout_sec)
        except ModelGatewayError as error:
            raise RuntimeExecutionError(error.code, str(error), recoverable=error.recoverable) from error

        tool_calls = response.get("toolCalls") if isinstance(response.get("toolCalls"), list) else []
        result: Json = {
            "messageId": message_id,
            "toolCalls": tool_calls,
            "model": response.get("model"),
            "usage": response.get("usage", {}),
        }
        if not tool_calls:
            result["final"] = {"text": str(response.get("text") or "")}
        return redact_sensitive(result)
