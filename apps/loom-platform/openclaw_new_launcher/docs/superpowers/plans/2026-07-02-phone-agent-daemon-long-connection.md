# Phone Agent Daemon Long Connection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a LOOM-side phone-agent daemon so Codex/LOOM can control APKClaw faster and more steadily by reusing the Node process, Lumi pairing, HTTP connection pool, event stream, and per-device action queues.

**Architecture:** Keep APKClaw phone APIs and Lumi security semantics unchanged. Add a local Node daemon in LOOM that runs on `127.0.0.1`, accepts signed local requests from existing CLI/Python bridge code, and forwards to APKClaw through the existing `openclaw-phone-secure.mjs` helpers. The old CLI remains compatible: it uses daemon in `auto` mode when available and falls back to the current direct path when daemon is down.

**Tech Stack:** Node.js ESM, built-in `node:http`, built-in `fetch`, existing Lumi helpers in `scripts/openclaw-phone-secure.mjs`, existing CLI in `scripts/openclaw-phone-agent.mjs`, Python unittest for LOOM route contracts.

## Global Constraints

- Do not hardcode real token, API key, account, keystore, or private key.
- Do not change APKClaw package name, signing, `TokenValidator`, or Lumi HMAC protocol semantics.
- Do not remove old CLI/API interfaces.
- Do not refactor LOOM main UI or unrelated installer pages.
- Dangerous actions remain blocked or require explicit confirmation: payment, deletion, login authorization, privacy data export.
- Same-device write actions are serialized: `action_fast`, `template_run`, and Agent tasks.
- Read-only operations may be concurrent with limits: `observe_fast` and screenshots.
- Daemon binds only to `127.0.0.1` and requires a local random daemon token header.

---

## Current Evidence

Use these measured numbers as the baseline:

- Before fast path: open settings through Agent loop took about `17.073s`, `rounds=3`, `llmRoundMs=16053`.
- After fast path:
  - `observe_fast`: 100 calls, concurrency 16, 100/100 success, device P50 `4ms`, P95 `8ms`.
  - `open-settings`: 60 calls, concurrency 16, 60/60 success, device P50 `9ms`, P95 `22ms`.
  - `screenshot`: 30 calls, concurrency 6, 30/30 success, device P50 `419ms`, P95 `673ms`.
- Remaining wall time is mostly local orchestration overhead: Node process startup, CLI parsing, Lumi pairing lookup, HTTP setup, JSON parse, and cross-process scheduling.

Reference docs:

- `D:\Axiangmu\AUSTART\openclaw_new_launcher\docs\APKCLAW_LOOM_LONG_CONNECTION.md`
- `D:\Axiangmu\AUSTART\openclaw_new_launcher\docs\APKCLAW_LOOM_FAST_PATH_STRESS_2026-07-02.md`

## File Structure

Create or modify only these LOOM-side files:

- Create: `D:\Axiangmu\AUSTART\openclaw_new_launcher\scripts\openclaw-phone-daemon.mjs`
  - Local daemon entrypoint. Starts HTTP server, loads runtime token, owns device sessions.
- Create: `D:\Axiangmu\AUSTART\openclaw_new_launcher\scripts\lib\phone-daemon\client.mjs`
  - CLI-side daemon client. Handles health check, auto-start, local auth header, request forwarding, fallback decisions.
- Create: `D:\Axiangmu\AUSTART\openclaw_new_launcher\scripts\lib\phone-daemon\device-session.mjs`
  - One in-memory session per phone device. Owns queues, pairing reuse, recent event state, and command execution.
- Create: `D:\Axiangmu\AUSTART\openclaw_new_launcher\scripts\lib\phone-daemon\queue.mjs`
  - Small serial and limited-concurrency queue implementation.
- Create: `D:\Axiangmu\AUSTART\openclaw_new_launcher\scripts\lib\phone-daemon\runtime-auth.mjs`
  - Creates and reads `data\.openclaw\runtime\phone-daemon.json` with local port, pid, and random daemon token.
- Create: `D:\Axiangmu\AUSTART\openclaw_new_launcher\scripts\lib\phone-command-core.mjs`
  - Shared command runner extracted from `openclaw-phone-agent.mjs`, so CLI and daemon use the same fast-path behavior.
- Modify: `D:\Axiangmu\AUSTART\openclaw_new_launcher\scripts\openclaw-phone-agent.mjs`
  - Add `--daemon auto|off|require`. Default `auto` for `run`, `metrics`, and `events-sync`. Fall back to direct path when daemon is unavailable.
- Modify: `D:\Axiangmu\AUSTART\openclaw_new_launcher\scripts\openclaw-phone-secure.mjs`
  - No protocol change. Only export helpers if needed by daemon. Keep generated stable Lumi launcher ID behavior.
- Create: `D:\Axiangmu\AUSTART\openclaw_new_launcher\scripts\openclaw-phone-daemon.test.mjs`
  - Node contract tests with a fake APKClaw phone server.
- Create: `D:\Axiangmu\AUSTART\openclaw_new_launcher\python\tests\test_phone_daemon_contract.py`
  - LOOM Python route/bridge contract tests.
- Modify: `D:\Axiangmu\AUSTART\openclaw_new_launcher\python\api\routes_phone.py`
  - Add daemon status/start/stop endpoints and use daemon-aware CLI flags for phone task execution.
- Modify: `D:\Axiangmu\AUSTART\openclaw_new_launcher\docs\APKCLAW_LOOM_LONG_CONNECTION.md`
  - Add daemon command channel section and link to this implementation plan.

Do not modify:

- LOOM main UI pages.
- Installer pages.
- NewAPI account flow.
- APKClaw package signing or Token/Lumi security semantics.

## Local Daemon API Contract

Bind:

```text
127.0.0.1:<runtime port>
```

