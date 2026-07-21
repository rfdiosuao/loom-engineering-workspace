#!/usr/bin/env node

import http from 'node:http';
import { createInterface } from 'node:readline';
import { DeviceSession } from './lib/phone-daemon/device-session.mjs';
import { getPhoneMetrics } from './lib/phone-command-core.mjs';
import {
  createRuntimeState,
  deviceKeyFromConfig,
  isAuthorized,
  readRuntimeState,
} from './lib/phone-daemon/runtime-auth.mjs';
import { phoneBridgeErrorPayload } from './openclaw-phone-secure.mjs';

const sessions = new Map();
const DEFAULT_MAX_ROUNDS_BY_MODE = {
  observe: 1,
  safe: 12,
  full: 30,
};

function sessionFor(config) {
  const key = deviceKeyFromConfig(config);
  let session = sessions.get(key);
  if (!session) {
    session = new DeviceSession(key);
    sessions.set(key, session);
  }
  return session;
}

function rememberSessionEvent(config, event) {
  const session = sessionFor(config);
  session.rememberEvent({
    ...runEventContext(config),
    ...event,
  });
  return session;
}

function runEventContext(config, result = null) {
  return {
    requestId: typeof config?.requestId === 'string' ? config.requestId : '',
    command: typeof config?.command === 'string' ? config.command : 'run',
    mode: typeof config?.mode === 'string' ? config.mode : 'safe',
    executionLayer: typeof config?.executionLayer === 'string' ? config.executionLayer : 'agent',
    templateName: typeof config?.templateName === 'string' ? config.templateName : '',
    currentStep: typeof result?.currentStep === 'string' ? result.currentStep : '',
    ok: typeof result?.ok === 'boolean' ? result.ok : undefined,
    error: typeof result?.error === 'string' ? result.error : '',
  };
}

function normalizeRunConfig(config) {
  const mode = String(config?.mode || 'safe').trim() || 'safe';
  const maxRounds =
    Number.isFinite(Number(config?.maxRounds)) && Number(config.maxRounds) > 0
      ? Number(config.maxRounds)
      : DEFAULT_MAX_ROUNDS_BY_MODE[mode] || DEFAULT_MAX_ROUNDS_BY_MODE.safe;
  return {
    ...config,
    command: config?.command || 'run',
    mode,
    timeoutSec: Number.isFinite(Number(config?.timeoutSec)) ? Number(config.timeoutSec) : 600,
    maxRounds,
    maxWaitSec: Number.isFinite(Number(config?.maxWaitSec)) ? Number(config.maxWaitSec) : 615,
    maxSec: Number.isFinite(Number(config?.maxSec)) ? Number(config.maxSec) : 3600,
    stepTimeoutSec: Number.isFinite(Number(config?.stepTimeoutSec)) ? Number(config.stepTimeoutSec) : 12,
    pollMs: Number.isFinite(Number(config?.pollMs)) ? Number(config.pollMs) : 1200,
    executionLayer: String(config?.executionLayer || 'agent').trim() || 'agent',
    templateName: typeof config?.templateName === 'string' ? config.templateName : '',
    maxEvents: Number.isFinite(Number(config?.maxEvents)) ? Number(config.maxEvents) : 0,
  };
}

async function handleRun(config) {
  const session = sessionFor(config);
  const normalized = normalizeRunConfig(config);
  return session.run(normalized, {
    onQueued: ({ queueKind, queueDepth }) => {
      session.rememberEvent({
        type: 'run_queued',
        ...runEventContext(normalized),
        queueKind,
        queueDepth,
      });
    },
    onRunning: ({ queueKind }) => {
      session.rememberEvent({
        type: 'run_running',
        ...runEventContext(normalized),
        queueKind,
      });
    },
    onResult: (result) => {
      session.rememberEvent({
        type: 'run_result',
        ...runEventContext(normalized, result),
      });
    },
    onError: (error) => {
      session.rememberEvent({
        type: 'run_error',
        ...runEventContext(normalized, { currentStep: 'error', ok: false, error: error?.message || String(error || 'daemon_error') }),
      });
    },
  });
}

