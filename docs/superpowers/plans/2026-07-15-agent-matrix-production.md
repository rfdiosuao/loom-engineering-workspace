# LOOM Agent and Matrix Production Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Ship a production-grade LOOM central Agent and multi-phone Matrix workbench in which every phone can receive an independent assignment, different phones execute with bounded concurrency, one phone remains serial, and all runs, approvals, evidence, retries, takeovers, and failures are traceable.

**Architecture:** Keep the Python FastAPI Bridge as the local control plane. Extract Matrix execution from route-private functions into a reusable service, use versioned contracts and a short-lived stream ticket for authenticated realtime events, and build Agent as an independent session/run subsystem that calls Matrix through the execution service. React remains a Zustand-driven desktop shell without React Router; high-frequency Matrix and Agent events stay in page reducers and hooks.

**Tech Stack:** React 18, TypeScript 5, Zustand 5, Vite 8, Tauri 2/Rust, Python FastAPI, JSON/JSONL local persistence, Node tests, Python unittest/pytest, Playwright with Microsoft Edge.

## Global Constraints

- Platform baseline: codex/workspace-baseline-20260715 at or after 3ac54e6.
- Product spec: docs/superpowers/specs/2026-07-15-loom-agent-matrix-production-design.md.
- Dispatch addendum: docs/superpowers/specs/2026-07-15-matrix-parallel-dispatch-addendum.md.
- Legacy deviceIds plus uniform prompt/template/action requests remain accepted and normalize to loom.matrix.dispatch.v2.
- One device has one active writer; different devices may run concurrently up to a server-capped limit.
- Long-lived Bridge, phone, model, CLI, and MCP secrets never enter WebView state, URLs, events, screenshots, or logs.
- Direct realtime HTTP uses a single-use stream ticket with TTL at most 30 seconds; reconnect gets a new ticket and resumes with afterSeq.
- Outbound messages, comments, private messages, publishing, adding contacts, login, captcha, 2FA, payment, deletion, authorization, and account changes require approval or human handling.
- Restart recovery never automatically replays an external write tool.
- Screenshots never travel through SSE and at most 12 screenshot requests are active.
- Visual gates: 1600x1000, 1280x800, and 1100x720.
- Tests use dependency injection and temporary directories; no public testMode.

---

## Delivery Graph

~~~mermaid
flowchart TD
    P["#3 Production plan"] --> C1["#4a Hub JSON Schemas"]
    C1 --> C2["#4b Platform contracts and secure streams"]
    C2 --> M1["#5 Matrix assignments and execution"]
    C2 --> A1["#8 Agent persistence"]
    C2 --> A2["#9 Agent runtime and policy"]
    M1 --> M2["#6 Matrix API and lease"]
    M2 --> MU["#7 Matrix UI"]
    M1 --> AO["#10 Agent orchestration"]
    A1 --> AO
    A2 --> AO
    AO --> AU["#11 Agent UI"]
    MU --> R["#12 Release"]
    AU --> R
~~~

## Exclusive Ownership

| Work | Exclusive production files |
|---|---|
| #4b | src/services/api.ts, loomContracts.ts, loomClient.ts, src/stores/appStore.ts, src/App.tsx, test bootstrap |
| #5 | python/core/phone_matrix.py, matrix_scheduler.py, python/services/matrix_execution.py, loom_cli.py, loom_mcp.py |
| #6 | python/api/routes_matrix.py and narrow control changes in routes_phone.py |
| #7 | src/components/matrix |
| #8 | python/core/agent_sessions.py and agent_events.py |
| #9 | python/core/agent_runtime.py, agent_capabilities.py, agent_policy.py |
| #10 | python/core/agent_orchestrator.py and python/api/routes_agent.py |
| #11 | src/components/agent, agentStore.ts, registry.ts, pages.tsx, Sidebar.tsx |
| #12 | fastapi_routes.py, bridge.py, feature_access.py, index.css, release tests |

Dependent branches do not edit upstream owner files to finish a contract. They rebase on the merged upstream PR.

---

### Task 1: Freeze Hub Contracts and Fixtures (#4a)

