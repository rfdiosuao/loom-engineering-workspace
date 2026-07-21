import { expect, type Locator, type Page } from '@playwright/test';
import {
  PAGE_REGISTRY,
  type AuditHarness,
  type RegistryEntry,
} from './audit-fixture';
import type { InvokeCall } from './tauri-ipc-mock';

export const ACTIONABLE_SELECTOR = [
  'button:visible',
  'a[href]:visible',
  'input:not([type="hidden"]):visible',
  'select:visible',
  'textarea:visible',
  'summary:visible',
  '[role="button"]:visible',
  '[role="link"]:visible',
  '[role="tab"]:visible',
  '[role="switch"]:visible',
].join(',');

export interface ProxyIntent {
  method: string;
  path: string;
  body: unknown;
}

export function registryEntry(key: string): RegistryEntry {
  const entry = PAGE_REGISTRY.find((candidate) => candidate.key === key);
  if (!entry) throw new Error(`Unknown PAGE_REGISTRY key: ${key}`);
  return entry;
}

export function appMain(page: Page): Locator {
  return page.locator('[data-commercial-app-shell] main').first();
}

export function shellControls(page: Page): Locator {
  return page.locator('[data-window-drag-above-overlays], [data-commercial-app-shell] aside')
    .locator(ACTIONABLE_SELECTOR);
}

export function pageControls(page: Page): Locator {
  return appMain(page).locator(ACTIONABLE_SELECTOR);
}

export async function navigateTo(audit: AuditHarness, key: string): Promise<void> {
  await audit.navigateTo(registryEntry(key));
}

export async function navigateToAndWait(
  page: Page,
  key: string,
  ready: Locator,
): Promise<void> {
  await page.evaluate(async (pageKey) => {
    const storePath = '/src/stores/appStore.ts';
    const { useAppStore } = await import(storePath) as {
      useAppStore: { getState: () => { setCurrentPage: (nextPage: string) => void } };
    };
    useAppStore.getState().setCurrentPage(pageKey);
  }, key);
  await expect(ready).toBeVisible();
}

export async function markCalls(audit: AuditHarness): Promise<number> {
  await audit.sync();
  return audit.callLogs.length;
}

export function callsAfter(audit: AuditHarness, index: number): InvokeCall[] {
  return audit.callLogs.slice(index);
}

export function proxyIntents(calls: InvokeCall[]): ProxyIntent[] {
  return calls
    .filter((call) => call.command === 'proxy_request')
    .map((call) => {
      const rawBody = call.args.body;
      return {
        method: String(call.args.method || 'GET').toUpperCase(),
        path: String(call.args.path || ''),
        body: typeof rawBody === 'string' ? JSON.parse(rawBody) : null,
      };
    });
}

export async function expectProxyIntent(
  audit: AuditHarness,
  afterIndex: number,
  expected: ProxyIntent,
): Promise<void> {
  await expect.poll(async () => {
    await audit.sync();
    return proxyIntents(callsAfter(audit, afterIndex));
  }).toContainEqual(expected);
}

export async function expectInvokeIntent(
  audit: AuditHarness,
  afterIndex: number,
  expected: InvokeCall,
): Promise<void> {
  await expect.poll(async () => {
    await audit.sync();
    return callsAfter(audit, afterIndex);
  }).toContainEqual(expected);
}

export async function expectToast(page: Page, message: string | RegExp): Promise<void> {
  await expect(page.locator('[data-toast-container]').getByText(message).last()).toBeVisible();
}

export async function confirmDialog(
  page: Page,
  title: string | RegExp,
  confirmName: string | RegExp,
): Promise<void> {
  const dialog = page.getByRole('dialog', { name: title });
  await expect(dialog).toBeVisible();
  await dialog.getByRole('button', { name: confirmName, exact: typeof confirmName === 'string' }).click();
  await expect(dialog).toBeHidden();
}

export function completedJob(id: string, result: Record<string, unknown> = {}) {
  return {
    id,
    kind: 'playwright-audit',
    label: 'isolated control audit',
    status: 'succeeded',
    message: 'completed by isolated audit mock',
    result,
    progress: {
      phase: 'complete',
      message: 'completed by isolated audit mock',
      executionLayer: 'mock',
    },
  };
}
