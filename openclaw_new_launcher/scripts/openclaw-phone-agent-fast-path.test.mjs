import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import { spawn } from 'node:child_process';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import { test } from 'node:test';
import { progressLogFromEvents, withProgressLogsInSseEvent } from './lib/phone-progress-log.mjs';

test('legacy APK events are translated into the compatible Chinese progress log', () => {
  const progressLog = progressLogFromEvents([
    { type: 'loop_start', round: 4, time: 100 },
    { type: 'tool_call', round: 4, toolId: 'get_screen_info', time: 200 },
    { type: 'complete', round: 4, success: true, time: 300 },
  ]);

  assert.deepEqual(progressLog.map((item) => item.text), [
    '第 4 阶段：分析下一步',
    '第 4 阶段：读取当前页面',
    '任务执行完成',
  ]);
});

test('legacy SSE task snapshots receive progressLog without changing raw events', () => {
  const event = {
    event: 'snapshot',
    data: {
      tasks: [{
        taskId: 'task-1',
        status: 'running',
        events: [{ type: 'tool_call', round: 2, toolId: 'tap', time: 500 }],
      }],
    },
  };

  const normalized = withProgressLogsInSseEvent(event);

  assert.equal(normalized.data.tasks[0].progressLog[0].text, '第 2 阶段：点击页面元素');
  assert.deepEqual(normalized.data.tasks[0].events, event.data.tasks[0].events);
});

test('legacy public SSE snapshots can backfill progress from agentReport.lastEvent', () => {
  const normalized = withProgressLogsInSseEvent({
    event: 'snapshot',
    data: {
      tasks: [{
        taskId: 'task-public',
        status: 'running',
        agentReport: {
          lastEvent: { type: 'tool_call', round: 3, toolId: 'open_app', time: 600 },
        },
      }],
    },
  });

  assert.equal(normalized.data.tasks[0].progressLog[0].text, '第 3 阶段：打开应用');
});

test('provided progress log is rebuilt from whitelisted fields instead of copying private text', () => {
  const normalized = withProgressLogsInSseEvent({
    event: 'snapshot',
    data: {
      tasks: [{
        taskId: 'task-private',
        progressLog: [{
          round: 2,
          type: 'tool',
          toolId: 'get_screen_info',
          text: 'private screen text sk-secret-123456789',
          parameters: { account: 'private@example.com' },
          time: 700,
        }],
      }],
    },
  });

  const serialized = JSON.stringify(normalized.data.tasks[0].progressLog);
  assert.equal(normalized.data.tasks[0].progressLog[0].text, '第 2 阶段：读取当前页面');
  assert.equal(serialized.includes('parameters'), false);
  assert.equal(serialized.includes('sk-secret-123456789'), false);
  assert.equal(serialized.includes('private@example.com'), false);
});