**Files:**
- Create packages/contracts/schemas/realtime-event.v1.schema.json
- Create packages/contracts/schemas/matrix-dispatch.v2.schema.json
- Create packages/contracts/schemas/matrix-campaign.v2.schema.json
- Create packages/contracts/schemas/matrix-screen.v1.schema.json
- Create packages/contracts/schemas/device-lease.v1.schema.json
- Create packages/contracts/schemas/agent-session.v1.schema.json
- Create packages/contracts/schemas/agent-message.v1.schema.json
- Create packages/contracts/schemas/agent-run.v1.schema.json
- Create packages/contracts/schemas/agent-approval.v1.schema.json
- Create matching JSON fixtures under packages/contracts/fixtures
- Modify scripts/test-workspace.ps1
- Modify .github/workflows/workspace-ci.yml

**Interfaces:**
- Produces schema IDs loom.realtime.event.v1, loom.matrix.dispatch.v2, loom.matrix.campaign.v2, loom.matrix.screen.v1, loom.matrix.device_lease.v1, loom.agent.session.v1, loom.agent.message.v1, loom.agent.run.v1, and loom.agent.approval.v1.
- Matrix assignment fields: assignmentId, deviceId, prompt or templateId, input, timeoutSec, retryBudget.

- [ ] **Step 1: Add failing workspace assertions**

~~~powershell
$schemaRoot = Join-Path $root 'packages\contracts\schemas'
$requiredSchemas = @(
    'realtime-event.v1.schema.json',
    'matrix-dispatch.v2.schema.json',
    'matrix-campaign.v2.schema.json',
    'agent-session.v1.schema.json',
    'agent-approval.v1.schema.json'
)
foreach ($name in $requiredSchemas) {
    $path = Join-Path $schemaRoot $name
    Assert-Workspace -Condition (Test-Path -LiteralPath $path -PathType Leaf) -Message "$name exists"
    $document = Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json
    Assert-Workspace -Condition (-not [string]::IsNullOrWhiteSpace($document.'$id')) -Message "$name has an id"
}
~~~

- [ ] **Step 2: Run the test**

Run: powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test-workspace.ps1
Expected: FAIL on realtime-event.v1.schema.json exists.

- [ ] **Step 3: Implement strict schemas**

~~~json
{
  "$id": "loom.matrix.dispatch.v2",
  "type": "object",
  "required": ["schema", "campaignId", "concurrency", "deviceAssignments"],
  "properties": {
    "schema": { "const": "loom.matrix.dispatch.v2" },
    "campaignId": { "type": "string", "minLength": 1 },
    "concurrency": { "type": "integer", "minimum": 1 },
    "mode": { "enum": ["observe", "safe", "full"] },
    "profile": { "enum": ["fast", "standard", "deep"] },
    "deviceAssignments": {
      "type": "array",
      "minItems": 1,
      "items": { "$ref": "#/$defs/assignment" }
    }
  },
  "additionalProperties": false
}
~~~

The complete assignment definition uses oneOf to require prompt or templateId. Schemas reject extra properties except documented extension maps such as event data.

- [ ] **Step 4: Validate all JSON in CI**

~~~powershell
Get-ChildItem .\packages\contracts -Recurse -Filter *.json | ForEach-Object {
  Get-Content -LiteralPath $_.FullName -Raw -Encoding UTF8 | ConvertFrom-Json | Out-Null
}
~~~

- [ ] **Step 5: Run and commit**

Run: powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test-workspace.ps1
Expected: PASS with more than 30 assertions.

~~~powershell
git add packages/contracts scripts/test-workspace.ps1 .github/workflows/workspace-ci.yml
git commit -m "feat(contracts): freeze Agent and Matrix schemas"
~~~

---

### Task 2: Platform Contracts, Secure Streams, and Navigation (#4b)

**Files:**
- Create src/types/realtime.ts, src/types/agent.ts, src/types/matrix.ts
- Create src/services/realtimeStream.ts and realtimeStream.test.ts
- Create src/stores/appNavigation.test.ts
- Create python/core/stream_tickets.py
- Create python/tests/agent_matrix_contract_fixtures.py
- Create python/tests/test_agent_matrix_contracts.py
- Create python/tests/test_stream_tickets.py
- Modify src/services/api.ts, loomContracts.ts, loomClient.ts
- Modify src/stores/appStore.ts and src/App.tsx
- Modify package.json and package-lock.json

**Interfaces:**
- Produces openFeature(key, context) and consumeNavigationContext(key).
- Produces StreamTicketIssuer.issue(topic, subject) and consume(ticket, topic).
- Produces openRealtimeStream with topic, afterSeq, AbortSignal, and event callback.
- Produces typed agentApi and expanded matrixApi. UI branches do not edit api.ts.

