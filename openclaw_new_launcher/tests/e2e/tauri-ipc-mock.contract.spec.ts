import { expect, test } from '@playwright/test';
import { installTauriIpcMock } from './support/tauri-ipc-mock';

test.beforeEach(async ({ page }) => {
  await page.addInitScript(installTauriIpcMock, {
    commands: {
      known_read: { value: { stable: true } },
    },
    routes: {
      'GET /known': { value: { source: 'local-mock' } },
    },
  });
  await page.goto('about:blank');
});
test('returns registered responses and records invoke calls', async ({ page }) => {
  const result = await page.evaluate(async () => {
    const first = await window.__TAURI_INTERNALS__.invoke('known_read', { id: 7 });
    const second = await window.__TAURI_INTERNALS__.invoke('known_read', { id: 7 });
    return {
      first,
      sameReference: first === second,
      calls: window.__TAURI_AUDIT__.calls,
    };
  });

  expect(result.first).toEqual({ stable: true });
  expect(result.sameReference).toBe(false);
  expect(result.calls).toEqual([
    { command: 'known_read', args: { id: 7 } },
    { command: 'known_read', args: { id: 7 } },
  ]);
});

test('rejects an unknown invoke command visibly', async ({ page }) => {
  const result = await page.evaluate(async () => {
    let message = '';
    try {
      await window.__TAURI_INTERNALS__.invoke('not_registered');
    } catch (error) {
      message = String(error);
    }
    return { message, failures: window.__TAURI_AUDIT__.unexpectedFailures };
  });

  expect(result.message).toContain('Unregistered Tauri invoke command: not_registered');
  expect(result.failures).toEqual(['Unregistered Tauri invoke command: not_registered']);
});

test('rejects an unregistered proxy route visibly', async ({ page }) => {
  const result = await page.evaluate(async () => {
    let message = '';
    try {
      await window.__TAURI_INTERNALS__.invoke('proxy_request', {
        path: '/missing',
        method: 'GET',
        body: null,
      });
    } catch (error) {
      message = String(error);
    }
    return { message, failures: window.__TAURI_AUDIT__.unexpectedFailures };
  });

  expect(result.message).toContain('Unregistered Tauri proxy route: GET /missing');
  expect(result.failures).toEqual(['Unregistered Tauri proxy route: GET /missing']);
});