test('open-settings template run uses action_fast instead of async Agent task', async () => {
  const seen = [];
  let actionBody = null;
  const server = http.createServer(async (request, response) => {
    seen.push(`${request.method} ${request.url}`);
    const body = await readBody(request);

    if (request.method === 'GET' && request.url === '/api/device/status') {
      return sendJson(response, {
        success: true,
        data: readyStatus({ llmConfigured: true }),
      });
    }
    if (request.method === 'POST' && request.url === '/api/lumi/security/pair') {
      return sendJson(response, {
        success: true,
        data: { launcherId: 'test-launcher', launcherSecret: 'test-secret' },
      });
    }
    if (request.method === 'POST' && request.url.startsWith('/api/lumi/agent/action_fast')) {
      actionBody = JSON.parse(body || '{}');
      return sendJson(response, {
        success: true,
        data: {
          mode: 'action_fast',
          action: 'open_app',
          currentStep: 'complete',
          summary: 'Settings',
          currentPackage: 'com.android.settings',
          screenHash: 'hash-after-open-settings',
          beforeHash: 'hash-before-open-settings',
          afterHash: 'hash-after-open-settings',
          changed: true,
          actionMs: 11,
          verifyMs: 17,
          metrics: { mode: 'action_fast', totalMs: 24, rounds: 0 },
          events: [{ type: 'action_fast_completed', success: true }],
        },
      });
    }
    if (request.method === 'POST' && request.url === '/api/lumi/agent/tasks') {
      return sendJson(response, { success: false, error: 'async_agent_should_not_be_called' }, 500);
    }

    return sendJson(response, { success: false, error: `unexpected ${request.method} ${request.url}` }, 404);
  });

  await listen(server);
  try {
    const port = server.address().port;
    const result = await runCli([
      'run',
      '--phone-url',
      `http://127.0.0.1:${port}`,
      '--phone-token',
      'test-token',
      '--execution-layer',
      'template',
      '--template',
      'open-settings',
      '--daemon',
      'off',
      '--prompt',
      '打开系统设置',
      '--json',
      '--step-timeout-sec',
      '5',
      '--timeout-sec',
      '30',
      '--max-wait-sec',
      '30',
    ]);

    assert.equal(result.code, 0, result.stderr);
    const payload = JSON.parse(result.stdout);
    assert.equal(payload.ok, true);
    assert.equal(payload.mode, 'action_fast');
    assert.equal(payload.metrics.rounds, 0);
    assert.equal(payload.screenHash, 'hash-after-open-settings');
    assert.equal(payload.beforeHash, 'hash-before-open-settings');
    assert.equal(payload.afterHash, 'hash-after-open-settings');
    assert.equal(payload.changed, true);
    assert.equal(payload.actionMs, 11);
    assert.equal(payload.verifyMs, 17);
    assert.equal(payload.currentPackage, 'com.android.settings');
    assert.equal(actionBody.action, 'open_app');
    assert.equal(actionBody.packageName, 'com.android.settings');
    assert.equal(actionBody.verifyForeground, true);
    assert.equal(seen.includes('POST /api/lumi/agent/tasks'), false);
    assert.equal(seen.some((line) => line.startsWith('POST /api/lumi/agent/action_fast')), true);
  } finally {
    await close(server);
  }
});

test('read-screen template run uses observe_fast without requiring an LLM model', async () => {
  const seen = [];
  const server = http.createServer(async (request, response) => {
    seen.push(`${request.method} ${request.url}`);
    await readBody(request);

    if (request.method === 'GET' && request.url === '/api/device/status') {
      return sendJson(response, {
        success: true,
        data: readyStatus({ llmConfigured: false, modelConfigured: false, modelReady: false }),
      });
    }
    if (request.method === 'POST' && request.url === '/api/lumi/security/pair') {
      return sendJson(response, {
        success: true,
        data: { launcherId: 'test-launcher', launcherSecret: 'test-secret' },
      });
    }
    if (request.method === 'GET' && request.url === '/api/lumi/agent/observe_fast?_lumi=1') {
      return sendJson(response, {
        success: true,
        data: {
          mode: 'observe_fast',
          summary: 'Home screen',
          currentPackage: 'com.example.home',
          screenHash: 'hash-fast',
          metrics: { mode: 'observe_fast', totalMs: 12, rounds: 0 },
        },
      });
    }
    if (request.method === 'POST' && request.url === '/api/lumi/agent/tasks') {
      return sendJson(response, { success: false, error: 'async_agent_should_not_be_called' }, 500);
    }

    return sendJson(response, { success: false, error: `unexpected ${request.method} ${request.url}` }, 404);
  });

  await listen(server);
  try {
    const port = server.address().port;
    const result = await runCli([
      'run',
      '--phone-url',
      `http://127.0.0.1:${port}`,
      '--phone-token',
      'test-token',
      '--execution-layer',
      'template',
      '--template',
      'read-screen',
      '--daemon',
      'off',
      '--prompt',
      '读取当前屏幕',
      '--json',
      '--step-timeout-sec',
      '5',
      '--timeout-sec',
      '30',
      '--max-wait-sec',
      '30',
    ]);

    assert.equal(result.code, 0, result.stderr);
    const payload = JSON.parse(result.stdout);
    assert.equal(payload.ok, true);
    assert.equal(payload.mode, 'observe_fast');
    assert.equal(payload.stalePossible, true);
    assert.equal(payload.metrics.rounds, 0);
    assert.equal(payload.currentStep, 'success');
    assert.equal(seen.includes('POST /api/lumi/agent/tasks'), false);
    assert.equal(seen.includes('GET /api/lumi/agent/observe_fast?_lumi=1'), true);
  } finally {
    await close(server);
  }
});

