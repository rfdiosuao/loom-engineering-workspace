import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import fs from 'node:fs/promises';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { phoneRuntimeTestEnv } from './phone-runtime-auth-fixture.mjs';

const SCRIPT = path.resolve(
  path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1')),
  '..',
  'openclaw-phone-fleet.mjs',
);

function listen(server) {
  return new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => resolve(server.address()));
  });
}

function runNode(args, env) {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [SCRIPT, ...args], {
      env: { ...process.env, ...env },
      windowsHide: true,
    });
    let stdout = '';
    let stderr = '';
    child.stdout.on('data', (chunk) => { stdout += chunk; });
    child.stderr.on('data', (chunk) => { stderr += chunk; });
    child.once('error', reject);
    child.once('exit', (code) => resolve({ code, stdout, stderr }));
  });
}

test('fleet run cooperatively cancels the remote phone task', async () => {
  const tempDir = await fs.mkdtemp(path.join(os.tmpdir(), 'loom-fleet-cancel-'));
  const cancelFile = path.join(tempDir, 'fleet.cancel');
  const seen = [];
  let resolveFirstPoll;
  const firstPoll = new Promise((resolve) => { resolveFirstPoll = resolve; });
  const server = http.createServer((request, response) => {
    seen.push(`${request.method} ${request.url}`);
    response.setHeader('Content-Type', 'application/json');
    if (request.method === 'POST' && request.url === '/api/lumi/agent/tasks') {
      response.end(JSON.stringify({ success: true, data: { taskId: 'task-fleet-cancel' } }));
      return;
    }
    if (request.method === 'GET' && request.url === '/api/lumi/agent/tasks/task-fleet-cancel') {
      resolveFirstPoll();
      response.end(JSON.stringify({ success: true, data: { status: 'running' } }));
      return;
    }
    if (request.method === 'POST' && request.url === '/api/lumi/agent/tasks/task-fleet-cancel/cancel') {
      response.end(JSON.stringify({ success: true, data: { status: 'cancelled' } }));
      return;
    }
    response.statusCode = 404;
    response.end(JSON.stringify({ error: 'not_found' }));
  });

  try {
    const address = await listen(server);
    const runtime = {
      selectedDeviceId: 'phone-a',
      devices: [{
        id: 'phone-a',
        name: 'Phone A',
        baseUrl: `http://127.0.0.1:${address.port}`,
        token: 'test-phone-token',
        launcherId: 'loom-test-launcher',
        launcherSecret: 'test-launcher-secret',
      }],
    };
    const running = runNode([
      'run',
      '--target',
      'phone-a',
      '--prompt',
      'inspect',
      '--poll-ms',
      '100',
      '--cancel-file',
      cancelFile,
      '--json',
    ], phoneRuntimeTestEnv(runtime));
    const firstEvent = await Promise.race([
      firstPoll.then(() => ({ type: 'poll' })),
      running.then((result) => ({ type: 'exit', result })),
      new Promise((resolve) => {
        const timer = setTimeout(() => resolve({ type: 'timeout' }), 5_000);
        timer.unref?.();
      }),
    ]);
    assert.equal(
      firstEvent.type,
      'poll',
      firstEvent.type === 'exit'
        ? `fleet exited before polling: ${firstEvent.result.stderr || firstEvent.result.stdout}`
        : 'fleet did not poll the fake phone within five seconds',
    );
    await fs.writeFile(cancelFile, 'cancelled\n', 'utf8');
    const result = await running;

    assert.equal(result.code, 0, result.stderr);
    const payload = JSON.parse(result.stdout);
    assert.equal(payload.results[0].final.status, 'cancelled');
    assert.equal(
      seen.includes('POST /api/lumi/agent/tasks/task-fleet-cancel/cancel'),
      true,
    );
  } finally {
    server.close();
    await fs.rm(tempDir, { recursive: true, force: true });
  }
});
