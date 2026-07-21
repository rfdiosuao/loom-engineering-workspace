#!/usr/bin/env node

import http from 'node:http';
import fs from 'node:fs/promises';
import path from 'node:path';
import { randomUUID, timingSafeEqual } from 'node:crypto';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const PROJECT_ROOT = path.resolve(__dirname, '..');
const DEFAULT_HOST = '0.0.0.0';
const DEFAULT_PORT = 8787;
const DEFAULT_DATA_DIR = path.join(PROJECT_ROOT, 'data', '.openclaw', 'publish-relay');
const DEFAULT_LEASE_MS = 30_000;
const DEFAULT_WAIT_MS = 15_000;
const DEFAULT_MAX_ATTEMPTS = 5;
const DEFAULT_BACKOFF_MS = 2_000;
const MAX_BACKOFF_MS = 5 * 60_000;
const MAX_BODY_BYTES = 16 * 1024 * 1024;
const SUPPORTED_PACKET_SCHEMAS = new Set(['openclaw.publish.packet.v1', 'openclaw.phone.screenshot.v1']);

function usage() {
  return `
OpenClaw publish relay

Usage:
  node scripts/openclaw-publish-relay.mjs

Options:
  --host <host>                Listen host. Default: ${DEFAULT_HOST}
  --port <n>                   Listen port. Default: ${DEFAULT_PORT}
  --data-dir <path>            State directory. Default: ${DEFAULT_DATA_DIR}
  --lease-ms <n>               Lease time for a polled packet. Default: ${DEFAULT_LEASE_MS}
  --wait-ms <n>                Long-poll wait time. Default: ${DEFAULT_WAIT_MS}
  --max-attempts <n>           Retry limit before a packet is marked failed. Default: ${DEFAULT_MAX_ATTEMPTS}
  --auth-token <token>         Require shared relay token. Env: OPENCLAW_PUBLISH_RELAY_TOKEN
  -h, --help                   Show help
`.trim();
}

function parseArgs(argv) {
  const args = {
    host: DEFAULT_HOST,
    port: DEFAULT_PORT,
    dataDir: DEFAULT_DATA_DIR,
    leaseMs: DEFAULT_LEASE_MS,
    waitMs: DEFAULT_WAIT_MS,
    maxAttempts: DEFAULT_MAX_ATTEMPTS,
    authToken: normalizeString(process.env.OPENCLAW_PUBLISH_RELAY_TOKEN),
    help: false,
  };

  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    const next = () => {
      const value = argv[i + 1];
      if (!value || value.startsWith('--')) throw new Error(`Missing value for ${arg}`);
      i += 1;
      return value;
    };
    const nextInt = () => {
      const value = Number.parseInt(next(), 10);
      if (!Number.isFinite(value)) throw new Error(`Invalid number for ${arg}`);
      return value;
    };

    switch (arg) {
      case '-h':
      case '--help':
        args.help = true;
        break;
      case '--host':
        args.host = next();
        break;
      case '--port':
        args.port = nextInt();
        break;
      case '--data-dir':
        args.dataDir = path.resolve(next());
        break;
      case '--lease-ms':
        args.leaseMs = nextInt();
        break;
      case '--wait-ms':
        args.waitMs = nextInt();
        break;
      case '--max-attempts':
        args.maxAttempts = nextInt();
        break;
      case '--auth-token':
        args.authToken = normalizeString(next());
        break;
      default:
        throw new Error(`Unknown option: ${arg}`);
    }
  }

  args.port = clampInt(args.port, 1, 65535, DEFAULT_PORT);
  args.leaseMs = clampInt(args.leaseMs, 1_000, 15 * 60_000, DEFAULT_LEASE_MS);
  args.waitMs = clampInt(args.waitMs, 0, 15 * 60_000, DEFAULT_WAIT_MS);
  args.maxAttempts = clampInt(args.maxAttempts, 1, 20, DEFAULT_MAX_ATTEMPTS);
  return args;
}

function clampInt(value, min, max, fallback) {
  if (!Number.isFinite(value)) return fallback;
  return Math.min(max, Math.max(min, Math.trunc(value)));
}

function nowIso() {
  return new Date().toISOString();
}

function nowMs() {
  return Date.now();
}

function randomId(prefix) {
  return `${prefix}_${randomUUID().replace(/-/g, '').slice(0, 12)}`;
}

