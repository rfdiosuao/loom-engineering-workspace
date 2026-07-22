import { expect, test } from './support/audit-fixture';
import {
  appMain,
  confirmDialog,
  expectInvokeIntent,
  expectProxyIntent,
  expectToast,
  markCalls,
  navigateTo,
  registryEntry,
} from './support/control-audit';
import { AUDIT_REPAIRABLE_DIAGNOSTICS } from './support/control-audit-data';
import { AUDIT_DIAGNOSTICS } from './support/mock-responses';

test.beforeEach(async ({ audit }) => {
  await audit.openAuthorizedShell();
});

test('global window controls invoke the native window handlers', async ({ audit, page }) => {
  const controls = [
    ['最小化', 'plugin:window|minimize'],
    ['最大化/还原', 'plugin:window|toggle_maximize'],
    ['关闭', 'plugin:window|close'],
  ] as const;

  for (const [name, command] of controls) {
    await test.step(name, async () => {
      const before = await markCalls(audit);
      await page.getByRole('button', { name, exact: true }).click();
      await expectInvokeIntent(audit, before, { command, args: { label: 'main' } });
    });
  }
});

test('every visible sidebar control navigates through the application handler', async ({ audit, page }) => {
  const sidebar = page.locator('[data-commercial-app-shell] aside');
  const destinations = [
    ['总览', 'dashboard'],
    ['安装', 'agents'],
    ['创作', 'creative'],
    ['获客', 'acquisition'],
    ['工作台', 'workbench'],
    ['模型账户', 'license'],
    ['Agent 接入', 'agentAccess'],
    ['系统设置', 'settings'],
  ] as const;

  for (const [name, key] of destinations) {
    await test.step(`${name} -> ${key}`, async () => {
      await sidebar.getByRole('button', { name, exact: true }).first().click();
      await expect(page.locator(registryEntry(key).readySelector).first()).toBeVisible();
    });
  }

  const accountButtons = sidebar.getByRole('button', { name: '模型账户', exact: true });
  await expect(accountButtons).toHaveCount(2);
  await navigateTo(audit, 'dashboard');
  await accountButtons.nth(1).click();
  await expect(page.locator(registryEntry('license').readySelector).first()).toBeVisible();
});

async function openDashboardLegacy(audit: Parameters<typeof navigateTo>[0], page: import('@playwright/test').Page) {
  await navigateTo(audit, 'dashboard');
  await page.getByRole('button', { name: '开始配置' }).click();
  await expect(appMain(page).getByRole('heading', { name: '开始使用麓鸣', exact: true })).toBeVisible();
}

test('dashboard hero controls reveal legacy configuration and open the workbench', async ({ audit, page }) => {
  await navigateTo(audit, 'dashboard');
  await page.getByRole('button', { name: '查看可做的事' }).click();
  await expect(page.locator(registryEntry('workbench').readySelector)).toBeVisible();

  await openDashboardLegacy(audit, page);
  await appMain(page).getByRole('button', { name: '返回总览图' }).click();
  await expect(page.locator('[data-dashboard-matrix-hero]')).toBeVisible();
});

const dashboardLegacyDestinations = [
  { label: 'first path card', key: 'agents', name: /第一步.*安装智能体.*选择智能体/ },
  { label: 'second path card', key: 'phone', name: /第二步.*连接手机.*打开手机控制/ },
] as const;

for (const destination of dashboardLegacyDestinations) {
  test(`dashboard legacy ${destination.label} navigates to ${destination.key}`, async ({ audit, page }) => {
    await openDashboardLegacy(audit, page);
    const control = appMain(page).getByRole('button', { name: destination.name });
    await control.click();
    await expect(page.locator(registryEntry(destination.key).readySelector).first()).toBeVisible();
  });
}