Runtime file:

```json
{
  "schema": "loom.phone_daemon.runtime.v1",
  "pid": 12345,
  "port": 19731,
  "token": "random-32-byte-base64url",
  "startedAt": "2026-07-02T16:00:00.000Z"
}
```

Required local header:

```text
X-LOOM-PHONE-DAEMON-TOKEN: <runtime token>
```

Endpoints:

```text
GET  /health
POST /v1/run
GET  /v1/device-status?deviceKey=<key>
GET  /v1/events/recent?deviceKey=<key>&limit=20
POST /shutdown
```

`POST /v1/run` request:

```json
{
  "schema": "loom.phone_daemon.run.v1",
  "requestId": "uuid",
  "command": "run",
  "deviceId": "",
  "phoneUrl": "http://127.0.0.1:19527",
  "phoneToken": "redacted-in-logs",
  "prompt": "打开系统设置",
  "mode": "safe",
  "executionLayer": "agent",
  "templateName": "",
  "timeoutSec": 600,
  "stepTimeoutSec": 8,
  "maxWaitSec": 30,
  "maxRounds": 12
}
```

`POST /v1/run` response must match old CLI JSON shape:

```json
{
  "ok": true,
  "fastPath": true,
  "mode": "action_fast",
  "executionLayer": "direct",
  "currentStep": "complete",
  "metrics": {
    "totalMs": 9,
    "screenTreeMs": 3,
    "llmRoundMs": 0,
    "toolCallMs": 6,
    "rounds": 0,
    "mode": "action_fast"
  },
  "data": {
    "currentPackage": "com.android.settings"
  }
}
```

Error response:

```json
{
  "ok": false,
  "mode": "daemon",
  "error": "accessibility_off",
  "currentStep": "failed",
  "needsCodex": true,
  "fixHint": "APKClaw accessibility service is not connected; inspect service binding and Android background restrictions."
}
```

## Queue Rules

Use one `DeviceSession` per normalized device key:

```text
deviceKey = sha256(normalizePhoneUrl(phoneUrl) + ":" + sha256(phoneToken)).slice(0, 24)
```

Queue mapping:

| Operation | Queue | Concurrency | Reason |
| --- | --- | ---: | --- |
| `observe_fast` | read queue | 4 | Read-only, cheap, can share current screen |
| `screenshot` | screenshot queue | 2 | Read-only but heavy base64 payload |
| `action_fast` | action queue | 1 | Changes screen state |
| `template_run` | action queue | 1 | Changes screen state |
| Agent loop | action queue | 1 | Multi-step screen mutation |
| `events-sync` | event stream | 1 per device | Long-lived status subscription |

If a read operation hits `System dialog blocked the screen`, return the structured error and do not auto-click the dialog.

## Task 1: Write Node Contract Tests First

**Files:**

- Create: `D:\Axiangmu\AUSTART\openclaw_new_launcher\scripts\openclaw-phone-daemon.test.mjs`

**Interfaces:**

- Consumes: no production daemon code yet.
- Produces: failing tests that define daemon behavior.

- [ ] **Step 1: Add fake phone server and first daemon test**

Add this test skeleton:

```js
import assert from 'node:assert/strict';
import http from 'node:http';
import test from 'node:test';
import { once } from 'node:events';
import { spawn } from 'node:child_process';

function startFakePhone(handler) {
  const server = http.createServer(async (request, response) => {
    try {
      await handler(request, response);
    } catch (error) {
      response.writeHead(500, { 'Content-Type': 'application/json' });
      response.end(JSON.stringify({ success: false, error: error.message }));
    }
  });
  return new Promise((resolve) => {
    server.listen(0, '127.0.0.1', () => {
      const { port } = server.address();
      resolve({ server, baseUrl: `http://127.0.0.1:${port}` });
    });
  });
}

async function readJson(request) {
  const chunks = [];
  for await (const chunk of request) chunks.push(chunk);
  const text = Buffer.concat(chunks).toString('utf8');
  return text ? JSON.parse(text) : {};
}

