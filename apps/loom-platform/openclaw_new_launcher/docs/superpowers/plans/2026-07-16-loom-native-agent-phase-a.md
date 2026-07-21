# LOOM Native Agent Phase A Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the central Agent's Codex/Claude dependency with a LOOM-managed cloud model client, preserve the existing Agent tool loop and APIs, and remove the runtime selector from the central Agent UI.

**Architecture:** Add a focused `LoomModelClient` that resolves the existing managed account session and normalizes OpenAI-compatible SSE into text, tool calls, usage, and stable errors. Wrap it in `LoomNativeRuntimeAdapter`, which continues to satisfy the existing `AgentRuntimeAdapter` protocol so `AgentOrchestrator`, persisted checkpoints, capabilities, Matrix attachments, and `/api/agent/*` remain intact. Wire the shared `NewApiAccountManager` into `AgentService`, normalize compatibility fields to `loom-native`, and keep `LoomCliRuntimeAdapter` available only for developer extensions.

**Tech Stack:** Python 3.11 standard library (`urllib`, `json`, `threading`, `dataclasses`), existing FastAPI Bridge and Agent services, React 18, TypeScript 5.5, Zustand, Node test runner, `unittest`.

## Global Constraints

- Users must not install Codex, Claude Code, or another external Agent to use the LOOM central Agent.
- Users must not enter a model API key; model credentials come from the current LOOM account session.
- Keep existing `/api/agent/*` URLs, SSE replay semantics, session schemas, tool policy checks, checkpoints, and Matrix control-plane integration compatible.
- The native runtime profile ID is exactly `loom-native`; compatibility fields may remain for one release but cannot select an external runtime.
- Backend events, errors, traces, and frontend state must never expose access tokens, cookies, authorization headers, or raw credentials.
- Use the current account-selected text model; do not hard-code a model vendor in the native Agent.
- Model connect timeout is 10 seconds, first-response timeout is 45 seconds, total round timeout is 120 seconds, with at most two retries before any tool side effect.
- `LoomCliRuntimeAdapter` remains developer-only and is not auto-discovered or presented in the central Agent UI.
- All new behavior is test-driven and each task ends in an independently passing commit.

---

## File Map

| File | Responsibility |
|---|---|
| `python/core/loom_model_client.py` | Managed account profile resolution, OpenAI-compatible request construction, SSE parsing, retry, cancellation, normalized model errors, secret redaction |
| `python/core/native_agent_runtime.py` | `AgentRuntimeAdapter` implementation, native runtime status, stable streamed message ID, model event translation, final/tool-call result contract |
| `python/core/agent_orchestrator.py` | Reuse a runtime-supplied stable message ID when persisting the final assistant message |
| `python/services/agent_service.py` | Default native runtime construction, one native bootstrap profile, compatibility normalization |
| `python/bridge.py` | Inject the process-wide `NewApiAccountManager` into `AgentService` |
| `src/types/agent.ts` | Allow a runtime profile to expose a safe structured error |
| `src/components/agent/AgentComposer.tsx` | Remove runtime selector while preserving devices, groups, capability hints, attachments, and send behavior |
| `src/components/agent/AgentHeader.tsx` | Show LOOM native Agent identity and readiness instead of external runtime selection |
| `src/components/agent/AgentWorkbenchPage.tsx` | Validate native account/runtime readiness and stop asking the user to install a runtime |
| `python/tests/test_loom_model_client.py` | Model profile, request, SSE, tool call, retry, cancellation, and redaction unit tests |
| `python/tests/test_native_agent_runtime.py` | Runtime adapter event/result and stable message ID unit tests |
| `python/tests/test_agent_service.py` | Bootstrap, session normalization, and no-discovery service tests |
| `python/tests/test_agent_orchestrator.py` | Streaming and final-message identity regression test |
| `python/tests/test_native_agent_integration.py` | End-to-end service run with a fake gateway and a real capability loop |
| `python/tests/test_native_agent_ui_contract.py` | Source contract preventing runtime selector and install-runtime copy from returning |

---

### Task 1: Managed Model Client

