import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import http from 'node:http';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { spawn } from 'node:child_process';
import { createRuntimeState, daemonAuthHeaders, deviceKeyFromConfig, readRuntimeState } from './lib/phone-daemon/runtime-auth.mjs';
import { DeviceSession } from './lib/phone-daemon/device-session.mjs';
import { tryGetMetricsViaDaemon, tryRunViaDaemon, trySyncEventsViaDaemon } from './lib/phone-daemon/client.mjs';
import { signedJsonRequest } from './openclaw-phone-secure.mjs';

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

async function fetchJson(url, init = {}) {
  const response = await fetch(url, init);
  const payload = await response.json();
  return { response, payload };
}

function waitFor(predicate, timeoutMs = 1000, pollMs = 5) {
  return new Promise((resolve, reject) => {
    const started = Date.now();
    const tick = () => {
      if (predicate()) {
        resolve();
        return;
      }
      if (Date.now() - started >= timeoutMs) {
        reject(new Error('timed out waiting for test condition'));
        return;
      }
      setTimeout(tick, pollMs);
    };
    tick();
  });
}

function createDaemonJsonReader(daemon) {
  const lines = [];
  const waiters = [];
  let stderr = '';

  daemon.stderr.on('data', (chunk) => {
    stderr += chunk.toString('utf8');
  });
  daemon.stdout.on('data', (chunk) => {
    for (const line of chunk.toString('utf8').split(/\r?\n/).filter(Boolean)) {
      const waiter = waiters.shift();
      if (waiter) waiter.resolve(line);
      else lines.push(line);
    }
  });

  const nextLine = (timeoutMs = 5000) => {
    if (lines.length) return Promise.resolve(lines.shift());
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        reject(new Error('timed out waiting for daemon stdout'));
      }, timeoutMs);
      waiters.push({
        resolve: (line) => {
          clearTimeout(timer);
          resolve(line);
        },
        reject,
      });
    });
  };

  daemon.on('error', (error) => {
    while (waiters.length) waiters.shift().reject(error);
  });
  daemon.on('exit', (code, signal) => {
    const error = new Error(stderr.trim() || `daemon exited before stdout with code ${code} signal ${signal}`);
    while (waiters.length) waiters.shift().reject(error);
  });

  return {
    async read() {
      return JSON.parse(await nextLine());
    },
  };
}

const RUNTIME_PATH = new URL('../data/.openclaw/runtime/phone-daemon.json', import.meta.url);

async function backupRuntimeFile() {
  try {
    return { exists: true, text: await fs.readFile(RUNTIME_PATH, 'utf8') };
  } catch (error) {
    if (error?.code !== 'ENOENT') throw error;
    return { exists: false, text: '' };
  }
}

async function restoreRuntimeFile(backup) {
  if (backup?.exists) {
    await fs.writeFile(RUNTIME_PATH, backup.text, 'utf8');
    return;
  }
  await fs.rm(RUNTIME_PATH, { force: true });
}

async function withTempCwd(handler) {
  const originalCwd = process.cwd();
  const tempDir = await fs.mkdtemp(path.join(os.tmpdir(), 'loom-phone-daemon-client-'));
  try {
    process.chdir(tempDir);
    return await handler();
  } finally {
    process.chdir(originalCwd);
    await fs.rm(tempDir, { recursive: true, force: true });
  }
}

async function withRuntimeSandbox(handler) {
  const backup = await backupRuntimeFile();
  try {
    return await handler();
  } finally {
    await restoreRuntimeFile(backup);
  }
}

async function startHttpDaemon() {
  const daemon = spawn(process.execPath, ['scripts/openclaw-phone-daemon.mjs'], {
    cwd: process.cwd(),
    windowsHide: true,
    stdio: ['pipe', 'pipe', 'pipe'],
  });
  const reader = createDaemonJsonReader(daemon);
  const started = await reader.read();
  assert.equal(started.ok, true);
  assert.equal(started.type, 'phone_daemon_started');
  const runtime = await readRuntimeState();
  return { daemon, runtime, port: started.port };
}

async function shutdownRuntimeDaemon(runtime) {
  if (!runtime?.port) return;
  try {
    await fetch(`http://127.0.0.1:${runtime.port}/shutdown`, {
      method: 'POST',
      headers: {
        ...daemonAuthHeaders(runtime),
        'Content-Type': 'application/json; charset=utf-8',
      },
      body: '{}',
    });
  } catch {
    // Test cleanup only; the runtime sandbox restores the runtime file.
  }
}

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

test('daemon health endpoint requires the random runtime token', async () => {
  await withRuntimeSandbox(async () => {
    const { daemon, runtime } = await startHttpDaemon();
    try {
      const denied = await fetch(`http://127.0.0.1:${runtime.port}/health`);
      const deniedPayload = await denied.json();
      assert.equal(denied.status, 401);
      assert.equal(deniedPayload.ok, false);
      assert.equal(deniedPayload.error, 'daemon_unauthorized');

      const allowed = await fetch(`http://127.0.0.1:${runtime.port}/health`, {
        headers: daemonAuthHeaders(runtime),
      });
      const allowedPayload = await allowed.json();
      assert.equal(allowed.status, 200);
      assert.equal(allowedPayload.ok, true);
      assert.equal(typeof allowedPayload.pid, 'number');
    } finally {
      daemon.kill();
    }
  });
});