test('Agent Access copies the one-shot and all advanced payloads through the real clipboard handler', async ({ audit, page }) => {
  await navigateTo(audit, 'agentAccess');
  await appMain(page).getByRole('button', { name: '复制接入提示词' }).click();
  await expect(appMain(page).getByRole('button', { name: '已复制' }).first()).toBeVisible();
  await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toContain('BEGIN_MCP_JSON');

  const details = appMain(page).locator('details');
  await details.locator('summary').click();
  await expect(details).toHaveAttribute('open', '');

  const payloads = [
    ['Skill 位置', 'luming-phone-agent'],
    ['MCP 配置', 'mcpServers'],
    ['CLI 验证', 'doctor --json'],
  ] as const;
  for (const [heading, expectedText] of payloads) {
    const section = details.getByRole('heading', { name: heading }).locator('xpath=ancestor::section');
    await section.getByRole('button', { name: '复制' }).click();
    await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toContain(expectedText);
  }

  await details.locator('summary').click();
  await expect(details).not.toHaveAttribute('open', '');
});

test('capabilities exposes only truthful unavailable status and no dead controls', async ({ audit, page }) => {
  await navigateTo(audit, 'capabilities');
  await expect(appMain(page).getByRole('status')).toHaveCount(4);
  await expect(appMain(page).getByRole('status', { name: /状态：暂未开放/ })).toHaveCount(4);
  await expect(appMain(page).locator('button, a[href], input, select, textarea, summary')).toHaveCount(0);
});

test('settings appearance controls persist language and theme state', async ({ audit, page }) => {
  await navigateTo(audit, 'settings');
  await appMain(page).getByRole('combobox', { name: '语言' }).selectOption('en-US');
  await expect(page.locator('html')).toHaveAttribute('lang', 'en-US');
  await expectToast(page, 'Language switched');

  await appMain(page).getByRole('combobox', { name: 'Language' }).selectOption('zh-CN');
  await expect(page.locator('html')).toHaveAttribute('lang', 'zh-CN');

  for (const [name, mode] of [['深色', 'dark'], ['跟随系统', 'system'], ['米白', 'light']] as const) {
    await appMain(page).getByRole('button', { name, exact: true }).click();
    await expect(page.locator('html')).toHaveAttribute('data-theme-mode', mode);
  }
});

test('settings opens the global update center and installs only after download verification', async ({ audit, page }) => {
  await audit.registerRoute('GET', '/api/update/check', {
    value: {
      current: '2.3.0',
      latest: '2.3.1-audit',
      hasUpdate: true,
      notes: 'Audit update center release notes',
      publishedAt: '2026-07-22T00:00:00.000Z',
      releaseUrl: 'https://example.invalid/releases/2.3.1-audit',
      size: 12_345_678,
    },
  });
  await audit.registerRoute('POST', '/api/update/do', {
    value: {
      success: true,
      outcome: 'ready',
      current_version: '2.3.1-audit',
      log: ['isolated audit download', 'isolated audit verification'],
      installer_path: 'C:\\LOOM\\playwright-audit\\update.exe',
    },
  });
  await audit.registerCommand('prepare_update_install', { value: null });

  await navigateTo(audit, 'settings');
  await appMain(page).getByRole('button', { name: '更新', exact: true }).click();
  const beforeCheck = await markCalls(audit);
  await appMain(page).getByRole('button', { name: '检查更新' }).click();
  await expectProxyIntent(audit, beforeCheck, { method: 'GET', path: '/api/update/check', body: null });
  const updateCenter = page.getByRole('dialog', { name: '发现新版本' });
  await expect(updateCenter).toBeVisible();
  await expect(updateCenter).toContainText('Audit update center release notes');

  const install = updateCenter.getByRole('button', { name: '立即更新' });
  await expect(install).toBeEnabled();
  const beforeInstall = await markCalls(audit);
  await install.click();
  await expectProxyIntent(audit, beforeInstall, { method: 'POST', path: '/api/update/do', body: null });
  await expect(updateCenter.getByText('下载与安全校验已完成')).toBeVisible();

  const beforeRestart = await markCalls(audit);
  await updateCenter.getByRole('button', { name: '立即重启' }).click();
  await expectInvokeIntent(audit, beforeRestart, {
    command: 'prepare_update_install',
    args: { installerPath: 'C:\\LOOM\\playwright-audit\\update.exe' },
  });
});

