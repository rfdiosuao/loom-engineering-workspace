from __future__ import annotations

import io
import json
import os
import socket
import sys
import threading
import traceback
import unittest
import urllib.error
from types import SimpleNamespace


PYTHON_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)


from core.loom_model_client import (
    MAX_RESPONSE_BYTES,
    LoomModelClient,
    LoomModelProfile,
    ModelGatewayError,
    UrlLibSseTransport,
    _model_tool_alias_maps,
    build_chat_payload,
    profile_from_session,
    redact_sensitive,
    redact_text,
)
from core.agent_capabilities import PHONE_PUBLISH_INPUT_SCHEMA


class FakeAccount:
    def __init__(self, session=None, refreshed_session=None, ensure_error=None):
        self.session = session
        self.refreshed_session = refreshed_session
        self.ensure_error = ensure_error
        self.ensure_calls = 0
        self.sync_runtime_values = []
        self.force_refresh_values = []

    def current(self):
        return self.session

    def ensure_launcher_token(self, *, sync_runtime=False, force_refresh=False):
        self.ensure_calls += 1
        self.sync_runtime_values.append(sync_runtime)
        self.force_refresh_values.append(force_refresh)
        if self.ensure_error is not None:
            raise self.ensure_error
        if not self.session:
            raise RuntimeError("not_logged_in")
        if self.refreshed_session and force_refresh:
            self.session = self.refreshed_session
        return self.session


def managed_session(token="sk-native-secret-value", model="glm-managed"):
    return {
        "source": "newapi_account",
        "gatewayBaseUrl": "https://gateway.example/v1",
        "memberToken": token,
        "gatewayDefaultModel": model,
        "gateway": {
            "baseUrl": "https://gateway.example/v1",
            "accessToken": token,
            "defaultModel": model,
        },
    }


class FakeTransport:
    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.requests = []

    def stream(self, profile, payload, cancel, *, timeout_sec):
        self.requests.append((profile, payload, timeout_sec))
        for chunk in self.chunks:
            if isinstance(chunk, Exception):
                raise chunk
            yield chunk


class ScriptedTransport:
    def __init__(self, attempts):
        self.attempts = [list(items) for items in attempts]
        self.requests = []

    def stream(self, profile, payload, cancel, *, timeout_sec):
        self.requests.append((profile, payload, timeout_sec))
        for item in self.attempts[len(self.requests) - 1]:
            if isinstance(item, Exception):
                raise item
            yield item


class RepeatingErrorTransport:
    def __init__(self, error):
        self.error = error
        self.requests = []

    def stream(self, profile, payload, cancel, *, timeout_sec):
        self.requests.append((profile, payload, timeout_sec))
        if False:
            yield {}
        raise self.error


class DeterministicResponse:
    def __init__(self, body=b"", *, read_error=None, on_read=None):
        self.body = io.BytesIO(body)
        self.read_error = read_error
        self.on_read = on_read
        self.readline_limits = []
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _traceback):
        self.closed = True

    def readline(self, limit=-1):
        self.readline_limits.append(limit)
        if self.on_read is not None:
            self.on_read()
        if self.read_error is not None:
            raise self.read_error
        return self.body.readline(limit)


