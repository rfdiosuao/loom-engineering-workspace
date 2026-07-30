import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import { spawn } from 'node:child_process';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import { test } from 'node:test';
import { progressLogFromEvents, withProgressLogsInSseEvent } from './lib/phone-progress-log.mjs';
import {
  phoneBridgeErrorPayload,
  readLauncherPhoneStore,
  resolveLauncherPhoneConnection,
} from './openclaw-phone-secure.mjs';
import {
  phoneRuntimeTestEnv,
} from './tests/phone-runtime-auth-fixture.mjs';

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

test('bridge runtime with no authorized devices does not fall back to the launcher phone store', async () => {
  const tempDir = await fs.mkdtemp(path.join(os.tmpdir(), 'loom-phone-runtime-empty-'));
  const storePath = path.join(tempDir, 'data', '.openclaw', 'launcher', 'phone-agents.json');
  const previousRuntimeConfig = process.env.LOOM_PHONE_RUNTIME_CONFIG_JSON;
  const previousRuntimeTestOnly = process.env.LOOM_PHONE_RUNTIME_AUTH_TEST_ONLY;
  const previousRuntimeTestKey = process.env.LOOM_PHONE_RUNTIME_AUTH_TEST_PUBLIC_KEY_B64;
  const previousLauncherRoot = process.env.LOOM_LAUNCHER_ROOT;

  try {
    await fs.mkdir(path.dirname(storePath), { recursive: true });
    await fs.writeFile(storePath, JSON.stringify({
      selectedDeviceId: 'phone-b',
      devices: [{
        id: 'phone-b',
        baseUrl: 'http://127.0.0.1:19527',
        token: 'disk-phone-b-token',
      }],
    }), 'utf8');
    Object.assign(
      process.env,
      phoneRuntimeTestEnv({ selectedDeviceId: '', devices: [] }),
    );
    process.env.LOOM_LAUNCHER_ROOT = tempDir;

    const store = await readLauncherPhoneStore();

    assert.equal(store.source, 'bridge-runtime');
    assert.deepEqual(store.devices, []);
  } finally {
    restoreEnv('LOOM_PHONE_RUNTIME_CONFIG_JSON', previousRuntimeConfig);
    restoreEnv('LOOM_PHONE_RUNTIME_AUTH_TEST_ONLY', previousRuntimeTestOnly);
    restoreEnv('LOOM_PHONE_RUNTIME_AUTH_TEST_PUBLIC_KEY_B64', previousRuntimeTestKey);
    restoreEnv('LOOM_LAUNCHER_ROOT', previousLauncherRoot);
    await fs.rm(tempDir, { recursive: true, force: true });
  }
});

test('standalone CLI without bridge runtime cannot use launcher phone credentials', async () => {
  const tempDir = await fs.mkdtemp(path.join(os.tmpdir(), 'loom-phone-runtime-standalone-'));
  const storePath = path.join(tempDir, 'data', '.openclaw', 'launcher', 'phone-agents.json');
  const previousRuntimeConfig = process.env.LOOM_PHONE_RUNTIME_CONFIG_JSON;
  const previousLauncherRoot = process.env.LOOM_LAUNCHER_ROOT;

  try {
    await fs.mkdir(path.dirname(storePath), { recursive: true });
    await fs.writeFile(storePath, JSON.stringify({
      selectedDeviceId: 'phone-b',
      devices: [{
        id: 'phone-b',
        baseUrl: 'http://127.0.0.1:19527',
        token: 'disk-phone-b-token',
      }],
    }), 'utf8');
    delete process.env.LOOM_PHONE_RUNTIME_CONFIG_JSON;
    process.env.LOOM_LAUNCHER_ROOT = tempDir;

    const store = await readLauncherPhoneStore();
    const resolved = resolveLauncherPhoneConnection(
      {},
      {},
      {},
    );

    assert.equal(store.source, 'bridge-runtime-required');
    assert.equal(store.selectedDeviceId, '');
    assert.deepEqual(store.devices, []);
    assert.equal(resolved.phoneUrl, '');
    assert.equal(resolved.phoneToken, '');
    assert.equal(resolved.lumiLauncherId, '');
    assert.equal(resolved.lumiLauncherSecret, '');
    assert.equal(resolved.source, 'bridge-runtime-required');
  } finally {
    restoreEnv('LOOM_PHONE_RUNTIME_CONFIG_JSON', previousRuntimeConfig);
    restoreEnv('LOOM_LAUNCHER_ROOT', previousLauncherRoot);
    await fs.rm(tempDir, { recursive: true, force: true });
  }
});