**Files:**
- Create: `python/core/loom_model_client.py`
- Create: `python/tests/test_loom_model_client.py`

**Interfaces:**
- Consumes: an account manager implementing `current() -> dict | None` and `ensure_launcher_token(sync_runtime=False) -> dict`.
- Produces: `LoomModelClient.status() -> dict`, `LoomModelClient.complete(request, emit, cancel, timeout_sec=None) -> dict`, `LoomModelProfile`, `ModelGatewayError`, and injectable `ModelGatewayTransport.stream(...)`.
- Result contract: `{"text": str, "toolCalls": list[dict], "usage": dict, "model": str}`.

- [ ] **Step 1: Write failing profile and redaction tests**

```python
class FakeAccount:
    def __init__(self, session=None):
        self.session = session
        self.ensure_calls = 0

    def current(self):
        return self.session

    def ensure_launcher_token(self, *, sync_runtime=False):
        self.ensure_calls += 1
        if not self.session:
            raise RuntimeError("not_logged_in")
        return self.session


def managed_session():
    return {
        "source": "newapi_account",
        "gatewayBaseUrl": "https://gateway.example/v1",
        "memberToken": "sk-native-secret-value",
        "gatewayDefaultModel": "glm-managed",
        "gateway": {
            "baseUrl": "https://gateway.example/v1",
            "accessToken": "sk-native-secret-value",
            "defaultModel": "glm-managed",
        },
    }


class LoomModelClientTests(unittest.TestCase):
    def test_status_requires_login_without_exposing_secret(self):
        client = LoomModelClient(FakeAccount())
        status = client.status()
        self.assertFalse(status["available"])
        self.assertEqual(status["error"]["code"], "AGENT_ACCOUNT_LOGIN_REQUIRED")

    def test_status_reports_selected_managed_model_only(self):
        client = LoomModelClient(FakeAccount(managed_session()))
        status = client.status()
        self.assertTrue(status["available"])
        self.assertEqual(status["profileId"], "loom-native")
        self.assertEqual(status["model"], "glm-managed")
        self.assertNotIn("sk-native-secret-value", json.dumps(status))
```

- [ ] **Step 2: Run the profile tests and verify failure**

Run: `python -m unittest discover -s python/tests -p "test_loom_model_client.py" -v`

Expected: FAIL because `core.loom_model_client` does not exist.

- [ ] **Step 3: Implement the profile and transport contracts**

```python
@dataclass(frozen=True)
class LoomModelProfile:
    base_url: str
    access_token: str
    model: str


class ModelAccountManager(Protocol):
    def current(self) -> dict[str, Any] | None: ...
    def ensure_launcher_token(self, *, sync_runtime: bool = True) -> dict[str, Any]: ...


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


def profile_from_session(session: Mapping[str, Any] | None) -> LoomModelProfile:
    if not isinstance(session, Mapping):
        raise ModelGatewayError("AGENT_ACCOUNT_LOGIN_REQUIRED", "请先登录麓鸣模型账号。")
    gateway = session.get("gateway") if isinstance(session.get("gateway"), Mapping) else {}
    profile = LoomModelProfile(
        base_url=str(session.get("gatewayBaseUrl") or gateway.get("baseUrl") or "").rstrip("/"),
        access_token=str(session.get("memberToken") or gateway.get("accessToken") or ""),
        model=str(session.get("gatewayDefaultModel") or gateway.get("defaultModel") or ""),
    )
    if not profile.base_url or not profile.access_token or not profile.model:
        raise ModelGatewayError("AGENT_MODEL_CONFIG_INVALID", "麓鸣模型账号尚未同步完整的网关配置。")
    return profile
```

Implement `UrlLibSseTransport.stream` with `urllib.request.Request`, `Authorization: Bearer ...`, JSON body, `Content-Type: application/json`, line-by-line `data:` parsing, `[DONE]` termination, a 2 MB response cap, cancellation checks between reads, and conversion of `HTTPError`, `URLError`, timeout, malformed JSON, and oversized output to `ModelGatewayError` without including response credentials.