test('parallel explicit CLI calls reuse the same generated Lumi launcher id', async () => {
  const launcherIds = [];
  let activeActions = 0;
  let maxActiveActions = 0;
  const server = http.createServer(async (request, response) => {
    const body = await readBody(request);

    if (request.method === 'GET' && request.url === '/api/device/status') {
      return sendJson(response, {
        success: true,
        data: readyStatus({ llmConfigured: true }),
      });
    }
    if (request.method === 'POST' && request.url === '/api/lumi/security/pair') {
      const parsed = JSON.parse(body || '{}');
      launcherIds.push(parsed.launcherId);
      return sendJson(response, {
        success: true,
        data: { launcherId: parsed.launcherId, launcherSecret: 'shared-secret' },
      });
    }
    if (request.method === 'POST' && request.url.startsWith('/api/lumi/agent/action_fast')) {
      activeActions += 1;
      maxActiveActions = Math.max(maxActiveActions, activeActions);
      await delay(120);
      activeActions -= 1;
      return sendJson(response, {
        success: true,
        data: {
          mode: 'action_fast',
          currentStep: 'complete',
          metrics: { mode: 'action_fast', totalMs: 10, rounds: 0 },
        },
      });
    }

    return sendJson(response, { success: false, error: `unexpected ${request.method} ${request.url}` }, 404);
  });

  await listen(server);
  try {
    const port = server.address().port;
    const baseArgs = [
      'run',
      '--phone-url',
      `http://127.0.0.1:${port}`,
      '--phone-token',
      'test-token',
      '--execution-layer',
      'template',
      '--template',
      'open-settings',
      '--daemon',
      'off',
      '--prompt',
      '打开系统设置',
      '--json',
      '--step-timeout-sec',
      '5',
      '--timeout-sec',
      '30',
      '--max-wait-sec',
      '30',
    ];

    const results = await Promise.all([runCli(baseArgs), runCli(baseArgs)]);

    assert.equal(results[0].code, 0, results[0].stderr);
    assert.equal(results[1].code, 0, results[1].stderr);
    assert.equal(launcherIds.length, 2);
    assert.equal(new Set(launcherIds).size, 1);
    assert.equal(maxActiveActions, 1);
  } finally {
    await close(server);
  }
});

test('unreachable phone url returns structured LAN Config guidance', async () => {
  const port = await unusedPort();
  const result = await runCli([
    'metrics',
    '--daemon',
    'off',
    '--phone-url',
    `http://127.0.0.1:${port}`,
    '--phone-token',
    'test-token',
    '--json',
    '--step-timeout-sec',
    '5',
  ]);

  assert.notEqual(result.code, 0);
  const payload = JSON.parse(result.stdout);
  assert.equal(payload.ok, false);
  assert.equal(payload.errorCode, 'phone_config_server_unreachable');
  assert.match(payload.message, /APKClaw ConfigServer/);
  assert.match(payload.remediation.join('\n'), /APKClaw -> Settings -> LAN Config/);
});

test('reachable phone with an invalid connection token reports auth_failed instead of device_offline', async () => {
  const server = http.createServer((request, response) => {
    if (request.method === 'GET' && request.url === '/api/device/status') {
      return sendJson(response, {
        success: false,
        error: 'Unauthorized: invalid or missing token',
      }, 401);
    }
    return sendJson(response, { success: false, error: `unexpected ${request.method} ${request.url}` }, 404);
  });

  await listen(server);
  try {
    const port = server.address().port;
    const result = await runCli([
      'run',
      '--daemon',
      'off',
      '--phone-url',
      `http://127.0.0.1:${port}`,
      '--phone-token',
      'stale-token',
      '--prompt',
      'inspect current page',
      '--json',
      '--step-timeout-sec',
      '5',
    ]);

    assert.notEqual(result.code, 0);
    const payload = JSON.parse(result.stdout);
    assert.equal(payload.ok, false);
    assert.equal(payload.errorCode, 'auth_failed');
    assert.equal(payload.message.includes('device_offline'), false);
    assert.match(payload.message, /连接令牌/);
    assert.match(payload.remediation.join('\n'), /重新复制/);
  } finally {
    await close(server);
  }
});