const settingsDataDestinations = [
  ['打开诊断', 'diagnostics'],
  ['查看日志', 'terminal'],
  ['打开模型账号', 'license'],
  ['打开安装', 'agents'],
  ['打开开发者接入', 'agentAccess'],
] as const;

for (const [controlName, key] of settingsDataDestinations) {
  test(`settings data control ${controlName} navigates to ${key}`, async ({ audit, page }) => {
    await navigateTo(audit, 'settings');
    await appMain(page).getByRole('button', { name: '数据', exact: true }).click();
    await appMain(page).getByRole('button', { name: controlName, exact: true }).click();
    await expect(page.locator(registryEntry(key).readySelector).first()).toBeVisible();
  });
}

test('settings about tab is an intentionally read-only surface', async ({ audit, page }) => {
  await navigateTo(audit, 'settings');
  await appMain(page).getByRole('button', { name: '关于', exact: true }).click();
  await expect(appMain(page).getByText('麓鸣AI矩阵获客工作台', { exact: true }).first()).toBeVisible();
  await expect(appMain(page).getByRole('button')).toHaveCount(4);
});

test('diagnostics copy, rerun, export, open-directory, and detail controls use strict local paths', async ({ audit, page }) => {
  await audit.registerRoute('POST', '/api/diagnostics/export', {
    value: {
      path: 'C:\\LOOM\\playwright-audit\\diagnostics\\audit.zip',
      directory: 'C:\\LOOM\\playwright-audit\\diagnostics',
      filename: 'audit.zip',
      size: 4096,
    },
  });
  await audit.registerCommand('open_path', { value: null });
  await navigateTo(audit, 'diagnostics');

  await appMain(page).getByRole('button', { name: '复制摘要' }).click();
  await expectToast(page, '诊断摘要已复制');
  await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toContain('环境诊断摘要');

  const detail = appMain(page).locator('details').first();
  await detail.locator('summary').click();
  await expect(detail).toHaveAttribute('open', '');

  const beforeRun = await markCalls(audit);
  await appMain(page).getByRole('button', { name: '重新诊断' }).click();
  await expectProxyIntent(audit, beforeRun, { method: 'GET', path: '/api/diagnostics/run', body: null });

  const beforeExport = await markCalls(audit);
  await appMain(page).getByRole('button', { name: '导出诊断包' }).click();
  await expectProxyIntent(audit, beforeExport, { method: 'POST', path: '/api/diagnostics/export', body: null });
  await expectToast(page, '诊断包已生成: audit.zip');

  const beforeOpen = await markCalls(audit);
  await appMain(page).getByRole('button', { name: '打开目录' }).click();
  await expectInvokeIntent(audit, beforeOpen, {
    command: 'open_path',
    args: { path: 'C:\\LOOM\\playwright-audit\\diagnostics' },
  });
  const exportedDetail = appMain(page).locator('details').filter({ hasText: 'audit.zip' });
  await exportedDetail.locator('summary').click();
  await expect(exportedDetail).toHaveAttribute('open', '');
});

test('diagnostics repair confirms destructive intent and never leaves the mock boundary', async ({ audit, page }) => {
  await audit.registerRoute('GET', '/api/diagnostics/run', { value: AUDIT_REPAIRABLE_DIAGNOSTICS });
  await audit.registerRoute('POST', '/api/diagnostics/repair', {
    value: {
      actions: [{ label: 'Audit repair', status: 'ok', message: 'Mock completed', count: 1 }],
      diagnostics: AUDIT_DIAGNOSTICS,
    },
  });
  await navigateTo(audit, 'diagnostics');
  const repair = appMain(page).getByRole('button', { name: '一键修复' });
  await expect(repair).toBeEnabled();
  const before = await markCalls(audit);
  await repair.click();
  await confirmDialog(page, '执行环境修复', '开始修复');
  await expectProxyIntent(audit, before, {
    method: 'POST',
    path: '/api/diagnostics/repair',
    body: { confirmed: true },
  });
  await expectToast(page, '一键修复已完成，可以重新检测运行状态');
});