- [ ] **Step 4: Add failing request, SSE, tool-call, cancellation, and retry tests**

```python
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


def test_complete_aggregates_text_tool_calls_usage_and_emits_deltas(self):
    transport = FakeTransport([
        {"choices": [{"delta": {"content": "正在"}}]},
        {"choices": [{"delta": {"content": "检查"}}]},
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call_1", "function": {"name": "loom.matrix.status", "arguments": "{\"campaignId\":\"c1\"}"}}]}}]},
        {"usage": {"prompt_tokens": 10, "completion_tokens": 3}},
    ])
    events = []
    result = LoomModelClient(FakeAccount(managed_session()), transport=transport).complete(
        {"runId": "run_1", "round": 1, "prompt": "检查矩阵", "capabilities": [{"name": "loom.matrix.status", "description": "读取矩阵", "inputSchema": {"type": "object"}}]},
        events.append,
        threading.Event(),
    )
    self.assertEqual(result["text"], "正在检查")
    self.assertEqual(result["toolCalls"], [{"toolCallId": "call_1", "name": "loom.matrix.status", "input": {"campaignId": "c1"}}])
    self.assertEqual(result["usage"]["prompt_tokens"], 10)
    self.assertEqual([event["type"] for event in events[:2]], ["model.text.delta", "model.text.delta"])
    payload = transport.requests[0][1]
    self.assertEqual(payload["model"], "glm-managed")
    self.assertEqual(payload["tool_choice"], "auto")
    self.assertNotIn("sk-native-secret-value", json.dumps(payload))
```

Add tests asserting: pre-cancel raises `AGENT_MODEL_CANCELLED`; invalid tool arguments raise `AGENT_MODEL_PROTOCOL_INVALID`; 401/403 triggers one `ensure_launcher_token(sync_runtime=False)` refresh; transient transport errors retry at most twice only before the first emitted chunk; every error string redacts `Bearer` and `sk-` values.

- [ ] **Step 5: Implement request construction and normalized aggregation**

`LoomModelClient.complete` must:

```python
def complete(self, request, emit, cancel, *, timeout_sec=None):
    if cancel.is_set():
        raise ModelGatewayError("AGENT_MODEL_CANCELLED", "模型调用已取消。")
    profile = profile_from_session(self.account.ensure_launcher_token(sync_runtime=False))
    payload = build_chat_payload(profile, request)
    aggregate = ChatAggregate()
    for chunk in self._stream_with_retry(profile, payload, cancel, timeout_sec or 120.0):
        for event in aggregate.consume(chunk):
            emit(redact_sensitive(event))
    return aggregate.result(profile.model)
```

`build_chat_payload` must include the fixed LOOM system contract, sanitized history, current prompt, summarized `toolResults`, OpenAI tool schemas derived only from listed capabilities, `stream: true`, `temperature: 0.2`, and `metadata.idempotencyKey = f"{runId}:{round}"`. `ChatAggregate.result` must reject missing tool IDs/names, non-object arguments, malformed JSON, and an empty response with no text and no tool calls.

- [ ] **Step 6: Run the model-client tests**

Run: `python -m unittest discover -s python/tests -p "test_loom_model_client.py" -v`

Expected: all model-client tests PASS.

- [ ] **Step 7: Commit the model client**

```bash
git add python/core/loom_model_client.py python/tests/test_loom_model_client.py
git commit -m "feat: add LOOM managed model client"
```

---

### Task 2: Native Runtime Adapter and Stable Streaming Message

**Files:**
- Create: `python/core/native_agent_runtime.py`
- Create: `python/tests/test_native_agent_runtime.py`
- Modify: `python/core/agent_orchestrator.py`
- Modify: `python/tests/test_agent_orchestrator.py`

**Interfaces:**
- Consumes: `LoomModelClient.status()` and `LoomModelClient.complete(...)` from Task 1.
- Produces: `LoomNativeRuntimeAdapter.status(profile_id=None)` and `start(request, emit, cancel, timeout_sec=None)` satisfying `AgentRuntimeAdapter`.
- Stable message ID: `message_{runId}` for streamed and persisted final output.