test('daemon client routes metrics and events-sync through authenticated daemon endpoints', async () => {
  const seen = [];
  const fake = await startFakePhone(async (request, response) => {
    seen.push(`${request.method} ${request.url}`);
    if (request.url === '/api/lumi/security/pair') {
      const body = await readJson(request);
      response.writeHead(200, { 'Content-Type': 'application/json' });
      response.end(JSON.stringify({ success: true, data: { launcherId: body.launcherId, launcherSecret: 'daemon-events-secret' } }));
      return;
    }
    if (request.url === '/api/device/status') {
      response.writeHead(200, { 'Content-Type': 'application/json' });
      response.end(JSON.stringify({
        success: true,
        data: {
          configServerRunning: true,
          accessibilityEnabled: true,
          agentInitialized: true,
          modelConfigured: true,
        },
      }));
      return;
    }
    if (request.url === '/api/lumi/agent/metrics?_lumi=1') {
      response.writeHead(200, { 'Content-Type': 'application/json' });
      response.end(JSON.stringify({ success: true, data: { metrics: { taskCount: 2, queueDepth: 1 } } }));
      return;
    }
    if (request.url === '/api/lumi/events') {
      response.writeHead(200, {
        'Content-Type': 'text/event-stream; charset=utf-8',
        'Cache-Control': 'no-store',
      });
      response.write('id: e1\nevent: running\ndata: {"step":"observe"}\n\n');
      await new Promise((resolve) => setTimeout(resolve, 120));
      response.write('id: e2\nevent: done\ndata: {"ok":true}\n\n');
      response.end();
      return;
    }
    throw new Error(`unexpected ${request.method} ${request.url}`);
  });

  try {
    await withRuntimeSandbox(async () => {
      const { daemon } = await startHttpDaemon();
      try {
        const config = {
          command: 'events-sync',
          phoneUrl: fake.baseUrl,
          phoneToken: 'test-token-daemon-events',
          stepTimeoutSec: 8,
          timeoutSec: 30,
          maxWaitSec: 30,
          maxSec: 2,
          maxEvents: 2,
        };

        const metricsAttempt = await tryGetMetricsViaDaemon({ ...config, command: 'metrics' });
        assert.equal(metricsAttempt.usedDaemon, true);
        assert.equal(metricsAttempt.error, undefined);
        assert.equal(metricsAttempt.result.ok, true);
        assert.equal(metricsAttempt.result.metrics.taskCount, 2);
        assert.equal(metricsAttempt.result.metrics.queueDepth, 1);

        const streamedEvents = [];
        let syncDone = false;
        const syncPromise = trySyncEventsViaDaemon(config, (event) => {
          streamedEvents.push(event);
        }).finally(() => {
          syncDone = true;
        });
        await waitFor(() => streamedEvents.length >= 1, 500);
        assert.equal(syncDone, false);
        const eventsAttempt = await syncPromise;
        assert.equal(eventsAttempt.usedDaemon, true);
        assert.equal(eventsAttempt.error, undefined);
        assert.equal(eventsAttempt.result.ok, true);
        assert.equal(eventsAttempt.result.events.length, 2);
        assert.equal(streamedEvents.length, 2);
        assert.equal(eventsAttempt.result.summary.eventCount, 2);
        assert.equal(eventsAttempt.result.summary.stoppedBy, 'max_events');
        assert.equal(seen.some((line) => line === 'GET /api/lumi/agent/metrics?_lumi=1'), true);
        assert.equal(seen.some((line) => line === 'GET /api/lumi/events'), true);
      } finally {
        daemon.kill();
      }
    });
  } finally {
    fake.server.close();
  }
});