- [ ] **Step 1: Write failing ticket tests**

~~~python
def test_ticket_is_single_use_and_topic_bound(fake_clock):
    issuer = StreamTicketIssuer(clock=fake_clock, ttl_seconds=30)
    ticket = issuer.issue(topic="matrix", subject="desktop")
    assert issuer.consume(ticket, topic="agent") is None
    grant = issuer.consume(ticket, topic="matrix")
    assert grant["subject"] == "desktop"
    assert issuer.consume(ticket, topic="matrix") is None
~~~

- [ ] **Step 2: Run the test**

Run: python -B -m unittest python.tests.test_stream_tickets -v
Expected: FAIL because core.stream_tickets does not exist.

- [ ] **Step 3: Implement the ticket issuer**

~~~python
class StreamTicketIssuer:
    def __init__(self, *, clock=time.time, ttl_seconds=30):
        self._clock = clock
        self._ttl_seconds = min(30, max(1, int(ttl_seconds)))
        self._tickets = {}
        self._lock = threading.RLock()

    def issue(self, *, topic, subject):
        ticket = secrets.token_urlsafe(32)
        with self._lock:
            self._tickets[ticket] = {
                "topic": topic,
                "subject": subject,
                "expiresAt": self._clock() + self._ttl_seconds,
            }
        return ticket

    def consume(self, ticket, *, topic):
        with self._lock:
            grant = self._tickets.pop(ticket, None)
        if not grant or grant["topic"] != topic or grant["expiresAt"] < self._clock():
            return None
        return grant
~~~

- [ ] **Step 4: Test navigation context**

~~~ts
const context = { campaignId: 'cmp_1', deviceId: 'P01', runId: 'run_1', source: 'agent' as const };
useAppStore.getState().openFeature('workbench', context);
assert.equal(useAppStore.getState().currentPage, 'workbench');
assert.deepEqual(useAppStore.getState().consumeNavigationContext('workbench'), context);
assert.equal(useAppStore.getState().consumeNavigationContext('workbench'), null);
~~~

Store context by destination key and delete it atomically on consume. Do not use URL or localStorage.

- [ ] **Step 5: Implement realtime client**

The client obtains a ticket via the protected Rust proxy, then opens direct fetch streaming with the ticket and afterSeq. It parses frames incrementally, accepts only loom.realtime.event.v1, deduplicates eventId, reconnects from committed seq, and never logs ticket or full payload.

- [ ] **Step 6: Run and commit**

Run: python -B -m unittest python.tests.test_stream_tickets python.tests.test_agent_matrix_contracts -v
Expected: PASS.

Run: node --test src/services/realtimeStream.test.ts src/stores/appNavigation.test.ts
Expected: PASS.

Run: npm run build
Expected: PASS.

~~~powershell
git add src python/core/stream_tickets.py python/tests package.json package-lock.json
git commit -m "feat(platform): add Agent Matrix contracts and secure streams"
~~~

---

### Task 3: Per-Device Matrix Execution (#5)

**Files:**
- Create python/core/matrix_scheduler.py
- Create python/services/matrix_execution.py
- Create python/tests/test_matrix_scheduler.py
- Modify python/core/phone_matrix.py at dispatch
- Modify python/loom_cli.py and python/loom_mcp.py
- Modify matrix, CLI, and MCP contract tests

**Interfaces:**
- Consumes loom.matrix.dispatch.v2.
- Produces MatrixExecutionService.dispatch(request) and retry(campaignId, deviceTaskIds, stepId).
- Produces assignmentId, deviceTaskId, jobId, attempt, status per phone.
- Produces CLI campaign-id, concurrency, device-assignments-json, and targeted retry arguments.

- [ ] **Step 1: Write failing scheduler test**

~~~python
def test_scheduler_limits_concurrency_and_serializes_a_device():
    probe = ExecutionProbe()
    scheduler = MatrixScheduler(max_concurrency=2, execute=probe.execute)
    scheduler.submit([
        assignment("a1", "P01"),
        assignment("a2", "P02"),
        assignment("a3", "P03"),
        assignment("a4", "P01"),
    ])
    scheduler.join()
    assert probe.max_active == 2
    assert probe.max_active_by_device["P01"] == 1
~~~

