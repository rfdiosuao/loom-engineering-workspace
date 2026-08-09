import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import fs from 'node:fs/promises';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import {
  phoneRuntimeTestEnv,
  TEST_ENTITLEMENT_PUBLIC_KEY_B64,
} from './phone-runtime-auth-fixture.mjs';

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
  const phoneRuntime = {
    phoneUrl: `http://127.0.0.1:${address.port}`,
    phoneToken: 'test-token',
  };
  const stdout = await runNode([
    publishScript,
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
  ], phoneRuntime);

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
  const phoneRuntime = {
    phoneUrl: `http://127.0.0.1:${address.port}`,
    phoneToken: 'test-token',
  };
  await assert.rejects(
    runNode([
      publishScript,
      '--platform',
      'douyin',
      '--title',
      'failure contract',
      '--max-wait-sec',
      '30',
      '--poll-ms',
      '500',
      '--json',
    ], phoneRuntime),
    /process exited 1[\s\S]*platform rejected draft/,
  );
});

test('reverse publish cannot use CLI shared relay credentials without signed runtime authorization', async (t) => {
  let relayRequests = 0;
  const relayServer = http.createServer(async (request, response) => {
    relayRequests += 1;
    await readJsonBody(request);
    return writeJson(response, {
      success: true,
      data: { packetId: 'must-not-be-created' },
    });
  });
  await listen(relayServer);
  t.after(() => relayServer.close());

  const address = relayServer.address();
  const phoneRuntime = {
    phoneUrl: 'http://127.0.0.1:19527',
    phoneToken: 'unsigned-runtime-phone-token',
  };
  await assert.rejects(
    runNode([
      publishScript,
      '--transport',
      'reverse',
      '--platform',
      'douyin',
      '--title',
      'unsigned reverse publish',
      '--relay-url',
      `http://127.0.0.1:${address.port}/api/lumi/publish/packet`,
      '--relay-token',
      'shared-relay-token',
      '--channel-id',
      'attacker-selected-channel',
      '--json',
    ], { ...phoneRuntime, unsignedRuntime: true }),
    /reverse_runtime_override_forbidden|runtime_entitlement|signed runtime|权益租约/i,
  );
  assert.equal(relayRequests, 0);
});

test('reverse publish uses only signed runtime relay context and sends its account authorization', async (t) => {
  const relayRequests = [];
  const relayServer = http.createServer(async (request, response) => {
    relayRequests.push({
      authorization: request.headers.authorization,
      relayToken: request.headers['x-openclaw-relay-token'],
      body: await readJsonBody(request),
    });
    return writeJson(response, {
      success: true,
      data: { packetId: 'runtime-authorized-packet' },
    });
  });
  await listen(relayServer);
  t.after(() => relayServer.close());

  const address = relayServer.address();
  const runtimeConfig = {
    selectedDeviceId: 'phone-runtime',
    devices: [{
      id: 'phone-runtime',
      deviceInstanceId: 'device-instance-runtime',
      baseUrl: 'http://127.0.0.1:19527',
      token: 'runtime-phone-token',
    }],
    reversePublish: {
      relayUrl: `http://127.0.0.1:${address.port}/api/lumi/publish/packet`,
      channelId: 'runtime-channel',
    },
  };
  const stdout = await runNode([
    publishScript,
    '--transport',
    'reverse',
    '--platform',
    'douyin',
    '--title',
    'authorized reverse publish',
    '--json',
  ], {
    runtimeConfig,
    env: {
      OPENCLAW_PUBLISH_RELAY_TOKEN: 'ambient-attacker-token',
    },
  });

  assert.equal(relayRequests.length, 1);
  assert.equal(
    relayRequests[0].authorization,
    'Bearer model-session-account-node-test',
  );
  assert.equal(relayRequests[0].relayToken, undefined);
  assert.equal(relayRequests[0].body.channelId, 'runtime-channel');
  assert.equal(relayRequests[0].body.authorization.schema, 'loom.phone.publish.authorization.v1');
  assert.equal(relayRequests[0].body.authorization.accountId, 'account-node-test');
  assert.equal(
    relayRequests[0].body.authorization.selectedDeviceInstanceId,
    'device-instance-runtime',
  );
  assert.equal(
    relayRequests[0].body.authorization.entitlementLease.limits.unlimitedDevices,
    true,
  );
  assert.match(
    relayRequests[0].body.authorization.entitlementLease.signature,
    /^[A-Za-z0-9+/]+={0,2}$/,
  );
  assert.match(
    relayRequests[0].body.authorization.phoneSeatLease.signature,
    /^[A-Za-z0-9+/]+={0,2}$/,
  );
  assert.equal(JSON.parse(stdout).relayedTo, runtimeConfig.reversePublish.relayUrl);
});