test('daemon serializes same-device events-sync streams', async () => {
  let activeStreams = 0;
  let maxActiveStreams = 0;
  let eventStreamRequests = 0;

  const fake = await startFakePhone(async (request, response) => {
    if (request.url === '/api/lumi/security/pair') {
      const body = await readJson(request);
      response.writeHead(200, { 'Content-Type': 'application/json' });
      response.end(JSON.stringify({ success: true, data: { launcherId: body.launcherId, launcherSecret: 'daemon-event-queue-secret' } }));
      return;
    }
    if (request.url === '/api/device/status') {
      response.writeHead(200, { 'Content-Type': 'application/json' });
      response.end(JSON.stringify({
        success: true,
        data: {
          configServerRunning: true,
          accessibilityEnabled: true,
          agentInitialized: true,
          modelConfigured: true,
        },
      }));
      return;
    }
    if (request.url === '/api/lumi/events') {
      eventStreamRequests += 1;
      activeStreams += 1;
      maxActiveStreams = Math.max(maxActiveStreams, activeStreams);
      response.writeHead(200, {
        'Content-Type': 'text/event-stream; charset=utf-8',
        'Cache-Control': 'no-store',
      });
      response.write(`id: ${eventStreamRequests}-a\nevent: running\ndata: {"request":${eventStreamRequests}}\n\n`);
      await new Promise((resolve) => setTimeout(resolve, 80));
      response.write(`id: ${eventStreamRequests}-b\nevent: done\ndata: {"request":${eventStreamRequests}}\n\n`);
      activeStreams -= 1;
      response.end();
      return;
    }
    throw new Error(`unexpected ${request.method} ${request.url}`);
  });

  try {
    await withRuntimeSandbox(async () => {
      const { daemon } = await startHttpDaemon();
      try {
        const config = {
          command: 'events-sync',
          phoneUrl: fake.baseUrl,
          phoneToken: 'test-token-daemon-event-queue',
          stepTimeoutSec: 8,
          timeoutSec: 30,
          maxWaitSec: 30,
          maxSec: 2,
          maxEvents: 2,
        };

        const [first, second] = await Promise.all([
          trySyncEventsViaDaemon({ ...config, requestId: 'events-a' }),
          trySyncEventsViaDaemon({ ...config, requestId: 'events-b' }),
        ]);

        assert.equal(first.usedDaemon, true);
        assert.equal(second.usedDaemon, true);
        assert.equal(first.error, undefined);
        assert.equal(second.error, undefined);
        assert.equal(first.result.events.length, 2);
        assert.equal(second.result.events.length, 2);
        assert.equal(eventStreamRequests, 2);
        assert.equal(maxActiveStreams, 1);
      } finally {
        daemon.kill();
      }
    });
  } finally {
    fake.server.close();
  }
});

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
    if (request.url.startsWith('/api/lumi/agent/action_fast')) {
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
    const reader = createDaemonJsonReader(daemon);
    daemon.stdin.write(`${JSON.stringify({
      schema: 'loom.phone_daemon.run.v1',
      requestId: 'test-1',
      command: 'run',
      phoneUrl: fake.baseUrl,
      phoneToken: 'test-token',
      executionLayer: 'template',
      templateName: 'back',
      prompt: 'back',
      stepTimeoutSec: 8,
      timeoutSec: 30,
      maxWaitSec: 30
    })}\n`);
    const payload = await reader.read();
    daemon.kill();
    assert.equal(payload.ok, true);
    assert.equal(payload.mode, 'action_fast');
    assert.equal(payload.metrics.rounds, 0);
    assert.equal(seen.some((line) => line.includes('/api/lumi/agent/action_fast')), true);
    assert.equal(seen.some((line) => line.includes('/api/agent/tasks')), false);
  } finally {
    fake.server.close();
  }
});

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
    if (request.url.startsWith('/api/lumi/agent/action_fast')) {
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
    const reader = createDaemonJsonReader(daemon);
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
      const payload = await reader.read();
      outputs.push(payload);
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
    const reader = createDaemonJsonReader(daemon);
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
      const payload = await reader.read();
      outputs.push(payload);
    }
    daemon.kill();
    assert.equal(outputs.every((item) => item.ok), true);
    assert.equal(maxActiveReads > 1, true);
  } finally {
    fake.server.close();
  }
});

test('concurrent same-device signed requests reuse repaired pairing instead of rotating repeatedly', async () => {
  let pairCount = 0;
  let currentSecret = '';
  const firstAttempts = new Map();
  const first403Sent = new Set();
  const seenRetryIds = new Set();
  const requestLog = [];

  const fake = await startFakePhone(async (request, response) => {
    if (request.url === '/api/lumi/security/pair') {
      const body = await readJson(request);
      pairCount += 1;
      currentSecret = `secret-${pairCount}`;
      response.writeHead(200, { 'Content-Type': 'application/json' });
      response.end(JSON.stringify({
        success: true,
        data: {
          launcherId: body.launcherId,
          launcherSecret: currentSecret,
        }
      }));
      return;
    }

    if (request.url.startsWith('/api/lumi/agent/action_fast')) {
      const body = await readJson(request);
      const requestId = String(body.requestId || '');
      const bodyText = JSON.stringify(body);
      const timestamp = String(request.headers['x-lumi-timestamp'] || '');
      const nonce = String(request.headers['x-lumi-nonce'] || '');
      const bodyHash = crypto.createHash('sha256').update(bodyText, 'utf8').digest('hex');
      const signatureInput = ['POST', request.url, timestamp, nonce, bodyHash].join('\n');
      const expectedSignature = crypto.createHmac('sha256', currentSecret).update(signatureInput, 'utf8').digest('base64url');
      const valid =
        request.headers['x-lumi-launcher-id']
        && request.headers['x-lumi-body-sha256'] === bodyHash
        && request.headers['x-lumi-signature'] === expectedSignature;
      const attempt = (firstAttempts.get(requestId) || 0) + 1;
      firstAttempts.set(requestId, attempt);
      requestLog.push({ requestId, attempt, valid, pairCountAtReceipt: pairCount });

      if (attempt === 1) {
        if (requestId === 'a') {
          first403Sent.add('a');
        } else if (requestId === 'b') {
          await waitFor(() => pairCount >= 2);
          first403Sent.add('b');
        } else if (requestId === 'c') {
          await waitFor(() => seenRetryIds.has('b'));
          first403Sent.add('c');
        } else {
          throw new Error(`unexpected request id ${requestId}`);
        }
        response.writeHead(403, { 'Content-Type': 'application/json' });
        response.end(JSON.stringify({ success: false, error: 'Invalid Lumi signature' }));
        return;
      }

      seenRetryIds.add(requestId);
      if (requestId === 'b') {
        await waitFor(() => first403Sent.has('c'));
        await new Promise((resolve) => setTimeout(resolve, 30));
      }

      const finalBodyHash = crypto.createHash('sha256').update(bodyText, 'utf8').digest('hex');
      const finalSignature = crypto
        .createHmac('sha256', currentSecret)
        .update(['POST', request.url, timestamp, nonce, finalBodyHash].join('\n'), 'utf8')
        .digest('base64url');

      if (
        request.headers['x-lumi-body-sha256'] !== finalBodyHash
        || request.headers['x-lumi-signature'] !== finalSignature
      ) {
        response.writeHead(403, { 'Content-Type': 'application/json' });
        response.end(JSON.stringify({ success: false, error: 'Invalid Lumi signature' }));
        return;
      }

      response.writeHead(200, { 'Content-Type': 'application/json' });
      response.end(JSON.stringify({
        success: true,
        data: {
          requestId,
          currentStep: 'complete',
          mode: 'action_fast',
        }
      }));
      return;
    }

    throw new Error(`unexpected ${request.method} ${request.url}`);
  });

  try {
    const makeConfig = () => ({
      phoneUrl: fake.baseUrl,
      phoneToken: 'test-token-concurrency-safe',
    });
    const results = await Promise.all([
      signedJsonRequest(makeConfig(), 'POST', '/api/lumi/agent/action_fast', { requestId: 'a' }),
      signedJsonRequest(makeConfig(), 'POST', '/api/lumi/agent/action_fast', { requestId: 'b' }),
      signedJsonRequest(makeConfig(), 'POST', '/api/lumi/agent/action_fast', { requestId: 'c' }),
    ]);

    assert.deepEqual(results.map((item) => item.data.requestId).sort(), ['a', 'b', 'c']);
    assert.equal(pairCount, 2);
    assert.equal(firstAttempts.get('a'), 2);
    assert.equal(firstAttempts.get('b'), 2);
    assert.equal(firstAttempts.get('c'), 2);
    assert.equal(requestLog.some((entry) => entry.attempt === 2 && entry.valid === false), false);
  } finally {
    fake.server.close();
  }
});