test('vision action supports PowerShell-safe action body file', async () => {
  let actionBody = null;
  const server = http.createServer(async (request, response) => {
    const body = await readBody(request);
    if (request.method === 'POST' && request.url === '/api/lumi/security/pair') {
      const parsed = JSON.parse(body || '{}');
      return sendJson(response, {
        success: true,
        data: { launcherId: parsed.launcherId, launcherSecret: 'vision-secret' },
      });
    }
    if (request.method === 'POST' && request.url.startsWith('/api/lumi/agent/action_fast')) {
      actionBody = JSON.parse(body || '{}');
      return sendJson(response, {
        success: true,
        data: {
          mode: 'action_fast',
          action: actionBody.action,
          currentStep: 'complete',
          metrics: { mode: 'action_fast', totalMs: 9, rounds: 0 },
        },
      });
    }
    return sendJson(response, { success: false, error: `unexpected ${request.method} ${request.url}` }, 404);
  });

  const tmpDir = await fs.mkdtemp(path.join(os.tmpdir(), 'loom-vision-body-'));
  await listen(server);
  try {
    const bodyPath = path.join(tmpDir, 'action.json');
    await fs.writeFile(bodyPath, JSON.stringify({
      action: 'tap',
      gridCell: 'C7',
      targetLabel: 'settings button',
      reason: 'open settings',
    }), 'utf8');
    const port = server.address().port;
    const result = await runVisionCli([
      'action',
      '--force-action',
      '--fast-path',
      'action_fast',
      '--phone-url',
      `http://127.0.0.1:${port}`,
      '--phone-token',
      'test-token',
      '--action-body-file',
      bodyPath,
      '--json',
    ]);

    assert.equal(result.code, 0, result.stderr);
    const payload = JSON.parse(result.stdout);
    assert.equal(payload.success, true);
    assert.equal(actionBody.action, 'tap');
    assert.equal(actionBody.gridCell, 'C7');
  } finally {
    await close(server);
    await fs.rm(tmpDir, { recursive: true, force: true });
  }
});

test('vision frame accepts a configurable timeout budget for slow phone screenshots', async () => {
  const server = http.createServer(async (request, response) => {
    const body = await readBody(request);
    if (request.method === 'POST' && request.url === '/api/lumi/security/pair') {
      const parsed = JSON.parse(body || '{}');
      return sendJson(response, {
        success: true,
        data: { launcherId: parsed.launcherId, launcherSecret: 'vision-secret' },
      });
    }
    if (request.method === 'GET' && request.url.startsWith('/api/lumi/vision/frame?')) {
      await delay(80);
      return sendJson(response, {
        success: true,
        data: {
          capturedAt: '2026-07-21T12:00:00Z',
          width: 360,
          height: 800,
          image: { mime: 'image/jpeg', width: 360, height: 800, base64: 'QUJD' },
        },
      });
    }
    return sendJson(response, { success: false, error: `unexpected ${request.method} ${request.url}` }, 404);
  });

  const tmpDir = await fs.mkdtemp(path.join(os.tmpdir(), 'loom-vision-frame-'));
  await listen(server);
  try {
    const port = server.address().port;
    const outputPath = path.join(tmpDir, 'frame.jpg');
    const result = await runVisionCli([
      'frame',
      '--phone-url',
      `http://127.0.0.1:${port}`,
      '--phone-token',
      'test-token',
      '--frame-timeout-ms',
      '500',
      '--out',
      outputPath,
      '--json',
    ]);

    assert.equal(result.code, 0, result.stderr);
    const payload = JSON.parse(result.stdout);
    assert.equal(payload.ok, true);
    assert.equal(payload.frame.width, 360);
    assert.equal(await fs.readFile(outputPath, 'base64'), 'QUJD');
  } finally {
    await close(server);
    await fs.rm(tmpDir, { recursive: true, force: true });
  }
});