test('reverse publish rejects a selected phone without a stable installation identity', async (t) => {
  let relayRequests = 0;
  const relayServer = http.createServer(async (request, response) => {
    relayRequests += 1;
    await readJsonBody(request);
    return writeJson(response, { success: true, data: { packetId: 'unexpected' } });
  });
  await listen(relayServer);
  t.after(() => relayServer.close());

  const address = relayServer.address();
  await assert.rejects(
    runNode([
      publishScript,
      '--transport',
      'reverse',
      '--platform',
      'douyin',
      '--title',
      'missing device identity',
      '--json',
    ], {
      runtimeConfig: {
        selectedDeviceId: 'phone-runtime',
        devices: [{
          id: 'phone-runtime',
          baseUrl: 'http://127.0.0.1:19527',
          token: 'runtime-phone-token',
        }],
        reversePublish: {
          relayUrl: `http://127.0.0.1:${address.port}/api/lumi/publish/packet`,
          channelId: 'runtime-channel',
        },
      },
    }),
    /selected.*device.*instance|deviceInstanceId|installation identity/i,
  );
  assert.equal(relayRequests, 0);
});

test('reverse publish rejects CLI relay overrides even with a valid signed runtime', async (t) => {
  let trustedRelayRequests = 0;
  let attackerRelayRequests = 0;
  const trustedRelay = http.createServer(async (request, response) => {
    trustedRelayRequests += 1;
    await readJsonBody(request);
    return writeJson(response, { success: true, data: { packetId: 'trusted' } });
  });
  const attackerRelay = http.createServer(async (request, response) => {
    attackerRelayRequests += 1;
    await readJsonBody(request);
    return writeJson(response, { success: true, data: { packetId: 'attacker' } });
  });
  await Promise.all([listen(trustedRelay), listen(attackerRelay)]);
  t.after(() => {
    trustedRelay.close();
    attackerRelay.close();
  });

  const trustedAddress = trustedRelay.address();
  const attackerAddress = attackerRelay.address();
  const runtimeConfig = {
    selectedDeviceId: 'phone-runtime',
    devices: [{
      id: 'phone-runtime',
      deviceInstanceId: 'device-instance-runtime',
      baseUrl: 'http://127.0.0.1:19527',
      token: 'runtime-phone-token',
    }],
    reversePublish: {
      relayUrl: `http://127.0.0.1:${trustedAddress.port}/api/lumi/publish/packet`,
      channelId: 'runtime-channel',
    },
  };

  await assert.rejects(
    runNode([
      publishScript,
      '--transport',
      'reverse',
      '--platform',
      'douyin',
      '--title',
      'override reverse publish',
      '--relay-url',
      `http://127.0.0.1:${attackerAddress.port}/api/lumi/publish/packet`,
      '--relay-token',
      'attacker-token',
      '--channel-id',
      'attacker-channel',
      '--json',
    ], { runtimeConfig }),
    /reverse_runtime_override_forbidden/i,
  );
  assert.equal(trustedRelayRequests, 0);
  assert.equal(attackerRelayRequests, 0);
});

test('reverse formal publish delegates final-click revalidation to the trusted relay', async (t) => {
  const relayPackets = [];
  const relayServer = http.createServer(async (request, response) => {
    relayPackets.push(await readJsonBody(request));
    return writeJson(response, {
      success: true,
      data: { packetId: 'formal-commit-gated' },
    });
  });
  await listen(relayServer);
  t.after(() => relayServer.close());

  const address = relayServer.address();
  const stdout = await runNode([
      publishScript,
      '--transport',
      'reverse',
      '--platform',
      'douyin',
      '--title',
      'revocable formal reverse publish',
      '--commit',
      '--json',
    ], {
      runtimeConfig: {
        selectedDeviceId: 'phone-runtime',
        devices: [{
          id: 'phone-runtime',
          deviceInstanceId: 'device-instance-runtime',
          baseUrl: 'http://127.0.0.1:19527',
          token: 'runtime-phone-token',
        }],
        reversePublish: {
          relayUrl: `http://127.0.0.1:${address.port}/api/lumi/publish/packet`,
          channelId: 'runtime-channel',
        },
      },
    });
  assert.equal(relayPackets.length, 1);
  assert.equal(relayPackets[0].draftOnly, false);
  assert.deepEqual(relayPackets[0].executionPolicy, {
    requireSignedEntitlementAtDequeue: true,
    requireSignedEntitlementBeforeCommit: true,
    denyCommitOnRevocation: true,
  });
  assert.equal(JSON.parse(stdout).relay.data.packetId, 'formal-commit-gated');
});