test('signedJsonRequest repairs and retries once when payload reports Invalid Lumi signature with HTTP 200', async () => {
  let pairCount = 0;
  let actionCount = 0;
  let currentSecret = '';

  const fake = await startFakePhone(async (request, response) => {
    if (request.url === '/api/lumi/security/pair') {
      const body = await readJson(request);
      pairCount += 1;
      currentSecret = `secret-${pairCount}`;
      response.writeHead(200, { 'Content-Type': 'application/json' });
      response.end(JSON.stringify({
        success: true,
        data: {
          launcherId: body.launcherId,
          launcherSecret: currentSecret,
        }
      }));
      return;
    }

    if (request.url.startsWith('/api/lumi/agent/action_fast')) {
      actionCount += 1;
      if (actionCount === 1) {
        response.writeHead(200, { 'Content-Type': 'application/json' });
        response.end(JSON.stringify({ success: false, error: 'Invalid Lumi signature' }));
        return;
      }

      const body = await readJson(request);
      const bodyText = JSON.stringify(body);
      const timestamp = String(request.headers['x-lumi-timestamp'] || '');
      const nonce = String(request.headers['x-lumi-nonce'] || '');
      const bodyHash = crypto.createHash('sha256').update(bodyText, 'utf8').digest('hex');
      const signatureInput = ['POST', request.url, timestamp, nonce, bodyHash].join('\n');
      const expectedSignature = crypto
        .createHmac('sha256', currentSecret)
        .update(signatureInput, 'utf8')
        .digest('base64url');

      assert.equal(request.headers['x-lumi-body-sha256'], bodyHash);
      assert.equal(request.headers['x-lumi-signature'], expectedSignature);
      response.writeHead(200, { 'Content-Type': 'application/json' });
      response.end(JSON.stringify({
        success: true,
        data: {
          requestId: body.requestId,
          currentStep: 'complete',
          mode: 'action_fast',
        }
      }));
      return;
    }

    throw new Error(`unexpected ${request.method} ${request.url}`);
  });

  try {
    const result = await signedJsonRequest({
      phoneUrl: fake.baseUrl,
      phoneToken: 'test-token-payload-repair',
    }, 'POST', '/api/lumi/agent/action_fast', { requestId: 'payload-repair' });

    assert.equal(result.data.requestId, 'payload-repair');
    assert.equal(pairCount, 2);
    assert.equal(actionCount, 2);
  } finally {
    fake.server.close();
  }
});