test('vision read preserves observe_fast accessibility errors instead of returning legacy placeholder success', async () => {
  const seen = [];
  const server = http.createServer(async (request, response) => {
    seen.push(`${request.method} ${request.url}`);
    const body = await readBody(request);

    if (request.method === 'POST' && request.url === '/api/lumi/security/pair') {
      const parsed = JSON.parse(body || '{}');
      return sendJson(response, {
        success: true,
        data: { launcherId: parsed.launcherId, launcherSecret: 'vision-secret' },
      });
    }
    if (request.method === 'GET' && request.url === '/api/lumi/agent/observe_fast?_lumi=1') {
      return sendJson(response, {
        success: false,
        data: {
          success: false,
          errorCode: 'accessibility_off',
          message: 'Enable APKClaw Accessibility before reading the screen.',
          currentStep: 'precheck',
          mode: 'observe_fast',
          retryable: true,
          accessibilityState: 'disabled',
        },
      }, 409);
    }
    if (request.method === 'GET' && request.url === '/api/tool/screen_tree') {
      return sendJson(response, { success: true, data: { text: '0' } });
    }
    if (request.method === 'GET' && request.url.startsWith('/api/lumi/device/profile')) {
      return sendJson(response, { success: true, data: { text: '0' } });
    }
    return sendJson(response, { success: false, error: `unexpected ${request.method} ${request.url}` }, 404);
  });

  await listen(server);
  try {
    const port = server.address().port;
    const result = await runVisionCli([
      'read',
      '--phone-url',
      `http://127.0.0.1:${port}`,
      '--phone-token',
      'test-token',
      '--json',
    ]);

    assert.notEqual(result.code, 0);
    const payload = JSON.parse(result.stdout);
    assert.equal(payload.ok, false);
    assert.equal(payload.errorCode, 'accessibility_off');
    assert.equal(payload.retryable, true);
    assert.equal(payload.currentStep, 'precheck');
    assert.equal(seen.includes('GET /api/tool/screen_tree'), false);
    assert.equal(seen.some((line) => line.startsWith('GET /api/lumi/device/profile')), false);
  } finally {
    await close(server);
  }
});

test('wechat-reply command calls signed safe auto reply endpoint', async () => {
  let requestBody = null;
  const server = http.createServer(async (request, response) => {
    const body = await readBody(request);
    if (request.method === 'POST' && request.url === '/api/lumi/security/pair') {
      const parsed = JSON.parse(body || '{}');
      return sendJson(response, {
        success: true,
        data: { launcherId: parsed.launcherId, launcherSecret: 'wechat-secret' },
      });
    }
    if (request.method === 'POST' && request.url === '/api/lumi/wechat/auto_reply') {
      requestBody = JSON.parse(body || '{}');
      return sendJson(response, {
        success: true,
        data: {
          mode: 'wechat_auto_reply',
          currentStep: 'drafted',
          contact: 'Alice',
          latestMessage: 'hello',
          replyText: requestBody.replyText,
          autoSend: requestBody.autoSend,
          sent: false,
        },
      });
    }
    return sendJson(response, { success: false, error: `unexpected ${request.method} ${request.url}` }, 404);
  });

  await listen(server);
  try {
    const port = server.address().port;
    const result = await runCli([
      'wechat-reply',
      '--phone-url',
      `http://127.0.0.1:${port}`,
      '--phone-token',
      'test-token',
      '--reply',
      '你好，我稍后回复你',
      '--json',
    ]);

    assert.equal(result.code, 0, result.stderr);
    const payload = JSON.parse(result.stdout);
    assert.equal(payload.ok, true);
    assert.equal(payload.mode, 'wechat_auto_reply');
    assert.equal(payload.currentStep, 'drafted');
    assert.equal(requestBody.replyText, '你好，我稍后回复你');
    assert.equal(requestBody.autoSend, false);
  } finally {
    await close(server);
  }
});

test('task events command polls task-specific Lumi events endpoint', async () => {
  const seen = [];
  const server = http.createServer(async (request, response) => {
    seen.push(`${request.method} ${request.url}`);
    await readBody(request);

    if (request.method === 'GET' && request.url === '/api/device/status') {
      return sendJson(response, { success: true, data: readyStatus({ llmConfigured: true }) });
    }
    if (request.method === 'POST' && request.url === '/api/lumi/security/pair') {
      return sendJson(response, {
        success: true,
        data: { launcherId: 'test-launcher', launcherSecret: 'test-secret' },
      });
    }
    if (request.method === 'GET' && request.url === '/api/lumi/agent/tasks/task-123/events') {
      return sendJson(response, {
        success: true,
        data: {
          taskId: 'task-123',
          status: 'running',
          cancelRequested: false,
          events: [{ type: 'tool_call', round: 1, message: 'Open App' }],
        },
      });
    }

    return sendJson(response, { success: false, error: `unexpected ${request.method} ${request.url}` }, 404);
  });

  await listen(server);
  try {
    const port = server.address().port;
    const result = await runCli([
      'events',
      '--phone-url',
      `http://127.0.0.1:${port}`,
      '--phone-token',
      'test-token',
      '--task-id',
      'task-123',
      '--daemon',
      'off',
      '--json',
    ]);

    assert.equal(result.code, 0, result.stderr);
    const payload = JSON.parse(result.stdout);
    assert.equal(payload.success, true);
    assert.equal(payload.data.taskId, 'task-123');
    assert.equal(payload.data.events[0].type, 'tool_call');
    assert.equal(seen.includes('GET /api/lumi/agent/tasks/task-123/events'), true);
  } finally {
    await close(server);
  }
});

