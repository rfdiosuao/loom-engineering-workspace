import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import http from 'node:http';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const publishScript = path.resolve(__dirname, '..', 'openclaw-publish-phone.mjs');

test('phone publish forwards explicit long-run task budget to APKClaw', async (t) => {
  const requests = [];
  const server = http.createServer(async (request, response) => {
    const url = new URL(request.url || '/', 'http://127.0.0.1');
    const body = request.method === 'GET' ? null : await readJsonBody(request);
    requests.push({ method: request.method, path: url.pathname, body });

    if (request.method === 'POST' && url.pathname === '/api/lumi/security/pair') {
      return writeJson(response, {
        success: true,
        data: {
          launcherId: body?.launcherId || 'test-launcher',
          launcherSecret: 'test-launcher-secret',
        },
      });
    }
    if (request.method === 'POST' && url.pathname === '/api/lumi/agent/tasks') {
      return writeJson(response, { success: true, data: { taskId: 'task-publish-1' } });
    }
    if (request.method === 'GET' && url.pathname === '/api/lumi/agent/tasks/task-publish-1') {
      return writeJson(response, {
        success: true,
        data: {
          status: 'success',
          result: { answer: 'published' },
        },
      });
    }
    response.writeHead(404, { 'Content-Type': 'application/json' });
    response.end(JSON.stringify({ success: false, error: `unexpected ${request.method} ${url.pathname}` }));
  });
  await listen(server);
  t.after(() => server.close());

  const address = server.address();
  const stdout = await runNode([
    publishScript,
    '--phone-url',
    `http://127.0.0.1:${address.port}`,
    '--phone-token',
    'test-token',
    '--platform',
    'xiaohongshu',
    '--title',
    'budget contract',
    '--body',
    'body',
    '--timeout-sec',
    '480',
    '--max-wait-sec',
    '30',
    '--max-rounds',
    '80',
    '--poll-ms',
    '500',
    '--json',
  ]);

  const taskRequest = requests.find((item) => item.method === 'POST' && item.path === '/api/lumi/agent/tasks');
  assert.ok(taskRequest, 'expected APKClaw task submit request');
  assert.equal(taskRequest.body.timeout_sec, 480);
  assert.equal(taskRequest.body.max_rounds, 80);
  assert.match(taskRequest.body.prompt, /只保存草稿/);
  assert.doesNotMatch(taskRequest.body.prompt, /允许点击最终发布/);
  assert.equal(JSON.parse(stdout).status, 'success');
  assert.equal(JSON.parse(stdout).draftOnly, true);
});

test('phone publish exits nonzero when APKClaw reports a failed task', async (t) => {
  const server = http.createServer(async (request, response) => {
    const url = new URL(request.url || '/', 'http://127.0.0.1');
    const body = request.method === 'GET' ? null : await readJsonBody(request);
    if (request.method === 'POST' && url.pathname === '/api/lumi/security/pair') {
      return writeJson(response, {
        success: true,
        data: {
          launcherId: body?.launcherId || 'test-launcher',
          launcherSecret: 'test-launcher-secret',
        },
      });
    }
    if (request.method === 'POST' && url.pathname === '/api/lumi/agent/tasks') {
      return writeJson(response, { success: true, data: { taskId: 'task-publish-failed' } });
    }
    if (request.method === 'GET' && url.pathname === '/api/lumi/agent/tasks/task-publish-failed') {
      return writeJson(response, {
        success: true,
        data: {
          status: 'error',
          result: { error: 'platform rejected draft' },
        },
      });
    }
    response.writeHead(404, { 'Content-Type': 'application/json' });
    response.end(JSON.stringify({ success: false }));
  });
  await listen(server);
  t.after(() => server.close());

  const address = server.address();
  await assert.rejects(
    runNode([
      publishScript,
      '--phone-url',
      `http://127.0.0.1:${address.port}`,
      '--phone-token',
      'test-token',
      '--platform',
      'douyin',
      '--title',
      'failure contract',
      '--max-wait-sec',
      '30',
      '--poll-ms',
      '500',
      '--json',
    ]),
    /process exited 1[\s\S]*platform rejected draft/,
  );
});

test('phone publish exits nonzero when APKClaw reports success with an explicit business failure', async (t) => {
  const server = http.createServer(async (request, response) => {
    const url = new URL(request.url || '/', 'http://127.0.0.1');
    const body = request.method === 'GET' ? null : await readJsonBody(request);
    if (request.method === 'POST' && url.pathname === '/api/lumi/security/pair') {
      return writeJson(response, {
        success: true,
        data: {
          launcherId: body?.launcherId || 'test-launcher',
          launcherSecret: 'test-launcher-secret',
        },
      });
    }
    if (request.method === 'POST' && url.pathname === '/api/lumi/agent/tasks') {
      return writeJson(response, { success: true, data: { taskId: 'task-publish-business-failed' } });
    }
    if (request.method === 'GET' && url.pathname === '/api/lumi/agent/tasks/task-publish-business-failed') {
      return writeJson(response, {
        success: true,
        data: {
          status: 'success',
          result: {
            answer: 'Task completed: 任务执行受阻：抖音需要登录才能进行创作/发布操作。',
          },
        },
      });
    }
    response.writeHead(404, { 'Content-Type': 'application/json' });
    response.end(JSON.stringify({ success: false }));
  });
  await listen(server);
  t.after(() => server.close());

  const address = server.address();
  await assert.rejects(
    runNode([
      publishScript,
      '--phone-url',
      `http://127.0.0.1:${address.port}`,
      '--phone-token',
      'test-token',
      '--platform',
      'douyin',
      '--title',
      'business failure contract',
      '--max-wait-sec',
      '30',
      '--poll-ms',
      '500',
      '--json',
    ]),
    /process exited 1[\s\S]*任务执行受阻/,
  );
});

function listen(server) {
  return new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => {
      server.off('error', reject);
      resolve();
    });
  });
}

function readJsonBody(request) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    request.on('data', (chunk) => chunks.push(chunk));
    request.on('error', reject);
    request.on('end', () => {
      const text = Buffer.concat(chunks).toString('utf8');
      resolve(text.trim() ? JSON.parse(text) : null);
    });
  });
}

function writeJson(response, payload) {
  response.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
  response.end(JSON.stringify(payload));
}

function runNode(args) {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, args, {
      cwd: path.resolve(__dirname, '..', '..'),
      env: { ...process.env },
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    let stdout = '';
    let stderr = '';
    const timer = setTimeout(() => {
      child.kill('SIGKILL');
      reject(new Error(`process timed out\nstdout=${stdout}\nstderr=${stderr}`));
    }, 15000);
    child.stdout.on('data', (chunk) => {
      stdout += chunk.toString('utf8');
    });
    child.stderr.on('data', (chunk) => {
      stderr += chunk.toString('utf8');
    });
    child.on('error', (error) => {
      clearTimeout(timer);
      reject(error);
    });
    child.on('exit', (code) => {
      clearTimeout(timer);
      if (code === 0) {
        resolve(stdout);
      } else {
        reject(new Error(`process exited ${code}\nstdout=${stdout}\nstderr=${stderr}`));
      }
    });
  });
}
