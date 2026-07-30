import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import fs from 'node:fs/promises';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { pathToFileURL } from 'node:url';
import * as phoneSecure from './openclaw-phone-secure.mjs';
import {
  authorizedPhoneRuntime,
  TEST_RELAY_PRODUCER_TOKEN,
  TEST_ENTITLEMENT_PUBLIC_KEY_B64,
} from './tests/phone-runtime-auth-fixture.mjs';

const VERIFY_OPTIONS = Object.freeze({
  nowSec: Math.floor(Date.now() / 1000),
  localInstallId: 'install-node-test',
  activeAccountIds: ['account-node-test'],
  producerToken: TEST_RELAY_PRODUCER_TOKEN,
});

function runtimeFor(baseUrl = 'http://127.0.0.1:19527') {
  return {
    selectedDeviceId: 'phone-a',
    devices: [{
      id: 'phone-a',
      baseUrl,
      token: 'phone-token-a',
      launcherId: 'launcher-a',
      launcherSecret: 'launcher-secret-a',
    }],
  };
}

test('runtime authorization verifier is exposed for the bridge boundary', () => {
  assert.equal(typeof phoneSecure.verifyLauncherPhoneRuntimeConfig, 'function');
});

test('runtime config without a service-signed entitlement is rejected', () => {
  assert.throws(
    () => phoneSecure.verifyLauncherPhoneRuntimeConfig(runtimeFor(), VERIFY_OPTIONS),
    (error) => error?.code === 'runtime_entitlement_required',
  );
});