- [ ] **Step 2: Run the test**

Run: python -B -m unittest python.tests.test_matrix_scheduler -v
Expected: FAIL because core.matrix_scheduler does not exist.

- [ ] **Step 3: Normalize and make dispatch idempotent**

Initial device state is queued. Persist full normalized input. Compute taskFingerprint from prompt, templateId, input, mode, and profile; idempotency key is campaignId plus fingerprint plus deviceId. Same key returns the original task. Same campaignId with a different fingerprint returns campaign_id_conflict.

- [ ] **Step 4: Implement scheduler and execution service**

MatrixScheduler owns a global semaphore and one lock per device. MatrixExecutionService obtains both, marks the device running, submits Phone Agent work, saves jobId, and records terminal state. Routes and Agent call the service, not route-private functions.

- [ ] **Step 5: Add targeted retry and event attribution**

retry_failed accepts deviceTaskIds, deviceId, and stepId. Runtime events resolve campaignId, deviceTaskId, and jobId from the active device task so campaign watch includes phone output.

- [ ] **Step 6: Extend CLI and MCP**

Chinese and English MCP schemas expose campaignId, concurrency, and deviceAssignments. Permission ceilings remain enforced and JSON output remains mandatory.

- [ ] **Step 7: Run and commit**

Run: python -B -m unittest python.tests.test_matrix_scheduler python.tests.test_matrix_control_plane python.tests.test_loom_cli_contract python.tests.test_loom_mcp_contract -v
Expected: PASS for bounded concurrency, idempotency, per-device jobs, partial result, and targeted retry.

~~~powershell
git add python/core/phone_matrix.py python/core/matrix_scheduler.py python/services/matrix_execution.py python/loom_cli.py python/loom_mcp.py python/tests
git commit -m "feat(matrix): execute independent device assignments"
~~~

---

### Task 4: Matrix Screen, Lease, Control, and Lifecycle APIs (#6)

**Files:**
- Modify python/api/routes_matrix.py
- Modify only required control adapter code in python/api/routes_phone.py
- Modify python/tests/test_routes_matrix.py
- Create test_matrix_screen_contract.py, test_matrix_device_lease.py, test_matrix_manual_control.py

**Interfaces:**
- Consumes MatrixExecutionService.
- Produces screen, timeline, lease GET/POST/DELETE, control, pause/resume, cancel/retry, emergency-stop routes.
- Produces authenticated Matrix SSE with stream ticket and afterSeq.

- [ ] **Step 1: Write failing lease test**

~~~python
def test_control_rejects_conflicting_lease(client):
    response = client.post("/api/matrix/devices/P01/control", json={
        "leaseId": "lease_wrong",
        "clientCommandId": "cmd_1",
        "action": "tap",
        "x": 0.5,
        "y": 0.4,
    })
    assert response.status_code == 409
    assert response.json()["code"] == "device_lease_conflict"
~~~

- [ ] **Step 2: Run the test**

Run: python -B -m unittest python.tests.test_matrix_device_lease python.tests.test_matrix_manual_control -v
Expected: FAIL because routes do not exist.

- [ ] **Step 3: Implement APIs**

Lease TTL is 30 seconds and only the holder renews. Expired leases are removed before decisions. Normalize coordinates to 0..1 and make clientCommandId idempotent. Pause/resume/cancel report requested, applied, or too_late. Emergency stop computes the complete affected set atomically and releases only related Agent leases.

- [ ] **Step 4: Secure Matrix stream**

Matrix SSE consumes a Matrix-scoped ticket, emits only loom.realtime.event.v1, supports afterSeq, sends keepalive, and never emits images.

- [ ] **Step 5: Run and commit**

Run: python -B -m unittest python.tests.test_routes_matrix python.tests.test_matrix_screen_contract python.tests.test_matrix_device_lease python.tests.test_matrix_manual_control -v
Expected: PASS.

~~~powershell
git add python/api/routes_matrix.py python/api/routes_phone.py python/tests
git commit -m "feat(matrix): add leased device control APIs"
~~~

---

### Task 5: Agent Persistence and Event Ledger (#8)

**Files:**
- Create python/core/agent_sessions.py and agent_events.py
- Create test_agent_session_repository.py and test_agent_events.py

**Interfaces:**
- Produces AgentSessionRepository session, message, run, idempotency, and index-rebuild methods.
- Produces AgentEventBus.append and read_after with persisted seq.