test('fleet CLI without bridge runtime cannot fall back to legacy launcher credentials', async () => {
  const directRequests = [];
  const directServer = http.createServer(async (request, response) => {
    directRequests.push(`${request.method} ${request.url}`);
    await readBody(request);
    return sendJson(response, {
      success: true,
      data: readyStatus(),
    });
  });
  const tempDir = await fs.mkdtemp(path.join(os.tmpdir(), 'loom-phone-runtime-fleet-'));
  const configPath = path.join(tempDir, 'data', '.openclaw', 'launcher', 'phone-agent.json');

  await listen(directServer);
  try {
    const directPort = directServer.address().port;
    await fs.mkdir(path.dirname(configPath), { recursive: true });
    await fs.writeFile(configPath, JSON.stringify({
      id: 'legacy-phone',
      name: 'Legacy Phone',
      baseUrl: `http://127.0.0.1:${directPort}`,
      token: 'legacy-disk-token',
    }), 'utf8');

    const result = await runPhoneScript('openclaw-phone-fleet.mjs', [
      'status',
      '--json',
    ], {
      LOOM_LAUNCHER_ROOT: tempDir,
      LOOM_PHONE_RUNTIME_CONFIG_JSON: undefined,
      OPENCLAW_PHONE_BASE_URL: `http://127.0.0.1:${directPort}`,
      OPENCLAW_PHONE_TOKEN: 'hostile-env-token',
    });

    assert.notEqual(result.code, 0, result.stdout);
    assert.match(
      `${result.stdout}\n${result.stderr}`,
      /No APKClaw devices are configured|bridge runtime/i,
    );
    assert.deepEqual(directRequests, []);
  } finally {
    await close(directServer);
    await fs.rm(tempDir, { recursive: true, force: true });
  }
});

test('runtime context cannot probe a phone from direct URL and token arguments', async () => {
  const directRequests = [];
  const directServer = http.createServer(async (request, response) => {
    directRequests.push(`${request.method} ${request.url}`);
    await readBody(request);
    return sendJson(response, {
      success: true,
      data: readyStatus(),
    });
  });
  const tempDir = await fs.mkdtemp(path.join(os.tmpdir(), 'loom-phone-runtime-context-'));

  await listen(directServer);
  try {
    const directPort = directServer.address().port;
    const result = await runPhoneScript('openclaw-context.mjs', [
      '--root',
      tempDir,
      '--probe',
      '--phone-url',
      `http://127.0.0.1:${directPort}`,
      '--phone-token',
      'direct-context-token',
      '--json',
    ], {
      LOOM_PHONE_RUNTIME_CONFIG_JSON: undefined,
      OPENCLAW_PHONE_BASE_URL: `http://127.0.0.1:${directPort}`,
      OPENCLAW_PHONE_TOKEN: 'hostile-env-token',
    });

    assert.equal(result.code, 0, result.stderr || result.stdout);
    const payload = JSON.parse(result.stdout);
    assert.equal(payload.phone.configured, false);
    assert.equal(payload.phone.connected, false);
    assert.equal(payload.phone.tokenAvailable, false);
    assert.equal(
      payload.capabilities.platformPublish.controlPolicy,
      'managed-api-only',
    );
    assert.deepEqual(
      payload.capabilities.platformPublish.launcherCommand,
      {
        endpoint: '/api/cli/run',
        command: 'phone:publish',
      },
    );
    assert.equal(
      payload.capabilities.phoneAgent.controlPolicy,
      'managed-api-only',
    );
    assert.doesNotMatch(
      JSON.stringify(payload.capabilities),
      /npm run phone:/,
    );
    assert.deepEqual(directRequests, []);
  } finally {
    await close(directServer);
    await fs.rm(tempDir, { recursive: true, force: true });
  }
});

