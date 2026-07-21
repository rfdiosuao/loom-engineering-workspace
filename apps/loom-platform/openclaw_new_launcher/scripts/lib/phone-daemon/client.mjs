import crypto from 'node:crypto';
import { spawn } from 'node:child_process';
import path from 'node:path';
import { setTimeout as sleep } from 'node:timers/promises';
import { fileURLToPath } from 'node:url';
import { daemonAuthHeaders, readRuntimeState } from './runtime-auth.mjs';
import { fetchWithTimeout } from '../../openclaw-phone-secure.mjs';

const DAEMON_HEALTH_TIMEOUT_MS = 5_000;
const DAEMON_REQUEST_MIN_TIMEOUT_SEC = 5;
const DAEMON_REQUEST_BUFFER_SEC = 5;
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const PROJECT_ROOT = path.resolve(__dirname, '..', '..', '..');
const DAEMON_ENTRYPOINT = path.join(PROJECT_ROOT, 'scripts', 'openclaw-phone-daemon.mjs');

class DaemonUnavailableError extends Error {
  constructor(message) {
    super(message);
    this.name = 'DaemonUnavailableError';
    this.daemonFailureKind = 'unavailable';
  }
}

class DaemonExecutionError extends Error {
  constructor(message, payload = null) {
    super(message);
    this.name = 'DaemonExecutionError';
    this.daemonFailureKind = 'execution';
    if (payload && typeof payload === 'object') {
      this.payload = payload;
      this.errorCode = payload.errorCode || payload.error || '';
      this.code = this.errorCode || this.code;
      this.retryable = payload.retryable;
      this.details = payload.details;
      this.remediation = payload.remediation;
      this.currentStep = payload.currentStep;
    }
  }
}

function daemonRequestTimeoutMs(config) {
  const candidates = [config?.maxWaitSec, config?.timeoutSec]
    .map((value) => Number(value))
    .filter((value) => Number.isFinite(value) && value > 0);
  const configuredSec = candidates.length ? Math.max(...candidates) : 30;
  return (Math.max(DAEMON_REQUEST_MIN_TIMEOUT_SEC, configuredSec) + DAEMON_REQUEST_BUFFER_SEC) * 1000;
}

function daemonEventStreamTimeoutMs(config) {
  const configuredSec = Number(config?.maxSec);
  const maxSec = Number.isFinite(configuredSec) && configuredSec > 0 ? configuredSec : 3600;
  return (maxSec + DAEMON_REQUEST_BUFFER_SEC) * 1000;
}

async function health(runtime) {
  const response = await fetchWithTimeout(`http://127.0.0.1:${runtime.port}/health`, {
    headers: daemonAuthHeaders(runtime),
  }, DAEMON_HEALTH_TIMEOUT_MS);
  const text = await response.text();
  let payload = {};
  try {
    payload = text ? JSON.parse(text) : {};
  } catch {
    throw new DaemonUnavailableError('daemon_health_invalid_json');
  }
  if (!response.ok) throw new DaemonUnavailableError(`daemon_health_http_${response.status}`);
  if (payload?.ok === false) {
    throw new DaemonUnavailableError(payload.error || 'daemon_health_failed');
  }
  return payload;
}