function jsonHeaders(extra = {}) {
  return {
    'Content-Type': 'application/json; charset=utf-8',
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type, Authorization, X-OpenClaw-Relay-Token',
    ...extra,
  };
}

function sendJson(res, statusCode, payload, extraHeaders = {}) {
  const body = `${JSON.stringify(payload)}\n`;
  res.writeHead(statusCode, jsonHeaders(extraHeaders));
  res.end(body);
}

function sendNoContent(res) {
  res.writeHead(204, {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type, Authorization, X-OpenClaw-Relay-Token',
  });
  res.end();
}

async function readJsonBody(req) {
  const chunks = [];
  let size = 0;
  for await (const chunk of req) {
    const buffer = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
    size += buffer.length;
    if (size > MAX_BODY_BYTES) {
      const error = new Error('Request body too large');
      error.statusCode = 413;
      throw error;
    }
    chunks.push(buffer);
  }

  const text = Buffer.concat(chunks).toString('utf8').trim();
  if (!text) return null;

  try {
    return JSON.parse(text);
  } catch (error) {
    const parseError = new Error('Invalid JSON body');
    parseError.statusCode = 400;
    throw parseError;
  }
}

function normalizeChannelId(value) {
  return String(value || '').trim();
}

function normalizeClientId(value) {
  const text = String(value || '').trim();
  return text || 'default-client';
}

function normalizeString(value) {
  return String(value == null ? '' : value).trim();
}

function firstHeaderValue(value) {
  if (Array.isArray(value)) return normalizeString(value[0]);
  return normalizeString(value);
}

function requestRelayToken(req) {
  const directToken = firstHeaderValue(req.headers['x-openclaw-relay-token']);
  if (directToken) return directToken;

  const authorization = firstHeaderValue(req.headers.authorization);
  const bearer = authorization.match(/^Bearer\s+(.+)$/i);
  return bearer ? normalizeString(bearer[1]) : '';
}

function tokenMatches(actual, expected) {
  const actualBuffer = Buffer.from(normalizeString(actual));
  const expectedBuffer = Buffer.from(normalizeString(expected));
  if (!actualBuffer.length || actualBuffer.length !== expectedBuffer.length) return false;
  return timingSafeEqual(actualBuffer, expectedBuffer);
}

function isAuthorized(req, authToken) {
  if (!authToken) return true;
  return tokenMatches(requestRelayToken(req), authToken);
}

function requireRelayAuth(req, res, authToken) {
  if (isAuthorized(req, authToken)) return true;
  sendJson(res, 401, { ok: false, error: 'Relay auth required' }, {
    'WWW-Authenticate': 'Bearer realm="openclaw-publish-relay"',
  });
  return false;
}

function summarizeRecord(record, includePacket = false) {
  return {
    id: record.id,
    channelId: record.channelId,
    status: record.status,
    attempts: record.attempts,
    createdAt: record.createdAt,
    updatedAt: record.updatedAt,
    leasedBy: record.leasedBy,
    leaseId: record.leaseId,
    leaseUntil: record.leaseUntil || null,
    nextAvailableAt: record.nextAvailableAt || null,
    completedAt: record.completedAt || null,
    lastError: record.lastError || '',
    result: record.result,
    ...(includePacket ? { packet: record.packet } : {}),
  };
}

function queueStats(records, channelId) {
  const now = nowMs();
  const scoped = channelId
    ? records.filter((record) => record.channelId === channelId)
    : records;
  const pending = scoped.filter((record) => record.status === 'pending' && (record.nextAvailableAt || 0) <= now);
  const leased = scoped.filter((record) => record.status === 'leased' && (record.leaseUntil || 0) > now);
  const failed = scoped.filter((record) => record.status === 'failed');
  const done = scoped.filter((record) => record.status === 'done');
  return {
    channelId: channelId || null,
    total: scoped.length,
    pending: pending.length,
    leased: leased.length,
    done: done.length,
    failed: failed.length,
  };
}

function backoffMs(attempts) {
  const factor = Math.max(1, Math.pow(2, Math.max(0, attempts - 1)));
  return Math.min(MAX_BACKOFF_MS, DEFAULT_BACKOFF_MS * factor);
}