- [ ] **Step 1: Write failing native runtime tests**

```python
class FakeModelClient:
    def status(self):
        return {"available": True, "model": "glm-managed"}

    def complete(self, request, emit, cancel, *, timeout_sec=None):
        emit({"type": "model.text.delta", "data": {"delta": "你好"}})
        emit({"type": "model.usage", "data": {"promptTokens": 4, "completionTokens": 2}})
        return {"text": "你好", "toolCalls": [], "usage": {"promptTokens": 4}, "model": "glm-managed"}


def test_native_runtime_translates_stream_and_returns_stable_message_id(self):
    events = []
    result = LoomNativeRuntimeAdapter(FakeModelClient()).start(
        {"sessionId": "session_1", "runId": "run_1", "prompt": "你好"},
        events.append,
        threading.Event(),
    )
    self.assertEqual(events[0], {"type": "message.delta", "data": {"messageId": "message_run_1", "role": "assistant", "delta": "你好"}})
    self.assertEqual(result["messageId"], "message_run_1")
    self.assertEqual(result["final"], {"text": "你好"})
```

Add tests for tool-call results (`final` absent while `toolCalls` is non-empty), status profile normalization to `loom-native`, pre-cancellation, and conversion of `ModelGatewayError` to `RuntimeExecutionError` with the same safe code and recoverability.

- [ ] **Step 2: Run native runtime tests and verify failure**

Run: `python -m unittest discover -s python/tests -p "test_native_agent_runtime.py" -v`

Expected: FAIL because `core.native_agent_runtime` does not exist.

- [ ] **Step 3: Implement `LoomNativeRuntimeAdapter`**

```python
class LoomNativeRuntimeAdapter:
    profile_id = "loom-native"

    def __init__(self, client: LoomModelClient):
        self.client = client

    def status(self, profile_id=None):
        status = self.client.status()
        return {
            **redact_sensitive(status),
            "profileId": self.profile_id,
            "runtime": "麓鸣原生智能体",
        }

    def start(self, request, emit, cancel, *, timeout_sec=None):
        run_id = str(request.get("runId") or "unknown")
        message_id = f"message_{run_id}"

        def relay(event):
            if event.get("type") == "model.text.delta":
                data = event.get("data") if isinstance(event.get("data"), Mapping) else {}
                emit({"type": "message.delta", "data": {"messageId": message_id, "role": "assistant", "delta": str(data.get("delta") or "")}})
            else:
                emit(redact_sensitive(event))

        try:
            response = self.client.complete(request, relay, cancel, timeout_sec=timeout_sec)
        except ModelGatewayError as error:
            raise RuntimeExecutionError(error.code, str(error), recoverable=error.recoverable) from error
        tool_calls = response.get("toolCalls") if isinstance(response.get("toolCalls"), list) else []
        result = {"messageId": message_id, "toolCalls": tool_calls, "model": response.get("model"), "usage": response.get("usage", {})}
        if not tool_calls:
            result["final"] = {"text": str(response.get("text") or "")}
        return redact_sensitive(result)
```

- [ ] **Step 4: Write a failing orchestrator identity regression test**

Add a runtime returning `{"messageId": "message_run-fixed", "final": {"text": "streamed final"}}`, execute a run, and assert that the repository's final assistant message and `message.completed.data.message.messageId` both equal `message_run-fixed`.

- [ ] **Step 5: Make final persistence reuse the runtime message ID**

Change the orchestrator signatures exactly to:

```python
message_id = str(result.get("messageId") or "").strip() or None
message = self._append_assistant_message(session_id, safe_final, message_id=message_id)

def _append_assistant_message(self, session_id: str, final: Any, *, message_id: str | None = None) -> Json | None:
    # Existing block construction remains unchanged.
    message = {
        "schema": "loom.agent.message.v1",
        "messageId": message_id or f"message_{uuid.uuid4().hex}",
        "sessionId": session_id,
        "role": "assistant",
        "status": "completed",
        "blocks": redact_sensitive(blocks),
        "createdAt": now,
        "completedAt": now,
    }
```