export async function ensureDaemon() {
  try {
    const runtime = await readRuntimeState();
    await health(runtime);
    return runtime;
  } catch (error) {
    if (error?.daemonFailureKind && error.daemonFailureKind !== 'unavailable') throw error;
    const child = spawn(process.execPath, [DAEMON_ENTRYPOINT], {
      cwd: PROJECT_ROOT,
      detached: true,
      stdio: 'ignore',
      windowsHide: true,
      env: process.env,
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
    throw new DaemonUnavailableError('daemon_start_timeout');
  }
}

export async function runViaDaemon(config) {
  const runtime = await ensureDaemon();
  return requestDaemon(runtime, '/v1/run', {
    schema: 'loom.phone_daemon.run.v1',
    requestId: crypto.randomUUID(),
    ...config,
  }, daemonRequestTimeoutMs(config));
}

export async function metricsViaDaemon(config) {
  const runtime = await ensureDaemon();
  return requestDaemon(runtime, '/v1/metrics', {
    schema: 'loom.phone_daemon.metrics.v1',
    requestId: crypto.randomUUID(),
    ...config,
  }, daemonRequestTimeoutMs(config));
}

export async function syncEventsViaDaemon(config, onEvent) {
  const runtime = await ensureDaemon();
  return requestDaemonEventStream(runtime, '/v1/events-sync', {
    schema: 'loom.phone_daemon.events_sync.v1',
    requestId: crypto.randomUUID(),
    ...config,
  }, daemonEventStreamTimeoutMs(config), onEvent);
}

async function requestDaemon(runtime, endpoint, requestPayload, timeoutMs) {
  const response = await fetchWithTimeout(`http://127.0.0.1:${runtime.port}${endpoint}`, {
    method: 'POST',
    headers: {
      ...daemonAuthHeaders(runtime),
      'Content-Type': 'application/json; charset=utf-8',
      Accept: 'application/json',
    },
    body: JSON.stringify(requestPayload),
  }, timeoutMs);
  const text = await response.text();
  let responsePayload = {};
  try {
    responsePayload = text ? JSON.parse(text) : {};
  } catch {
    throw new DaemonExecutionError(`daemon_invalid_json: HTTP ${response.status}`);
  }
  if (!response.ok) {
    throw new DaemonExecutionError(responsePayload?.message || responsePayload?.error || `daemon_http_${response.status}`, responsePayload);
  }
  if (responsePayload?.ok === false) {
    throw new DaemonExecutionError(responsePayload?.message || responsePayload?.error || 'daemon_execution_failed', responsePayload);
  }
  return responsePayload;
}

async function requestDaemonEventStream(runtime, endpoint, requestPayload, timeoutMs, onEvent) {
  const response = await fetchWithTimeout(`http://127.0.0.1:${runtime.port}${endpoint}`, {
    method: 'POST',
    headers: {
      ...daemonAuthHeaders(runtime),
      'Content-Type': 'application/json; charset=utf-8',
      Accept: 'application/x-ndjson, application/json',
    },
    body: JSON.stringify(requestPayload),
  }, timeoutMs);

  if (!response.ok) {
    const text = await response.text();
    let payload = {};
    try {
      payload = text ? JSON.parse(text) : {};
    } catch {
      throw new DaemonExecutionError(`daemon_http_${response.status}`);
    }
    throw new DaemonExecutionError(payload?.message || payload?.error || `daemon_http_${response.status}`, payload);
  }

  if (!response.body || typeof response.body.getReader !== 'function') {
    throw new DaemonExecutionError('daemon_event_stream_unavailable');
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  const events = [];
  let summary = null;

  const processLine = (line) => {
    const trimmed = line.trim();
    if (!trimmed) return;
    let payload;
    try {
      payload = JSON.parse(trimmed);
    } catch {
      throw new DaemonExecutionError('daemon_event_stream_invalid_json');
    }
    if (payload?.ok === false) {
      throw new DaemonExecutionError(payload.message || payload.error || 'daemon_events_sync_failed', payload);
    }
    if (payload?.type === 'phone_event') {
      const event = payload.event || {};
      events.push(event);
      onEvent?.(event);
      return;
    }
    if (payload?.type === 'phone_event_sync_summary') {
      summary = payload.summary || { ok: true, eventCount: events.length };
    }
  };

  try {
    while (true) {
      const readResult = await reader.read();
      if (readResult.done) break;
      buffer += decoder.decode(readResult.value, { stream: true });
      const lines = buffer.split(/\r?\n/);
      buffer = lines.pop() || '';
      for (const line of lines) processLine(line);
    }
    buffer += decoder.decode();
    if (buffer) processLine(buffer);
  } finally {
    try {
      reader.releaseLock();
    } catch {
      // The stream may already be closed by the daemon.
    }
  }

  return {
    ok: true,
    summary: summary || { ok: true, eventCount: events.length, stoppedBy: 'eof' },
    events,
  };
}

export async function tryRunViaDaemon(config) {
  try {
    return { usedDaemon: true, result: await runViaDaemon(config) };
  } catch (error) {
    if (error?.daemonFailureKind === 'unavailable') {
      return { usedDaemon: false, error };
    }
    return { usedDaemon: true, error };
  }
}

export async function tryGetMetricsViaDaemon(config) {
  try {
    return { usedDaemon: true, result: await metricsViaDaemon(config) };
  } catch (error) {
    if (error?.daemonFailureKind === 'unavailable') {
      return { usedDaemon: false, error };
    }
    return { usedDaemon: true, error };
  }
}

export async function trySyncEventsViaDaemon(config, onEvent) {
  try {
    return { usedDaemon: true, result: await syncEventsViaDaemon(config, onEvent) };
  } catch (error) {
    if (error?.daemonFailureKind === 'unavailable') {
      return { usedDaemon: false, error };
    }
    return { usedDaemon: true, error };
  }
}