async function loadState(filePath) {
  try {
    const raw = await fs.readFile(filePath, 'utf8');
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object') {
      return { version: 1, nextSeq: 1, records: [] };
    }
    return {
      version: 1,
      nextSeq: Number.isFinite(parsed.nextSeq) ? parsed.nextSeq : 1,
      records: Array.isArray(parsed.records) ? parsed.records : [],
    };
  } catch (error) {
    if (error.code !== 'ENOENT') {
      console.warn(`[relay] Failed to load state, starting empty: ${error.message}`);
    }
    return { version: 1, nextSeq: 1, records: [] };
  }
}

async function saveState(filePath, state) {
  await fs.mkdir(path.dirname(filePath), { recursive: true });
  const tmpPath = `${filePath}.${process.pid}.tmp`;
  await fs.writeFile(tmpPath, `${JSON.stringify(state, null, 2)}\n`, 'utf8');
  await fs.rm(filePath, { force: true });
  await fs.rename(tmpPath, filePath);
}

function createRelayStore(stateFilePath, maxAttempts) {
  const state = {
    version: 1,
    nextSeq: 1,
    records: [],
  };

  let saveChain = Promise.resolve();

  const enqueueSave = () => {
    saveChain = saveChain.then(() => saveState(stateFilePath, state));
    return saveChain;
  };

  const queue = {
    async hydrate() {
      const loaded = await loadState(stateFilePath);
      state.version = loaded.version;
      state.nextSeq = loaded.nextSeq;
      state.records = loaded.records;
      await enqueueSave();
    },

    async enqueue(packet) {
      const channelId = normalizeChannelId(packet?.channelId);
      if (!channelId) {
        const error = new Error('Missing required field: channelId');
        error.statusCode = 400;
        throw error;
      }
      if (!SUPPORTED_PACKET_SCHEMAS.has(normalizeString(packet?.schema))) {
        const error = new Error('Unsupported packet schema');
        error.statusCode = 400;
        throw error;
      }

      const record = {
        id: `relay_${String(state.nextSeq).padStart(6, '0')}_${randomUUID().slice(0, 8)}`,
        seq: state.nextSeq,
        channelId,
        packet,
        status: 'pending',
        attempts: 0,
        createdAt: nowIso(),
        updatedAt: nowIso(),
        leaseId: '',
        leasedBy: '',
        leaseUntil: 0,
        nextAvailableAt: 0,
        completedAt: '',
        result: null,
        lastError: '',
      };

      state.nextSeq += 1;
      state.records.push(record);
      await enqueueSave();
      return record;
    },

    claim(channelId, clientId, leaseMs) {
      const now = nowMs();
      const channelRecords = state.records
        .filter((record) => record.channelId === channelId)
        .sort((left, right) => left.seq - right.seq);

      for (const record of channelRecords) {
        if (record.status === 'done' || record.status === 'failed') continue;

        if (record.status === 'leased' && (record.leaseUntil || 0) > now) {
          continue;
        }

        if ((record.nextAvailableAt || 0) > now) {
          continue;
        }

        if (record.attempts >= maxAttempts) {
          record.status = 'failed';
          record.updatedAt = nowIso();
          record.completedAt = nowIso();
          record.lastError = record.lastError || 'Max retry attempts reached';
          continue;
        }

        record.attempts += 1;
        record.status = 'leased';
        record.leasedBy = clientId;
        record.leaseId = randomId('lease');
        record.leaseUntil = now + leaseMs;
        record.updatedAt = nowIso();
        return record;
      }

      return null;
    },

    complete({ packetId, leaseId, clientId, success, result, error }) {
      const record = state.records.find((item) => item.id === packetId);
      if (!record) {
        const notFound = new Error(`Packet not found: ${packetId}`);
        notFound.statusCode = 404;
        throw notFound;
      }
      if (leaseId && record.leaseId && leaseId !== record.leaseId) {
        const conflict = new Error('Lease id mismatch');
        conflict.statusCode = 409;
        throw conflict;
      }
      if (clientId && record.leasedBy && clientId !== record.leasedBy) {
        const conflict = new Error('Client id mismatch');
        conflict.statusCode = 409;
        throw conflict;
      }

      const now = nowMs();
      record.updatedAt = nowIso();
      record.lastError = success ? '' : normalizeString(error);
      record.result = result ?? null;

      if (success) {
        record.status = 'done';
        record.completedAt = nowIso();
        record.leaseId = '';
        record.leasedBy = '';
        record.leaseUntil = 0;
        record.nextAvailableAt = 0;
      } else {
        const retryable = record.attempts < maxAttempts;
        if (retryable) {
          record.status = 'pending';
          record.leaseId = '';
          record.leasedBy = '';
          record.leaseUntil = 0;
          record.nextAvailableAt = now + backoffMs(record.attempts);
        } else {
          record.status = 'failed';
          record.completedAt = nowIso();
          record.leaseId = '';
          record.leasedBy = '';
          record.leaseUntil = 0;
          record.nextAvailableAt = 0;
        }
      }

      return record;
    },

    getRecord(packetId) {
      return state.records.find((record) => record.id === packetId) || null;
    },

    stats(channelId) {
      return queueStats(state.records, channelId);
    },

    async save() {
      await enqueueSave();
    },
  };

  return queue;
}