test('reverse publish rejects a forged signed-runtime envelope before contacting its relay', async (t) => {
  let relayRequests = 0;
  const relayServer = http.createServer(async (request, response) => {
    relayRequests += 1;
    await readJsonBody(request);
    return writeJson(response, {
      success: true,
      data: { packetId: 'must-not-be-created' },
    });
  });
  await listen(relayServer);
  t.after(() => relayServer.close());

  const address = relayServer.address();
  const nowSec = Math.floor(Date.now() / 1000);
  const forgedRuntime = {
    selectedDeviceId: 'phone-forged',
    devices: [{
      id: 'phone-forged',
      deviceInstanceId: 'device-instance-forged',
      baseUrl: 'http://127.0.0.1:19527',
      token: 'forged-phone-token',
    }],
    entitlementLease: {
      schema: 'loom.entitlement_lease.v1',
      accountId: 'forged-account',
      installId: 'forged-install',
      features: ['matrix.devices'],
      limits: { unlimitedDevices: true },
      issuedAt: nowSec - 60,
      expiresAt: nowSec + 3600,
      offlineGraceUntil: nowSec + 7200,
      entitlementVersion: 1,
      keyId: 'openclaw-ed25519-v1',
      signature: 'forged-signature',
    },
    phoneSeatLease: {
      schema: 'loom.phone_seat_lease.v1',
      accountId: 'forged-account',
      installId: 'forged-install',
      hostDeviceId: 'forged-host',
      phoneDeviceIds: ['phone-forged'],
      limit: 1000,
      issuedAt: nowSec - 60,
      expiresAt: nowSec + 3600,
      entitlementVersion: 1,
      keyId: 'openclaw-ed25519-v1',
      signature: 'forged-signature',
    },
    reversePublish: {
      relayUrl: `http://127.0.0.1:${address.port}/api/lumi/publish/packet`,
      channelId: 'runtime-channel',
    },
  };
  await assert.rejects(
    runNode([
      publishScript,
      '--transport',
      'reverse',
      '--platform',
      'douyin',
      '--title',
      'forged reverse publish',
      '--json',
    ], { runtimeConfig: forgedRuntime, unsignedRuntime: true }),
    /runtime_entitlement|signature|signed runtime|verifier|权益|签名/i,
  );
  assert.equal(relayRequests, 0);
});

test('direct formal publish fails closed before submitting a generic Agent task', async (t) => {
  let taskSubmissions = 0;
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
      taskSubmissions += 1;
      return writeJson(response, {
        success: true,
        data: { taskId: 'unsafe-direct-formal-task' },
      });
    }
    return writeJson(response, {
      success: false,
      error: `unexpected ${request.method} ${url.pathname}`,
    }, 404);
  });
  await listen(server);
  t.after(() => server.close());

  const address = server.address();
  await assert.rejects(
    runNode([
      publishScript,
      '--transport',
      'direct',
      '--platform',
      'douyin',
      '--title',
      'must use trusted relay',
      '--commit',
      '--json',
    ], {
      phoneUrl: `http://127.0.0.1:${address.port}`,
      phoneToken: 'test-token',
    }),
    /formal_publish_trusted_relay_required|trusted signed relay|正式发布.*反向中继/i,
  );
  assert.equal(taskSubmissions, 0);
});