test('DeviceSession serializes repaired Lumi retries across mixed read and action requests', async () => {
  let pairCount = 0;
  let currentSecret = '';
  let actionAttempts = 0;
  let readAttempts = 0;
  let actionRetryStarted = false;
  let readForcedRepair = false;

  function signatureValid(request, method, endpoint, bodyText) {
    const timestamp = String(request.headers['x-lumi-timestamp'] || '');
    const nonce = String(request.headers['x-lumi-nonce'] || '');
    const bodyHash = crypto.createHash('sha256').update(bodyText, 'utf8').digest('hex');
    const signatureInput = [method, endpoint, timestamp, nonce, bodyHash].join('\n');
    const expectedSignature = crypto
      .createHmac('sha256', currentSecret)
      .update(signatureInput, 'utf8')
      .digest('base64url');
    return (
      request.headers['x-lumi-body-sha256'] === bodyHash
      && request.headers['x-lumi-signature'] === expectedSignature
    );
  }

  const fake = await startFakePhone(async (request, response) => {
    if (request.url === '/api/lumi/security/pair') {
      const body = await readJson(request);
      pairCount += 1;
      currentSecret = `mixed-secret-${pairCount}`;
      response.writeHead(200, { 'Content-Type': 'application/json' });
      response.end(JSON.stringify({
        success: true,
        data: {
          launcherId: body.launcherId,
          launcherSecret: currentSecret,
        }
      }));
      return;
    }

    if (request.url === '/api/device/status') {
      response.writeHead(200, { 'Content-Type': 'application/json' });
      response.end(JSON.stringify({ success: true, data: { accessibilityEnabled: true, modelConfigured: false } }));
      return;
    }

    if (request.url.startsWith('/api/lumi/agent/action_fast')) {
      actionAttempts += 1;
      const body = await readJson(request);
      const bodyText = JSON.stringify(body);
      if (actionAttempts === 1) {
        response.writeHead(403, { 'Content-Type': 'application/json' });
        response.end(JSON.stringify({ success: false, error: 'Invalid Lumi signature' }));
        return;
      }

      actionRetryStarted = true;
      await Promise.race([
        waitFor(() => pairCount >= 3, 250),
        new Promise((resolve) => setTimeout(resolve, 80)),
      ]);

      if (!signatureValid(request, 'POST', request.url, bodyText)) {
        response.writeHead(403, { 'Content-Type': 'application/json' });
        response.end(JSON.stringify({ success: false, error: 'Invalid Lumi signature' }));
        return;
      }

      response.writeHead(200, { 'Content-Type': 'application/json' });
      response.end(JSON.stringify({
        success: true,
        data: {
          mode: 'action_fast',
          success: true,
          currentStep: 'complete',
          metrics: { totalMs: 5, rounds: 0 },
        }
      }));
      return;
    }

    if (request.url === '/api/lumi/agent/observe_fast?_lumi=1') {
      readAttempts += 1;
      await waitFor(() => actionRetryStarted);
      if (readAttempts === 1) {
        readForcedRepair = true;
        response.writeHead(403, { 'Content-Type': 'application/json' });
        response.end(JSON.stringify({ success: false, error: 'Invalid Lumi signature' }));
        return;
      }

      if (!signatureValid(request, 'GET', '/api/lumi/agent/observe_fast?_lumi=1', '')) {
        response.writeHead(403, { 'Content-Type': 'application/json' });
        response.end(JSON.stringify({ success: false, error: 'Invalid Lumi signature' }));
        return;
      }

      response.writeHead(200, { 'Content-Type': 'application/json' });
      response.end(JSON.stringify({
        success: true,
        data: {
          mode: 'observe_fast',
          success: true,
          currentStep: 'complete',
          metrics: { totalMs: 5, rounds: 0 },
        }
      }));
      return;
    }

    throw new Error(`unexpected ${request.method} ${request.url}`);
  });

  try {
    const session = new DeviceSession('mixed-race-device');
    const baseConfig = {
      command: 'run',
      mode: 'safe',
      executionLayer: 'agent',
      phoneUrl: fake.baseUrl,
      phoneToken: 'test-token-mixed-race',
      stepTimeoutSec: 8,
      timeoutSec: 30,
      maxWaitSec: 30,
    };

    const action = session.run({
      ...baseConfig,
      prompt: 'open settings',
    });
    await waitFor(() => actionRetryStarted);
    const read = session.run({
      ...baseConfig,
      executionLayer: 'template',
      templateName: 'read-screen',
      prompt: 'read screen',
    });

    const results = await Promise.all([action, read]);

    assert.equal(results.every((item) => item.ok), true);
    assert.equal(pairCount, 3);
    assert.equal(actionAttempts, 2);
    assert.equal(readAttempts, 2);
    assert.equal(readForcedRepair, true);
  } finally {
    fake.server.close();
  }
});

test('DeviceSession keeps read-then-action_fast on the fast path without the old quiet-guard delay', async () => {
  const oldGuardFloorMs = 500;
  let readFinishedAt = 0;
  let actionAttempts = 0;
  let actionStartedAt = 0;

  const fake = await startFakePhone(async (request, response) => {
    if (request.url === '/api/lumi/security/pair') {
      const body = await readJson(request);
      response.writeHead(200, { 'Content-Type': 'application/json' });
      response.end(JSON.stringify({
        success: true,
        data: {
          launcherId: body.launcherId,
          launcherSecret: 'read-action-secret',
        }
      }));
      return;
    }

    if (request.url === '/api/device/status') {
      response.writeHead(200, { 'Content-Type': 'application/json' });
      response.end(JSON.stringify({ success: true, data: { accessibilityEnabled: true, modelConfigured: true } }));
      return;
    }

    if (request.url === '/api/lumi/agent/observe_fast?_lumi=1') {
      readFinishedAt = Date.now();
      response.writeHead(200, { 'Content-Type': 'application/json' });
      response.end(JSON.stringify({
        success: true,
        data: {
          mode: 'observe_fast',
          success: true,
          currentStep: 'complete',
          metrics: { totalMs: 5, rounds: 0 },
        }
      }));
      return;
    }

    if (request.url.startsWith('/api/lumi/agent/action_fast')) {
      actionAttempts += 1;
      actionStartedAt = Date.now();

      response.writeHead(200, { 'Content-Type': 'application/json' });
      response.end(JSON.stringify({
        success: true,
        data: {
          mode: 'action_fast',
          success: true,
          currentStep: 'complete',
          metrics: { totalMs: 5, rounds: 0 },
        }
      }));
      return;
    }

    throw new Error(`unexpected ${request.method} ${request.url}`);
  });

  try {
    const session = new DeviceSession('read-action-transition-device');
    const baseConfig = {
      command: 'run',
      mode: 'safe',
      executionLayer: 'agent',
      phoneUrl: fake.baseUrl,
      phoneToken: 'test-token-read-action-transition',
      stepTimeoutSec: 8,
      timeoutSec: 30,
      maxWaitSec: 30,
    };

    const read = await session.run({
      ...baseConfig,
      executionLayer: 'template',
      templateName: 'read-screen',
      prompt: 'read screen',
    });
    const action = await session.run({
      ...baseConfig,
      prompt: 'open settings',
    });

    assert.equal(read.ok, true);
    assert.equal(action.ok, true);
    assert.equal(action.mode, 'action_fast');
    assert.equal(actionAttempts, 1);
    assert.ok(readFinishedAt > 0);
    assert.ok(actionStartedAt > 0);
    assert.ok(
      actionStartedAt - readFinishedAt < oldGuardFloorMs,
      `expected action_fast to start in under ${oldGuardFloorMs}ms after the read, got ${actionStartedAt - readFinishedAt}ms`,
    );
  } finally {
    fake.server.close();
  }
});