test('run cooperatively cancels the remote APKClaw task when the launcher cancel file appears', async () => {
  const seen = [];
  const tempDir = await fs.mkdtemp(path.join(os.tmpdir(), 'loom-phone-cancel-'));
  const cancelFile = path.join(tempDir, 'job.cancel');
  let releaseBlockedPoll;
  const blockedPoll = new Promise((resolve) => {
    releaseBlockedPoll = resolve;
  });
  const server = http.createServer(async (request, response) => {
    seen.push(`${request.method} ${request.url}`);
    await readBody(request);

    if (request.method === 'GET' && request.url === '/api/device/status') {
      return sendJson(response, { success: true, data: readyStatus({ llmConfigured: true }) });
    }
    if (request.method === 'POST' && request.url === '/api/lumi/security/pair') {
      return sendJson(response, {
        success: true,
        data: { launcherId: 'test-launcher', launcherSecret: 'test-secret' },
      });
    }
    if (request.method === 'POST' && request.url === '/api/lumi/agent/tasks') {
      return sendJson(response, { success: true, data: { taskId: 'task-cancel' } });
    }
    if (request.method === 'GET' && request.url === '/api/lumi/agent/tasks/task-cancel') {
      await blockedPoll;
      return sendJson(response, { success: true, data: { taskId: 'task-cancel', status: 'running' } });
    }
    if (request.method === 'POST' && request.url === '/api/lumi/agent/tasks/task-cancel/cancel') {
      releaseBlockedPoll();
      return sendJson(response, { success: true, data: { taskId: 'task-cancel', status: 'cancelled' } });
    }
    return sendJson(response, { success: false, error: `unexpected ${request.method} ${request.url}` }, 404);
  });

  await listen(server);
  try {
    const port = server.address().port;
    const startedAt = Date.now();
    const cliPromise = runCli([
      'run',
      '--phone-url',
      `http://127.0.0.1:${port}`,
      '--phone-token',
      'test-token',
      '--prompt',
      'cooperative cancellation probe',
      '--mode',
      'safe',
      '--daemon',
      'off',
      '--cancel-file',
      cancelFile,
      '--json',
    ]);
    const pollDeadline = Date.now() + 3_000;
    while (!seen.includes('GET /api/lumi/agent/tasks/task-cancel') && Date.now() < pollDeadline) {
      await new Promise((resolve) => setTimeout(resolve, 20));
    }
    assert.equal(seen.includes('GET /api/lumi/agent/tasks/task-cancel'), true);
    await fs.writeFile(cancelFile, 'cancelled\n', 'utf8');
    const result = await cliPromise;

    assert.equal(result.code, 0, result.stderr);
    const payload = JSON.parse(result.stdout);
    assert.equal(payload.ok, false);
    assert.equal(payload.error, 'cancelled');
    assert.equal(seen.includes('POST /api/lumi/agent/tasks/task-cancel/cancel'), true);
    assert.ok(Date.now() - startedAt < 4_000, 'cancellation must interrupt an in-flight task poll');
  } finally {
    releaseBlockedPoll();
    await close(server);
    await fs.rm(tempDir, { recursive: true, force: true });
  }
});