test('unsigned runtime fails before a phone network request', async () => {
  const requests = [];
  const server = http.createServer((request, response) => {
    requests.push(`${request.method} ${request.url}`);
    response.writeHead(200, { 'Content-Type': 'application/json' });
    response.end(JSON.stringify({ success: true }));
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));

  try {
    const baseUrl = `http://127.0.0.1:${server.address().port}`;
    const result = await runPhoneVision(
      ['status', '--device-id', 'phone-a', '--json'],
      {
        LOOM_PHONE_RUNTIME_CONFIG_JSON: JSON.stringify(runtimeFor(baseUrl)),
        LOOM_PHONE_RUNTIME_AUTH_TEST_ONLY: undefined,
        LOOM_PHONE_RUNTIME_AUTH_TEST_PUBLIC_KEY_B64: undefined,
      },
    );

    assert.notEqual(result.code, 0, result.stdout);
    assert.equal(requests.length, 0);
    assert.match(
      `${result.stdout}\n${result.stderr}`,
      /runtime_entitlement_required|服务端签名的账号权益租约/,
    );
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
});

test('runtime config with a forged service signature is rejected', () => {
  const runtime = authorizedPhoneRuntime(runtimeFor(), VERIFY_OPTIONS);
  runtime.entitlementLease.accountId = 'attacker-account';

  withTestRuntimeKey(() => {
    assert.throws(
      () => phoneSecure.verifyLauncherPhoneRuntimeConfig(runtime, VERIFY_OPTIONS),
      (error) => error?.code === 'runtime_entitlement_signature_invalid',
    );
  });
});

test('runtime device must be covered by the signed phone seat lease', () => {
  const runtime = authorizedPhoneRuntime(runtimeFor(), VERIFY_OPTIONS);
  runtime.devices[0].id = 'phone-outside-signed-seat';

  withTestRuntimeKey(() => {
    assert.throws(
      () => phoneSecure.verifyLauncherPhoneRuntimeConfig(runtime, VERIFY_OPTIONS),
      (error) => error?.code === 'runtime_phone_device_unauthorized',
    );
  });
});

test('signed runtime without unlimited phone entitlement is rejected', () => {
  const runtime = authorizedPhoneRuntime(runtimeFor(), {
    ...VERIFY_OPTIONS,
    unlimitedDevices: false,
  });

  withTestRuntimeKey(() => {
    assert.throws(
      () => phoneSecure.verifyLauncherPhoneRuntimeConfig(runtime, VERIFY_OPTIONS),
      (error) => error?.code === 'runtime_entitlement_feature_required',
    );
  });
});

test('valid signed bridge runtime preserves selected phone credentials and identity', () => {
  const sourceRuntime = runtimeFor();
  sourceRuntime.devices[0].deviceInstanceId = 'stable-phone-a';
  const runtime = authorizedPhoneRuntime(sourceRuntime, VERIFY_OPTIONS);

  const verified = withTestRuntimeKey(
    () => phoneSecure.verifyLauncherPhoneRuntimeConfig(runtime, VERIFY_OPTIONS),
  );

  assert.equal(verified.accountId, 'account-node-test');
  assert.equal(verified.selectedDeviceId, 'phone-a');
  assert.equal(verified.devices[0].phoneUrl, 'http://127.0.0.1:19527');
  assert.equal(verified.devices[0].phoneToken, 'phone-token-a');
  assert.equal(verified.devices[0].deviceInstanceId, 'stable-phone-a');
  assert.match(verified.configDigest, /^[a-f0-9]{64}$/);
});

test('valid signed runtime rejects a missing or mismatched producer token', () => {
  const runtime = authorizedPhoneRuntime(runtimeFor(), VERIFY_OPTIONS);

  withTestRuntimeKey(() => {
    assert.throws(
      () => phoneSecure.verifyLauncherPhoneRuntimeConfig(runtime, {
        ...VERIFY_OPTIONS,
        producerToken: '',
      }),
      (error) => error?.code === 'runtime_producer_token_required',
    );
    assert.throws(
      () => phoneSecure.verifyLauncherPhoneRuntimeConfig(runtime, {
        ...VERIFY_OPTIONS,
        producerToken: 'wrong-model-account-token',
      }),
      (error) => error?.code === 'runtime_producer_token_mismatch',
    );
  });
});

test('packaged runtime ignores forged test-only public-key overrides', async () => {
  const tempDir = await fs.mkdtemp(path.join(os.tmpdir(), 'loom-phone-packaged-auth-'));
  const packagedScripts = path.join(tempDir, '_up_', 'scripts');
  const packagedSecurePath = path.join(packagedScripts, 'openclaw-phone-secure.mjs');
  const previousTestOnly = process.env.LOOM_PHONE_RUNTIME_AUTH_TEST_ONLY;
  const previousTestKey = process.env.LOOM_PHONE_RUNTIME_AUTH_TEST_PUBLIC_KEY_B64;

  try {
    await fs.mkdir(packagedScripts, { recursive: true });
    await fs.copyFile(
      new URL('./openclaw-phone-secure.mjs', import.meta.url),
      packagedSecurePath,
    );
    process.env.LOOM_PHONE_RUNTIME_AUTH_TEST_ONLY = '1';
    process.env.LOOM_PHONE_RUNTIME_AUTH_TEST_PUBLIC_KEY_B64 = TEST_ENTITLEMENT_PUBLIC_KEY_B64;
    const packagedSecure = await import(
      `${pathToFileURL(packagedSecurePath).href}?test=${Date.now()}`
    );
    const runtime = authorizedPhoneRuntime(runtimeFor(), VERIFY_OPTIONS);

    assert.throws(
      () => packagedSecure.verifyLauncherPhoneRuntimeConfig(runtime, VERIFY_OPTIONS),
      (error) => error?.code === 'runtime_entitlement_signature_invalid',
    );
  } finally {
    restoreEnv('LOOM_PHONE_RUNTIME_AUTH_TEST_ONLY', previousTestOnly);
    restoreEnv('LOOM_PHONE_RUNTIME_AUTH_TEST_PUBLIC_KEY_B64', previousTestKey);
    await fs.rm(tempDir, { recursive: true, force: true });
  }
});

function restoreEnv(name, value) {
  if (value === undefined) delete process.env[name];
  else process.env[name] = value;
}

function withTestRuntimeKey(callback) {
  const previousTestOnly = process.env.LOOM_PHONE_RUNTIME_AUTH_TEST_ONLY;
  const previousTestKey = process.env.LOOM_PHONE_RUNTIME_AUTH_TEST_PUBLIC_KEY_B64;
  try {
    process.env.LOOM_PHONE_RUNTIME_AUTH_TEST_ONLY = '1';
    process.env.LOOM_PHONE_RUNTIME_AUTH_TEST_PUBLIC_KEY_B64 = TEST_ENTITLEMENT_PUBLIC_KEY_B64;
    return callback();
  } finally {
    restoreEnv('LOOM_PHONE_RUNTIME_AUTH_TEST_ONLY', previousTestOnly);
    restoreEnv('LOOM_PHONE_RUNTIME_AUTH_TEST_PUBLIC_KEY_B64', previousTestKey);
  }
}

function runPhoneVision(args, envOverrides) {
  return new Promise((resolve) => {
    const env = { ...process.env, NO_COLOR: '1', ...envOverrides };
    for (const [name, value] of Object.entries(env)) {
      if (value === undefined) delete env[name];
    }
    const child = spawn(
      process.execPath,
      ['scripts/openclaw-phone-vision.mjs', ...args],
      {
        cwd: new URL('..', import.meta.url),
        env,
        stdio: ['ignore', 'pipe', 'pipe'],
      },
    );
    let stdout = '';
    let stderr = '';
    child.stdout.on('data', (chunk) => {
      stdout += chunk.toString();
    });
    child.stderr.on('data', (chunk) => {
      stderr += chunk.toString();
    });
    child.on('close', (code) => resolve({ code, stdout, stderr }));
  });
}
