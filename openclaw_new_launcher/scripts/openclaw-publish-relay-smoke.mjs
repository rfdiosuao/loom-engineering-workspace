#!/usr/bin/env node

import { spawn } from 'node:child_process';
import { once } from 'node:events';
import fs from 'node:fs/promises';
import net from 'node:net';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const PROJECT_ROOT = path.resolve(__dirname, '..');
const RELAY_SCRIPT = path.join(__dirname, 'openclaw-publish-relay.mjs');
const SMOKE_DATA_DIR = path.join(PROJECT_ROOT, 'data', '.openclaw', 'publish-relay-smoke');
const SMOKE_TOKEN = 'openclaw-relay-smoke-token';
const CHANNEL_ID = 'smoke-channel';
const CLIENT_ID = 'smoke-client';

async function freePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const address = server.address();
      const port = typeof address === 'object' && address ? address.port : 0;
      server.close(() => resolve(port));
    });
  });
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, options);
  const text = await response.text();
  const json = text ? JSON.parse(text) : null;
  return { status: response.status, json };
}

function authHeaders(token = SMOKE_TOKEN) {
  return {
    Authorization: `Bearer ${token}`,
    'X-OpenClaw-Relay-Token': token,
  };
}

async function waitForRelay(baseUrl, child) {
  const startedAt = Date.now();
  while (Date.now() - startedAt < 10_000) {
    if (child.exitCode != null) {
      throw new Error(`Relay exited early with code ${child.exitCode}`);
    }
    try {
      const response = await requestJson(`${baseUrl}/health`);
      if (response.status === 200) return;
    } catch {
      // wait
    }
    await new Promise((resolve) => setTimeout(resolve, 150));
  }
  throw new Error('Timed out waiting for relay startup');
}

async function stopChild(child) {
  if (child.exitCode != null) return;
  child.kill();
  await Promise.race([
    once(child, 'exit'),
    new Promise((resolve) => setTimeout(resolve, 3000)),
  ]);
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

async function run() {
  await fs.rm(SMOKE_DATA_DIR, { recursive: true, force: true });
  const port = await freePort();
  const baseUrl = `http://127.0.0.1:${port}`;
  const child = spawn(process.execPath, [
    RELAY_SCRIPT,
    '--host',
    '127.0.0.1',
    '--port',
    String(port),
    '--data-dir',
    SMOKE_DATA_DIR,
    '--wait-ms',
    '0',
    '--auth-token',
    SMOKE_TOKEN,
  ], {
    stdio: ['ignore', 'pipe', 'pipe'],
    windowsHide: true,
  });

  let stdout = '';
  let stderr = '';
  child.stdout.on('data', (chunk) => {
    stdout += chunk.toString();
  });
  child.stderr.on('data', (chunk) => {
    stderr += chunk.toString();
  });

  try {
    await waitForRelay(baseUrl, child);

    const publicHealth = await requestJson(`${baseUrl}/health`);
    assert(publicHealth.status === 200, `health expected 200, got ${publicHealth.status}`);
    assert(publicHealth.json?.data?.authRequired === true, 'health should report authRequired=true');
    assert(publicHealth.json?.data?.queue === null, 'unauthenticated health should not expose queue stats');

    const packet = {
      schema: 'openclaw.publish.packet.v1',
      channelId: CHANNEL_ID,
      platformId: 'custom',
      title: 'relay smoke',
      body: 'relay smoke',
      media: [],
    };

    const deniedIngest = await requestJson(`${baseUrl}/api/lumi/publish/packet`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(packet),
    });
    assert(deniedIngest.status === 401, `unauthenticated ingest expected 401, got ${deniedIngest.status}`);

    const ingest = await requestJson(`${baseUrl}/api/lumi/publish/packet`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify(packet),
    });
    assert(ingest.status === 202, `authenticated ingest expected 202, got ${ingest.status}`);

    const deniedPoll = await requestJson(`${baseUrl}/api/lumi/relay/poll?channelId=${CHANNEL_ID}&clientId=${CLIENT_ID}&waitMs=0`);
    assert(deniedPoll.status === 401, `unauthenticated poll expected 401, got ${deniedPoll.status}`);

    const poll = await requestJson(`${baseUrl}/api/lumi/relay/poll?channelId=${CHANNEL_ID}&clientId=${CLIENT_ID}&waitMs=0&leaseMs=30000`, {
      headers: authHeaders(),
    });
    assert(poll.status === 200, `authenticated poll expected 200, got ${poll.status}`);
    assert(poll.json?.data?.packet?.schema === 'openclaw.publish.packet.v1', 'poll did not return publish packet');

    const complete = await requestJson(`${baseUrl}/api/lumi/relay/complete`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify({
        packetId: poll.json.data.packetId,
        leaseId: poll.json.data.leaseId,
        clientId: CLIENT_ID,
        success: true,
        result: { ok: true },
      }),
    });
    assert(complete.status === 200, `complete expected 200, got ${complete.status}`);

    const status = await requestJson(`${baseUrl}/api/lumi/relay/status?id=${encodeURIComponent(poll.json.data.packetId)}`, {
      headers: authHeaders(),
    });
    assert(status.status === 200, `status expected 200, got ${status.status}`);
    assert(status.json?.data?.status === 'done', `status expected done, got ${status.json?.data?.status}`);

    console.log(JSON.stringify({
      ok: true,
      baseUrl,
      packetId: poll.json.data.packetId,
      status: status.json.data.status,
      authRequired: publicHealth.json.data.authRequired,
    }, null, 2));
  } catch (error) {
    console.error(error?.stack || error?.message || error);
    if (stdout.trim()) console.error(`\nrelay stdout:\n${stdout}`);
    if (stderr.trim()) console.error(`\nrelay stderr:\n${stderr}`);
    process.exitCode = 1;
  } finally {
    await stopChild(child);
    await fs.rm(SMOKE_DATA_DIR, { recursive: true, force: true });
  }
}

run().catch((error) => {
  console.error(error?.stack || error?.message || error);
  process.exit(1);
});