test('phone CLI help and remediation only advertise LOOM managed pairing', async () => {
  const helpScripts = [
    'openclaw-phone-agent.mjs',
    'openclaw-phone-video.mjs',
    'openclaw-phone-game.mjs',
    'openclaw-phone-vision.mjs',
    'openclaw-image-phone.mjs',
    'openclaw-publish-phone.mjs',
    'openclaw-phone-demo.mjs',
    'openclaw-context.mjs',
  ];
  const helpResults = await Promise.all(
    helpScripts.map((script) => runPhoneScript(script, ['--help'])),
  );

  for (let index = 0; index < helpResults.length; index += 1) {
    const result = helpResults[index];
    const output = `${result.stdout}\n${result.stderr}`;
    assert.equal(result.code, 0, `${helpScripts[index]}: ${output}`);
    assert.doesNotMatch(output, /--phone-token|--phone-url|OPENCLAW_PHONE_TOKEN/);
  }

  const missingConfig = phoneBridgeErrorPayload(
    new Error('Missing phone token'),
  );
  const invalidAuth = phoneBridgeErrorPayload(
    new Error('HTTP 401 Unauthorized'),
  );
  const remediation = JSON.stringify([
    missingConfig.message,
    missingConfig.remediation,
    invalidAuth.message,
    invalidAuth.remediation,
  ]);

  assert.doesNotMatch(remediation, /连接令牌|--phone-token|OPENCLAW_PHONE_TOKEN/);
  assert.match(remediation, /配对码/);
  assert.match(remediation, /LOOM|麓鸣/);
});

test('bridge runtime credentials cannot be overridden by device B direct credentials', async () => {
  const runtimeRequests = [];
  const directRequests = [];
  const runtimeServer = http.createServer(async (request, response) => {
    runtimeRequests.push({
      path: request.url,
      phoneToken: request.headers['x-agent-phone-token'],
      launcherId: request.headers['x-lumi-launcher-id'],
    });
    await readBody(request);
    return sendJson(response, {
      success: true,
      data: { vision: { mode: 'runtime-a', reason: 'authorized' } },
    });
  });
  const directServer = http.createServer(async (request, response) => {
    directRequests.push(request.url);
    await readBody(request);
    return sendJson(response, {
      success: true,
      data: { vision: { mode: 'direct-b', reason: 'must-not-run' } },
    });
  });

  await Promise.all([listen(runtimeServer), listen(directServer)]);
  try {
    const runtimePort = runtimeServer.address().port;
    const directPort = directServer.address().port;
    const result = await runPhoneScript('openclaw-phone-vision.mjs', [
      'status',
      '--device-id',
      'phone-a',
      '--phone-url',
      `http://127.0.0.1:${directPort}`,
      '--phone-token',
      'direct-phone-b-token',
      '--json',
    ], {
      ...phoneRuntimeTestEnv({
        selectedDeviceId: 'phone-a',
        devices: [{
          id: 'phone-a',
          baseUrl: `http://127.0.0.1:${runtimePort}`,
          token: 'runtime-phone-a-token',
          launcherId: 'runtime-launcher-a',
          launcherSecret: 'runtime-launcher-a-secret',
        }],
      }),
      OPENCLAW_PHONE_BASE_URL: `http://127.0.0.1:${directPort}`,
      OPENCLAW_PHONE_TOKEN: 'env-openclaw-phone-b-token',
      APKCLAW_BASE_URL: `http://127.0.0.1:${directPort}`,
      APKCLAW_TOKEN: 'env-apkclaw-phone-b-token',
      LUMI_LAUNCHER_ID: 'env-launcher-b',
      LUMI_LAUNCHER_SECRET: 'env-launcher-b-secret',
    });

    assert.equal(result.code, 0, result.stderr || result.stdout);
    assert.equal(directRequests.length, 0);
    assert.equal(runtimeRequests.length, 1);
    assert.equal(runtimeRequests[0].phoneToken, 'runtime-phone-a-token');
    assert.equal(runtimeRequests[0].launcherId, 'runtime-launcher-a');
    assert.equal(JSON.parse(result.stdout).configSource, 'bridge-runtime');
  } finally {
    await Promise.all([close(runtimeServer), close(directServer)]);
  }
});