test('canonical Matrix assignment fields reach the APKClaw task body unchanged', async () => {
  let submittedBody = null;
  const server = http.createServer(async (request, response) => {
    const rawBody = await readBody(request);
    if (request.method === 'GET' && request.url === '/api/device/status') {
      return sendJson(response, { success: true, data: readyStatus({ llmConfigured: true }) });
    }
    if (request.method === 'POST' && request.url === '/api/lumi/security/pair') {
      return sendJson(response, {
        success: true,
        data: { launcherId: 'matrix-launcher', launcherSecret: 'matrix-secret' },
      });
    }
    if (request.method === 'POST' && request.url === '/api/lumi/agent/tasks') {
      submittedBody = JSON.parse(rawBody || '{}');
      return sendJson(response, { success: true, data: { taskId: 'matrix-task' } });
    }
    if (request.method === 'GET' && request.url === '/api/lumi/agent/tasks/matrix-task') {
      return sendJson(response, {
        success: true,
        data: { taskId: 'matrix-task', status: 'success', result: { summary: 'done' } },
      });
    }
    return sendJson(response, { success: false, error: `unexpected ${request.method} ${request.url}` }, 404);
  });

  await listen(server);
  try {
    const port = server.address().port;
    const assignmentInput = { candidateId: 'candidate-7', filters: { active: true } };
    const result = await runCli([
      'run',
      '--daemon',
      'off',
      '--phone-url',
      `http://127.0.0.1:${port}`,
      '--phone-token',
      'test-token',
      '--device-id',
      'phone-b',
      '--prompt',
      'Execute this exact canonical prompt.',
      '--mode',
      'safe',
      '--execution-layer',
      'template',
      '--template',
      'read-screen',
      '--campaign-id',
      'campaign-canonical-7',
      '--assignment-id',
      'assignment-canonical-7',
      '--assignment-template-id',
      'screen_read_v1',
      '--input-json',
      JSON.stringify(assignmentInput),
      '--timeout-sec',
      '180',
      '--max-wait-sec',
      '180',
      '--retry-budget',
      '2',
      '--poll-ms',
      '500',
      '--json',
    ]);

    assert.equal(result.code, 0, result.stderr || result.stdout);
    assert.ok(submittedBody);
    assert.equal(submittedBody.prompt, 'Execute this exact canonical prompt.');
    assert.equal(submittedBody.campaign_id, 'campaign-canonical-7');
    assert.equal(submittedBody.assignment_id, 'assignment-canonical-7');
    assert.equal(submittedBody.assignment_template_id, 'screen_read_v1');
    assert.equal(submittedBody.device_id, 'phone-b');
    assert.deepEqual(submittedBody.input, assignmentInput);
    assert.equal(submittedBody.timeout_sec, 180);
    assert.equal(submittedBody.retry_budget, 2);
    assert.deepEqual(submittedBody.template_params.input, assignmentInput);
    assert.equal(submittedBody.template_params.assignment_id, 'assignment-canonical-7');
  } finally {
    await close(server);
  }
});

test('run keeps tracking the same phone task after a transient status poll failure', async () => {
  let statusPolls = 0;
  const server = http.createServer(async (request, response) => {
    await readBody(request);
    if (request.method === 'GET' && request.url === '/api/device/status') {
      return sendJson(response, { success: true, data: readyStatus({ llmConfigured: true }) });
    }
    if (request.method === 'POST' && request.url === '/api/lumi/security/pair') {
      return sendJson(response, {
        success: true,
        data: { launcherId: 'test-launcher', launcherSecret: 'test-secret' },
      });
    }
    if (request.method === 'POST' && request.url === '/api/lumi/agent/tasks') {
      return sendJson(response, { success: true, data: { taskId: 'task-transient-poll' } });
    }
    if (request.method === 'GET' && request.url === '/api/lumi/agent/tasks/task-transient-poll') {
      statusPolls += 1;
      if (statusPolls === 1) {
        return sendJson(response, {
          success: false,
          errorCode: 'phone_task_status_busy',
          message: 'temporary status service overload',
          retryable: true,
        }, 503);
      }
      return sendJson(response, {
        success: true,
        data: { taskId: 'task-transient-poll', status: 'success', result: { summary: 'done' } },
      });
    }
    return sendJson(response, { success: false, error: `unexpected ${request.method} ${request.url}` }, 404);
  });

  await listen(server);
  try {
    const port = server.address().port;
    const result = await runCli([
      'run',
      '--daemon',
      'off',
      '--phone-url',
      `http://127.0.0.1:${port}`,
      '--phone-token',
      'test-token',
      '--prompt',
      'continue after one transient poll failure',
      '--mode',
      'safe',
      '--max-wait-sec',
      '5',
      '--json',
    ]);

    assert.equal(result.code, 0, result.stderr || result.stdout);
    assert.equal(JSON.parse(result.stdout).ok, true);
    assert.equal(statusPolls, 2);
  } finally {
    await close(server);
  }
});

