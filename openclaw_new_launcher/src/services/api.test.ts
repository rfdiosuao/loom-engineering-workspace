import 'tsx/esm';

import assert from 'node:assert/strict';
import { afterEach, test } from 'node:test';

import { api } from './api.ts';

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