test('terminal controls scroll, export, open, cancel, and clear an owned log buffer', async ({ audit, page }) => {
  await audit.registerCommand('export_log', {
    value: 'C:\\LOOM\\playwright-audit\\logs\\audit.log',
  });
  await audit.registerCommand('open_path', { value: null });
  await audit.registerRoute('GET', '/api/log/get?*', {
    value: { log: '', offset: 0, generation: 'e2e-empty-log', reset: false },
  });
  await audit.registerRoute('POST', '/api/log/clear', { value: { cleared: true } });
  await navigateTo(audit, 'terminal');

  const emptyExportBefore = await markCalls(audit);
  await appMain(page).getByRole('button', { name: '导出日志' }).click();
  await expectToast(page, '当前没有可导出的日志');
  await audit.sync();
  expect(audit.callLogs.slice(emptyExportBefore).some(({ command }) => command === 'export_log')).toBe(false);

  const logText = Array.from({ length: 120 }, (_, index) => `[Audit] deterministic line ${index}`).join('\n');
  await page.evaluate(async (value) => {
    const storePath = '/src/stores/logStore.ts';
    const { useLogStore } = await import(storePath) as {
      useLogStore: { getState: () => { replace: (next: string) => void } };
    };
    useLogStore.getState().replace(value);
  }, logText);

  await appMain(page).getByRole('button', { name: '全部日志' }).click();
  const logViewport = appMain(page).locator('[tabindex="0"]');
  await logViewport.evaluate((element) => { element.scrollTop = 0; });
  await appMain(page).getByRole('button', { name: '跳到底部' }).click();
  await expect.poll(() => logViewport.evaluate((element) => element.scrollTop)).toBeGreaterThan(0);

  await appMain(page).getByRole('button', { name: '错误与警告' }).click();
  await expect(appMain(page).getByText('当前没有错误或警告')).toBeVisible();
  await appMain(page).getByRole('button', { name: '全部日志' }).click();

  const beforeExport = await markCalls(audit);
  await appMain(page).getByRole('button', { name: '导出日志' }).click();
  await expectInvokeIntent(audit, beforeExport, {
    command: 'export_log',
    args: { content: logText },
  });
  await expectToast(page, /日志已导出/);

  const beforeOpen = await markCalls(audit);
  await appMain(page).getByRole('button', { name: '打开目录' }).click();
  await expectInvokeIntent(audit, beforeOpen, {
    command: 'open_path',
    args: { path: 'C:\\LOOM\\playwright-audit\\logs' },
  });

  await appMain(page).getByRole('button', { name: '清空' }).click();
  let dialog = page.getByRole('dialog', { name: '清空当前日志' });
  await dialog.getByRole('button', { name: '取消' }).last().click();
  await expect(dialog).toBeHidden();

  await appMain(page).getByRole('button', { name: '清空' }).click();
  dialog = page.getByRole('dialog', { name: '清空当前日志' });
  await dialog.getByRole('button', { name: '取消' }).last().click();
  await expect(dialog).toBeHidden();

  const beforeClear = await markCalls(audit);
  await appMain(page).getByRole('button', { name: '清空' }).click();
  await confirmDialog(page, '清空当前日志', '清空');
  await expectProxyIntent(audit, beforeClear, { method: 'POST', path: '/api/log/clear', body: null });
  await expect(appMain(page).getByText('暂无运行日志')).toBeVisible();
});