- [ ] **Step 1: Write failing sequence test**

~~~python
def test_event_sequence_survives_restart(tmp_path):
    first = AgentEventBus(tmp_path)
    assert first.append("s1", "agent.run", "r1", "run.started", {})["seq"] == 1
    second = AgentEventBus(tmp_path)
    assert second.append("s1", "agent.run", "r1", "run.completed", {})["seq"] == 2
~~~

- [ ] **Step 2: Run the test**

Run: python -B -m unittest python.tests.test_agent_session_repository python.tests.test_agent_events -v
Expected: FAIL because modules do not exist.

- [ ] **Step 3: Implement persistence**

Use temporary sibling file, flush, fsync, and os.replace for JSON. Lock JSONL append. Rebuild the index by scanning session directories. Redact token, secret, password, api_key, apikey, cookie, and authorization fields. Store evidence references, not screenshot or private-message bodies.

- [ ] **Step 4: Run and commit**

Run: python -B -m unittest python.tests.test_agent_session_repository python.tests.test_agent_events -v
Expected: PASS.

~~~powershell
git add python/core/agent_sessions.py python/core/agent_events.py python/tests
git commit -m "feat(agent): persist sessions and ordered events"
~~~

---

### Task 6: Agent Runtime, Capabilities, and Policy (#9)

**Files:**
- Create agent_runtime.py, agent_capabilities.py, agent_policy.py
- Create test_agent_runtime.py and test_agent_policy.py

**Interfaces:**
- Produces AgentRuntimeAdapter.status and start.
- Produces CapabilityRegistry.list_allowed.
- Produces AgentPolicyEngine.evaluate.

- [ ] **Step 1: Write failing policy test**

~~~python
def test_outbound_call_requires_single_tool_approval():
    decision = policy.evaluate(
        tool_call={"toolCallId": "tc1", "capability": "loom.phone.publish", "input": {"deviceId": "P01"}},
        context={"approvals": []},
    )
    assert decision.action == "require_approval"
    assert decision.risk == "outbound"
~~~

- [ ] **Step 2: Run the test**

Run: python -B -m unittest python.tests.test_agent_policy python.tests.test_agent_runtime -v
Expected: FAIL because modules do not exist.

- [ ] **Step 3: Implement runtime and policy**

Launch allowlisted runtimes with argument arrays, never shell strings. Parse structured JSON/JSONL. Approval binds runId, toolCallId, capability, inputHash, and expiresAt; model-provided confirmed has no authority and decisions are single-use.

- [ ] **Step 4: Run and commit**

Run: python -B -m unittest python.tests.test_agent_policy python.tests.test_agent_runtime -v
Expected: PASS.

~~~powershell
git add python/core/agent_runtime.py python/core/agent_capabilities.py python/core/agent_policy.py python/tests
git commit -m "feat(agent): add controlled runtime and policy"
~~~

---

### Task 7: Super Matrix Workbench (#7)

**Files:**
- Create MatrixCommandBar, MatrixMetrics, DeviceGroupRail, PhoneWall, PhoneTile
- Create DeviceInspector, FocusScreen, ManualControls, DeviceTimeline, MatrixTaskDrawer
- Create matrixViewModel, useMatrixStream, useMatrixCommands, useVisibleScreens, visibleScreenScheduler
- Create matrixWorkbench.css and focused tests
- Reduce MatrixWorkbenchPage.tsx to composition/navigation
- Create tests/e2e/matrix-workbench.spec.ts

**Interfaces:**
- Consumes Task 2 client/types and Task 4 APIs.
- Produces devicesById, deviceTasksById, activeTaskIdByDeviceId, campaignsById, commandStateByTaskId.
- Produces screenshot scheduler capped at 12.

- [ ] **Step 1: Write failing reducer test**

~~~ts
const next = reduceMatrixEvent(state, assignmentEvent({
  deviceId: 'P02',
  deviceTaskId: 'dt_2',
  type: 'matrix.assignment.progress',
  data: { progress: 40 },
}));
assert.equal(next.deviceTasksById.dt_2.progress, 40);
assert.equal(next.deviceTasksById.dt_1.progress, state.deviceTasksById.dt_1.progress);
~~~

Also test that a 20-screen queue never exceeds 12 active fetches.

- [ ] **Step 2: Run the tests**