- [ ] **Step 6: Run runtime and orchestrator tests**

Run: `python -m unittest discover -s python/tests -p "test_native_agent_runtime.py" -v`

Run: `python -m unittest discover -s python/tests -p "test_agent_orchestrator.py" -v`

Expected: both suites PASS.

- [ ] **Step 7: Commit the native adapter**

```bash
git add python/core/native_agent_runtime.py python/core/agent_orchestrator.py python/tests/test_native_agent_runtime.py python/tests/test_agent_orchestrator.py
git commit -m "feat: add LOOM native agent runtime"
```

---

### Task 3: Agent Service and Bridge Wiring

**Files:**
- Modify: `python/services/agent_service.py`
- Modify: `python/bridge.py`
- Modify: `python/tests/test_agent_service.py`

**Interfaces:**
- Consumes: `LoomNativeRuntimeAdapter` and shared `NewApiAccountManager`.
- Produces: exactly one central Agent runtime profile, `loom-native`, while preserving injected test runtimes.

- [ ] **Step 1: Replace external-discovery expectations with failing native bootstrap tests**

```python
def test_default_bootstrap_exposes_only_loom_native_profile(self):
    account = FakeAccount(managed_session())
    with tempfile.TemporaryDirectory() as root:
        with patch("services.agent_service.shutil.which") as discover:
            service = AgentService(AppPaths(root), account_manager=account, capabilities=_registry())
            try:
                bootstrap = service.bootstrap()
            finally:
                service.shutdown()
    discover.assert_not_called()
    self.assertEqual(bootstrap["defaultRuntimeProfileId"], "loom-native")
    self.assertEqual(bootstrap["runtimeProfiles"], [{
        "runtimeProfileId": "loom-native",
        "name": "麓鸣原生智能体",
        "available": True,
        "isDefault": True,
    }])
```

Add tests asserting `create_session({"runtimeProfileId": "codex"})` stores `loom-native`, `send_message(..., {"runtimeProfileId": "claude"})` persists `loom-native`, and logged-out bootstrap returns one native profile with a safe `AGENT_ACCOUNT_LOGIN_REQUIRED` error.

- [ ] **Step 2: Run service tests and verify the new tests fail**

Run: `python -m unittest discover -s python/tests -p "test_agent_service.py" -v`

Expected: the native bootstrap tests FAIL because the service still discovers Codex and Claude.

- [ ] **Step 3: Wire the native runtime into `AgentService`**

Change the constructor to accept `account_manager: Any | None = None` and `model_client: LoomModelClient | None = None`. When `runtime` is absent, construct:

```python
self.account_manager = account_manager or NewApiAccountManager(paths, lambda _text: None)
self.model_client = model_client or LoomModelClient(self.account_manager)
self.runtime = LoomNativeRuntimeAdapter(self.model_client)
```

When an explicit runtime is injected, use it unchanged but still expose the compatibility profile ID `loom-native`. Replace `_runtime_profile_ids()` use in `bootstrap()` with one status call and one profile. Normalize session creation, outgoing requests, resume fallback, and prompt snapshots with:

```python
NATIVE_RUNTIME_PROFILE_ID = "loom-native"

def _native_runtime_profile_id(_value: Any = None) -> str:
    return NATIVE_RUNTIME_PROFILE_ID
```

Do not delete the legacy CLI adapter class from `core/agent_runtime.py`; remove only central service auto-discovery and default construction.

- [ ] **Step 4: Inject the shared account manager from Bridge**

```python
_agent_service = AgentService(
    paths,
    account_manager=_get_newapi_account_mgr(),
    context_factory=_build_fastapi_context,
    job_manager=_get_job_mgr(),
)
```

This prevents duplicate account refresh state and ensures login/logout is immediately visible to the Agent.

- [ ] **Step 5: Run service and route regression tests**

Run: `python -m unittest discover -s python/tests -p "test_agent_service.py" -v`

Run: `python -m unittest discover -s python/tests -p "test_agent_routes.py" -v`

Expected: both suites PASS; `/api/agent/bootstrap` still returns HTTP 200 through the existing route.

