import {
  expect,
  test as base,
  type BrowserContext,
  type Page,
} from '@playwright/test';
import { createBaselineSeed } from './mock-responses';
import {
  installTauriIpcMock,
  type ExternalOpenIntent,
  type InvokeCall,
  type MockResponse,
  type TauriMockSeed,
} from './tauri-ipc-mock';

export interface RegistryEntry {
  key: string;
  readySelector: string;
}

export const PAGE_REGISTRY: RegistryEntry[] = [
  { key: 'dashboard', readySelector: '[data-dashboard-matrix-hero]' },
  { key: 'agents', readySelector: '[data-agent-page-scroll]' },
  { key: 'creative', readySelector: '[data-creative-media-page]' },
  { key: 'acquisition', readySelector: '[data-acquisition-workbench]' },
  { key: 'phone', readySelector: 'main h1:has-text("手机控制")' },
  { key: 'workbench', readySelector: '[data-matrix-command-bar]' },
  { key: 'agent', readySelector: '[data-agent-workbench]' },
  { key: 'license', readySelector: '[data-account-subscription-page]' },
  { key: 'agentAccess', readySelector: 'main h1:has-text("Agent 接入")' },
  { key: 'capabilities', readySelector: 'main h1:has-text("暂未开放")' },
  { key: 'settings', readySelector: 'main h1' },
  { key: 'models', readySelector: 'main h1:has-text("模型选择")' },
  { key: 'diagnostics', readySelector: 'main h1:has-text("环境诊断")' },
  { key: 'terminal', readySelector: 'main [tabindex="0"]' },
];

export interface AuditHarness {
  callLogs: InvokeCall[];
  consoleErrors: string[];
  unexpectedCommandFailures: string[];
  blockedNetworkRequests: string[];
  externalOpenIntents: ExternalOpenIntent[];
  openAuthorizedShell: () => Promise<void>;
  navigateTo: (entry: RegistryEntry) => Promise<void>;
  registerCommand: (command: string, response: MockResponse) => Promise<void>;
  registerRoute: (method: string, path: string, response: MockResponse) => Promise<void>;
  sync: () => Promise<void>;
}

interface AuditFixtures {
  audit: AuditHarness;
}

function replaceArray<T>(target: T[], source: T[]): void {
  target.splice(0, target.length, ...source);
}

function installConsoleAudit(page: Page, errors: string[]): void {
  page.on('console', (message) => {
    if (message.type() === 'error') errors.push(message.text());
  });
  page.on('pageerror', (error) => errors.push(`pageerror: ${error.message}`));
}

async function denyExternalNetwork(
  context: BrowserContext,
  blocked: string[],
  baseURL: string | undefined,
): Promise<void> {
  const allowedOrigin = new URL(baseURL || 'http://127.0.0.1:1420').origin;
  const transparentPixel = Buffer.from(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9ZQmcAAAAASUVORK5CYII=',
    'base64',
  );
  await context.route('**/*', async (route) => {
    const url = new URL(route.request().url());
    const localViteRequest = url.origin === allowedOrigin;
    if (localViteRequest) {
      await route.continue();
      return;
    }
    if (url.origin === 'http://asset.localhost') {
      await route.fulfill({ status: 200, contentType: 'image/png', body: transparentPixel });
      return;
    }
    blocked.push(`${route.request().method()} ${url.href}`);
    await route.abort('blockedbyclient');
  });
}

export const test = base.extend<AuditFixtures>({
  audit: async ({ baseURL, context, page }, use) => {
    const seed: TauriMockSeed = createBaselineSeed();
    const callLogs: InvokeCall[] = [];
    const consoleErrors: string[] = [];
    const unexpectedCommandFailures: string[] = [];
    const blockedNetworkRequests: string[] = [];
    const externalOpenIntents: ExternalOpenIntent[] = [];
    let opened = false;

    installConsoleAudit(page, consoleErrors);
    await denyExternalNetwork(context, blockedNetworkRequests, baseURL);

    const sync = async () => {
      if (!opened || page.isClosed()) return;
      const snapshot = await page.evaluate(() => ({
        calls: window.__TAURI_AUDIT__.calls,
        externalOpenIntents: window.__TAURI_AUDIT__.externalOpenIntents,
        failures: window.__TAURI_AUDIT__.unexpectedFailures,
      }));
      replaceArray(callLogs, snapshot.calls);
      replaceArray(externalOpenIntents, snapshot.externalOpenIntents);
      replaceArray(unexpectedCommandFailures, snapshot.failures);
    };

    const registerCommand = async (command: string, response: MockResponse) => {
      seed.commands[command] = response;
      if (opened) {
        await page.evaluate(({ name, value }) => {
          window.__TAURI_AUDIT__.registerCommand(name, value);
        }, { name: command, value: response });
      }
    };

    const registerRoute = async (method: string, path: string, response: MockResponse) => {
      const key = `${method.toUpperCase()} ${path}`;
      seed.routes[key] = response;
      if (opened) {
        await page.evaluate(({ name, value }) => {
          window.__TAURI_AUDIT__.registerRoute(name, value);
        }, { name: key, value: response });
      }
    };

    const audit: AuditHarness = {
      callLogs,
      consoleErrors,
      unexpectedCommandFailures,
      blockedNetworkRequests,
      externalOpenIntents,
      openAuthorizedShell: async () => {
        if (opened) return;
        await context.grantPermissions(['clipboard-read', 'clipboard-write']);
        await page.addInitScript(installTauriIpcMock, seed);
        await page.goto('/?licenseState=authorized');
        opened = true;
        await expect(page.locator('[data-commercial-app-shell]')).toBeVisible({ timeout: 15_000 });
      },
      navigateTo: async (entry) => {
        if (!opened) throw new Error('Call audit.openAuthorizedShell() before navigating');
        await page.evaluate(async (key) => {
          const storePath = '/src/stores/appStore.ts';
          const { useAppStore } = await import(storePath) as {
            useAppStore: { getState: () => { setCurrentPage: (page: string) => void } };
          };
          useAppStore.getState().setCurrentPage(key);
        }, entry.key);
        await expect(page.locator(entry.readySelector).first()).toBeVisible({ timeout: 15_000 });
        await page.evaluate(() => new Promise<void>((resolve) => {
          requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
        }));
      },
      registerCommand,
      registerRoute,
      sync,
    };

    await use(audit);
    await sync();
    expect(consoleErrors, 'Browser console/page errors').toEqual([]);
    expect(unexpectedCommandFailures, 'Unregistered Tauri commands or proxy routes').toEqual([]);
    expect(blockedNetworkRequests, 'External network requests attempted by the audited flow').toEqual([]);
  },
});

export { expect };