Run: node --test src/components/matrix/matrixViewModel.test.ts src/components/matrix/visibleScreenScheduler.test.ts
Expected: FAIL because modules do not exist.

- [ ] **Step 3: Implement state and screenshots**

Events update one task. Recompute campaign aggregates from device states. On seq gap fetch a fresh snapshot and ticket. Poll focused device at 700 ms, visible running at 1500 ms, visible idle at 4000 ms, hidden never. Revoke object URLs after replacement/unmount.

- [ ] **Step 4: Implement UI**

Phone wall is the largest region. Use icons, tooltips, uniform/per-device segmented mode, and an advanced drawer. AI mode click selects only; manual mode requires a lease.

- [ ] **Step 5: Run and commit**

Run: node --test src/components/matrix/*.test.ts
Expected: PASS.

Run: npm run build
Expected: PASS.

Run: npm run test:e2e -- tests/e2e/matrix-workbench.spec.ts
Expected: PASS at all desktop viewports.

~~~powershell
git add src/components/matrix tests/e2e/matrix-workbench.spec.ts
git commit -m "feat(matrix-ui): add production phone workbench"
~~~

---

### Task 8: Agent Orchestration and API (#10)

**Files:**
- Create python/core/agent_orchestrator.py
- Create python/api/routes_agent.py
- Create test_agent_orchestrator.py and test_agent_routes.py

**Interfaces:**
- Consumes MatrixExecutionService, Agent repository/event bus, runtime, capability registry, and policy.
- Produces all /api/agent endpoints and matrix.attached events.

- [ ] **Step 1: Write failing idempotency test**

~~~python
def test_duplicate_client_message_returns_same_run(client):
    body = {"clientMessageId": "client-1", "text": "读取三台手机状态"}
    first = client.post("/api/agent/sessions/s1/messages", json=body).json()
    second = client.post("/api/agent/sessions/s1/messages", json=body).json()
    assert first["run"]["runId"] == second["run"]["runId"]
~~~

- [ ] **Step 2: Run the test**

Run: python -B -m unittest python.tests.test_agent_orchestrator python.tests.test_agent_routes -v
Expected: FAIL because modules do not exist.

- [ ] **Step 3: Implement lifecycle**

Persist user message and queued Run atomically. One Session has at most one active Run. Matrix calls use MatrixExecutionService. Startup marks leftover active Runs as recoverable interrupted and never replays tools. Agent SSE consumes an Agent ticket and reads persisted events after afterSeq.

- [ ] **Step 4: Run and commit**

Run: python -B -m unittest python.tests.test_agent_orchestrator python.tests.test_agent_routes -v
Expected: PASS.

~~~powershell
git add python/core/agent_orchestrator.py python/api/routes_agent.py python/tests
git commit -m "feat(agent): orchestrate sessions tools and approvals"
~~~

---

### Task 9: Central Agent Workbench (#11)

**Files:**
- Create AgentWorkbenchPage, AgentHeader, ConversationSidebar, ConversationStream
- Create AgentComposer, AgentDebugger, AgentRunAttachment, AgentApprovalCard
- Create messageBlocks, agentViewModel, useAgentStream, agentWorkbench.css
- Create src/stores/agentStore.ts
- Modify registry.ts, pages.tsx, Sidebar.tsx
- Create focused tests and tests/e2e/agent-workbench.spec.ts

**Interfaces:**
- Consumes Task 2 client/context and Task 8 APIs.
- Produces visible agent feature and preserves hidden agentAccess.
- Produces workbench deep-link with campaignId, deviceId, runId, source.

- [ ] **Step 1: Write failing reducer test**

~~~ts
const next = reduceAgentEvent(state, event({
  seq: 7,
  entityId: 'message-2',
  type: 'message.delta',
  data: { delta: '完成 2/3' },
}));
assert.equal(next.messagesById['message-2'].text, '完成 2/3');
assert.equal(next.messagesById['message-1'].text, state.messagesById['message-1'].text);
~~~

Also test deduplication, cross-session isolation, terminal Run protection from late events, and switching sessions aborting only the stream.

- [ ] **Step 2: Run the tests**

Run: node --test src/components/agent/agentViewModel.test.ts src/stores/agentStore.test.ts
Expected: FAIL because modules do not exist.

- [ ] **Step 3: Implement UI and navigation**

Store only session/message indexes, Run summaries, drafts, debugger state, selected trace, and cursor. Conversation is primary; Debugger is collapsed and uses real events. Approval cards show action, targets, impact, and expiry. Add visible agent, retain hidden agentAccess, lazy-load, and do not add React Router.

- [ ] **Step 4: Run and commit**

Run: node --test src/components/agent/*.test.ts src/stores/agentStore.test.ts
Expected: PASS.

Run: npm run build
Expected: PASS.

Run: npm run test:e2e -- tests/e2e/agent-workbench.spec.ts
Expected: PASS at all desktop viewports.

~~~powershell
git add src/components/agent src/stores/agentStore.ts src/features src/components/sidebar tests/e2e/agent-workbench.spec.ts
git commit -m "feat(agent-ui): add central Agent workbench"
~~~

---

### Task 10: Integrate, Recover, Measure, and Release (#12)

**Files:**
- Modify python/api/fastapi_routes.py, python/bridge.py, python/core/feature_access.py, python/core/paths.py
- Modify test_commercial_license_feature_gate.py and src/styles/index.css
- Create test_agent_matrix_integration.py
- Create agent-matrix-release.spec.ts, accessibility.spec.ts, performance.spec.ts

**Interfaces:**
- Consumes every preceding task.
- Produces Bridge lifecycle dependencies, agent.workbench feature, protected /api/agent routes, and release evidence.

- [ ] **Step 1: Write failing integration test**

~~~python
def test_agent_matrix_partial_result_round_trip(app_client, fake_runtime, fake_phones):
    run = create_agent_message(app_client, "让三台手机分别读取自己的候选人")
    fake_phones.complete("P01")
    fake_phones.fail("P02", code="wrong_page")
    fake_phones.complete("P03")
    trace = app_client.get("/api/agent/runs/" + run["runId"] + "/trace").json()
    assert matrix_attachment(trace)["status"] == "partial"
    assert matrix_attachment(trace)["counts"] == {"completed": 2, "failed": 1}
~~~

- [ ] **Step 2: Register and recover services**

bridge.py constructs and starts/stops dependencies; domain logic remains in services. Register Agent before catch-all. Shutdown cancels runtime processes and persists interrupted state.

- [ ] **Step 3: Add visual and 100-device gates**

Add keyboard focus, aria-live, reduced-motion, list/conversation semantics, and stable control dimensions. With 100 devices assert state updates within 2 seconds, screenshot requests at most 12, hidden polling stopped, stable ordering, and no images in events.

- [ ] **Step 4: Run full gates**

Run: python -B -m unittest discover -s python\tests -p "test_*.py"
Expected: all tests pass.

Run: npm run build
Expected: PASS.

Run: npm run test:e2e
Expected: all Agent and Matrix projects pass.

Run from apps/loom-phone-agent: .\gradlew.bat testDebugUnitTest
Expected: BUILD SUCCESSFUL.

- [ ] **Step 5: Run real-device smoke**

1. Dispatch three different read-only assignments with concurrency 2.
2. Confirm the third stays queued until a slot opens.
3. Force one wrong-page failure and retry only that device.
4. Take over one device with a lease, release it, then explicitly resume Agent control.
5. Verify trace, device events, evidence references, and deep-link targeting.
6. Attempt outbound action and confirm it stops at approval without sending.

- [ ] **Step 6: Commit**

~~~powershell
git add python src/styles/index.css tests/e2e
git commit -m "feat: complete Agent Matrix production loop"
~~~

---

## Merge and Rollback Rules

1. Merge #4a, then #4b.
2. Rebase #5, #8, and #9 on #4b and run them in parallel.
3. Merge #5 before #6 and #10.
4. Merge #6 before #7; merge #8 and #9 before #10.
5. Merge #7 and #11 after their backend dependencies.
6. Merge #12 last.
7. Roll back by reverting the failing feature PR. Do not reset shared branches or delete evidence.
8. Never rewrite a released schema major version; create the next ID and a normalizer.

## Self-Review

- Coverage includes Agent UI/backend, Matrix UI/backend, assignments, concurrency, device serialization, lease/control, approvals, persistence, realtime recovery, performance, security, and release.
- No placeholders remain.
- campaignId, assignmentId, deviceTaskId, jobId, runId, toolCallId, eventId, and seq retain one meaning.
- Long-lived secrets stay in Rust/Python; tickets are single-use; external writes cannot be auto-approved or auto-retried.