- [ ] **Step 6: Commit service wiring**

```bash
git add python/services/agent_service.py python/bridge.py python/tests/test_agent_service.py
git commit -m "feat: make native runtime the central agent default"
```

---

### Task 4: Native Agent UI

**Files:**
- Modify: `src/types/agent.ts`
- Modify: `src/components/agent/AgentComposer.tsx`
- Modify: `src/components/agent/AgentHeader.tsx`
- Modify: `src/components/agent/AgentWorkbenchPage.tsx`
- Create: `python/tests/test_native_agent_ui_contract.py`

**Interfaces:**
- Consumes: one `loom-native` bootstrap profile and optional safe profile error.
- Produces: central Agent UI with no runtime selector and a clear login/model-readiness failure.

- [ ] **Step 1: Write the failing static UI contract**

```python
class NativeAgentUiContractTests(unittest.TestCase):
    def test_composer_has_no_external_runtime_selector(self):
        source = (ROOT / "src/components/agent/AgentComposer.tsx").read_text(encoding="utf-8")
        self.assertNotIn("选择运行时", source)
        self.assertNotIn(">运行时<", source)
        self.assertNotIn("bootstrap?.runtimeProfiles || []", source)

    def test_workbench_does_not_request_installed_runtime(self):
        source = (ROOT / "src/components/agent/AgentWorkbenchPage.tsx").read_text(encoding="utf-8")
        self.assertNotIn("请选择已安装且可用的运行时", source)
        self.assertIn("麓鸣原生智能体尚未就绪", source)

    def test_header_identifies_native_agent(self):
        source = (ROOT / "src/components/agent/AgentHeader.tsx").read_text(encoding="utf-8")
        self.assertIn("麓鸣原生智能体", source)
        self.assertNotIn("未选择运行时", source)
```

- [ ] **Step 2: Run the UI contract and verify failure**

Run: `python -m unittest discover -s python/tests -p "test_native_agent_ui_contract.py" -v`

Expected: FAIL on the current runtime selector and install-runtime copy.

- [ ] **Step 3: Remove runtime selection and use native readiness**

Add `error?: AgentError` to `AgentRuntimeProfile`. Remove `selectedRuntime` and the runtime `<select>` from `AgentComposer`; keep the `bootstrap` prop because it supplies capability hints.

In `AgentHeader`, replace runtime lookup and fallback with:

```tsx
const nativeProfile = bootstrap?.runtimeProfiles.find((profile) => profile.runtimeProfileId === 'loom-native');
const nativeState = nativeProfile?.available ? '模型已就绪' : nativeProfile?.error?.message || '等待模型账号';

<span className="truncate">麓鸣原生智能体</span>
<span aria-hidden="true">/</span>
<span className="truncate">{nativeState}</span>
```

In `AgentWorkbenchPage.sendMessage`, replace installed-runtime validation with:

```tsx
const nativeProfile = bootstrap?.runtimeProfiles.find((profile) => profile.runtimeProfileId === 'loom-native');
if (!nativeProfile?.available) {
  throw new Error(nativeProfile?.error?.message || '麓鸣原生智能体尚未就绪，请先登录模型账号');
}
```

Keep `runtimeProfileId: 'loom-native'` in API calls for one-release compatibility. Change bootstrap failure copy to `智能体状态读取失败`.

- [ ] **Step 4: Run UI and TypeScript tests**

Run: `python -m unittest discover -s python/tests -p "test_native_agent_ui_contract.py" -v`

Run: `npm run test:platform-contracts`

Expected: the UI contract, TypeScript compile, and platform contract tests PASS.

- [ ] **Step 5: Commit the UI change**

```bash
git add src/types/agent.ts src/components/agent/AgentComposer.tsx src/components/agent/AgentHeader.tsx src/components/agent/AgentWorkbenchPage.tsx python/tests/test_native_agent_ui_contract.py
git commit -m "feat: present the LOOM native central agent"
```

---

### Task 5: Native Agent Service Integration

**Files:**
- Create: `python/tests/test_native_agent_integration.py`