test('DeviceSession caches fast-path readiness across queued actions', async () => {
  let statusCount = 0;
  let actionCount = 0;

  const fake = await startFakePhone(async (request, response) => {
    if (request.url === '/api/lumi/security/pair') {
      const body = await readJson(request);
      response.writeHead(200, { 'Content-Type': 'application/json' });
      response.end(JSON.stringify({
        success: true,
        data: {
          launcherId: body.launcherId,
          launcherSecret: 'ready-cache-secret',
        }
      }));
      return;
    }

    if (request.url === '/api/device/status') {
      statusCount += 1;
      response.writeHead(200, { 'Content-Type': 'application/json' });
      response.end(JSON.stringify({ success: true, data: { accessibilityEnabled: true, modelConfigured: true } }));
      return;
    }

    if (request.url.startsWith('/api/lumi/agent/action_fast')) {
      actionCount += 1;
      response.writeHead(200, { 'Content-Type': 'application/json' });
      response.end(JSON.stringify({
        success: true,
        data: {
          mode: 'action_fast',
          success: true,
          currentStep: 'complete',
          metrics: { totalMs: 5, rounds: 0 },
        }
      }));
      return;
    }

    throw new Error(`unexpected ${request.method} ${request.url}`);
  });

  try {
    const session = new DeviceSession('ready-cache-device');
    const config = {
      command: 'run',
      mode: 'safe',
      executionLayer: 'template',
      templateName: 'open-settings',
      prompt: 'open settings',
      phoneUrl: fake.baseUrl,
      phoneToken: 'test-token-ready-cache',
      stepTimeoutSec: 8,
      timeoutSec: 30,
      maxWaitSec: 30,
    };

    const results = await Promise.all([
      session.run(config),
      session.run(config),
      session.run(config),
    ]);

    assert.equal(results.every((item) => item.ok && item.mode === 'action_fast'), true);
    assert.equal(actionCount, 1);
    assert.equal(statusCount, 1);
  } finally {
    fake.server.close();
  }
});

test('DeviceSession cancels queued daemon work before submitting another APKClaw task', async () => {
  const tempDir = await fs.mkdtemp(path.join(os.tmpdir(), 'loom-daemon-queued-cancel-'));
  const cancelFile = path.join(tempDir, 'queued.cancel');
  let taskSubmissions = 0;
  let releaseFirstPoll;
  const firstPollBarrier = new Promise((resolve) => {
    releaseFirstPoll = resolve;
  });
  let firstSubmitted;
  const firstSubmittedBarrier = new Promise((resolve) => {
    firstSubmitted = resolve;
  });
  const fake = await startFakePhone(async (request, response) => {
    if (request.url === '/api/lumi/security/pair') {
      const body = await readJson(request);
      response.writeHead(200, { 'Content-Type': 'application/json' });
      response.end(JSON.stringify({ success: true, data: { launcherId: body.launcherId, launcherSecret: 'queue-cancel-secret' } }));
      return;
    }
    if (request.url === '/api/device/status') {
      response.writeHead(200, { 'Content-Type': 'application/json' });
      response.end(JSON.stringify({ success: true, data: { accessibilityEnabled: true, modelConfigured: true } }));
      return;
    }
    if (request.url === '/api/lumi/agent/tasks') {
      taskSubmissions += 1;
      if (taskSubmissions === 1) firstSubmitted();
      response.writeHead(200, { 'Content-Type': 'application/json' });
      response.end(JSON.stringify({ success: true, data: { taskId: `task-${taskSubmissions}` } }));
      return;
    }
    if (request.url === '/api/lumi/agent/tasks/task-1') {
      await firstPollBarrier;
      response.writeHead(200, { 'Content-Type': 'application/json' });
      response.end(JSON.stringify({ success: true, data: { taskId: 'task-1', status: 'success', result: {} } }));
      return;
    }
    if (request.url === '/api/lumi/agent/tasks/task-2') {
      response.writeHead(200, { 'Content-Type': 'application/json' });
      response.end(JSON.stringify({ success: true, data: { taskId: 'task-2', status: 'success', result: {} } }));
      return;
    }
    throw new Error(`unexpected ${request.method} ${request.url}`);
  });

  try {
    const session = new DeviceSession('queued-cancel-device');
    const baseConfig = {
      command: 'run',
      mode: 'safe',
      executionLayer: 'agent',
      phoneUrl: fake.baseUrl,
      phoneToken: 'queue-cancel-token',
      stepTimeoutSec: 8,
      timeoutSec: 30,
      maxWaitSec: 30,
      maxRounds: 2,
      pollMs: 500,
    };
    const first = session.run({ ...baseConfig, prompt: 'first complex task' });
    await firstSubmittedBarrier;
    const second = session.run({ ...baseConfig, prompt: 'second complex task', cancelFile });
    await waitFor(() => session.status().queues.actionDepth === 2);
    await fs.writeFile(cancelFile, 'cancelled\n', 'utf8');
    releaseFirstPoll();
    const [firstResult, secondResult] = await Promise.all([first, second]);

    assert.equal(firstResult.ok, true);
    assert.equal(secondResult.ok, false);
    assert.equal(secondResult.error, 'cancelled');
    assert.equal(secondResult.errorCode, 'cancelled');
    assert.equal(taskSubmissions, 1);
  } finally {
    releaseFirstPoll();
    fake.server.close();
    await fs.rm(tempDir, { recursive: true, force: true });
  }
});