class RecordingOpener:
    def __init__(self, response=None, *, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def __call__(self, request, *, timeout):
        self.calls.append({"request": request, "timeout": timeout})
        if self.error is not None:
            raise self.error
        return self.response


class RecordingSocket:
    def __init__(self):
        self.timeouts = []

    def settimeout(self, timeout):
        self.timeouts.append(timeout)


class RecordingCancel(threading.Event):
    def __init__(self):
        super().__init__()
        self.waits = []

    def wait(self, timeout=None):
        self.waits.append(timeout)
        return self.is_set()


def transport_profile():
    return LoomModelProfile(
        base_url="https://gateway.example/v1",
        access_token="sk-transport-secret-value",
        model="account-selected-model",
    )


def model_tool_call_chunk(tool_call_id, name):
    return {
        "choices": [{"delta": {"tool_calls": [{
            "index": 0,
            "id": tool_call_id,
            "function": {"name": name, "arguments": "{}"},
        }]}}],
    }


class LoomModelClientTests(unittest.TestCase):
    def test_chat_payload_reads_persisted_block_messages_as_conversation_history(self):
        payload = build_chat_payload(transport_profile(), {
            "prompt": "我上一句发了什么？",
            "history": [
                {
                    "role": "user",
                    "blocks": [{"type": "text", "data": {"text": "你能生图么？"}}],
                },
                {
                    "role": "assistant",
                    "blocks": [{"type": "text", "data": {"text": "可以，请描述画面。"}}],
                },
            ],
        })

        conversation = payload["messages"][1:]
        self.assertEqual(
            [(item["role"], item["content"]) for item in conversation],
            [
                ("user", "你能生图么？"),
                ("assistant", "可以，请描述画面。"),
                ("user", "我上一句发了什么？"),
            ],
        )

    def test_chat_payload_honors_system_override_when_provided(self) -> None:
        profile = profile_from_session(managed_session())
        payload = build_chat_payload(profile, {
            "prompt": "写文案",
            "systemOverride": "你是九步文案专家，只输出JSON。",
        })
        messages = payload["messages"]
        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("九步文案专家", messages[0]["content"])
        self.assertNotIn("麓鸣原生中枢智能体", messages[0]["content"])

    def test_chat_payload_uses_dynamic_chinese_native_agent_contract(self):
        payload = build_chat_payload(transport_profile(), {
            "prompt": "查看当前状态",
            "capabilities": [{
                "name": "loom.status",
                "displayName": "查看麓鸣状态",
                "description": "读取本地系统状态",
                "domain": "system",
                "inputSchema": {"type": "object"},
            }],
        })

        system_prompt = payload["messages"][0]["content"]
        self.assertIn("麓鸣原生中枢智能体", system_prompt)
        self.assertIn("自行判断", system_prompt)
        self.assertIn("查看麓鸣状态", system_prompt)

    def test_profile_from_session_overrides_only_the_model_for_this_request(self):
        session = managed_session(model="account-default-model")

        profile = profile_from_session(session, model_id="qwen3.7-plus")

        self.assertEqual(profile.model, "qwen3.7-plus")
        self.assertEqual(profile.base_url, "https://gateway.example/v1")
        self.assertEqual(profile.access_token, "sk-native-secret-value")
        self.assertEqual(session["gatewayDefaultModel"], "account-default-model")

    def test_complete_routes_one_run_to_its_snapshotted_model_without_mutating_account(self):
        account = FakeAccount(managed_session(model="account-default-model"))
        transport = FakeTransport([{"choices": [{"delta": {"content": "Done"}}]}])

        result = LoomModelClient(account, transport=transport).complete(
            {
                "runId": "run_model_override",
                "round": 1,
                "prompt": "check",
                "modelId": "qwen3.7-plus",
            },
            lambda _event: None,
            threading.Event(),
        )

        profile, payload, _timeout = transport.requests[0]
        self.assertEqual(profile.model, "qwen3.7-plus")
        self.assertEqual(payload["model"], "qwen3.7-plus")
        self.assertEqual(result["model"], "qwen3.7-plus")
        self.assertEqual(account.session["gatewayDefaultModel"], "account-default-model")

    def test_status_requires_login_without_exposing_secret(self):
        client = LoomModelClient(FakeAccount())

        status = client.status()

        self.assertFalse(status["available"])
        self.assertEqual(status["error"]["code"], "AGENT_ACCOUNT_LOGIN_REQUIRED")
        self.assertNotIn("not_logged_in", json.dumps(status))

    def test_status_reports_selected_managed_model_only(self):
        client = LoomModelClient(FakeAccount(managed_session()))

        status = client.status()

        self.assertTrue(status["available"])
        self.assertEqual(status["profileId"], "loom-native")
        self.assertEqual(status["model"], "glm-managed")
        self.assertNotIn("sk-native-secret-value", json.dumps(status))

    def test_status_requires_relogin_when_launcher_token_upgrade_is_forbidden(self):
        error = RuntimeError("launcher token upgrade requires re-login")
        error.status_code = 403
        account = FakeAccount(managed_session(), ensure_error=error)

        status = LoomModelClient(account).status()

        self.assertFalse(status["available"])
        self.assertEqual(status["error"], {
            "code": "AGENT_ACCOUNT_RELOGIN_REQUIRED",
            "message": "Managed model account must be signed in again.",
        })
        self.assertEqual(account.ensure_calls, 1)
        self.assertEqual(account.sync_runtime_values, [False])
        self.assertNotIn("launcher token upgrade", json.dumps(status))

    def test_complete_preserves_relogin_error_instead_of_reporting_generic_login_required(self):
        error = RuntimeError("launcher token upgrade requires re-login")
        error.status_code = 403
        events = []

        with self.assertRaises(ModelGatewayError) as caught:
            LoomModelClient(FakeAccount(managed_session(), ensure_error=error)).complete(
                {"runId": "run_relogin", "round": 1, "prompt": "generate an image"},
                events.append,
                threading.Event(),
            )

        self.assertEqual(caught.exception.code, "AGENT_ACCOUNT_RELOGIN_REQUIRED")
        self.assertEqual(events[-1]["type"], "model.failed")
        self.assertEqual(events[-1]["data"]["error"]["code"], "AGENT_ACCOUNT_RELOGIN_REQUIRED")

    def test_complete_aggregates_text_tool_calls_usage_and_emits_deltas(self):
        transport = FakeTransport([
            {"choices": [{"delta": {"content": "Checking "}}]},
            {"choices": [{"delta": {"content": "matrix"}}]},
            {"choices": [{"delta": {"tool_calls": [{
                "index": 0,
                "id": "call_1",
                "function": {
                    "name": "loom.matrix.status",
                    "arguments": "{\"campaignId\":\"c1\"}",
                },
            }]}}]},
            {"usage": {"prompt_tokens": 10, "completion_tokens": 3}},
        ])
        events = []

        result = LoomModelClient(FakeAccount(managed_session()), transport=transport).complete(
            {
                "runId": "run_1",
                "round": 1,
                "prompt": "Check the matrix",
                "history": [{"role": "user", "content": "Earlier context"}],
                "toolResults": [{"toolCallId": "prior", "result": {"token": "sk-tool-secret", "ok": True}}],
                "capabilities": [{
                    "name": "loom.matrix.status",
                    "description": "Read the matrix",
                    "inputSchema": {"type": "object"},
                }],
            },
            events.append,
            threading.Event(),
        )

        self.assertEqual(result["text"], "Checking matrix")
        self.assertEqual(result["toolCalls"], [{
            "toolCallId": "call_1",
            "name": "loom.matrix.status",
            "input": {"campaignId": "c1"},
        }])
        self.assertEqual(result["usage"]["prompt_tokens"], 10)
        self.assertEqual([event["type"] for event in events], [
            "model.text.delta",
            "model.text.delta",
            "model.tool_call.delta",
            "model.usage",
            "model.completed",
        ])
        self.assertEqual(events[-2]["data"], {"prompt_tokens": 10, "completion_tokens": 3})
        self.assertEqual(events[-1]["data"]["toolCallCount"], 1)
        self.assertEqual(events[-1]["data"]["usage"], {"prompt_tokens": 10, "completion_tokens": 3})
        self.assertNotIn("sk-tool-secret", json.dumps(events))
        payload = transport.requests[0][1]
        self.assertEqual(payload["model"], "glm-managed")
        self.assertEqual(payload["tool_choice"], "auto")
        self.assertEqual(payload["temperature"], 0.2)
        self.assertTrue(payload["stream"])
        self.assertEqual(payload["metadata"]["idempotencyKey"], "run_1:1")
        self.assertEqual(payload["tools"][0]["function"]["name"], "loom_matrix_status")
        self.assertNotIn("sk-native-secret-value", json.dumps(payload))
        self.assertNotIn("sk-tool-secret", json.dumps(payload))
        self.assertEqual(transport.requests[0][2], 120.0)

    def test_complete_restores_gateway_safe_tool_alias_to_capability_name(self):
        transport = FakeTransport([
            model_tool_call_chunk("call_status_1", "loom_mcp_loom_loom_status"),
        ])

        result = LoomModelClient(FakeAccount(managed_session()), transport=transport).complete(
            {
                "runId": "run_status_1",
                "round": 1,
                "prompt": "Read the current LOOM status",
                "capabilities": [{
                    "name": "loom.mcp.loom.loom_status",
                    "description": "Read LOOM local status",
                    "inputSchema": {"type": "object"},
                }],
            },
            lambda _event: None,
            threading.Event(),
        )

        payload = transport.requests[0][1]
        self.assertEqual(payload["tools"][0]["function"]["name"], "loom_mcp_loom_loom_status")
        self.assertEqual(result["toolCalls"], [{
            "toolCallId": "call_status_1",
            "name": "loom.mcp.loom.loom_status",
            "input": {},
        }])

    def test_complete_keeps_normalized_tool_aliases_unique(self):
        transport = FakeTransport([
            {"choices": [{"delta": {"content": "Ready"}}]},
        ])

        LoomModelClient(FakeAccount(managed_session()), transport=transport).complete(
            {
                "runId": "run_alias_collision",
                "round": 1,
                "prompt": "Check tools",
                "capabilities": [
                    {"name": "loom.test.read", "inputSchema": {"type": "object"}},
                    {"name": "loom_test_read", "inputSchema": {"type": "object"}},
                ],
            },
            lambda _event: None,
            threading.Event(),
        )

        aliases = [item["function"]["name"] for item in transport.requests[0][1]["tools"]]
        self.assertEqual(len(set(aliases)), 2)
        self.assertTrue(all(len(alias) <= 64 for alias in aliases))

    def test_explicit_capability_id_forces_first_round_tool_without_filtering_schema(self):
        payload = build_chat_payload(transport_profile(), {
            "runId": "run_explicit_publish",
            "round": 1,
            "prompt": "Please use loom.phone.publish to save this Douyin draft.",
            "capabilityHints": ["loom.phone.publish"],
            "capabilities": [
                {
                    "name": "loom.status",
                    "description": "Read LOOM status",
                    "inputSchema": {"type": "object"},
                },
                {
                    "name": "loom.phone.publish",
                    "description": "Save a phone publishing draft",
                    "inputSchema": PHONE_PUBLISH_INPUT_SCHEMA,
                },
            ],
        })

        self.assertEqual(len(payload["tools"]), 2)
        self.assertEqual(payload["tools"][0]["function"]["name"], "loom_phone_publish")
        self.assertIn(
            "title",
            payload["tools"][0]["function"]["parameters"]["properties"],
        )
        self.assertEqual(payload["tool_choice"], {
            "type": "function",
            "function": {"name": "loom_phone_publish"},
        })

    def test_explicit_capability_force_is_not_repeated_after_tool_result(self):
        payload = build_chat_payload(transport_profile(), {
            "runId": "run_explicit_publish",
            "round": 2,
            "prompt": "Please use loom.phone.publish to save this Douyin draft.",
            "capabilityHints": ["loom.phone.publish"],
            "toolResults": [{"capability": "loom.phone.publish", "status": "completed"}],
            "capabilities": [{
                "name": "loom.phone.publish",
                "inputSchema": PHONE_PUBLISH_INPUT_SCHEMA,
            }],
        })

        self.assertEqual(payload["tool_choice"], "auto")

    def test_capability_router_can_force_the_catalog_tool(self):
        payload = build_chat_payload(transport_profile(), {
            "runId": "run_catalog",
            "round": 1,
            "prompt": "列出当前已经连接的全部能力",
            "capabilityRouting": {
                "mode": "forced",
                "forcedCapability": "loom.capabilities.list",
            },
            "capabilities": [{
                "name": "loom.capabilities.list",
                "description": "查看当前真实连接的能力目录。",
                "inputSchema": {"type": "object", "additionalProperties": False},
            }],
        })

        self.assertEqual(payload["tool_choice"], {
            "type": "function",
            "function": {"name": "loom_capabilities_list"},
        })

    def test_capability_router_disables_more_tools_after_catalog_result(self):
        payload = build_chat_payload(transport_profile(), {
            "runId": "run_catalog",
            "round": 2,
            "prompt": "列出当前已经连接的全部能力",
            "capabilityRouting": {"mode": "response_only", "toolChoice": "none"},
            "toolResults": [{
                "toolCallId": "catalog-1",
                "capability": "loom.capabilities.list",
                "status": "completed",
                "result": {"count": 12},
            }],
            "capabilities": [{
                "name": "loom.capabilities.list",
                "inputSchema": {"type": "object", "additionalProperties": False},
            }],
        })

        self.assertEqual(payload["tool_choice"], "none")

    def test_invalid_tool_input_forces_one_model_repair_call_for_the_same_capability(self):
        payload = build_chat_payload(transport_profile(), {
            "runId": "run_repair_publish",
            "round": 2,
            "prompt": "Please use loom.phone.publish to save this Douyin draft.",
            "toolResults": [{
                "toolCallId": "call_publish_invalid",
                "capability": "loom.phone.publish",
                "status": "failed",
                "input": {"platform": "douyin"},
                "error": {
                    "code": "capability_invalid_input",
                    "message": "input.title is required",
                    "recoverable": True,
                },
            }],
            "capabilities": [{
                "name": "loom.phone.publish",
                "inputSchema": PHONE_PUBLISH_INPUT_SCHEMA,
            }],
        })

        self.assertEqual(payload["tool_choice"], {
            "type": "function",
            "function": {"name": "loom_phone_publish"},
        })
        repair_message = payload["messages"][-1]
        self.assertEqual(repair_message["role"], "user")
        self.assertIn("input.title is required", repair_message["content"])
        self.assertIn("loom.phone.publish", repair_message["content"])
        self.assertNotIn("tool", [message["role"] for message in payload["messages"]])
        self.assertNotIn("assistant", [message["role"] for message in payload["messages"]])

    def test_unknown_capability_result_requests_a_fresh_selection_from_current_tools(self):
        payload = build_chat_payload(transport_profile(), {
            "runId": "run_repair_selection",
            "round": 2,
            "prompt": "检查麓鸣状态",
            "toolResults": [{
                "toolCallId": "call_unknown_status",
                "capability": "loom_mcp_loom_loom_status",
                "status": "failed",
                "input": {},
                "error": {
                    "code": "capability_not_found",
                    "message": "Unknown capability: loom_mcp_loom_loom_status",
                    "recoverable": True,
                },
            }],
            "capabilities": [{
                "name": "loom.mcp.loom.loom_status",
                "inputSchema": {"type": "object"},
            }],
        })

        repair_message = payload["messages"][-1]
        self.assertEqual(repair_message["role"], "user")
        self.assertIn("上一轮选择的能力不存在", repair_message["content"])
        self.assertIn("loom.mcp.loom.loom_status", repair_message["content"])
        self.assertNotIn("Unknown capability", repair_message["content"])
        self.assertEqual(payload["tool_choice"], "auto")

    def test_tool_results_use_native_assistant_and_tool_protocol_messages(self):
        payload = build_chat_payload(transport_profile(), {
            "runId": "run_tool_history",
            "round": 2,
            "prompt": "Check the system once and report the result.",
            "toolResults": [{
                "toolCallId": "call_status_1",
                "capability": "loom.matrix.status",
                "status": "completed",
                "input": {"detail": "summary"},
                "result": {"online": 1, "running": 0},
            }],
            "capabilities": [{
                "name": "loom.matrix.status",
                "inputSchema": {
                    "type": "object",
                    "properties": {"detail": {"type": "string"}},
                },
            }],
        })

        assistant = next(message for message in payload["messages"] if message["role"] == "assistant")
        tool = next(message for message in payload["messages"] if message["role"] == "tool")
        self.assertEqual(assistant["tool_calls"], [{
            "id": "call_status_1",
            "type": "function",
            "function": {
                "name": "loom_matrix_status",
                "arguments": '{"detail":"summary"}',
            },
        }])
        self.assertEqual(tool["tool_call_id"], "call_status_1")
        self.assertEqual(json.loads(tool["content"]), {
            "status": "completed",
            "result": {"online": 1, "running": 0},
        })
        self.assertFalse(any(
            message["role"] == "user" and str(message.get("content") or "").startswith("Tool results from LOOM:")
            for message in payload["messages"]
        ))

    def test_session_artifacts_are_exposed_as_reusable_runtime_context(self):
        payload = build_chat_payload(transport_profile(), {
            "runId": "run_reuse_artifact",
            "round": 1,
            "prompt": "Use the image already generated and publish it.",
            "sessionArtifacts": [{
                "name": "wukong.png",
                "path": "D:/media/wukong.png",
                "mime": "image/png",
                "kind": "image",
            }],
            "capabilities": [{
                "name": "loom.phone.publish",
                "inputSchema": PHONE_PUBLISH_INPUT_SCHEMA,
            }],
        })

        system_context = payload["messages"][0]["content"]
        self.assertIn("D:/media/wukong.png", system_context)
        self.assertIn("wukong.png", system_context)
        self.assertIn("Do not regenerate", system_context)

    def test_hint_without_explicit_capability_id_does_not_force_tool(self):
        payload = build_chat_payload(transport_profile(), {
            "runId": "run_natural_language",
            "round": 1,
            "prompt": "Save this as a Douyin draft.",
            "capabilityHints": ["loom.phone.publish"],
            "capabilities": [{
                "name": "loom.phone.publish",
                "inputSchema": PHONE_PUBLISH_INPUT_SCHEMA,
            }],
        })

        self.assertEqual(payload["tool_choice"], "auto")

    def test_negated_or_discussed_capability_id_does_not_force_tool(self):
        capabilities = [{
            "name": "loom.phone.publish",
            "inputSchema": PHONE_PUBLISH_INPUT_SCHEMA,
        }]
        for prompt in (
            "Do not use loom.phone.publish; explain what it does.",
            "请不要调用 loom.phone.publish，只说明它的作用。",
            "不要再调用 loom.phone.publish，只总结之前的结果。",
            "请勿使用 loom.phone.publish。",
            "切勿执行 loom.phone.publish。",
            "You must not call loom.phone.publish.",
            "You should not invoke loom.phone.publish.",
            "Do not ever run loom.phone.publish.",
            "What does loom.phone.publish do?",
        ):
            with self.subTest(prompt=prompt):
                payload = build_chat_payload(transport_profile(), {
                    "runId": "run_no_force",
                    "round": 1,
                    "prompt": prompt,
                    "capabilities": capabilities,
                })
                self.assertEqual(payload["tool_choice"], "auto")

    def test_tool_alias_reverse_map_survives_safe_canonical_name_collision(self):
        canonical_to_alias, alias_to_canonical = _model_tool_alias_maps([
            {"name": "loom.test.read"},
            {"name": "loom_test_read"},
        ])

        self.assertNotEqual(
            canonical_to_alias["loom.test.read"],
            canonical_to_alias["loom_test_read"],
        )
        self.assertEqual(
            alias_to_canonical[canonical_to_alias["loom.test.read"]],
            "loom.test.read",
        )
        self.assertEqual(
            alias_to_canonical[canonical_to_alias["loom_test_read"]],
            "loom_test_read",
        )

    def test_tool_aliases_replace_dots_and_enforce_provider_length_limit(self):
        canonical = f"loom.mcp.{('very.long.capability.' * 5)}status"

        canonical_to_alias, _alias_to_canonical = _model_tool_alias_maps([
            {"name": canonical},
        ])

        alias = canonical_to_alias[canonical]
        self.assertNotIn(".", alias)
        self.assertLessEqual(len(alias), 64)

    def test_pre_cancelled_run_raises_cancelled_without_starting_transport(self):
        transport = FakeTransport([])
        cancel = threading.Event()
        cancel.set()

        with self.assertRaises(ModelGatewayError) as caught:
            LoomModelClient(FakeAccount(managed_session()), transport=transport).complete(
                {"runId": "run_1", "round": 1, "prompt": "stop"},
                lambda _event: None,
                cancel,
            )

        self.assertEqual(caught.exception.code, "AGENT_MODEL_CANCELLED")
        self.assertEqual(transport.requests, [])

    def test_invalid_tool_arguments_raise_protocol_error(self):
        transport = FakeTransport([{
            "choices": [{"delta": {"tool_calls": [{
                "index": 0,
                "id": "call_1",
                "function": {"name": "loom.matrix.status", "arguments": "not-json"},
            }]}}],
        }])

        events = []
        with self.assertRaises(ModelGatewayError) as caught:
            LoomModelClient(FakeAccount(managed_session()), transport=transport).complete(
                {"runId": "run_1", "round": 1, "prompt": "check"},
                events.append,
                threading.Event(),
            )

        self.assertEqual(caught.exception.code, "AGENT_MODEL_PROTOCOL_INVALID")
        self.assertEqual(events[-1]["type"], "model.failed")
        self.assertEqual(events[-1]["data"]["error"]["code"], "AGENT_MODEL_PROTOCOL_INVALID")

    def test_tool_identifiers_reject_secret_shaped_values_without_redacting_them(self):
        unsafe_values = (
            "Bearer raw-tool-secret",
            "sk-model-secret-value",
            "password=raw model secret",
        )
        for field in ("toolCallId", "name"):
            for unsafe in unsafe_values:
                with self.subTest(field=field, unsafe=unsafe):
                    tool_call_id = unsafe if field == "toolCallId" else "call_1"
                    name = unsafe if field == "name" else "loom.matrix.status"
                    transport = FakeTransport([model_tool_call_chunk(tool_call_id, name)])

                    with self.assertRaises(ModelGatewayError) as caught:
                        LoomModelClient(FakeAccount(managed_session()), transport=transport).complete(
                            {"runId": "run_1", "round": 1, "prompt": "check"},
                            lambda _event: None,
                            threading.Event(),
                        )

                    self.assertEqual(caught.exception.code, "AGENT_MODEL_PROTOCOL_INVALID")
                    self.assertNotIn(unsafe, str(caught.exception))

    def test_tool_identifiers_enforce_bounded_syntax_and_length(self):
        invalid_cases = (
            ("toolCallId", "call/unsafe"),
            ("toolCallId", "c" * 129),
            ("name", "loom.matrix/status"),
            ("name", "n" * 129),
        )
        for field, invalid in invalid_cases:
            with self.subTest(field=field, invalid=invalid[:20]):
                tool_call_id = invalid if field == "toolCallId" else "call-1"
                name = invalid if field == "name" else "loom.matrix.status"
                transport = FakeTransport([model_tool_call_chunk(tool_call_id, name)])

                with self.assertRaises(ModelGatewayError) as caught:
                    LoomModelClient(FakeAccount(managed_session()), transport=transport).complete(
                        {"runId": "run_1", "round": 1, "prompt": "check"},
                        lambda _event: None,
                        threading.Event(),
                    )

                self.assertEqual(caught.exception.code, "AGENT_MODEL_PROTOCOL_INVALID")

    def test_unauthorized_response_refreshes_launcher_token_once(self):
        account = FakeAccount(
            managed_session("sk-expired-secret"),
            refreshed_session=managed_session("sk-refreshed-secret", "account-selected-model"),
        )
        transport = ScriptedTransport([
            [ModelGatewayError("AGENT_MODEL_HTTP_ERROR", "Bearer sk-expired-secret", status_code=401)],
            [{"choices": [{"delta": {"content": "Recovered"}}]}],
        ])

        result = LoomModelClient(account, transport=transport).complete(
            {"runId": "run_1", "round": 1, "prompt": "check"},
            lambda _event: None,
            threading.Event(),
        )

        self.assertEqual(result["model"], "account-selected-model")
        self.assertEqual(len(transport.requests), 2)
        self.assertEqual(account.ensure_calls, 2)
        self.assertEqual(account.sync_runtime_values, [False, False])
        self.assertEqual(account.force_refresh_values, [False, True])
        self.assertEqual(transport.requests[1][0].access_token, "sk-refreshed-secret")

    def test_unauthorized_refresh_preserves_the_run_model_snapshot(self):
        account = FakeAccount(
            managed_session("sk-expired-secret", "account-default-before"),
            refreshed_session=managed_session("sk-refreshed-secret", "account-default-after"),
        )
        transport = ScriptedTransport([
            [ModelGatewayError("AGENT_MODEL_HTTP_ERROR", "unauthorized", status_code=401)],
            [{"choices": [{"delta": {"content": "Recovered"}}]}],
        ])

        result = LoomModelClient(account, transport=transport).complete(
            {
                "runId": "run_model_refresh",
                "round": 1,
                "prompt": "check",
                "modelId": "qwen3.7-plus",
            },
            lambda _event: None,
            threading.Event(),
        )

        self.assertEqual(result["model"], "qwen3.7-plus")
        self.assertEqual(transport.requests[0][0].model, "qwen3.7-plus")
        self.assertEqual(transport.requests[1][0].model, "qwen3.7-plus")
        self.assertEqual(transport.requests[1][1]["model"], "qwen3.7-plus")

    def test_transient_errors_retry_at_most_twice_before_the_first_chunk(self):
        transport = ScriptedTransport([
            [ModelGatewayError("AGENT_MODEL_NETWORK_ERROR", "network one")],
            [ModelGatewayError("AGENT_MODEL_NETWORK_ERROR", "network two")],
            [{"choices": [{"delta": {"content": "Third attempt"}}]}],
        ])

        cancel = RecordingCancel()
        result = LoomModelClient(FakeAccount(managed_session()), transport=transport).complete(
            {"runId": "run_1", "round": 1, "prompt": "check"},
            lambda _event: None,
            cancel,
        )

        self.assertEqual(result["text"], "Third attempt")
        self.assertEqual(len(transport.requests), 3)
        self.assertEqual(len(cancel.waits), 2)
        self.assertGreaterEqual(cancel.waits[0], 0.25)
        self.assertLessEqual(cancel.waits[0], 0.3125)
        self.assertGreaterEqual(cancel.waits[1], 0.5)
        self.assertLessEqual(cancel.waits[1], 0.625)

    def test_retry_backoff_stops_immediately_when_cancelled(self):
        transport = RepeatingErrorTransport(
            ModelGatewayError("AGENT_MODEL_NETWORK_ERROR", "network down")
        )

        class CancelDuringWait(RecordingCancel):
            def wait(self, timeout=None):
                self.waits.append(timeout)
                self.set()
                return True

        cancel = CancelDuringWait()
        with self.assertRaises(ModelGatewayError) as caught:
            LoomModelClient(FakeAccount(managed_session()), transport=transport).complete(
                {"runId": "run_1", "round": 1, "prompt": "check"},
                lambda _event: None,
                cancel,
            )

        self.assertEqual(caught.exception.code, "AGENT_MODEL_CANCELLED")
        self.assertEqual(len(transport.requests), 1)
        self.assertEqual(len(cancel.waits), 1)

    def test_transport_errors_do_not_retry_after_a_chunk_is_emitted(self):
        transport = ScriptedTransport([[
            {"choices": [{"delta": {"content": "partial"}}]},
            ModelGatewayError("AGENT_MODEL_NETWORK_ERROR", "Bearer sk-stream-secret"),
        ]])
        events = []

        with self.assertRaises(ModelGatewayError) as caught:
            LoomModelClient(FakeAccount(managed_session()), transport=transport).complete(
                {"runId": "run_1", "round": 1, "prompt": "check"},
                events.append,
                threading.Event(),
            )

        self.assertEqual(caught.exception.code, "AGENT_MODEL_NETWORK_ERROR")
        self.assertEqual(len(transport.requests), 1)
        self.assertNotIn("sk-stream-secret", str(caught.exception))
        self.assertNotIn("sk-stream-secret", json.dumps(events))

    def test_redact_text_removes_bearer_and_sk_values(self):
        message = redact_text("request failed: Bearer abc.def sk-native-secret-value token=private-value")

        self.assertNotIn("abc.def", message)
        self.assertNotIn("sk-native-secret-value", message)
        self.assertNotIn("private-value", message)

    def test_redact_text_removes_full_authorization_and_multi_value_cookie_lines(self):
        message = redact_text(
            "request failed\n"
            "Authorization: Basic dXNlcjpwYXNzd29yZA==\n"
            "Cookie: session=raw-session-value; refresh=raw-refresh-value\n"
            "ordinary diagnostic text"
        )

        self.assertNotIn("dXNlcjpwYXNzd29yZA==", message)
        self.assertNotIn("raw-session-value", message)
        self.assertNotIn("raw-refresh-value", message)
        self.assertIn("request failed", message)
        self.assertIn("ordinary diagnostic text", message)

    def test_redact_text_removes_complete_sensitive_header_lines_case_insensitively(self):
        message = redact_text(
            'aUtHoRiZaTiOn: Digest username="raw-user", realm="raw-realm", '
            'nonce="raw-nonce", response="raw-response"\n'
            'pRoXy-AuThOrIzAtIoN: Digest username="raw-proxy-user", '
            'realm="raw-proxy-realm", nonce="raw-proxy-nonce"\n'
            'Authorization: AWS4-HMAC-SHA256 Credential=raw-aws-credential, '
            'SignedHeaders=host;x-amz-date, Signature=raw-aws-signature\n'
            'Proxy-Authorization: Signature keyId="raw-signature-key", '
            'signature="raw-proxy-signature"\n'
            'cOoKiE: session=raw-session; refresh=raw-refresh\n'
            'sEt-CoOkIe: session=raw-set-cookie; Path=/; HttpOnly\n'
            'ordinary following line'
        )

        self.assertEqual(
            message,
            'aUtHoRiZaTiOn: [REDACTED]\n'
            'pRoXy-AuThOrIzAtIoN: [REDACTED]\n'
            'Authorization: [REDACTED]\n'
            'Proxy-Authorization: [REDACTED]\n'
            'cOoKiE: [REDACTED]\n'
            'sEt-CoOkIe: [REDACTED]\n'
            'ordinary following line',
        )
        for fragment in (
            "raw-user",
            "raw-realm",
            "raw-nonce",
            "raw-response",
            "raw-proxy-user",
            "raw-proxy-realm",
            "raw-proxy-nonce",
            "raw-aws-credential",
            "raw-aws-signature",
            "raw-signature-key",
            "raw-proxy-signature",
            "raw-session",
            "raw-refresh",
            "raw-set-cookie",
            "Path=/",
            "HttpOnly",
        ):
            self.assertNotIn(fragment, message)

    def test_redact_text_removes_sensitive_headers_embedded_after_diagnostic_prefixes(self):
        message = redact_text(
            "gateway failed: Authorization: AWS4-HMAC-SHA256 Credential=raw-credential, "
            "SignedHeaders=host;x-amz-date, Signature=raw-signature\n"
            "proxy failed: Proxy-Authorization: Signature keyId=raw-key, signature=raw-proxy-signature\n"
            "cookie failed: Cookie: session=raw-session; refresh=raw-refresh"
        )

        self.assertEqual(
            message,
            "gateway failed: Authorization: [REDACTED]\n"
            "proxy failed: Proxy-Authorization: [REDACTED]\n"
            "cookie failed: Cookie: [REDACTED]",
        )

    def test_redact_text_removes_quoted_and_spaced_secret_values(self):
        message = redact_text(
            'password="raw double secret phrase", ordinaryOne=keep one\n'
            "password='raw single secret phrase'; ordinaryTwo=keep two\n"
            "secret=raw comma secret phrase, ordinaryThree=keep three\n"
            "password=raw semicolon secret phrase; ordinaryFour=keep four\n"
            "secret=raw newline secret phrase\n"
            "ordinary line preserved"
        )

        self.assertEqual(
            message,
            "password=[REDACTED], ordinaryOne=keep one\n"
            "password=[REDACTED]; ordinaryTwo=keep two\n"
            "secret=[REDACTED], ordinaryThree=keep three\n"
            "password=[REDACTED]; ordinaryFour=keep four\n"
            "secret=[REDACTED]\n"
            "ordinary line preserved",
        )

    def test_redact_text_removes_json_like_secret_values_without_corrupting_neighbors(self):
        message = redact_text(
            '{"password":"raw secret","safe":"keep"}\n'
            "{'authorization':'Basic raw-auth','safe':'keep'}\n"
            '{ "password" : "raw \\"quoted\\" secret", "safe" : "keep \\u263a" }\n'
            "{ 'authorization' : 'Basic raw\\'auth', 'safe' : 'keep' }\n"
            'password : raw unquoted secret, safe: keep\n'
            'authorization: Basic raw unquoted auth; safe=keep\n'
            'password: raw final line secret\n'
            'safe line remains'
        )

        self.assertEqual(
            message,
            '{"password":"[REDACTED]","safe":"keep"}\n'
            "{'authorization':'[REDACTED]','safe':'keep'}\n"
            '{ "password" : "[REDACTED]", "safe" : "keep \\u263a" }\n'
            "{ 'authorization' : '[REDACTED]', 'safe' : 'keep' }\n"
            'password : [REDACTED], safe: keep\n'
            'authorization: [REDACTED]\n'
            'password: [REDACTED]\n'
            'safe line remains',
        )

    def test_redact_text_uses_structured_classifier_for_compound_assignment_keys(self):
        message = redact_text(
            '{"secretKey":"json-secret-key","clientSecretKey":"json-client-secret-key",'
            '"secretAccessKey":"json-secret-access-key","apiKeyHeader":"json-api-key",'
            '"accessToken":"json-access-token","passwordValue":"json-password",'
            '"credentials":"json-credentials","authorizationHeader":"json-authorization",'
            '"cookieJar":"json-cookie","maxTokens":100,"prompt_tokens":10,"safe":"json-keep"}\n'
            'secretKey=raw-secret-key, clientSecretKey=raw-client-secret-key, '
            'secretAccessKey=raw-secret-access-key, apiKeyHeader=raw-api-key, '
            'accessToken=raw-access-token, passwordValue=raw-password, '
            'credentials=raw-credentials, authorizationHeader=raw-authorization, '
            'authHeader=raw-auth-header, authCredentials=raw-auth-credentials, '
            'cookieJar=raw-cookie, maxTokens=100, prompt_tokens=10, safe=assignment-keep'
        )

        self.assertEqual(
            message,
            '{"secretKey":"[REDACTED]","clientSecretKey":"[REDACTED]",'
            '"secretAccessKey":"[REDACTED]","apiKeyHeader":"[REDACTED]",'
            '"accessToken":"[REDACTED]","passwordValue":"[REDACTED]",'
            '"credentials":"[REDACTED]","authorizationHeader":"[REDACTED]",'
            '"cookieJar":"[REDACTED]","maxTokens":100,"prompt_tokens":10,"safe":"json-keep"}\n'
            'secretKey=[REDACTED], clientSecretKey=[REDACTED], '
            'secretAccessKey=[REDACTED], apiKeyHeader=[REDACTED], '
            'accessToken=[REDACTED], passwordValue=[REDACTED], '
            'credentials=[REDACTED], authorizationHeader=[REDACTED], '
            'authHeader=[REDACTED], authCredentials=[REDACTED], '
            'cookieJar=[REDACTED], maxTokens=100, prompt_tokens=10, safe=assignment-keep',
        )

    def test_redact_sensitive_recognizes_all_compound_credential_markers(self):
        safe = redact_sensitive({
            "token": "raw-token",
            "accessToken": "raw-access-token",
            "refreshToken": "raw-refresh-token",
            "apiKeyHeader": "raw-api-key-header",
            "idToken": "raw-id-token",
            "authToken": "raw-auth-token",
            "tokenValue": "raw-token-value",
            "tokenHeader": "raw-token-header",
            "passwordValue": "raw-password-value",
            "credentials": {"username": "raw-user", "password": "raw-password"},
            "authorizationHeader": "Basic raw-authorization-value",
            "authHeader": "Basic raw-auth-header-value",
            "authCredentials": "raw-auth-credentials-value",
            "X-API-Key": "raw-prefixed-api-key",
            "vendorApiKeyHeader": "raw-vendor-api-key",
            "vendorAccessToken": "raw-vendor-access-token",
            "clientTokenValue": "raw-client-token-value",
            "AWSAccessKeyId": "raw-aws-access-key",
            "requestSignature": "raw-request-signature",
            "bearerCredential": "raw-bearer-credential",
            "cookieJar": ["session=raw-cookie-value", "refresh=raw-refresh-value"],
            "clientSecret": "raw-client-secret",
            "refreshTokens": ["raw-refresh-token"],
            "secretValues": ["raw-secret-value"],
            "maxTokens": 100,
            "tokenBudget": 25,
            "prompt_tokens": 10,
            "prompt_tokens_details": {"cached_tokens": 4, "audio_tokens": 2},
            "completion_tokens": 6,
            "completion_tokens_details": {"reasoning_tokens": 3},
            "ordinaryText": "keep this text",
        })

        self.assertEqual(safe["token"], "[REDACTED]")
        self.assertEqual(safe["accessToken"], "[REDACTED]")
        self.assertEqual(safe["refreshToken"], "[REDACTED]")
        self.assertEqual(safe["apiKeyHeader"], "[REDACTED]")
        self.assertEqual(safe["idToken"], "[REDACTED]")
        self.assertEqual(safe["authToken"], "[REDACTED]")
        self.assertEqual(safe["tokenValue"], "[REDACTED]")
        self.assertEqual(safe["tokenHeader"], "[REDACTED]")
        self.assertEqual(safe["passwordValue"], "[REDACTED]")
        self.assertEqual(safe["credentials"], "[REDACTED]")
        self.assertEqual(safe["authorizationHeader"], "[REDACTED]")
        self.assertEqual(safe["authHeader"], "[REDACTED]")
        self.assertEqual(safe["authCredentials"], "[REDACTED]")
        self.assertEqual(safe["X-API-Key"], "[REDACTED]")
        self.assertEqual(safe["vendorApiKeyHeader"], "[REDACTED]")
        self.assertEqual(safe["vendorAccessToken"], "[REDACTED]")
        self.assertEqual(safe["clientTokenValue"], "[REDACTED]")
        self.assertEqual(safe["AWSAccessKeyId"], "[REDACTED]")
        self.assertEqual(safe["requestSignature"], "[REDACTED]")
        self.assertEqual(safe["bearerCredential"], "[REDACTED]")
        self.assertEqual(safe["cookieJar"], "[REDACTED]")
        self.assertEqual(safe["clientSecret"], "[REDACTED]")
        self.assertEqual(safe["refreshTokens"], "[REDACTED]")
        self.assertEqual(safe["secretValues"], "[REDACTED]")
        self.assertEqual(safe["maxTokens"], 100)
        self.assertEqual(safe["tokenBudget"], 25)
        self.assertEqual(safe["prompt_tokens"], 10)
        self.assertEqual(safe["prompt_tokens_details"], {"cached_tokens": 4, "audio_tokens": 2})
        self.assertEqual(safe["completion_tokens"], 6)
        self.assertEqual(safe["completion_tokens_details"], {"reasoning_tokens": 3})
        self.assertEqual(safe["ordinaryText"], "keep this text")

    def test_redact_text_classifies_prefixed_credential_assignments_but_preserves_usage_metrics(self):
        message = redact_text(
            "X-API-Key=raw-x-api-key, vendorApiKeyHeader=raw-vendor-api-key, "
            "vendorAccessToken=raw-vendor-token, maxTokens=100, prompt_tokens=10, "
            "completion_tokens=5, tokenBudget=200"
        )

        self.assertEqual(
            message,
            "X-API-Key=[REDACTED], vendorApiKeyHeader=[REDACTED], "
            "vendorAccessToken=[REDACTED], maxTokens=100, prompt_tokens=10, "
            "completion_tokens=5, tokenBudget=200",
        )

    def test_redact_sensitive_redacts_any_secret_compound_key_and_preserves_usage_fields(self):
        safe = redact_sensitive({
            "secretKey": "raw-secret-key",
            "clientSecretKey": "raw-client-secret-key",
            "secretAccessKey": "raw-secret-access-key",
            "secretValue": "raw-secret-value",
            "maxTokens": 100,
            "tokenBudget": 25,
            "prompt_tokens": 10,
            "prompt_tokens_details": {"cached_tokens": 4},
            "completion_tokens": 6,
        })

        self.assertEqual(safe["secretKey"], "[REDACTED]")
        self.assertEqual(safe["clientSecretKey"], "[REDACTED]")
        self.assertEqual(safe["secretAccessKey"], "[REDACTED]")
        self.assertEqual(safe["secretValue"], "[REDACTED]")
        self.assertEqual(safe["maxTokens"], 100)
        self.assertEqual(safe["tokenBudget"], 25)
        self.assertEqual(safe["prompt_tokens"], 10)
        self.assertEqual(safe["prompt_tokens_details"], {"cached_tokens": 4})
        self.assertEqual(safe["completion_tokens"], 6)

    def test_transport_bounds_newline_less_response_during_read(self):
        response = DeterministicResponse(b"x" * (MAX_RESPONSE_BYTES + 4096))
        transport = UrlLibSseTransport(opener=lambda _request, *, timeout: response)

        with self.assertRaises(ModelGatewayError) as caught:
            list(transport.stream(
                transport_profile(),
                {"model": "account-selected-model", "stream": True},
                threading.Event(),
                timeout_sec=120.0,
            ))

        self.assertEqual(caught.exception.code, "AGENT_MODEL_OUTPUT_TOO_LARGE")
        self.assertEqual(response.readline_limits, [MAX_RESPONSE_BYTES + 1])

    def test_transport_conversion_suppresses_credential_bearing_exception_chains(self):
        raw_fragments = (
            "raw-bearer-chain",
            "sk-chain-secret-value",
            "raw-cookie-chain",
            "raw-cookie-refresh",
        )
        raw_message = (
            "Bearer raw-bearer-chain sk-chain-secret-value "
            "Cookie: session=raw-cookie-chain; refresh=raw-cookie-refresh"
        )

        cases = {
            "url": lambda: list(UrlLibSseTransport(
                opener=RecordingOpener(error=urllib.error.URLError(raw_message))
            ).stream(transport_profile(), {"stream": True}, threading.Event(), timeout_sec=120.0)),
            "http": lambda: list(UrlLibSseTransport(
                opener=RecordingOpener(error=urllib.error.HTTPError(
                    "https://gateway.example/v1/chat/completions",
                    502,
                    raw_message,
                    {},
                    None,
                ))
            ).stream(transport_profile(), {"stream": True}, threading.Event(), timeout_sec=120.0)),
            "timeout": lambda: list(UrlLibSseTransport(
                opener=RecordingOpener(DeterministicResponse(read_error=socket.timeout(raw_message)))
            ).stream(transport_profile(), {"stream": True}, threading.Event(), timeout_sec=120.0)),
            "protocol": lambda: list(UrlLibSseTransport(
                opener=RecordingOpener(DeterministicResponse(
                    b'data: {"secret":"Bearer raw-bearer-chain sk-chain-secret-value '
                    b'Cookie: session=raw-cookie-chain; refresh=raw-cookie-refresh"\n'
                ))
            ).stream(transport_profile(), {"stream": True}, threading.Event(), timeout_sec=120.0)),
        }

        for name, invoke in cases.items():
            with self.subTest(name=name):
                with self.assertRaises(ModelGatewayError) as caught:
                    invoke()
                formatted = "".join(traceback.format_exception(caught.exception))
                for fragment in raw_fragments:
                    self.assertNotIn(fragment, formatted)
                self.assertIsNone(caught.exception.__cause__)
                self.assertTrue(caught.exception.__suppress_context__)

    def test_complete_caps_large_timeout_and_preserves_lower_positive_timeout(self):
        for requested, expected in ((300.0, 120.0), (30.0, 30.0)):
            with self.subTest(requested=requested):
                transport = FakeTransport([{"choices": [{"delta": {"content": "ok"}}]}])

                LoomModelClient(FakeAccount(managed_session()), transport=transport).complete(
                    {"runId": "run_1", "round": 1, "prompt": "check"},
                    lambda _event: None,
                    threading.Event(),
                    timeout_sec=requested,
                )

                self.assertEqual(transport.requests[0][2], expected)

    def test_complete_rejects_non_finite_boolean_and_non_positive_timeouts(self):
        invalid_values = (
            ("nan", float("nan")),
            ("positive_infinity", float("inf")),
            ("negative_infinity", float("-inf")),
            ("true", True),
            ("false", False),
            ("zero", 0),
            ("negative", -1.0),
        )
        for label, invalid in invalid_values:
            with self.subTest(value=label):
                transport = FakeTransport([{"choices": [{"delta": {"content": "must not run"}}]}])

                with self.assertRaises(ModelGatewayError) as caught:
                    LoomModelClient(FakeAccount(managed_session()), transport=transport).complete(
                        {"runId": "run_1", "round": 1, "prompt": "check"},
                        lambda _event: None,
                        threading.Event(),
                        timeout_sec=invalid,
                    )

                self.assertEqual(caught.exception.code, "AGENT_MODEL_TIMEOUT")
                self.assertEqual(transport.requests, [])

    def test_non_retryable_output_and_protocol_errors_attempt_transport_once(self):
        for code in ("AGENT_MODEL_OUTPUT_TOO_LARGE", "AGENT_MODEL_PROTOCOL_INVALID"):
            with self.subTest(code=code):
                transport = RepeatingErrorTransport(ModelGatewayError(code, "invalid model output"))

                with self.assertRaises(ModelGatewayError) as caught:
                    LoomModelClient(FakeAccount(managed_session()), transport=transport).complete(
                        {"runId": "run_1", "round": 1, "prompt": "check"},
                        lambda _event: None,
                        threading.Event(),
                    )

                self.assertEqual(caught.exception.code, code)
                self.assertEqual(len(transport.requests), 1)

    def test_transport_assigns_45_second_socket_response_timeout(self):
        sock = RecordingSocket()
        response = DeterministicResponse(b"data: [DONE]\n")
        response.fp = SimpleNamespace(raw=SimpleNamespace(_sock=sock))

        list(UrlLibSseTransport(opener=RecordingOpener(response)).stream(
            transport_profile(),
            {"stream": True},
            threading.Event(),
            timeout_sec=120.0,
        ))

        self.assertGreaterEqual(len(sock.timeouts), 1)
        self.assertTrue(all(timeout == 45.0 for timeout in sock.timeouts))

    def test_transport_parses_sse_done_and_builds_authorized_request(self):
        response = DeterministicResponse(
            b": keepalive\n"
            b"\n"
            b'data: {"choices":[{"delta":{"content":"hello"}}]}\n'
            b"\n"
            b"data: [DONE]\n"
            b'data: {"ignored":true}\n'
        )
        opener = RecordingOpener(response)
        payload = {"model": "account-selected-model", "stream": True}

        chunks = list(UrlLibSseTransport(opener=opener).stream(
            transport_profile(),
            payload,
            threading.Event(),
            timeout_sec=120.0,
        ))

        self.assertEqual(chunks, [{"choices": [{"delta": {"content": "hello"}}]}])
        self.assertNotIn("sk-transport-secret-value", json.dumps(chunks))
        self.assertEqual(len(opener.calls), 1)
        call = opener.calls[0]
        self.assertEqual(call["timeout"], 10.0)
        self.assertEqual(call["request"].full_url, "https://gateway.example/v1/chat/completions")
        self.assertEqual(call["request"].get_header("Authorization"), "Bearer sk-transport-secret-value")
        self.assertEqual(json.loads(call["request"].data), payload)
        self.assertTrue(response.closed)

    def test_transport_cancellation_before_read_does_not_open_request(self):
        opener = RecordingOpener(DeterministicResponse(b"data: [DONE]\n"))
        cancel = threading.Event()
        cancel.set()

        with self.assertRaises(ModelGatewayError) as caught:
            list(UrlLibSseTransport(opener=opener).stream(
                transport_profile(),
                {"stream": True},
                cancel,
                timeout_sec=120.0,
            ))

        self.assertEqual(caught.exception.code, "AGENT_MODEL_CANCELLED")
        self.assertEqual(opener.calls, [])

    def test_transport_cancellation_during_read_stops_before_yielding_chunk(self):
        cancel = threading.Event()
        response = DeterministicResponse(
            b'data: {"choices":[{"delta":{"content":"late"}}]}\n',
            on_read=cancel.set,
        )
        stream = UrlLibSseTransport(opener=RecordingOpener(response)).stream(
            transport_profile(),
            {"stream": True},
            cancel,
            timeout_sec=120.0,
        )

        with self.assertRaises(ModelGatewayError) as caught:
            next(stream)

        self.assertEqual(caught.exception.code, "AGENT_MODEL_CANCELLED")
        self.assertEqual(len(response.readline_limits), 1)

    def test_transport_rejects_malformed_sse_json_without_echoing_body(self):
        response = DeterministicResponse(b"data: {raw-secret-json}\n")

        with self.assertRaises(ModelGatewayError) as caught:
            list(UrlLibSseTransport(opener=RecordingOpener(response)).stream(
                transport_profile(),
                {"stream": True},
                threading.Event(),
                timeout_sec=120.0,
            ))

        self.assertEqual(caught.exception.code, "AGENT_MODEL_PROTOCOL_INVALID")
        self.assertNotIn("raw-secret-json", str(caught.exception))

    def test_transport_converts_http_error_without_exposing_reason_credentials(self):
        error = urllib.error.HTTPError(
            "https://gateway.example/v1/chat/completions",
            401,
            "Authorization: Basic raw-http-auth\nCookie: session=raw-http-cookie; refresh=raw-http-refresh",
            {},
            None,
        )

        with self.assertRaises(ModelGatewayError) as caught:
            list(UrlLibSseTransport(opener=RecordingOpener(error=error)).stream(
                transport_profile(),
                {"stream": True},
                threading.Event(),
                timeout_sec=120.0,
            ))

        self.assertEqual(caught.exception.code, "AGENT_MODEL_HTTP_ERROR")
        self.assertEqual(caught.exception.status_code, 401)
        self.assertNotIn("raw-http-auth", str(caught.exception))
        self.assertNotIn("raw-http-cookie", str(caught.exception))
        self.assertNotIn("raw-http-refresh", str(caught.exception))

    def test_transport_converts_network_error_without_exposing_reason_credentials(self):
        error = urllib.error.URLError("credentials=raw-network-credential")

        with self.assertRaises(ModelGatewayError) as caught:
            list(UrlLibSseTransport(opener=RecordingOpener(error=error)).stream(
                transport_profile(),
                {"stream": True},
                threading.Event(),
                timeout_sec=120.0,
            ))

        self.assertEqual(caught.exception.code, "AGENT_MODEL_NETWORK_ERROR")
        self.assertNotIn("raw-network-credential", str(caught.exception))

    def test_transport_converts_read_timeout_without_exposing_error_text(self):
        response = DeterministicResponse(
            read_error=socket.timeout("AuthorizationHeader=Basic raw-timeout-credential")
        )

        with self.assertRaises(ModelGatewayError) as caught:
            list(UrlLibSseTransport(opener=RecordingOpener(response)).stream(
                transport_profile(),
                {"stream": True},
                threading.Event(),
                timeout_sec=120.0,
            ))

        self.assertEqual(caught.exception.code, "AGENT_MODEL_TIMEOUT")
        self.assertNotIn("raw-timeout-credential", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