**Interfaces:**
- Consumes: real `AgentService`, `LoomNativeRuntimeAdapter`, `LoomModelClient`, `CapabilityRegistry`, and a fake model transport.
- Produces: proof that a managed model can answer and execute an internal tool without an external CLI process.

- [ ] **Step 1: Write a failing full-loop integration test**

Create a fake transport that records both rounds. On the first request it yields a `loom.test.read` tool call; when the second request contains a completed `toolResults` entry, it yields text `状态正常` and usage. Build the service with a real native client and registry:

```python
registry = CapabilityRegistry(
    internal_operations={
        "loom.test.read": {
            "description": "Read test status",
            "permission": "read",
            "risk": "read",
            "executor": lambda _payload: {"status": "ok"},
        }
    },
    skill_provider=lambda: [],
    mcp_provider=lambda: [],
    cli_catalog_provider=lambda: {"domains": []},
)
client = LoomModelClient(FakeAccount(managed_session()), transport=TwoRoundTransport())
service = AgentService(AppPaths(root), model_client=client, capabilities=registry)
session = service.create_session({"title": "Native"})
sent = service.send_message(session["sessionId"], {"clientMessageId": "client_1", "text": "读取状态"})
run = wait_for_status(service, sent["run"]["runId"], "completed")
self.assertEqual(run["status"], "completed")
self.assertEqual(service.session_detail(session["sessionId"])["messages"][-1]["blocks"][0]["data"]["text"], "状态正常")
self.assertEqual(len(transport.requests), 2)
self.assertNotIn("codex", json.dumps(transport.requests).lower())
self.assertNotIn("claude", json.dumps(transport.requests).lower())
```

- [ ] **Step 2: Run the integration test**

Run: `python -m unittest discover -s python/tests -p "test_native_agent_integration.py" -v`

Expected: PASS. A failure sends execution back to the owning Task 1-3 unit test and implementation before Task 5 continues; Task 5 does not modify production code.

- [ ] **Step 3: Run the complete Agent backend suite**

Run:

```powershell
$patterns = @(
  'test_loom_model_client.py',
  'test_native_agent_runtime.py',
  'test_agent_runtime.py',
  'test_agent_orchestrator.py',
  'test_agent_service.py',
  'test_agent_routes.py',
  'test_agent_capabilities.py',
  'test_agent_policy.py',
  'test_agent_session_repository.py',
  'test_agent_event_ledger.py',
  'test_agent_matrix_integration.py',
  'test_native_agent_integration.py',
  'test_native_agent_ui_contract.py'
)
foreach ($pattern in $patterns) {
  python -m unittest discover -s python/tests -p $pattern -v
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
```

Expected: all listed suites PASS.

- [ ] **Step 4: Run build, source, and diff verification**

Run: `npm run build`

Run from the worktree root: `.\scripts\verify-source-text.ps1`

Run: `git diff --check`

Expected: all commands exit 0; no generated build output or unrelated file is staged.

- [ ] **Step 5: Commit the integration proof**

```bash
git add python/tests/test_native_agent_integration.py
git commit -m "test: verify native agent model and tool loop"
```

---

## Phase A Completion Gate

Phase A is complete only when:

- `AgentService(paths)` constructs `LoomNativeRuntimeAdapter`, never auto-discovers a CLI, and bootstrap exposes only `loom-native`.
- A logged-in managed account can stream a model response and complete an internal tool round through the existing orchestrator.
- A logged-out account receives `AGENT_ACCOUNT_LOGIN_REQUIRED` with a recoverable, user-facing message.
- Model tokens are absent from bootstrap, SSE, trace, errors, persisted Agent messages, and test snapshots.
- The central Agent UI contains no runtime selector and no request to install Codex/Claude.
- Existing pause, resume, cancel, approval, Matrix attachment, session repository, route, and event-ledger tests remain green.
- `npm run build`, `npm run test:platform-contracts`, source-text verification, and `git diff --check` pass.

After this gate, the next independent plan is Phase B: LOOM Skill Store and bundled `luming-phone-agent` with signed official updates.