test('DeviceSession remembers recent events', () => {
  const session = new DeviceSession('device-1');
  session.rememberEvent({ type: 'run_complete', result: 'ok' });

  const events = session.recentEvents(1);
  assert.equal(events.length, 1);
  assert.equal(events[0].type, 'run_complete');
  assert.equal(events[0].result, 'ok');
  assert.ok(events[0].receivedAt);
});

test('daemon reports device status after a run completes', async () => {
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
    if (request.url.startsWith('/api/lumi/agent/action_fast')) {
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

  const config = {
    command: 'run',
    phoneUrl: fake.baseUrl,
    phoneToken: 'test-token',
    prompt: 'open settings',
    stepTimeoutSec: 8,
    timeoutSec: 30,
    maxWaitSec: 30,
  };

  try {
    await withRuntimeSandbox(async () => {
      const { daemon, runtime } = await startHttpDaemon();
      try {
        const runResponse = await fetch(`http://127.0.0.1:${runtime.port}/v1/run`, {
          method: 'POST',
          headers: {
            ...daemonAuthHeaders(runtime),
            'Content-Type': 'application/json; charset=utf-8',
            Accept: 'application/json',
          },
          body: JSON.stringify({ schema: 'loom.phone_daemon.run.v1', requestId: 'status-test', ...config }),
        });
        const runPayload = await runResponse.json();
        assert.equal(runResponse.ok, true);
        assert.equal(runPayload.ok, true);

        const deviceKey = deviceKeyFromConfig(config);
        const statusResponse = await fetch(`http://127.0.0.1:${runtime.port}/v1/device-status?deviceKey=${encodeURIComponent(deviceKey)}`, {
          headers: daemonAuthHeaders(runtime),
        });
        const statusPayload = await statusResponse.json();

        assert.equal(statusResponse.ok, true);
        assert.equal(statusPayload.ok, true);
        assert.equal(statusPayload.deviceKey, deviceKey);
        assert.equal(statusPayload.status.queues.actionDepth, 0);
      } finally {
        daemon.kill();
      }
    });
  } finally {
    fake.server.close();
  }
});

test('daemon exposes recent run events after a run completes', async () => {
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
    if (request.url.startsWith('/api/lumi/agent/action_fast')) {
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

  const config = {
    command: 'run',
    phoneUrl: fake.baseUrl,
    phoneToken: 'test-token',
    prompt: 'open settings',
    stepTimeoutSec: 8,
    timeoutSec: 30,
    maxWaitSec: 30,
  };

  try {
    await withRuntimeSandbox(async () => {
      const { daemon, runtime } = await startHttpDaemon();
      try {
        const runResult = await fetchJson(`http://127.0.0.1:${runtime.port}/v1/run`, {
          method: 'POST',
          headers: {
            ...daemonAuthHeaders(runtime),
            'Content-Type': 'application/json; charset=utf-8',
            Accept: 'application/json',
          },
          body: JSON.stringify({ schema: 'loom.phone_daemon.run.v1', requestId: 'events-test', ...config }),
        });
        assert.equal(runResult.response.ok, true);
        assert.equal(runResult.payload.ok, true);

        const deviceKey = deviceKeyFromConfig(config);
        const eventsResult = await fetchJson(`http://127.0.0.1:${runtime.port}/v1/events/recent?deviceKey=${encodeURIComponent(deviceKey)}&limit=20`, {
          headers: daemonAuthHeaders(runtime),
        });

        assert.equal(eventsResult.response.ok, true);
        assert.equal(eventsResult.payload.ok, true);
        assert.equal(eventsResult.payload.deviceKey, deviceKey);
        assert.ok(Array.isArray(eventsResult.payload.events));
        assert.ok(eventsResult.payload.events.length > 0);
        assert.equal(eventsResult.payload.events.some((event) => event.type === 'run_queued' && event.requestId === 'events-test' && event.command === 'run' && event.mode === 'safe' && event.executionLayer === 'agent'), true);
        assert.equal(eventsResult.payload.events.some((event) => event.type === 'run_running' && event.requestId === 'events-test'), true);
        assert.equal(eventsResult.payload.events.some((event) => event.type === 'run_result' && event.requestId === 'events-test' && event.ok === true && event.currentStep === 'complete'), true);
      } finally {
        daemon.kill();
      }
    });
  } finally {
    fake.server.close();
  }
});

test('daemon device status no-session fallback returns zero queue depths', async () => {
  await withRuntimeSandbox(async () => {
    const { daemon, runtime } = await startHttpDaemon();
    try {
      const deviceKey = 'missing-device-key';
      const statusResult = await fetchJson(`http://127.0.0.1:${runtime.port}/v1/device-status?deviceKey=${encodeURIComponent(deviceKey)}`, {
        headers: daemonAuthHeaders(runtime),
      });

      assert.equal(statusResult.response.ok, true);
      assert.equal(statusResult.payload.ok, true);
      assert.equal(statusResult.payload.deviceKey, deviceKey);
      assert.deepEqual(statusResult.payload.status.queues, { actionDepth: 0, readDepth: 0, screenshotDepth: 0, eventDepth: 0 });
    } finally {
      daemon.kill();
    }
  });
});

test('daemon client auto-starts from a non-project current working directory', async () => {
  await withRuntimeSandbox(async () => withTempCwd(async () => {
    await fs.rm(RUNTIME_PATH, { force: true });
    let runtime = null;
    try {
      const started = Date.now();
      const result = await tryRunViaDaemon({
        command: 'run',
        phoneUrl: 'http://127.0.0.1:19527',
        phoneToken: 'test-token',
        prompt: 'open settings',
        timeoutSec: 1,
        maxWaitSec: 1,
        stepTimeoutSec: 1,
      });

      runtime = await readRuntimeState();
      assert.equal(result.usedDaemon, true);
      assert.doesNotMatch(result.error.message, /daemon_start_timeout|Cannot find module/i);
      assert.ok(Date.now() - started < 15_000);
    } finally {
      await shutdownRuntimeDaemon(runtime);
    }
  }));
});

for (const scenario of [
  {
    name: 'HTTP 500',
    response(request, response) {
      response.writeHead(500, { 'Content-Type': 'application/json' });
      response.end(JSON.stringify({ ok: false, error: 'daemon_http_500' }));
    },
    expected: /daemon_http_500/i,
  },
  {
    name: 'invalid JSON',
    response(request, response) {
      response.writeHead(200, { 'Content-Type': 'application/json' });
      response.end('{not json');
    },
    expected: /daemon_invalid_json/i,
  },
  {
    name: 'payload ok false',
    response(request, response) {
      response.writeHead(200, { 'Content-Type': 'application/json' });
      response.end(JSON.stringify({ ok: false, error: 'daemon_payload_failed' }));
    },
    expected: /daemon_payload_failed/i,
  },
]) {
  test(`daemon client surfaces ${scenario.name} as execution failure`, async () => {
    await withRuntimeSandbox(async () => {
      let expectedToken = '';
      const server = http.createServer(async (request, response) => {
        if (request.url === '/health') {
          assert.equal(request.headers['x-loom-phone-daemon-token'], expectedToken);
          response.writeHead(200, { 'Content-Type': 'application/json' });
          response.end(JSON.stringify({ ok: true }));
          return;
        }
        if (request.method === 'POST' && request.url === '/v1/run') {
          await scenario.response(request, response);
          return;
        }
        response.writeHead(404, { 'Content-Type': 'application/json' });
        response.end(JSON.stringify({ ok: false, error: 'unexpected' }));
      });

      await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
      try {
        const { port } = server.address();
        const runtime = await createRuntimeState(port);
        expectedToken = runtime.token;
        const result = await tryRunViaDaemon({
          command: 'run',
          phoneUrl: `http://127.0.0.1:${port}`,
          phoneToken: 'test-token',
          prompt: 'open settings',
          timeoutSec: 1,
          maxWaitSec: 1,
        });

        assert.equal(result.usedDaemon, true);
        assert.match(result.error.message, scenario.expected);
      } finally {
        await new Promise((resolve) => server.close(resolve));
      }
    });
  });
}

test('daemon client aborts a stalled daemon request', async () => {
  await withRuntimeSandbox(async () => {
    let expectedToken = '';
    const server = http.createServer(async (request, response) => {
      if (request.url === '/health') {
        assert.equal(request.headers['x-loom-phone-daemon-token'], expectedToken);
        response.writeHead(200, { 'Content-Type': 'application/json' });
        response.end(JSON.stringify({ ok: true }));
        return;
      }
      if (request.method === 'POST' && request.url === '/v1/run') {
        await new Promise(() => {});
        return;
      }
      response.writeHead(404, { 'Content-Type': 'application/json' });
      response.end(JSON.stringify({ ok: false, error: 'unexpected' }));
    });

    await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
    try {
      const { port } = server.address();
      const runtime = await createRuntimeState(port);
      expectedToken = runtime.token;
      const started = Date.now();
      const result = await tryRunViaDaemon({
        command: 'run',
        phoneUrl: `http://127.0.0.1:${port}`,
        phoneToken: 'test-token',
        prompt: 'open settings',
        timeoutSec: 1,
        maxWaitSec: 1,
      });

      assert.equal(result.usedDaemon, true);
      assert.match(result.error.message, /aborted|timeout|AbortError|超时/i);
      assert.ok(Date.now() - started < 15_000);
    } finally {
      await new Promise((resolve) => server.close(resolve));
    }
  });
});