test('phone publish cooperatively cancels the real APKClaw task', async (t) => {
  const tempDir = await fs.mkdtemp(path.join(os.tmpdir(), 'loom-publish-cancel-'));
  const cancelFile = path.join(tempDir, 'publish.cancel');
  let cancelled = false;
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
      await fs.writeFile(cancelFile, 'cancelled\n', 'utf8');
      return writeJson(response, {
        success: true,
        data: { taskId: 'task-publish-cancelled' },
      });
    }
    if (
      request.method === 'POST'
      && url.pathname === '/api/lumi/agent/tasks/task-publish-cancelled/cancel'
    ) {
      cancelled = true;
      return writeJson(response, {
        success: true,
        data: {
          taskId: 'task-publish-cancelled',
          status: 'cancelled',
        },
      });
    }
    response.writeHead(404, { 'Content-Type': 'application/json' });
    response.end(JSON.stringify({ success: false }));
  });
  await listen(server);
  t.after(async () => {
    server.close();
    await fs.rm(tempDir, { recursive: true, force: true });
  });

  const address = server.address();
  const phoneRuntime = {
    phoneUrl: `http://127.0.0.1:${address.port}`,
    phoneToken: 'test-token',
  };
  await assert.rejects(
    runNode([
      publishScript,
      '--platform',
      'douyin',
      '--title',
      'cancel contract',
      '--cancel-file',
      cancelFile,
      '--max-wait-sec',
      '30',
      '--poll-ms',
      '500',
      '--json',
    ], phoneRuntime),
    /process exited 1[\s\S]*cancelled/,
  );
  assert.equal(cancelled, true);
});

test('direct draft publish retries transient cancellation failures and confirms the remote stop', async (t) => {
  const tempDir = await fs.mkdtemp(path.join(os.tmpdir(), 'loom-publish-cancel-retry-'));
  const cancelFile = path.join(tempDir, 'publish.cancel');
  let cancelAttempts = 0;
  let statusPolls = 0;
  let submittedPrompt = '';
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
      submittedPrompt = String(body?.prompt || '');
      await fs.writeFile(cancelFile, 'revoked\n', 'utf8');
      return writeJson(response, {
        success: true,
        data: { taskId: 'task-publish-cancel-retry' },
      });
    }
    if (
      request.method === 'POST'
      && url.pathname === '/api/lumi/agent/tasks/task-publish-cancel-retry/cancel'
    ) {
      cancelAttempts += 1;
      if (cancelAttempts <= 2) {
        return writeJson(response, {
          success: false,
          errorCode: 'phone_cancel_temporarily_unavailable',
          message: 'temporary cancellation service outage',
          retryable: true,
        }, 503);
      }
      return writeJson(response, {
        success: true,
        data: {
          taskId: 'task-publish-cancel-retry',
          status: 'cancelling',
        },
      });
    }
    if (
      request.method === 'GET'
      && url.pathname === '/api/lumi/agent/tasks/task-publish-cancel-retry'
    ) {
      statusPolls += 1;
      return writeJson(response, {
        success: true,
        data: {
          taskId: 'task-publish-cancel-retry',
          status: 'cancelled',
        },
      });
    }
    return writeJson(response, {
      success: false,
      error: `unexpected ${request.method} ${url.pathname}`,
    }, 404);
  });
  await listen(server);
  t.after(async () => {
    server.close();
    await fs.rm(tempDir, { recursive: true, force: true });
  });

  const address = server.address();
  const phoneRuntime = {
    phoneUrl: `http://127.0.0.1:${address.port}`,
    phoneToken: 'test-token',
  };
  const output = await runNodeFailureJson([
    publishScript,
    '--platform',
    'douyin',
    '--title',
    'revoked formal publish',
      '--cancel-file',
    cancelFile,
    '--max-wait-sec',
    '30',
    '--poll-ms',
    '100',
    '--json',
  ], phoneRuntime);

  assert.equal(cancelAttempts, 3);
  assert.ok(statusPolls >= 1, 'accepted cancellation should be polled to a terminal state');
  assert.match(submittedPrompt, /只保存草稿|绝对不要点击最终发布/);
  assert.equal(output.success, false);
  assert.equal(output.status, 'cancelled');
  assert.equal(output.cancelled, true);
  assert.equal(output.executionMayContinue, false);
});

