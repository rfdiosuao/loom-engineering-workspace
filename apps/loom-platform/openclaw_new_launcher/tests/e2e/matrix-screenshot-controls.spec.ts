import { expect, test, type AuditHarness } from './support/audit-fixture';
import {
  appMain,
  markCalls,
  navigateTo,
  proxyIntents,
} from './support/control-audit';
import { AUDIT_MATRIX_WITH_DEVICE } from './support/control-audit-data';

const DEVICE_ID = 'phone-audit-1';
const SCREEN_PATH = '/api/matrix/screens';
const CONTROL_PATH = `/api/matrix/devices/${DEVICE_ID}/control`;
const MATRIX_SCREEN = {
  schema: 'loom.matrix.screen.v1',
  deviceId: DEVICE_ID,
  capturedAt: '2026-07-18T00:00:00.000Z',
  screenHash: 'matrix-screen-control-audit',
  mime: 'image/png',
  width: 1,
  height: 1,
  notModified: false,
  image: 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=',
};

async function registerMatrixControlRoutes(audit: AuditHarness) {
  await audit.registerRoute('GET', '/api/matrix/status', { value: AUDIT_MATRIX_WITH_DEVICE });
  await audit.registerRoute('GET', `/api/matrix/devices/${DEVICE_ID}/timeline?limit=80`, { value: { events: [] } });
  await audit.registerRoute('GET', `/api/matrix/devices/${DEVICE_ID}/lease`, { value: { lease: null } });
  await audit.registerRoute('POST', SCREEN_PATH, {
    value: { schema: 'loom.matrix.screens.v1', screens: [MATRIX_SCREEN], errors: [] },
  });
  await audit.registerRoute('POST', `/api/matrix/devices/${DEVICE_ID}/lease`, {
    value: {
      lease: {
        schema: 'loom.matrix.device_lease.v1',
        leaseId: 'lease-screen-control-audit',
        deviceId: DEVICE_ID,
        holderType: 'human',
        holderId: 'screen-control-audit',
        mode: 'control',
        expiresAt: '2099-12-31T23:59:59.000Z',
      },
    },
  });
  await audit.registerRoute('POST', CONTROL_PATH, { value: { status: 'applied' } });
}

async function openManualInspector(audit: AuditHarness, page: Parameters<typeof appMain>[0]) {
  await registerMatrixControlRoutes(audit);
  await navigateTo(audit, 'workbench');

  const main = appMain(page);
  const inspector = main.locator('[data-matrix-device-inspector]');
  await expect(inspector.getByRole('img', { name: 'Audit Phone 聚焦画面' })).toBeVisible();
  await inspector.getByRole('button', { name: '人工' }).click();
  await expect(inspector.getByRole('button', { name: '截图' })).toBeEnabled();
  return { inspector, main };
}

test.beforeEach(async ({ audit }) => {
  await audit.openAuthorizedShell();
});

test('matrix screenshot control performs one screen read and no control write', async ({ audit, page }) => {
  const { inspector } = await openManualInspector(audit, page);
  const before = await markCalls(audit);

  await inspector.getByRole('button', { name: '截图' }).click();
  await expect.poll(async () => {
    await audit.sync();
    return proxyIntents(audit.callLogs.slice(before)).filter((intent) => intent.path.startsWith(SCREEN_PATH)).length;
  }).toBe(1);
  await page.waitForTimeout(200);
  await audit.sync();

  const intents = proxyIntents(audit.callLogs.slice(before));
  expect(intents.filter((intent) => intent.path.startsWith(SCREEN_PATH))).toHaveLength(1);
  expect(intents.filter((intent) => intent.path === CONTROL_PATH)).toEqual([]);
});

test('failed screen refresh keeps last-frame controls available and supports retry', async ({ audit, page }) => {
  const { inspector } = await openManualInspector(audit, page);
  await audit.registerRoute('POST', SCREEN_PATH, { error: 'USB screenshot transport unavailable' });

  await inspector.getByRole('button', { name: '截图' }).click();

  const staleFrameNotice = inspector.getByText('画面刷新较慢，暂时显示上一帧');
  await expect(staleFrameNotice).toBeVisible();
  await expect(inspector.getByRole('button', { name: '主页' })).toBeEnabled();
  await expect(inspector.getByRole('button', { name: '截图' })).toBeEnabled();

  await audit.registerRoute('POST', SCREEN_PATH, {
    value: {
      schema: 'loom.matrix.screens.v1',
      screens: [{ ...MATRIX_SCREEN, capturedAt: '2026-07-18T00:00:01.000Z' }],
      errors: [],
    },
  });
  await inspector.getByRole('button', { name: '重试', exact: true }).click();

  await expect(staleFrameNotice).toBeHidden();
  await expect(inspector.getByRole('button', { name: '主页' })).toBeEnabled();
});

test('focus status overlay does not dispatch a phone tap', async ({ audit, page }) => {
  const { inspector } = await openManualInspector(audit, page);
  const before = await markCalls(audit);

  await inspector.locator('[data-matrix-focus-status]').click();
  await page.waitForTimeout(100);
  await audit.sync();

  expect(proxyIntents(audit.callLogs.slice(before)).filter((intent) => intent.path === CONTROL_PATH)).toEqual([]);
});