test('bridge runtime album is not overridden by image environment or publish defaults', async () => {
  const uploadedAlbums = [];
  let taskSequence = 0;
  const runtimeServer = http.createServer(async (request, response) => {
    const bodyText = await readBody(request);
    const body = bodyText ? JSON.parse(bodyText) : {};
    if (request.method === 'POST' && request.url === '/api/lumi/media/import_image') {
      uploadedAlbums.push(body.album);
      return sendJson(response, {
        success: true,
        data: { relativePath: `Pictures/${body.album}/runtime.png`, album: body.album },
      });
    }
    if (request.method === 'POST' && request.url === '/api/lumi/agent/tasks') {
      taskSequence += 1;
      return sendJson(response, { success: true, data: { taskId: `runtime-task-${taskSequence}` } });
    }
    if (request.method === 'GET' && request.url?.startsWith('/api/lumi/agent/tasks/runtime-task-')) {
      return sendJson(response, {
        success: true,
        data: { status: 'success', result: { answer: 'runtime publish complete' } },
      });
    }
    return sendJson(response, { success: false, error: `unexpected ${request.method} ${request.url}` }, 404);
  });
  const tempDir = await fs.mkdtemp(path.join(os.tmpdir(), 'loom-phone-runtime-album-'));

  await listen(runtimeServer);
  try {
    const imagePath = path.join(tempDir, 'runtime.png');
    await fs.writeFile(imagePath, Buffer.from('runtime album image'));
    const runtimePort = runtimeServer.address().port;
    const runtimeEnv = {
      ...phoneRuntimeTestEnv({
        selectedDeviceId: 'phone-a',
        devices: [{
          id: 'phone-a',
          baseUrl: `http://127.0.0.1:${runtimePort}`,
          token: 'runtime-phone-a-token',
          launcherId: 'runtime-launcher-a',
          launcherSecret: 'runtime-launcher-a-secret',
          album: 'Runtime Album',
        }],
      }),
      OPENCLAW_PHONE_ALBUM: 'Legacy Environment Album',
    };

    const imageResult = await runPhoneScript('openclaw-image-phone.mjs', [
      '--image',
      imagePath,
      '--json',
    ], runtimeEnv);
    const publishResult = await runPhoneScript('openclaw-publish-phone.mjs', [
      '--platform',
      'custom',
      '--title',
      'runtime album guard',
      '--image',
      imagePath,
      '--max-wait-sec',
      '2',
      '--poll-ms',
      '100',
      '--json',
    ], runtimeEnv);

    assert.equal(imageResult.code, 0, imageResult.stderr || imageResult.stdout);
    assert.equal(publishResult.code, 0, publishResult.stderr || publishResult.stdout);
    assert.deepEqual(uploadedAlbums, ['Runtime Album', 'Runtime Album']);
  } finally {
    await close(runtimeServer);
    await fs.rm(tempDir, { recursive: true, force: true });
  }
});