async function handleMetrics(config) {
  const normalized = normalizeRunConfig(config);
  const result = await getPhoneMetrics(normalized);
  rememberSessionEvent(normalized, {
    type: 'metrics_result',
    ok: result.ok !== false,
  });
  return result;
}

async function handleEventsSync(config, lifecycle = {}) {
  const normalized = normalizeRunConfig(config);
  const session = sessionFor(normalized);
  const events = [];
  const maxEvents = Math.max(0, Math.min(200, Number(normalized.maxEvents || normalized.limit || 50) || 50));
  const summary = await session.syncEvents(normalized, (event) => {
    if (events.length < maxEvents) events.push(event);
    session.rememberEvent({
      ...runEventContext(normalized),
      type: 'phone_event',
      event,
    });
    lifecycle.onEvent?.(event);
  }, {
    onQueued: ({ queueDepth }) => {
      session.rememberEvent({
        ...runEventContext(normalized),
        type: 'events_sync_queued',
        queueKind: 'events',
        queueDepth,
      });
    },
    onRunning: () => {
      session.rememberEvent({
        ...runEventContext(normalized),
        type: 'events_sync_running',
        queueKind: 'events',
      });
    },
    onError: (error) => {
      session.rememberEvent({
        ...runEventContext(normalized, { currentStep: 'error', ok: false, error: error?.message || String(error || 'daemon_error') }),
        type: 'events_sync_error',
      });
    },
  });
  const result = { ok: true, summary, events };
  session.rememberEvent({
    ...runEventContext(normalized),
    type: 'events_sync_result',
    ok: true,
    eventCount: events.length,
  });
  lifecycle.onSummary?.(result);
  return result;
}

async function readJsonBody(request) {
  const chunks = [];
  for await (const chunk of request) chunks.push(chunk);
  const text = Buffer.concat(chunks).toString('utf8');
  return text ? JSON.parse(text) : {};
}

function sendJson(response, statusCode, payload) {
  response.writeHead(statusCode, {
    'Content-Type': 'application/json; charset=utf-8',
    'Cache-Control': 'no-store',
  });
  response.end(`${JSON.stringify(payload)}\n`);
}

function startNdjson(response) {
  response.writeHead(200, {
    'Content-Type': 'application/x-ndjson; charset=utf-8',
    'Cache-Control': 'no-store',
    'X-Accel-Buffering': 'no',
  });
}

function writeNdjson(response, payload) {
  response.write(`${JSON.stringify(payload)}\n`);
}

function safeErrorPayload(error, fallback = 'daemon_error') {
  const payload = phoneBridgeErrorPayload(error || new Error(fallback), {}, fallback);
  return {
    ...payload,
    error: payload.error || fallback,
  };
}