async function waitForPacket(queue, channelId, clientId, leaseMs, waitMs) {
  const deadline = nowMs() + waitMs;
  while (true) {
    const claimed = queue.claim(channelId, clientId, leaseMs);
    if (claimed) return claimed;
    if (waitMs <= 0 || nowMs() >= deadline) return null;
    const remaining = Math.max(250, Math.min(500, deadline - nowMs()));
    await new Promise((resolve) => setTimeout(resolve, remaining));
  }
}

function routeMatch(pathname, routes) {
  return routes.includes(pathname);
}

function buildPacketIngestResponse(record) {
  return {
    ok: true,
    data: {
      packetId: record.id,
      channelId: record.channelId,
      status: record.status,
      attempts: record.attempts,
      createdAt: record.createdAt,
      updatedAt: record.updatedAt,
      statusUrl: `/api/lumi/relay/status?id=${encodeURIComponent(record.id)}`,
    },
  };
}

function normalizePacketResponse(record) {
  return {
    ok: true,
    data: {
      packetId: record.id,
      leaseId: record.leaseId,
      channelId: record.channelId,
      leaseUntil: record.leaseUntil,
      attempts: record.attempts,
      packet: record.packet,
    },
  };
}

async function run() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help) {
    console.log(usage());
    return;
  }

  const stateFile = path.join(args.dataDir, 'relay-state.json');
  const queue = createRelayStore(stateFile, args.maxAttempts);
  await queue.hydrate();

  const server = http.createServer(async (req, res) => {
    try {
      const requestUrl = new URL(req.url || '/', `http://${req.headers.host || `${args.host}:${args.port}`}`);
      const { pathname, searchParams } = requestUrl;

      if (req.method === 'OPTIONS') {
        sendNoContent(res);
        return;
      }

      if (req.method === 'GET' && routeMatch(pathname, ['/health', '/api/lumi/relay/health', '/api/lumi/publish/health'])) {
        const authorized = isAuthorized(req, args.authToken);
        sendJson(res, 200, {
          ok: true,
          data: {
            authRequired: Boolean(args.authToken),
            authenticated: authorized,
            queue: authorized ? queue.stats(null) : null,
            timestamp: nowIso(),
          },
        });
        return;
      }

      if (req.method === 'POST' && routeMatch(pathname, ['/api/lumi/relay/packet', '/api/lumi/publish/packet'])) {
        if (!requireRelayAuth(req, res, args.authToken)) return;
        const packet = await readJsonBody(req);
        if (!packet || typeof packet !== 'object') {
          sendJson(res, 400, { ok: false, error: 'Invalid JSON body' });
          return;
        }
        const record = await queue.enqueue(packet);
        sendJson(res, 202, buildPacketIngestResponse(record));
        return;
      }

      if (req.method === 'GET' && routeMatch(pathname, ['/api/lumi/relay/poll', '/api/lumi/publish/poll'])) {
        if (!requireRelayAuth(req, res, args.authToken)) return;
        const channelId = normalizeChannelId(searchParams.get('channelId') || searchParams.get('channel_id'));
        if (!channelId) {
          sendJson(res, 400, { ok: false, error: 'Missing channelId' });
          return;
        }
        const clientId = normalizeClientId(searchParams.get('clientId') || searchParams.get('client_id'));
        const leaseMs = clampInt(Number.parseInt(searchParams.get('leaseMs') || searchParams.get('lease_ms') || `${args.leaseMs}`, 10), 1_000, 15 * 60_000, args.leaseMs);
        const waitMs = clampInt(Number.parseInt(searchParams.get('waitMs') || searchParams.get('wait_ms') || `${args.waitMs}`, 10), 0, 15 * 60_000, args.waitMs);
        const record = await waitForPacket(queue, channelId, clientId, leaseMs, waitMs);
        if (!record) {
          sendJson(res, 200, {
            ok: true,
            data: {
              packet: null,
              channelId,
              clientId,
              waitMs,
              leaseMs,
            },
          });
          return;
        }
        await queue.save();
        sendJson(res, 200, normalizePacketResponse(record));
        return;
      }

      if (req.method === 'POST' && routeMatch(pathname, ['/api/lumi/relay/complete', '/api/lumi/publish/complete'])) {
        if (!requireRelayAuth(req, res, args.authToken)) return;
        const body = await readJsonBody(req);
        if (!body || typeof body !== 'object') {
          sendJson(res, 400, { ok: false, error: 'Invalid JSON body' });
          return;
        }
        const packetId = normalizeString(body.packetId || body.id);
        const leaseId = normalizeString(body.leaseId || body.lease_id);
        const clientId = normalizeClientId(body.clientId || body.client_id);
        if (!packetId) {
          sendJson(res, 400, { ok: false, error: 'Missing packetId' });
          return;
        }
        const record = queue.complete({
          packetId,
          leaseId,
          clientId,
          success: Boolean(body.success),
          result: body.result ?? body.response ?? null,
          error: normalizeString(body.error || body.message),
        });
        await queue.save();
        sendJson(res, 200, {
          ok: true,
          data: summarizeRecord(record),
        });
        return;
      }

      if (req.method === 'GET' && routeMatch(pathname, ['/api/lumi/relay/status', '/api/lumi/publish/status'])) {
        if (!requireRelayAuth(req, res, args.authToken)) return;
        const packetId = normalizeString(searchParams.get('id') || searchParams.get('packetId') || searchParams.get('packet_id'));
        const channelId = normalizeChannelId(searchParams.get('channelId') || searchParams.get('channel_id'));
        if (packetId) {
          const record = queue.getRecord(packetId);
          if (!record) {
            sendJson(res, 404, { ok: false, error: `Packet not found: ${packetId}` });
            return;
          }
          sendJson(res, 200, { ok: true, data: summarizeRecord(record, true) });
          return;
        }
        sendJson(res, 200, {
          ok: true,
          data: {
            queue: queue.stats(channelId || null),
          },
        });
        return;
      }

      sendJson(res, 404, { ok: false, error: `Not found: ${pathname}` });
    } catch (error) {
      const statusCode = Number.isFinite(error?.statusCode) ? error.statusCode : 500;
      sendJson(res, statusCode, { ok: false, error: error?.message || 'Internal error' });
    }
  });

  await new Promise((resolve) => {
    server.listen(args.port, args.host, resolve);
  });

  const address = server.address();
  const actualPort = typeof address === 'object' && address ? address.port : args.port;
  console.log(`[relay] listening on http://${args.host}:${actualPort}`);
  console.log(`[relay] ingest: http://${args.host}:${actualPort}/api/lumi/publish/packet`);
  console.log(`[relay] poll:   http://${args.host}:${actualPort}/api/lumi/publish/poll?channelId=...`);
  console.log(`[relay] health: http://${args.host}:${actualPort}/health`);
  console.log(`[relay] auth:   ${args.authToken ? 'required' : 'disabled'}`);

  const shutdown = async () => {
    await new Promise((resolve) => server.close(resolve));
    await queue.save();
  };

  process.on('SIGINT', async () => {
    try {
      await shutdown();
    } catch (error) {
      console.error(`[relay] shutdown error: ${error?.message || error}`);
    } finally {
      process.exit(0);
    }
  });

  process.on('SIGTERM', async () => {
    try {
      await shutdown();
    } catch (error) {
      console.error(`[relay] shutdown error: ${error?.message || error}`);
    } finally {
      process.exit(0);
    }
  });
}

run().catch((error) => {
  console.error(`[relay] fatal: ${error?.stack || error?.message || error}`);
  process.exit(1);
});