test('bridge runtime empty allowlist blocks legacy credentials in every phone CLI parser', async () => {
  const directRequests = [];
  const directServer = http.createServer(async (request, response) => {
    directRequests.push(`${request.method} ${request.url}`);
    await readBody(request);
    return sendJson(response, { success: true, data: {} });
  });
  const tempDir = await fs.mkdtemp(path.join(os.tmpdir(), 'loom-phone-runtime-parsers-'));

  await listen(directServer);
  try {
    const directPort = directServer.address().port;
    const directUrl = `http://127.0.0.1:${directPort}`;
    const imagePath = path.join(tempDir, 'phone-runtime.png');
    await fs.writeFile(imagePath, Buffer.from('runtime parser test image'));
    const hostileEnv = {
      ...phoneRuntimeTestEnv({ selectedDeviceId: '', devices: [] }),
      OPENCLAW_PHONE_BASE_URL: directUrl,
      OPENCLAW_PHONE_TOKEN: 'env-openclaw-phone-b-token',
      APKCLAW_BASE_URL: directUrl,
      APKCLAW_TOKEN: 'env-apkclaw-phone-b-token',
      LUMI_LAUNCHER_ID: 'env-launcher-b',
      LUMI_LAUNCHER_SECRET: 'env-launcher-b-secret',
      OPENCLAW_PHONE_DAEMON: 'off',
    };
    const directArgs = ['--phone-url', directUrl, '--phone-token', 'direct-phone-b-token'];
    const cases = [
      ['openclaw-phone-agent.mjs', ['metrics', '--daemon', 'off', ...directArgs, '--json']],
      ['openclaw-phone-video.mjs', ['status', ...directArgs, '--json']],
      ['openclaw-phone-game.mjs', ['capture', ...directArgs, '--json']],
      ['openclaw-phone-vision.mjs', ['status', ...directArgs, '--json']],
      ['openclaw-image-phone.mjs', ['--image', imagePath, ...directArgs, '--json']],
      ['openclaw-publish-phone.mjs', ['--platform', 'custom', '--title', 'runtime guard', ...directArgs, '--json']],
    ];

    const results = await Promise.all(cases.map(([script, args]) => runPhoneScript(script, args, hostileEnv)));

    for (let index = 0; index < results.length; index += 1) {
      const result = results[index];
      assert.notEqual(result.code, 0, `${cases[index][0]} unexpectedly succeeded: ${result.stdout}`);
      assert.match(
        `${result.stdout}\n${result.stderr}`,
        /手机连接(?:地址|信息)缺失|Missing phone URL/,
        `${cases[index][0]} did not fail closed: ${result.stdout}\n${result.stderr}`,
      );
    }
    assert.deepEqual(directRequests, []);
  } finally {
    await close(directServer);
    await fs.rm(tempDir, { recursive: true, force: true });
  }
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
  assert.match(payload.remediation.join('\n'), /LOOM 手机连接页|安全配对/);
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
    assert.match(payload.message, /安全配对凭据|连接令牌/);
    assert.match(payload.remediation.join('\n'), /重新完成安全配对|重新复制/);
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

test('vision system key action uses the compatible phone endpoint', async () => {
  let actionBody = null;
  let actionPath = '';
  const server = http.createServer(async (request, response) => {
    const body = await readBody(request);
    if (request.method === 'POST' && request.url === '/api/lumi/security/pair') {
      const parsed = JSON.parse(body || '{}');
      return sendJson(response, {
        success: true,
        data: { launcherId: parsed.launcherId, launcherSecret: 'vision-secret' },
      });
    }
    if (request.method === 'POST' && request.url === '/api/tool/system_key') {
      actionPath = request.url;
      actionBody = JSON.parse(body || '{}');
      return sendJson(response, {
        success: true,
        data: {
          action: actionBody.action,
          key: actionBody.key,
          currentStep: 'complete',
        },
      });
    }
    return sendJson(response, { success: false, error: `unexpected ${request.method} ${request.url}` }, 404);
  });

  const tmpDir = await fs.mkdtemp(path.join(os.tmpdir(), 'loom-vision-system-key-'));
  await listen(server);
  try {
    const bodyPath = path.join(tmpDir, 'action.json');
    await fs.writeFile(bodyPath, JSON.stringify({
      action: 'system_key',
      key: 'recent',
      targetLabel: 'system recent apps navigation',
      reason: 'User requested the recent-apps control from Matrix',
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
    assert.equal(actionPath, '/api/tool/system_key');
    assert.equal(actionBody.action, 'system_key');
    assert.equal(actionBody.key, 'recent');
    assert.equal(actionBody.visualize, true);
    assert.match(actionBody.traceId, /^vision_/);
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
    // The full Node contract suite runs several child-process-heavy files in
    // parallel on Windows, so wait for readiness without weakening the
    // post-cancel four-second interruption assertion below.
    const pollDeadline = Date.now() + 30_000;
    while (!seen.includes('GET /api/lumi/agent/tasks/task-cancel') && Date.now() < pollDeadline) {
      await new Promise((resolve) => setTimeout(resolve, 20));
    }
    assert.equal(seen.includes('GET /api/lumi/agent/tasks/task-cancel'), true);
    const cancelStartedAt = Date.now();
    await fs.writeFile(cancelFile, 'cancelled\n', 'utf8');
    const result = await cliPromise;

    assert.equal(result.code, 0, result.stderr);
    const payload = JSON.parse(result.stdout);
    assert.equal(payload.ok, false);
    assert.equal(payload.error, 'cancelled');
    assert.equal(seen.includes('POST /api/lumi/agent/tasks/task-cancel/cancel'), true);
    assert.ok(Date.now() - cancelStartedAt < 4_000, 'cancellation must interrupt an in-flight task poll');
  } finally {
    releaseBlockedPoll();
    await close(server);
    await fs.rm(tempDir, { recursive: true, force: true });
  }
});

test('run retries two transient 503 cancellation failures and confirms the remote terminal state', async () => {
  const tempDir = await fs.mkdtemp(path.join(os.tmpdir(), 'loom-phone-cancel-retry-'));
  const cancelFile = path.join(tempDir, 'job.cancel');
  let cancelAttempts = 0;
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
      await fs.writeFile(cancelFile, 'cancelled\n', 'utf8');
      return sendJson(response, { success: true, data: { taskId: 'task-cancel-retry' } });
    }
    if (
      request.method === 'POST'
      && request.url === '/api/lumi/agent/tasks/task-cancel-retry/cancel'
    ) {
      cancelAttempts += 1;
      if (cancelAttempts <= 2) {
        return sendJson(response, {
          success: false,
          errorCode: 'phone_cancel_temporarily_unavailable',
          message: 'temporary cancellation service outage',
          retryable: true,
        }, 503);
      }
      return sendJson(response, {
        success: true,
        data: { taskId: 'task-cancel-retry', status: 'cancelling' },
      });
    }
    if (request.method === 'GET' && request.url === '/api/lumi/agent/tasks/task-cancel-retry') {
      statusPolls += 1;
      return sendJson(response, {
        success: true,
        data: { taskId: 'task-cancel-retry', status: 'cancelled' },
      });
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
      '--prompt',
      'retry remote cancellation',
      '--mode',
      'safe',
      '--daemon',
      'off',
      '--cancel-file',
      cancelFile,
      '--max-wait-sec',
      '5',
      '--poll-ms',
      '100',
      '--json',
    ]);

    assert.equal(result.code, 0, result.stderr || result.stdout);
    const payload = JSON.parse(result.stdout);
    assert.equal(cancelAttempts, 3);
    assert.ok(statusPolls >= 1, 'accepted cancellation should be polled to a terminal state');
    assert.equal(payload.ok, false);
    assert.equal(payload.status, 'cancelled');
    assert.equal(payload.cancelled, true);
    assert.equal(payload.executionMayContinue, false);
  } finally {
    await close(server);
    await fs.rm(tempDir, { recursive: true, force: true });
  }
});

test('run reports an unconfirmed permanent remote cancellation failure as still executing', async () => {
  const tempDir = await fs.mkdtemp(path.join(os.tmpdir(), 'loom-phone-cancel-failed-'));
  const cancelFile = path.join(tempDir, 'job.cancel');
  let cancelAttempts = 0;
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
      await fs.writeFile(cancelFile, 'cancelled\n', 'utf8');
      return sendJson(response, { success: true, data: { taskId: 'task-cancel-failed' } });
    }
    if (
      request.method === 'POST'
      && request.url === '/api/lumi/agent/tasks/task-cancel-failed/cancel'
    ) {
      cancelAttempts += 1;
      return sendJson(response, {
        success: false,
        errorCode: 'phone_cancel_unavailable',
        message: 'cancellation service unavailable',
        retryable: true,
      }, 503);
    }
    if (request.method === 'GET' && request.url === '/api/lumi/agent/tasks/task-cancel-failed') {
      statusPolls += 1;
      return sendJson(response, {
        success: true,
        data: { taskId: 'task-cancel-failed', status: 'running' },
      });
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
      '--prompt',
      'permanent remote cancellation failure',
      '--mode',
      'safe',
      '--daemon',
      'off',
      '--cancel-file',
      cancelFile,
      '--max-wait-sec',
      '5',
      '--poll-ms',
      '100',
      '--json',
    ]);

    assert.equal(result.code, 0, result.stderr || result.stdout);
    const payload = JSON.parse(result.stdout);
    assert.equal(cancelAttempts, 3);
    assert.ok(statusPolls >= 1, 'failed cancellation should still poll for a remote terminal state');
    assert.equal(payload.ok, false);
    assert.equal(payload.status, 'cancelling');
    assert.equal(payload.cancelled, false);
    assert.equal(payload.errorCode, 'phone_task_cancel_unconfirmed');
    assert.equal(payload.executionMayContinue, true);
  } finally {
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

function bridgeRuntimeFromCliArgs(args) {
  const urlIndex = args.indexOf('--phone-url');
  const tokenIndex = args.indexOf('--phone-token');
  const deviceIndex = args.indexOf('--device-id');
  if (urlIndex < 0 || tokenIndex < 0) return undefined;
  const baseUrl = String(args[urlIndex + 1] || '').trim();
  const token = String(args[tokenIndex + 1] || '').trim();
  const deviceId = deviceIndex >= 0
    ? String(args[deviceIndex + 1] || '').trim()
    : 'phone-test';
  if (!baseUrl || !token) return undefined;
  return phoneRuntimeTestEnv({
    selectedDeviceId: deviceId,
    devices: [{
      id: deviceId,
      baseUrl,
      token,
    }],
  });
}

function runCli(args) {
  const bridgeRuntime = bridgeRuntimeFromCliArgs(args);
  return new Promise((resolve) => {
    const child = spawn(process.execPath, ['scripts/openclaw-phone-agent.mjs', ...args], {
      cwd: new URL('..', import.meta.url),
      env: {
        ...process.env,
        NO_COLOR: '1',
        ...(bridgeRuntime || {}),
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
  const bridgeRuntime = bridgeRuntimeFromCliArgs(args);
  return new Promise((resolve) => {
    const child = spawn(process.execPath, ['scripts/openclaw-phone-vision.mjs', ...args], {
      cwd: new URL('..', import.meta.url),
      env: {
        ...process.env,
        NO_COLOR: '1',
        ...(bridgeRuntime || {}),
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

function runPhoneScript(script, args, envOverrides = {}) {
  return new Promise((resolve) => {
    const env = {
      ...process.env,
      NO_COLOR: '1',
      ...envOverrides,
    };
    for (const [name, value] of Object.entries(env)) {
      if (value === undefined) delete env[name];
    }
    const child = spawn(process.execPath, [`scripts/${script}`, ...args], {
      cwd: new URL('..', import.meta.url),
      env,
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

function restoreEnv(name, value) {
  if (value === undefined) delete process.env[name];
  else process.env[name] = value;
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