async function startHttpServer() {
  const server = http.createServer(async (request, response) => {
    try {
      const url = new URL(request.url || '/', 'http://127.0.0.1');
      const pathname = url.pathname;

      const runtime = await readRuntimeOrNull();
      if (!isAuthorized(request, runtime)) {
        sendJson(response, 401, { ok: false, error: 'daemon_unauthorized' });
        return;
      }

      if (pathname === '/health') {
        sendJson(response, 200, { ok: true, pid: process.pid, sessions: sessions.size });
        return;
      }

      if (request.method === 'POST' && pathname === '/v1/run') {
        const body = await readJsonBody(request);
        const result = await handleRun(body);
        sendJson(response, 200, result);
        return;
      }

      if (request.method === 'POST' && pathname === '/v1/metrics') {
        const body = await readJsonBody(request);
        const result = await handleMetrics(body);
        sendJson(response, 200, result);
        return;
      }

      if (request.method === 'POST' && pathname === '/v1/events-sync') {
        let body;
        try {
          body = await readJsonBody(request);
        } catch {
          sendJson(response, 400, { ok: false, error: 'invalid_json' });
          return;
        }
        startNdjson(response);
        try {
          await handleEventsSync(body, {
            onEvent: (event) => writeNdjson(response, { ok: true, type: 'phone_event', event }),
            onSummary: (result) => writeNdjson(response, {
              ok: true,
              type: 'phone_event_sync_summary',
              summary: result.summary,
              events: result.events,
            }),
          });
        } catch (error) {
          writeNdjson(response, safeErrorPayload(error, 'daemon_events_sync_error'));
        } finally {
          response.end();
        }
        return;
      }

      if (request.method === 'GET' && pathname === '/v1/events/recent') {
        const key = url.searchParams.get('deviceKey') || '';
        const limit = Number(url.searchParams.get('limit') || 20);
        const session = sessions.get(key);
        sendJson(response, 200, {
          ok: true,
          deviceKey: key,
          events: session ? session.recentEvents(limit) : [],
        });
        return;
      }

      if (request.method === 'GET' && pathname === '/v1/device-status') {
        const key = url.searchParams.get('deviceKey') || '';
        const session = sessions.get(key);
        sendJson(response, 200, {
          ok: true,
          deviceKey: key,
          status: session ? session.status() : { deviceKey: key, queues: { actionDepth: 0, readDepth: 0, screenshotDepth: 0, eventDepth: 0 } },
        });
        return;
      }

      if (request.method === 'POST' && pathname === '/shutdown') {
        sendJson(response, 200, { ok: true, stopping: true });
        server.close(() => process.exit(0));
        return;
      }

      sendJson(response, 404, { ok: false, error: 'not_found' });
    } catch (error) {
      const statusCode = error instanceof SyntaxError ? 400 : 500;
      const payload = statusCode === 400
        ? { ok: false, error: 'invalid_json' }
        : safeErrorPayload(error, 'daemon_error');
      sendJson(response, statusCode, payload);
    }
  });

  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', resolve);
  });

  try {
    const address = server.address();
    const port = typeof address === 'object' && address ? address.port : 0;
    const runtime = await createRuntimeState(port);
    process.stdout.write(`${JSON.stringify({ ok: true, type: 'phone_daemon_started', port: runtime.port, pid: runtime.pid })}\n`);
  } catch (error) {
    await new Promise((resolve) => server.close(resolve));
    throw error;
  }

  await new Promise((resolve) => {
    server.on('close', resolve);
  });
}

async function readRuntimeOrNull() {
  try {
    return await readRuntimeState();
  } catch {
    return null;
  }
}

async function writeStdoutJson(value) {
  const line = `${JSON.stringify(value)}\n`;
  stdoutTail = stdoutTail.then(() => new Promise((resolve) => {
    process.stdout.write(line, resolve);
  }));
  return stdoutTail;
}

let stdoutTail = Promise.resolve();

async function startStdioServer() {
  const rl = createInterface({ input: process.stdin, crlfDelay: Infinity });
  let closed = false;
  let inflight = 0;
  let finish;
  const done = new Promise((resolve) => {
    finish = resolve;
  });

  const maybeFinish = () => {
    if (closed && inflight === 0) finish();
  };

  rl.on('line', (line) => {
    if (!line.trim()) return;
    inflight += 1;
    void (async () => {
      try {
        const body = JSON.parse(line);
        const result = await handleRun(body);
        await writeStdoutJson(result);
      } catch (error) {
        await writeStdoutJson(error instanceof SyntaxError ? { ok: false, error: 'invalid_json' } : safeErrorPayload(error, 'daemon_error'));
      } finally {
        inflight -= 1;
        maybeFinish();
      }
    })();
  });

  rl.on('close', () => {
    closed = true;
    maybeFinish();
  });

  await done;
}

if (process.argv.includes('--stdio-json')) {
  await startStdioServer();
} else {
  await startHttpServer();
}
