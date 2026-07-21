import { defineConfig, devices } from '@playwright/test';

const edgeDesktop = {
  ...devices['Desktop Edge'],
  channel: 'msedge' as const,
};

const auditDesktop = process.env.LOOM_AUDIT_BROWSER === 'chromium'
  ? { ...devices['Desktop Chrome'] }
  : edgeDesktop;

const auditPort = Number.parseInt(process.env.LOOM_AUDIT_PORT || '14321', 10);
const auditBaseUrl = `http://127.0.0.1:${auditPort}`;
const reuseAuditServer = process.env.LOOM_AUDIT_REUSE_SERVER === '1';

export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: 0,
  reporter: 'list',
  outputDir: 'node_modules/.cache/playwright-audit',
  use: {
    baseURL: auditBaseUrl,
    trace: 'retain-on-failure',
  },
  webServer: {
    command: `npm run dev -- --host 127.0.0.1 --port ${auditPort} --strictPort`,
    url: auditBaseUrl,
    reuseExistingServer: reuseAuditServer,
    timeout: 120_000,
  },
  projects: [
    {
      name: 'edge-960x640',
      use: { ...auditDesktop, viewport: { width: 960, height: 640 } },
    },
    {
      name: 'edge-1200x800',
      use: { ...auditDesktop, viewport: { width: 1200, height: 800 } },
    },
    {
      name: 'edge-1440x900',
      use: { ...auditDesktop, viewport: { width: 1440, height: 900 } },
    },
  ],
});