test('run honors a one-second CLI wait window and returns a cancellable timeout', async () => {
  const seen = [];
  const server = http.createServer(async (request, response) => {
    seen.push(`${request.method} ${request.url}`);
    await readBody(request);

    if (request.method === 'GET' && request.url === '/api/device/status') {
      return sendJson(response, { success: true, data: readyStatus({ llmConfigured: true }) });
    }
    if (request.method === 'POST' && request.url === '/api/lumi/security/pair') {
      return sendJson(response, {
        success: true,
        data: { launcherId: 'test-launcher', launcherSecret: 'test-secret' },
      });
    }
    if (request.method === 'POST' && request.url === '/api/lumi/agent/tasks') {
      return sendJson(response, { success: true, data: { taskId: 'task-timeout' } });
    }
    if (request.method === 'GET' && request.url === '/api/lumi/agent/tasks/task-timeout') {
      return sendJson(response, {
        success: true,
        data: { taskId: 'task-timeout', status: 'running', queueDepth: 0 },
      });
    }
    return sendJson(response, { success: false, error: `unexpected ${request.method} ${request.url}` }, 404);
  });

  await listen(server);
  try {
    const port = server.address().port;
    const startedAt = Date.now();
    const result = await runCli([
      'run',
      '--phone-url',
      `http://127.0.0.1:${port}`,
      '--phone-token',
      'test-token',
      '--prompt',
      'bounded timeout probe',
      '--mode',
      'safe',
      '--daemon',
      'off',
      '--max-wait-sec',
      '1',
      '--json',
    ]);
    const elapsedMs = Date.now() - startedAt;

    assert.notEqual(result.code, 0);
    const payload = JSON.parse(result.stdout);
    assert.equal(payload.ok, false);
    assert.equal(payload.errorCode, 'timeout');
    assert.equal(payload.retryable, true);
    assert.equal(payload.currentStep, 'wait_task');
    assert.equal(payload.details.taskId, 'task-timeout');
    assert.ok(elapsedMs < 5_000, `expected explicit one-second wait window, got ${elapsedMs}ms`);
    assert.equal(seen.includes('POST /api/lumi/agent/tasks'), true);
  } finally {
    await close(server);
  }
});

function readyStatus(overrides = {}) {
  return {
    busy: false,
    queueSupported: true,
    accessibilityState: 'healthy',
    accessibilityHealthy: true,
    accessibilityRunning: true,
    screenOn: true,
    interactive: true,
    deviceLocked: false,
    agentInitialized: true,
    llmConfigured: true,
    modelConfigured: true,
    modelReady: true,
    ...overrides,
  };
}

function runCli(args) {
  return new Promise((resolve) => {
    const child = spawn(process.execPath, ['scripts/openclaw-phone-agent.mjs', ...args], {
      cwd: new URL('..', import.meta.url),
      env: {
        ...process.env,
        NO_COLOR: '1',
      },
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    let stdout = '';
    let stderr = '';
    child.stdout.on('data', (chunk) => {
      stdout += chunk.toString();
    });
    child.stderr.on('data', (chunk) => {
      stderr += chunk.toString();
    });
    child.on('close', (code) => {
      resolve({ code, stdout, stderr });
    });
  });
}

function runVisionCli(args) {
  return new Promise((resolve) => {
    const child = spawn(process.execPath, ['scripts/openclaw-phone-vision.mjs', ...args], {
      cwd: new URL('..', import.meta.url),
      env: {
        ...process.env,
        NO_COLOR: '1',
      },
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    let stdout = '';
    let stderr = '';
    child.stdout.on('data', (chunk) => {
      stdout += chunk.toString();
    });
    child.stderr.on('data', (chunk) => {
      stderr += chunk.toString();
    });
    child.on('close', (code) => {
      resolve({ code, stdout, stderr });
    });
  });
}

async function unusedPort() {
  const server = http.createServer();
  await listen(server);
  const port = server.address().port;
  await close(server);
  return port;
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function readBody(request) {
  return new Promise((resolve, reject) => {
    let body = '';
    request.setEncoding('utf8');
    request.on('data', (chunk) => {
      body += chunk;
    });
    request.on('end', () => resolve(body));
    request.on('error', reject);
  });
}

function sendJson(response, payload, status = 200) {
  response.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8' });
  response.end(JSON.stringify(payload));
}

function listen(server) {
  return new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
}

function close(server) {
  return new Promise((resolve, reject) => {
    server.close((error) => (error ? reject(error) : resolve()));
  });
}