test('daemon run routes open-settings through action_fast without async Agent', async () => {
  const seen = [];
  const fake = await startFakePhone(async (request, response) => {
    seen.push(`${request.method} ${request.url}`);
    if (request.url === '/api/lumi/security/pair') {
      const body = await readJson(request);
      response.writeHead(200, { 'Content-Type': 'application/json' });
      response.end(JSON.stringify({ success: true, data: { launcherId: body.launcherId, launcherSecret: 'secret' } }));
      return;
    }
    if (request.url === '/api/device/status') {
      response.writeHead(200, { 'Content-Type': 'application/json' });
      response.end(JSON.stringify({ success: true, data: { accessibilityEnabled: true, modelConfigured: false } }));
      return;
    }
    if (request.url === '/api/lumi/agent/action_fast') {
      response.writeHead(200, { 'Content-Type': 'application/json' });
      response.end(JSON.stringify({
        success: true,
        data: {
          mode: 'action_fast',
          success: true,
          currentStep: 'complete',
          currentPackage: 'com.android.settings',
          metrics: { mode: 'action_fast', totalMs: 10, rounds: 0, llmRoundMs: 0 }
        }
      }));
      return;
    }
    throw new Error(`unexpected ${request.method} ${request.url}`);
  });

  try {
    const daemon = spawn(process.execPath, ['scripts/openclaw-phone-daemon.mjs', '--stdio-json'], {
      cwd: process.cwd(),
      windowsHide: true,
      stdio: ['pipe', 'pipe', 'pipe'],
    });
    daemon.stdin.write(`${JSON.stringify({
      schema: 'loom.phone_daemon.run.v1',
      requestId: 'test-1',
      command: 'run',
      phoneUrl: fake.baseUrl,
      phoneToken: 'test-token',
      prompt: 'open settings',
      stepTimeoutSec: 8,
      timeoutSec: 30,
      maxWaitSec: 30
    })}\n`);
    const [chunk] = await once(daemon.stdout, 'data');
    daemon.kill();
    const payload = JSON.parse(chunk.toString('utf8').trim());
    assert.equal(payload.ok, true);
    assert.equal(payload.mode, 'action_fast');
    assert.equal(payload.metrics.rounds, 0);
    assert.equal(seen.some((line) => line.includes('/api/lumi/agent/action_fast')), true);
    assert.equal(seen.some((line) => line.includes('/api/agent/tasks')), false);
  } finally {
    fake.server.close();
  }
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```powershell
node --test scripts\openclaw-phone-daemon.test.mjs
```

Expected:

```text
not ok 1 - daemon run routes open-settings through action_fast without async Agent
Error: Cannot find module ... openclaw-phone-daemon.mjs
```

- [ ] **Step 3: Add queue behavior tests**

Add two more tests to the same file:

```js
test('daemon serializes same-device action_fast requests', async () => {
  let activeActions = 0;
  let maxActiveActions = 0;
  const fake = await startFakePhone(async (request, response) => {
    if (request.url === '/api/lumi/security/pair') {
      const body = await readJson(request);
      response.writeHead(200, { 'Content-Type': 'application/json' });
      response.end(JSON.stringify({ success: true, data: { launcherId: body.launcherId, launcherSecret: 'secret' } }));
      return;
    }
    if (request.url === '/api/device/status') {
      response.writeHead(200, { 'Content-Type': 'application/json' });
      response.end(JSON.stringify({ success: true, data: { accessibilityEnabled: true, modelConfigured: true } }));
      return;
    }
    if (request.url === '/api/lumi/agent/action_fast') {
      activeActions += 1;
      maxActiveActions = Math.max(maxActiveActions, activeActions);
      await new Promise((resolve) => setTimeout(resolve, 40));
      activeActions -= 1;
      response.writeHead(200, { 'Content-Type': 'application/json' });
      response.end(JSON.stringify({ success: true, data: { mode: 'action_fast', success: true, currentStep: 'complete', metrics: { totalMs: 40, rounds: 0 } } }));
      return;
    }
    throw new Error(`unexpected ${request.method} ${request.url}`);
  });

  try {
    const daemon = spawn(process.execPath, ['scripts/openclaw-phone-daemon.mjs', '--stdio-json'], {
      cwd: process.cwd(),
      windowsHide: true,
      stdio: ['pipe', 'pipe', 'pipe'],
    });
    const request = (id) => daemon.stdin.write(`${JSON.stringify({
      schema: 'loom.phone_daemon.run.v1',
      requestId: id,
      command: 'run',
      phoneUrl: fake.baseUrl,
      phoneToken: 'test-token',
      prompt: 'open settings',
      stepTimeoutSec: 8,
      timeoutSec: 30,
      maxWaitSec: 30
    })}\n`);
    request('a');
    request('b');
    request('c');
    const outputs = [];
    while (outputs.length < 3) {
      const [chunk] = await once(daemon.stdout, 'data');
      outputs.push(...chunk.toString('utf8').trim().split(/\r?\n/).filter(Boolean).map((line) => JSON.parse(line)));
    }
    daemon.kill();
    assert.equal(outputs.every((item) => item.ok), true);
    assert.equal(maxActiveActions, 1);
  } finally {
    fake.server.close();
  }
});

test('daemon allows concurrent observe_fast reads', async () => {
  let activeReads = 0;
  let maxActiveReads = 0;
  const fake = await startFakePhone(async (request, response) => {
    if (request.url === '/api/lumi/security/pair') {
      const body = await readJson(request);
      response.writeHead(200, { 'Content-Type': 'application/json' });
      response.end(JSON.stringify({ success: true, data: { launcherId: body.launcherId, launcherSecret: 'secret' } }));
      return;
    }
    if (request.url === '/api/device/status') {
      response.writeHead(200, { 'Content-Type': 'application/json' });
      response.end(JSON.stringify({ success: true, data: { accessibilityEnabled: true, modelConfigured: false } }));
      return;
    }
    if (request.url === '/api/lumi/agent/observe_fast?_lumi=1') {
      activeReads += 1;
      maxActiveReads = Math.max(maxActiveReads, activeReads);
      await new Promise((resolve) => setTimeout(resolve, 40));
      activeReads -= 1;
      response.writeHead(200, { 'Content-Type': 'application/json' });
      response.end(JSON.stringify({ success: true, data: { mode: 'observe_fast', success: true, currentPackage: 'com.android.settings', metrics: { totalMs: 4, rounds: 0 } } }));
      return;
    }
    throw new Error(`unexpected ${request.method} ${request.url}`);
  });

  try {
    const daemon = spawn(process.execPath, ['scripts/openclaw-phone-daemon.mjs', '--stdio-json'], {
      cwd: process.cwd(),
      windowsHide: true,
      stdio: ['pipe', 'pipe', 'pipe'],
    });
    for (const id of ['a', 'b', 'c', 'd']) {
      daemon.stdin.write(`${JSON.stringify({
        schema: 'loom.phone_daemon.run.v1',
        requestId: id,
        command: 'run',
        phoneUrl: fake.baseUrl,
        phoneToken: 'test-token',
        executionLayer: 'template',
        templateName: 'read-screen',
        prompt: 'read screen',
        stepTimeoutSec: 8,
        timeoutSec: 30,
        maxWaitSec: 30
      })}\n`);
    }
    const outputs = [];
    while (outputs.length < 4) {
      const [chunk] = await once(daemon.stdout, 'data');
      outputs.push(...chunk.toString('utf8').trim().split(/\r?\n/).filter(Boolean).map((line) => JSON.parse(line)));
    }
    daemon.kill();
    assert.equal(outputs.every((item) => item.ok), true);
    assert.equal(maxActiveReads > 1, true);
  } finally {
    fake.server.close();
  }
});
```

- [ ] **Step 4: Run tests again**

Run:

```powershell
node --test scripts\openclaw-phone-daemon.test.mjs
```

Expected: fail because daemon files do not exist yet.

## Task 2: Extract Shared Phone Command Core

**Files:**

- Create: `D:\Axiangmu\AUSTART\openclaw_new_launcher\scripts\lib\phone-command-core.mjs`
- Modify: `D:\Axiangmu\AUSTART\openclaw_new_launcher\scripts\openclaw-phone-agent.mjs`

**Interfaces:**

- Consumes: existing helpers from `openclaw-phone-secure.mjs`.
- Produces:

```js
export async function runPhoneCommand(config)
export async function getPhoneMetrics(config)
export async function syncPhoneEvents(config, onEvent)
export function fixedFastPathPlan(config)
export function commandQueueKind(config)
```

- [ ] **Step 1: Move fast-path planner and runner into the core file**

Create `scripts\lib\phone-command-core.mjs` with these exported shapes:

```js
import {
  signedFetch,
  signedJsonRequest,
} from '../openclaw-phone-secure.mjs';

export const QUEUE_KIND = Object.freeze({
  READ: 'read',
  SCREENSHOT: 'screenshot',
  ACTION: 'action',
});

export function commandQueueKind(config) {
  const plan = fixedFastPathPlan(config);
  if (plan?.kind === 'observe') return QUEUE_KIND.READ;
  if (plan?.kind === 'screenshot') return QUEUE_KIND.SCREENSHOT;
  return QUEUE_KIND.ACTION;
}

export function fixedFastPathPlan(config) {
  // Move the existing fixedFastPathPlan implementation from openclaw-phone-agent.mjs here.
  // Keep exact behavior: read-screen -> observe_fast, screenshot -> vision frame, open-settings/home/back/open-app -> action_fast.
}

export async function runPhoneCommand(config) {
  const plan = fixedFastPathPlan(config);
  if (plan) return runFixedFastPath(config, plan);
  return runAgentCommand(config);
}

export async function getPhoneMetrics(config) {
  const payload = await signedJsonRequest(config, 'GET', '/api/lumi/agent/metrics?_lumi=1', undefined, config.stepTimeoutSec * 1000);
  return { ok: true, metrics: payload?.data?.metrics || payload?.data || payload };
}

export async function syncPhoneEvents(config, onEvent) {
  const response = await signedFetch(config, 'GET', '/api/lumi/events', (config.maxSec + 5) * 1000);
  if (!response.ok) throw new Error(`Phone event stream failed: HTTP ${response.status}`);
  return readSseChunksWithDeadline(response, config, onEvent);
}
```

Replace the comment inside `fixedFastPathPlan` with the current implementation from `openclaw-phone-agent.mjs`. Do not change matching rules during extraction.

- [ ] **Step 2: Update CLI to call shared core**

In `scripts\openclaw-phone-agent.mjs`, import:

```js
import {
  runPhoneCommand,
  getPhoneMetrics,
  syncPhoneEvents,
} from './lib/phone-command-core.mjs';
```

In the `run` branch, replace the inline fast-path and Agent execution block with:

```js
const result = await runPhoneCommand(config);
await appendHistory({
  command: config.command,
  status: result.ok ? 'success' : 'error',
  submittedAt: new Date().toISOString(),
  finishedAt: new Date().toISOString(),
  taskId: result.taskId || '',
  mode: result.mode || '',
  metrics: result.metrics || {},
  summary: result.currentStep || '',
  error: result.error || '',
});
print(config, result, result.ok ? summarizeFastPath(result) : result.error);
return;
```

Keep `submit`, `status`, and `cancel` behavior direct if extraction would make this task too large.

- [ ] **Step 3: Run existing fast-path tests**

Run:

```powershell
node --test scripts\openclaw-phone-agent-fast-path.test.mjs
node --check scripts\openclaw-phone-agent.mjs
node --check scripts\lib\phone-command-core.mjs
```

Expected: all pass.

## Task 3: Implement Queue Primitives

**Files:**

- Create: `D:\Axiangmu\AUSTART\openclaw_new_launcher\scripts\lib\phone-daemon\queue.mjs`

**Interfaces:**

- Produces:

```js
export class SerialQueue
export class LimitQueue
```

- [ ] **Step 1: Write queue tests inside daemon test file**

Add:

```js
test('SerialQueue runs one task at a time', async () => {
  const { SerialQueue } = await import('./lib/phone-daemon/queue.mjs');
  const queue = new SerialQueue();
  let active = 0;
  let maxActive = 0;
  await Promise.all([1, 2, 3].map((id) => queue.enqueue(async () => {
    active += 1;
    maxActive = Math.max(maxActive, active);
    await new Promise((resolve) => setTimeout(resolve, 10));
    active -= 1;
    return id;
  })));
  assert.equal(maxActive, 1);
});

test('LimitQueue respects configured concurrency', async () => {
  const { LimitQueue } = await import('./lib/phone-daemon/queue.mjs');
  const queue = new LimitQueue(2);
  let active = 0;
  let maxActive = 0;
  await Promise.all([1, 2, 3, 4].map((id) => queue.enqueue(async () => {
    active += 1;
    maxActive = Math.max(maxActive, active);
    await new Promise((resolve) => setTimeout(resolve, 10));
    active -= 1;
    return id;
  })));
  assert.equal(maxActive, 2);
});
```

- [ ] **Step 2: Implement the queues**

Create:

```js
export class SerialQueue {
  constructor() {
    this.tail = Promise.resolve();
    this.depth = 0;
  }

  enqueue(fn) {
    this.depth += 1;
    const run = this.tail.then(fn, fn);
    this.tail = run.catch(() => {});
    return run.finally(() => {
      this.depth -= 1;
    });
  }
}

export class LimitQueue {
  constructor(limit) {
    if (!Number.isInteger(limit) || limit < 1) throw new Error('invalid_queue_limit');
    this.limit = limit;
    this.active = 0;
    this.pending = [];
  }

  enqueue(fn) {
    return new Promise((resolve, reject) => {
      this.pending.push({ fn, resolve, reject });
      this.pump();
    });
  }

  pump() {
    while (this.active < this.limit && this.pending.length) {
      const item = this.pending.shift();
      this.active += 1;
      Promise.resolve()
        .then(item.fn)
        .then(item.resolve, item.reject)
        .finally(() => {
          this.active -= 1;
          this.pump();
        });
    }
  }

  get depth() {
    return this.pending.length + this.active;
  }
}
```

- [ ] **Step 3: Run queue tests**

Run:

```powershell
node --test scripts\openclaw-phone-daemon.test.mjs --test-name-pattern "Queue|queue"
```

Expected: queue tests pass. Daemon process tests may still fail until Task 4.

## Task 4: Implement DeviceSession

**Files:**

- Create: `D:\Axiangmu\AUSTART\openclaw_new_launcher\scripts\lib\phone-daemon\device-session.mjs`

**Interfaces:**

- Consumes:

```js
import { runPhoneCommand, commandQueueKind, QUEUE_KIND } from '../phone-command-core.mjs';
```

- Produces:

```js
export class DeviceSession {
  constructor(deviceKey, options)
  run(config)
  status()
  rememberEvent(event)
  recentEvents(limit)
}
```

- [ ] **Step 1: Implement session routing**

Create:

```js
import { QUEUE_KIND, commandQueueKind, runPhoneCommand } from '../phone-command-core.mjs';
import { LimitQueue, SerialQueue } from './queue.mjs';

export class DeviceSession {
  constructor(deviceKey, options = {}) {
    this.deviceKey = deviceKey;
    this.createdAt = Date.now();
    this.lastUsedAt = 0;
    this.actionQueue = new SerialQueue();
    this.readQueue = new LimitQueue(options.readConcurrency || 4);
    this.screenshotQueue = new LimitQueue(options.screenshotConcurrency || 2);
    this.events = [];
  }

  run(config) {
    this.lastUsedAt = Date.now();
    const kind = commandQueueKind(config);
    const queue =
      kind === QUEUE_KIND.READ ? this.readQueue :
      kind === QUEUE_KIND.SCREENSHOT ? this.screenshotQueue :
      this.actionQueue;
    return queue.enqueue(() => runPhoneCommand(config));
  }

  rememberEvent(event) {
    this.events.push({ receivedAt: new Date().toISOString(), ...event });
    if (this.events.length > 200) this.events.splice(0, this.events.length - 200);
  }

  recentEvents(limit = 20) {
    return this.events.slice(-Math.max(0, Math.min(200, Number(limit) || 20)));
  }

  status() {
    return {
      deviceKey: this.deviceKey,
      createdAt: new Date(this.createdAt).toISOString(),
      lastUsedAt: this.lastUsedAt ? new Date(this.lastUsedAt).toISOString() : '',
      queues: {
        actionDepth: this.actionQueue.depth,
        readDepth: this.readQueue.depth,
        screenshotDepth: this.screenshotQueue.depth,
      },
      recentEventCount: this.events.length,
    };
  }
}
```

- [ ] **Step 2: Run syntax checks**

Run:

```powershell
node --check scripts\lib\phone-daemon\device-session.mjs
node --check scripts\lib\phone-daemon\queue.mjs
```

Expected: no output and exit code 0.

## Task 5: Implement Runtime Auth and Local Daemon Server

**Files:**

- Create: `D:\Axiangmu\AUSTART\openclaw_new_launcher\scripts\lib\phone-daemon\runtime-auth.mjs`
- Create: `D:\Axiangmu\AUSTART\openclaw_new_launcher\scripts\openclaw-phone-daemon.mjs`

**Interfaces:**

- Produces:

```js
export async function createRuntimeState(port)
export async function readRuntimeState()
export function daemonAuthHeaders(runtime)
```

- [ ] **Step 1: Implement runtime auth**

Create:

```js
import crypto from 'node:crypto';
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const PROJECT_ROOT = path.resolve(__dirname, '..', '..', '..');
const RUNTIME_PATH = path.join(PROJECT_ROOT, 'data', '.openclaw', 'runtime', 'phone-daemon.json');

export async function createRuntimeState(port) {
  const runtime = {
    schema: 'loom.phone_daemon.runtime.v1',
    pid: process.pid,
    port,
    token: crypto.randomBytes(32).toString('base64url'),
    startedAt: new Date().toISOString(),
  };
  await fs.mkdir(path.dirname(RUNTIME_PATH), { recursive: true });
  await fs.writeFile(RUNTIME_PATH, `${JSON.stringify(runtime, null, 2)}\n`, 'utf8');
  return runtime;
}

export async function readRuntimeState() {
  return JSON.parse(await fs.readFile(RUNTIME_PATH, 'utf8'));
}

export function daemonAuthHeaders(runtime) {
  return { 'X-LOOM-PHONE-DAEMON-TOKEN': runtime.token };
}

export function isAuthorized(request, runtime) {
  return request.headers['x-loom-phone-daemon-token'] === runtime.token;
}
```

- [ ] **Step 2: Implement daemon HTTP server and stdio mode**

Create `scripts\openclaw-phone-daemon.mjs`:

```js
#!/usr/bin/env node

import http from 'node:http';
import { createInterface } from 'node:readline';
import { DeviceSession } from './lib/phone-daemon/device-session.mjs';
import { createRuntimeState, isAuthorized } from './lib/phone-daemon/runtime-auth.mjs';
import { normalizePhoneUrl } from './openclaw-phone-secure.mjs';
import crypto from 'node:crypto';

const sessions = new Map();

function deviceKey(config) {
  const url = normalizePhoneUrl(config.phoneUrl);
  const tokenHash = crypto.createHash('sha256').update(String(config.phoneToken || ''), 'utf8').digest('hex');
  return crypto.createHash('sha256').update(`${url}:${tokenHash}`, 'utf8').digest('hex').slice(0, 24);
}

function sessionFor(config) {
  const key = deviceKey(config);
  let session = sessions.get(key);
  if (!session) {
    session = new DeviceSession(key);
    sessions.set(key, session);
  }
  return session;
}

async function handleRun(config) {
  const session = sessionFor(config);
  return session.run({ ...config, command: config.command || 'run' });
}

async function readJsonBody(request) {
  const chunks = [];
  for await (const chunk of request) chunks.push(chunk);
  const text = Buffer.concat(chunks).toString('utf8');
  return text ? JSON.parse(text) : {};
}

async function writeJson(response, status, payload) {
  response.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' });
  response.end(JSON.stringify(payload));
}

async function startHttpServer() {
  let runtime;
  const server = http.createServer(async (request, response) => {
    try {
      if (request.url === '/health') {
        await writeJson(response, 200, { ok: true, pid: process.pid, sessions: sessions.size });
        return;
      }
      if (!isAuthorized(request, runtime)) {
        await writeJson(response, 401, { ok: false, error: 'daemon_unauthorized' });
        return;
      }
      if (request.method === 'POST' && request.url === '/v1/run') {
        const body = await readJsonBody(request);
        await writeJson(response, 200, await handleRun(body));
        return;
      }
      if (request.method === 'POST' && request.url === '/shutdown') {
        await writeJson(response, 200, { ok: true, stopping: true });
        server.close(() => process.exit(0));
        return;
      }
      await writeJson(response, 404, { ok: false, error: 'not_found' });
    } catch (error) {
      await writeJson(response, 500, { ok: false, error: error?.message || String(error) });
    }
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  runtime = await createRuntimeState(server.address().port);
  console.log(JSON.stringify({ ok: true, type: 'phone_daemon_started', port: runtime.port, pid: runtime.pid }));
}

async function startStdioServer() {
  const rl = createInterface({ input: process.stdin });
  for await (const line of rl) {
    if (!line.trim()) continue;
    try {
      const body = JSON.parse(line);
      console.log(JSON.stringify(await handleRun(body)));
    } catch (error) {
      console.log(JSON.stringify({ ok: false, error: error?.message || String(error) }));
    }
  }
}

if (process.argv.includes('--stdio-json')) await startStdioServer();
else await startHttpServer();
```

- [ ] **Step 3: Run daemon tests**

Run:

```powershell
node --test scripts\openclaw-phone-daemon.test.mjs
```

Expected: daemon contract tests pass after Task 2 extraction is complete.

## Task 6: Add CLI Daemon Client and Compatibility Switch

**Files:**

- Create: `D:\Axiangmu\AUSTART\openclaw_new_launcher\scripts\lib\phone-daemon\client.mjs`
- Modify: `D:\Axiangmu\AUSTART\openclaw_new_launcher\scripts\openclaw-phone-agent.mjs`

**Interfaces:**

- Produces:

```js
export async function runViaDaemon(config)
export async function tryRunViaDaemon(config)
export async function ensureDaemon()
```

- [ ] **Step 1: Implement daemon client**

Create:

```js
import { spawn } from 'node:child_process';
import { setTimeout as sleep } from 'node:timers/promises';
import { daemonAuthHeaders, readRuntimeState } from './runtime-auth.mjs';

async function health(runtime) {
  const response = await fetch(`http://127.0.0.1:${runtime.port}/health`);
  if (!response.ok) throw new Error(`daemon_health_http_${response.status}`);
  return response.json();
}

export async function ensureDaemon() {
  try {
    const runtime = await readRuntimeState();
    await health(runtime);
    return runtime;
  } catch {
    const child = spawn(process.execPath, ['scripts/openclaw-phone-daemon.mjs'], {
      cwd: process.cwd(),
      detached: true,
      stdio: 'ignore',
      windowsHide: true,
    });
    child.unref();
    for (let i = 0; i < 20; i += 1) {
      await sleep(100);
      try {
        const runtime = await readRuntimeState();
        await health(runtime);
        return runtime;
      } catch {
        continue;
      }
    }
    throw new Error('daemon_start_timeout');
  }
}

export async function runViaDaemon(config) {
  const runtime = await ensureDaemon();
  const response = await fetch(`http://127.0.0.1:${runtime.port}/v1/run`, {
    method: 'POST',
    headers: {
      ...daemonAuthHeaders(runtime),
      'Content-Type': 'application/json; charset=utf-8',
      Accept: 'application/json',
    },
    body: JSON.stringify({ schema: 'loom.phone_daemon.run.v1', requestId: crypto.randomUUID(), ...config }),
  });
  const payload = await response.json();
  if (!response.ok || payload.ok === false) throw new Error(payload.error || `daemon_http_${response.status}`);
  return payload;
}

export async function tryRunViaDaemon(config) {
  try {
    return { usedDaemon: true, result: await runViaDaemon(config) };
  } catch (error) {
    return { usedDaemon: false, error };
  }
}
```

Add missing import at top:

```js
import crypto from 'node:crypto';
```

- [ ] **Step 2: Add CLI flag**

In `parseArgs`, add:

```js
daemon: 'auto',
```

In the switch:

```js
case '--daemon':
  args.daemon = next().toLowerCase();
  if (!['auto', 'off', 'require'].includes(args.daemon)) throw new Error('Invalid --daemon, expected auto|off|require');
  break;
```

In usage text:

```text
  --daemon <auto|off|require>  Default: auto. Reuse local phone-agent daemon when possible.
```

- [ ] **Step 3: Route run through daemon in auto mode**

Near the start of the `run` command branch:

```js
if (config.command === 'run' && config.daemon !== 'off') {
  const daemonAttempt = await tryRunViaDaemon(config);
  if (daemonAttempt.usedDaemon) {
    print(config, daemonAttempt.result, daemonAttempt.result.currentStep || daemonAttempt.result.mode || 'daemon result');
    return;
  }
  if (config.daemon === 'require') {
    throw new Error(`daemon_required: ${daemonAttempt.error?.message || daemonAttempt.error}`);
  }
}
```

Direct mode remains the fallback path.

- [ ] **Step 4: Run compatibility tests**

Run:

```powershell
node --test scripts\openclaw-phone-agent-fast-path.test.mjs
node --test scripts\openclaw-phone-daemon.test.mjs
node --check scripts\openclaw-phone-agent.mjs
node --check scripts\openclaw-phone-daemon.mjs
node --check scripts\lib\phone-daemon\client.mjs
```

Expected: all pass.

## Task 7: Add Python Bridge Contract

**Files:**

- Create: `D:\Axiangmu\AUSTART\openclaw_new_launcher\python\tests\test_phone_daemon_contract.py`
- Modify: `D:\Axiangmu\AUSTART\openclaw_new_launcher\python\api\routes_phone.py`

**Interfaces:**

- Produces:

```text
GET  /api/phone/daemon/status
POST /api/phone/daemon/start
POST /api/phone/daemon/stop
```

- [ ] **Step 1: Write Python contract tests**

Add:

```python
import json
import unittest
from unittest.mock import patch

from python.api import routes_phone


class PhoneDaemonContractTest(unittest.TestCase):
    def test_phone_agent_command_uses_daemon_auto_flag(self):
        cmd = routes_phone.build_phone_agent_command({
            "prompt": "打开系统设置",
            "mode": "safe",
            "json": True,
        })
        self.assertIn("--daemon", cmd)
        self.assertIn("auto", cmd)

    @patch("python.api.routes_phone.subprocess.Popen")
    def test_daemon_start_route_spawns_node_daemon(self, popen):
        popen.return_value.pid = 123
        result = routes_phone.start_phone_daemon()
        self.assertTrue(result["ok"])
        args = popen.call_args.args[0]
        self.assertIn("openclaw-phone-daemon.mjs", " ".join(args))

    def test_daemon_status_missing_runtime_is_structured(self):
        with patch("python.api.routes_phone.read_phone_daemon_runtime", side_effect=FileNotFoundError()):
            result = routes_phone.phone_daemon_status()
        self.assertFalse(result["running"])
        self.assertEqual(result["state"], "stopped")
```

If existing helper names differ, add thin wrappers with these exact names in `routes_phone.py` and route the HTTP handlers through them.

- [ ] **Step 2: Implement route helpers**

In `routes_phone.py`, add helpers:

```python
def build_phone_agent_command(payload: dict) -> list[str]:
    cmd = [
        node_executable(),
        str(OPENCLAW_ROOT / "scripts" / "openclaw-phone-agent.mjs"),
        "run",
        "--daemon",
        str(payload.get("daemon") or "auto"),
    ]
    if payload.get("prompt"):
        cmd.extend(["--prompt", str(payload["prompt"])])
    if payload.get("mode"):
        cmd.extend(["--mode", str(payload["mode"])])
    if payload.get("json", True):
        cmd.append("--json")
    return cmd

def start_phone_daemon() -> dict:
    proc = subprocess.Popen(
        [node_executable(), str(OPENCLAW_ROOT / "scripts" / "openclaw-phone-daemon.mjs")],
        cwd=str(OPENCLAW_ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    return {"ok": True, "pid": proc.pid, "state": "starting"}

def read_phone_daemon_runtime() -> dict:
    path = OPENCLAW_ROOT / "data" / ".openclaw" / "runtime" / "phone-daemon.json"
    return json.loads(path.read_text(encoding="utf-8"))

def phone_daemon_status() -> dict:
    try:
        runtime = read_phone_daemon_runtime()
        return {"ok": True, "running": True, "state": "running", "pid": runtime.get("pid"), "port": runtime.get("port")}
    except FileNotFoundError:
        return {"ok": True, "running": False, "state": "stopped"}
```

- [ ] **Step 3: Run Python tests**

Run:

```powershell
python -m unittest python.tests.test_phone_daemon_contract python.tests.test_phone_signature_contract python.tests.test_phone_fast_path_contract
```

Expected: all pass.

## Task 8: Add Event Cache to Daemon

**Files:**

- Modify: `D:\Axiangmu\AUSTART\openclaw_new_launcher\scripts\lib\phone-daemon\device-session.mjs`
- Modify: `D:\Axiangmu\AUSTART\openclaw_new_launcher\scripts\openclaw-phone-daemon.mjs`

**Interfaces:**

- Produces:

```text
GET /v1/events/recent?deviceKey=<key>&limit=20
```

- [ ] **Step 1: Add recent event endpoint**

In daemon server:

```js
if (request.method === 'GET' && request.url.startsWith('/v1/events/recent')) {
  const url = new URL(request.url, 'http://127.0.0.1');
  const key = url.searchParams.get('deviceKey') || '';
  const limit = Number(url.searchParams.get('limit') || 20);
  const session = sessions.get(key);
  await writeJson(response, 200, {
    ok: true,
    deviceKey: key,
    events: session ? session.recentEvents(limit) : [],
  });
  return;
}
```

- [ ] **Step 2: Add device status endpoint**

```js
if (request.method === 'GET' && request.url.startsWith('/v1/device-status')) {
  const url = new URL(request.url, 'http://127.0.0.1');
  const key = url.searchParams.get('deviceKey') || '';
  const session = sessions.get(key);
  await writeJson(response, 200, {
    ok: true,
    deviceKey: key,
    status: session ? session.status() : { deviceKey: key, queues: { actionDepth: 0, readDepth: 0, screenshotDepth: 0 } },
  });
  return;
}
```

- [ ] **Step 3: Test status endpoint**

Add a daemon test that runs one command, calls `/v1/device-status`, and asserts `queues.actionDepth === 0` after completion.

Run:

```powershell
node --test scripts\openclaw-phone-daemon.test.mjs
```

Expected: all pass.

## Task 9: Real Emulator Validation and Pressure Test

**Files:**

- Modify: `D:\Axiangmu\AUSTART\openclaw_new_launcher\docs\APKCLAW_LOOM_FAST_PATH_STRESS_2026-07-02.md`

**Interfaces:**

- Produces updated validation evidence.

- [ ] **Step 1: Start daemon**

Run:

```powershell
node scripts\openclaw-phone-daemon.mjs
```

Expected first line:

```json
{"ok":true,"type":"phone_daemon_started","port":19731,"pid":12345}
```

- [ ] **Step 2: Verify CLI daemon mode**

Run:

```powershell
node scripts\openclaw-phone-agent.mjs run --daemon require --phone-url http://127.0.0.1:19527 --phone-token apkclaw-test-token-20260702 --prompt "打开系统设置" --json --step-timeout-sec 8 --timeout-sec 30 --max-wait-sec 30
```

Expected:

```json
{
  "ok": true,
  "mode": "action_fast",
  "metrics": { "rounds": 0 }
}
```

- [ ] **Step 3: Run daemon pressure script**

Run the same pressure shape used in the latest report:

```powershell
node scripts\openclaw-phone-agent.mjs run --daemon require --phone-url http://127.0.0.1:19527 --phone-token apkclaw-test-token-20260702 --execution-layer template --template read-screen --prompt "read screen" --json --step-timeout-sec 8 --timeout-sec 30 --max-wait-sec 30
```

Then run batches:

- `observe_fast`: 100 calls, concurrency 16.
- `screenshot`: 30 calls, concurrency 6.
- `open-settings`: 60 calls, concurrency 16.
- mixed `open-settings/home/back/read-screen`: 100 calls, concurrency 12.

Acceptance targets:

| Suite | Success | Wall P50 target | Device P50 target |
| --- | ---: | ---: | ---: |
| `observe_fast` | 100 percent | under 250ms | under 10ms |
| `screenshot` | 100 percent | under 700ms | under 700ms |
| `open-settings` | 100 percent | under 500ms | under 30ms |
| mixed | no Lumi signature failures | under 800ms for non-blocked calls | mode remains fast path |

- [ ] **Step 4: Update report**

Append a new section to:

```text
D:\Axiangmu\AUSTART\openclaw_new_launcher\docs\APKCLAW_LOOM_FAST_PATH_STRESS_2026-07-02.md
```

Use this format:

```markdown
## Daemon Pressure Update

- Date:
- APKClaw version:
- LOOM commit/worktree:
- Daemon mode:
- Results table:
- Failures:
- Remaining bottleneck:
```

## Rollback Plan

Rollback is simple because the old direct path remains:

```powershell
node scripts\openclaw-phone-agent.mjs run --daemon off --prompt "打开系统设置" --json
```

Disable daemon globally:

```powershell
$env:OPENCLAW_PHONE_DAEMON = "off"
```

Delete runtime file if it points to a stale daemon:

```powershell
Remove-Item -LiteralPath D:\Axiangmu\AUSTART\openclaw_new_launcher\data\.openclaw\runtime\phone-daemon.json -Force
```

Do not revert APKClaw. This plan is LOOM-side and does not require changing the installed APK.

## Final Verification Checklist

- [ ] `node --test scripts\openclaw-phone-agent-fast-path.test.mjs`
- [ ] `node --test scripts\openclaw-phone-daemon.test.mjs`
- [ ] `node --check scripts\openclaw-phone-agent.mjs`
- [ ] `node --check scripts\openclaw-phone-daemon.mjs`
- [ ] `node --check scripts\lib\phone-command-core.mjs`
- [ ] `node --check scripts\lib\phone-daemon\client.mjs`
- [ ] `node --check scripts\lib\phone-daemon\device-session.mjs`
- [ ] `node --check scripts\lib\phone-daemon\queue.mjs`
- [ ] `python -m unittest python.tests.test_phone_daemon_contract python.tests.test_phone_signature_contract python.tests.test_phone_fast_path_contract`
- [ ] Real emulator `observe_fast` smoke passes.
- [ ] Real emulator screenshot smoke passes.
- [ ] Real emulator open-settings smoke passes with `--daemon require`.
- [ ] Mixed pressure test has no Lumi signature failures.

## Self-Review

- Spec coverage: The plan covers daemon process reuse, Lumi pairing reuse, HTTP pooling through a persistent Node process, per-device queueing, old CLI compatibility, Python route integration, event cache, pressure testing, and rollback.
- Placeholder scan: The plan contains no unresolved marker text, and each task has concrete paths, commands, and expected results.
- Type consistency: `DeviceSession.run(config)`, `commandQueueKind(config)`, `runPhoneCommand(config)`, `runViaDaemon(config)`, and daemon `/v1/run` request/response are used consistently across tasks.