test('direct draft publish exposes permanent cancellation failure without a false terminal state', async (t) => {
  const tempDir = await fs.mkdtemp(path.join(os.tmpdir(), 'loom-publish-cancel-failed-'));
  const cancelFile = path.join(tempDir, 'publish.cancel');
  let cancelAttempts = 0;
  let statusPolls = 0;
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
      await fs.writeFile(cancelFile, 'revoked\n', 'utf8');
      return writeJson(response, {
        success: true,
        data: { taskId: 'task-publish-cancel-failed' },
      });
    }
    if (
      request.method === 'POST'
      && url.pathname === '/api/lumi/agent/tasks/task-publish-cancel-failed/cancel'
    ) {
      cancelAttempts += 1;
      return writeJson(response, {
        success: false,
        errorCode: 'phone_cancel_unavailable',
        message: 'cancellation service unavailable',
        retryable: true,
      }, 503);
    }
    if (
      request.method === 'GET'
      && url.pathname === '/api/lumi/agent/tasks/task-publish-cancel-failed'
    ) {
      statusPolls += 1;
      return writeJson(response, {
        success: true,
        data: {
          taskId: 'task-publish-cancel-failed',
          status: 'running',
        },
      });
    }
    return writeJson(response, {
      success: false,
      error: `unexpected ${request.method} ${url.pathname}`,
    }, 404);
  });
  await listen(server);
  t.after(async () => {
    server.close();
    await fs.rm(tempDir, { recursive: true, force: true });
  });

  const address = server.address();
  const phoneRuntime = {
    phoneUrl: `http://127.0.0.1:${address.port}`,
    phoneToken: 'test-token',
  };
  const output = await runNodeFailureJson([
    publishScript,
    '--platform',
    'douyin',
    '--title',
    'unconfirmed revoked formal publish',
      '--cancel-file',
    cancelFile,
    '--max-wait-sec',
    '30',
    '--poll-ms',
    '100',
    '--json',
  ], phoneRuntime);

  assert.equal(cancelAttempts, 3);
  assert.ok(statusPolls >= 1, 'failed cancellation should still poll for a remote terminal state');
  assert.equal(output.success, false);
  assert.equal(output.status, 'cancelling');
  assert.equal(output.cancelled, false);
  assert.equal(output.errorCode, 'phone_task_cancel_unconfirmed');
  assert.equal(output.executionMayContinue, true);
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
  const phoneRuntime = {
    phoneUrl: `http://127.0.0.1:${address.port}`,
    phoneToken: 'test-token',
  };
  await assert.rejects(
    runNode([
      publishScript,
      '--platform',
      'douyin',
      '--title',
      'business failure contract',
      '--max-wait-sec',
      '30',
      '--poll-ms',
      '500',
      '--json',
    ], phoneRuntime),
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

function writeJson(response, payload, status = 200) {
  response.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8' });
  response.end(JSON.stringify(payload));
}

async function runNodeFailureJson(args, phoneRuntime) {
  let failure = null;
  try {
    await runNode(args, phoneRuntime);
  } catch (error) {
    failure = error;
  }
  assert.ok(failure, 'expected the publish process to exit nonzero');
  const message = String(failure.message || failure);
  const stdoutStart = message.indexOf('stdout=');
  const stderrStart = message.lastIndexOf('\nstderr=');
  assert.ok(stdoutStart >= 0 && stderrStart > stdoutStart, message);
  return JSON.parse(message.slice(stdoutStart + 'stdout='.length, stderrStart).trim());
}

function runNode(args, phoneRuntime = {}) {
  return new Promise((resolve, reject) => {
    const unsignedRuntimeConfig = phoneRuntime.runtimeConfig || {
      selectedDeviceId: 'phone-contract',
      devices: [{
        id: 'phone-contract',
        deviceInstanceId: 'device-instance-contract',
        baseUrl: phoneRuntime.phoneUrl,
        token: phoneRuntime.phoneToken,
      }],
    };
    const runtimeEnv = phoneRuntime.unsignedRuntime
      ? {
          LOOM_PHONE_RUNTIME_CONFIG_JSON: JSON.stringify(unsignedRuntimeConfig),
          LOOM_PHONE_RUNTIME_AUTH_TEST_ONLY: '1',
          LOOM_PHONE_RUNTIME_AUTH_TEST_PUBLIC_KEY_B64: TEST_ENTITLEMENT_PUBLIC_KEY_B64,
        }
      : phoneRuntimeTestEnv(unsignedRuntimeConfig, phoneRuntime.authOptions);
    const child = spawn(process.execPath, args, {
      cwd: path.resolve(__dirname, '..', '..'),
      env: {
        ...process.env,
        ...(phoneRuntime.env || {}),
        ...runtimeEnv,
      },
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
    // `exit` may fire before the stdout/stderr pipes are fully drained. Waiting
    // for `close` prevents transient empty or truncated JSON under parallel CI.
    child.on('close', (code) => {
      clearTimeout(timer);
      if (code === 0) {
        resolve(stdout);
      } else {
        reject(new Error(`process exited ${code}\nstdout=${stdout}\nstderr=${stderr}`));
      }
    });
  });
}
