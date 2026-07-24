import 'tsx/esm';

import assert from 'node:assert/strict';
import { afterEach, test } from 'node:test';

import { api, jobApi, updateApi, waitForJob } from './api.ts';
import * as apiModule from './api.ts';

const originalWindow = globalThis.window;

afterEach(() => {
  if (originalWindow === undefined) {
    Reflect.deleteProperty(globalThis, 'window');
    return;
  }
  Object.defineProperty(globalThis, 'window', {
    configurable: true,
    writable: true,
    value: originalWindow,
  });
});

function mockProxyResponse(payload: unknown) {
  Object.defineProperty(globalThis, 'window', {
    configurable: true,
    writable: true,
    value: {
      localStorage: {
        setItem: () => undefined,
      },
      __TAURI_INTERNALS__: {
        invoke: async (command: string) => {
          if (command === 'get_bridge_port') return 24680;
          if (command === 'proxy_request') return JSON.stringify(payload);
          throw new Error(`Unexpected Tauri command: ${command}`);
        },
      },
    },
  });
}

test('api accepts Feishu-style success responses with an empty error string', async () => {
  const response = { success: true, error: '', records: 1 };
  mockProxyResponse(response);

  assert.deepEqual(await api('/api/feishu/test-write', 'POST'), response);
});

test('api rejects responses with a nonempty error string', async () => {
  const response = { success: false, error: 'Feishu write failed' };
  mockProxyResponse(response);

  await assert.rejects(
    api('/api/feishu/test-write', 'POST'),
    (error) => {
      assert.deepEqual(error, response);
      return true;
    },
  );
});

test('update API exposes cancellation and post-restart result endpoints', () => {
  assert.equal(typeof (updateApi as unknown as { cancel?: unknown }).cancel, 'function');
  assert.equal(typeof (updateApi as unknown as { result?: unknown }).result, 'function');
});

test('automatic update presentation respects a skipped version but manual checks do not', () => {
  const shouldPresent = (apiModule as unknown as {
    shouldPresentUpdate?: (latest: string, skipped: string, manual: boolean) => boolean;
  }).shouldPresentUpdate;
  assert.equal(typeof shouldPresent, 'function');
  if (!shouldPresent) return;

  assert.equal(shouldPresent('2.3.0', '2.3.0', false), false);
  assert.equal(shouldPresent('2.3.0', '2.3.0', true), true);
  assert.equal(shouldPresent('2.3.1', '2.3.0', false), true);
});

test('job polling returns needs_manual as a terminal result', async () => {
  const originalGet = jobApi.get;
  let polls = 0;
  const manualJob = {
    id: 'job-manual-install',
    status: 'needs_manual',
    result: {
      manualRequired: true,
      message: '请在 Microsoft Store 完成安装',
    },
  };

  jobApi.get = async () => {
    polls += 1;
    return { job: manualJob };
  };

  try {
    const result = await waitForJob('job-manual-install', {
      intervalMs: 1,
      timeoutMs: 25,
    });

    assert.equal(result, manualJob);
    assert.equal(polls, 1);
  } finally {
    jobApi.get = originalGet;
  }
});

test('parseErrorText localizes managed model login failures', () => {
  assert.equal(
    apiModule.parseErrorText('Managed model login is required.'),
    '请先在“模型账号”完成登录，然后返回当前页面重试。',
  );
});
