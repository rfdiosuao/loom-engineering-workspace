import { expect, test } from './support/audit-fixture';
import {
  AUDIT_ACCOUNT_WITH_CHOICES,
  AUDIT_LOGGED_OUT_ACCOUNT,
  AUDIT_SUBSCRIPTION,
  componentSnapshot,
} from './support/control-audit-data';
import {
  appMain,
  callsAfter,
  confirmDialog,
  expectInvokeIntent,
  expectProxyIntent,
  expectToast,
  markCalls,
  navigateTo,
  proxyIntents,
} from './support/control-audit';

const AUDIT_WIRE = {
  ok: true,
  managedBy: 'heang_account',
  provider: 'audit',
  baseUrl: 'https://api.example.invalid/v1',
  models: {
    text: 'audit-text-model',
    phone: 'audit-text-model',
    image: 'audit-image-model',
    video: 'audit-video-model',
  },
  modelLists: {
    text: ['audit-text-model', 'audit-text-model-2'],
    phone: ['audit-text-model'],
    image: ['audit-image-model', 'audit-image-model-2'],
    video: ['audit-video-model', 'audit-video-model-2'],
  },
  targets: {},
  updatedAt: '2026-07-15T00:00:00.000Z',
};

test.beforeEach(async ({ audit }) => {
  await audit.openAuthorizedShell();
});

test('agent installer controls select, inspect, detect, and submit only mocked install intent', async ({ audit, page }) => {
  const notInstalled = componentSnapshot();
  const manualInstall = {
    ...notInstalled,
    components: notInstalled.components.map((component) => component.id === 'codex-desktop'
      ? { ...component, status: 'manual_install_required' }
      : component),
  };
  await audit.registerRoute('GET', '/api/components/status', { value: notInstalled });
  for (const componentId of ['claude-code', 'opencode', 'openclaw-companion']) {
    await audit.registerRoute('GET', `/api/components/model-config/status?componentId=${componentId}`, {
      value: {
        status: {
          componentId,
          supported: true,
          configured: false,
          installed: false,
          status: 'not_installed',
          message: 'Not installed in the isolated audit fixture',
          availableModels: [],
        },
      },
    });
  }
  await audit.registerRoute('POST', '/api/components/detect', { value: { catalog: notInstalled } });
  await audit.registerRoute('POST', '/api/components/install', { value: { catalog: manualInstall } });
  await navigateTo(audit, 'agents');

  const main = appMain(page);
  await expect(main.getByRole('heading', { name: '安装智能体' })).toBeVisible();

  const beforeRefresh = await markCalls(audit);
  await main.getByRole('button', { name: '刷新', exact: true }).click();
  await expectProxyIntent(audit, beforeRefresh, { method: 'GET', path: '/api/components/status', body: null });

  await expect(main.getByRole('button', { name: '一键安装' })).toHaveCount(0);
  await expect(main.getByRole('button', { name: '复制接入提示词' })).toHaveCount(0);
  await expect(main.getByText('前置环境已就绪')).toHaveCount(0);

  const agents = [
    ['ChatGPT Codex 原版', /^1\s.*ChatGPT Codex 原版/],
    ['Claude Code', /^2\s.*Claude Code/],
    ['opencode', /^3\s.*opencode/],
    ['OpenClaw', /^4\s.*OpenClaw/],
    ['Hermes', /^5\s.*Hermes/],
  ] as const;
  for (const [heading, buttonName] of agents) {
    await main.getByRole('button', { name: buttonName }).click();
    await expect(main.getByRole('heading', { name: heading, exact: true })).toBeVisible();
  }
  await main.getByRole('button', { name: /^1\s.*ChatGPT Codex 原版/ }).click();

  await main.getByRole('button', { name: 'OpenAI 官方', exact: true }).click();
  await expect(main.getByRole('button', { name: '恢复 OpenAI 官方渠道' })).toBeVisible();
  await main.getByRole('button', { name: '自定义', exact: true }).click();
  await expect(main.locator('[data-agent-custom-provider-card]')).toBeVisible();

  const oneClickModel = main.locator('[data-agent-one-click-config-lock]');
  await expect(oneClickModel).toBeDisabled();
  await expect(oneClickModel).toHaveAttribute('title', '登录后解锁：请先同步托管模型');

  const beforeDetect = await markCalls(audit);
  await main.getByRole('button', { name: '重新检测' }).last().click();
  await expectProxyIntent(audit, beforeDetect, {
    method: 'POST', path: '/api/components/detect', body: { componentId: 'codex-desktop' },
  });
  await expectToast(page, 'ChatGPT Codex 原版 检测完成');

  const beforeInstall = await markCalls(audit);
  await main.getByRole('button', { name: '安装原版' }).click();
  await confirmDialog(page, '安装 ChatGPT Codex 原版', '安装原版');
  await expectProxyIntent(audit, beforeInstall, {
    method: 'POST', path: '/api/components/detect', body: { componentId: 'codex-desktop' },
  });
  await expectProxyIntent(audit, beforeInstall, {
    method: 'POST', path: '/api/components/install', body: { componentId: 'codex-desktop', confirmed: true },
  });
  await expectToast(page, /等待 Microsoft Store/);

  await expect(main.locator('summary').filter({ hasText: '检测耗时' })).toHaveCount(0);
  for (const summary of ['安装日志', '高级详情']) {
    await main.locator('summary').filter({ hasText: summary }).click();
  }
});

test('agent detection failures stop before any install request', async ({ audit, page }) => {
  const notInstalled = componentSnapshot();
  await audit.registerRoute('GET', '/api/components/status', { value: notInstalled });
  await audit.registerRoute('POST', '/api/components/detect', { error: 'isolated detect unavailable' });
  await navigateTo(audit, 'agents');

  const main = appMain(page);
  const beforeInstall = await markCalls(audit);
  await main.getByRole('button', { name: '安装原版' }).click();
  await confirmDialog(page, '安装 ChatGPT Codex 原版', '安装原版');
  await expectProxyIntent(audit, beforeInstall, {
    method: 'POST', path: '/api/components/detect', body: { componentId: 'codex-desktop' },
  });
  await expectToast(page, /isolated detect unavailable|检测失败/);
  await audit.sync();
  expect(proxyIntents(callsAfter(audit, beforeInstall)))
    .not.toContainEqual(expect.objectContaining({ method: 'POST', path: '/api/components/install' }));
});

test('model controls refresh, select, sync, roll back, and apply custom provider through strict routes', async ({ audit, page }) => {
  await audit.registerRoute('GET', '/api/account/current', { value: { account: AUDIT_ACCOUNT_WITH_CHOICES } });
  await audit.registerRoute('GET', '/api/wire/current', { value: { wire: AUDIT_WIRE } });
  await audit.registerRoute('POST', '/api/wire/rollback', { value: { wire: AUDIT_WIRE, syncResults: [] } });
  await audit.registerRoute('POST', '/api/account/models/select', {
    value: { account: AUDIT_ACCOUNT_WITH_CHOICES, syncResults: [] },
  });
  await audit.registerRoute('POST', '/api/account/sync', {
    value: { account: AUDIT_ACCOUNT_WITH_CHOICES, syncResults: [] },
  });
  await audit.registerRoute('POST', '/api/wire/custom', {
    value: {
      wire: {
        ...AUDIT_WIRE,
        managedBy: 'custom',
        provider: 'Audit Provider',
        baseUrl: 'https://models.example.invalid/v1',
        models: {
          text: 'audit-custom-text',
          phone: 'audit-custom-phone',
          image: 'audit-custom-image',
          video: 'audit-custom-video',
        },
      },
      syncResults: [],
    },
  });
  await navigateTo(audit, 'models');
  const main = appMain(page);
  await expect(main.getByRole('heading', { name: '模型选择' })).toBeVisible();

  const beforeRefresh = await markCalls(audit);
  await main.getByRole('button', { name: '刷新', exact: true }).click();
  await expectProxyIntent(audit, beforeRefresh, { method: 'GET', path: '/api/account/current', body: null });
  await expectProxyIntent(audit, beforeRefresh, { method: 'GET', path: '/api/wire/current', body: null });

  const beforeRollback = await markCalls(audit);
  await main.getByRole('button', { name: '关闭', exact: true }).click();
  await confirmDialog(page, '关闭 LOOM 模型来源', '关闭并回滚');
  await expectProxyIntent(audit, beforeRollback, { method: 'POST', path: '/api/wire/rollback', body: null });
  await expectToast(page, /模型来源已关闭/);

  await main.getByRole('button', { name: '一键配置', exact: true }).click();
  await main.getByRole('combobox', { name: '默认文本模型' }).selectOption('audit-text-model-2');
  await main.getByRole('combobox', { name: '默认图像模型' }).selectOption('audit-image-model-2');
  await main.getByRole('combobox', { name: '视频模型草案' }).selectOption('audit-video-model-2');
  const beforeSave = await markCalls(audit);
  await main.getByRole('button', { name: '保存选择' }).click();
  await expectProxyIntent(audit, beforeSave, {
    method: 'POST',
    path: '/api/account/models/select',
    body: {
      textModel: 'audit-text-model-2',
      imageModel: 'audit-image-model-2',
      videoModel: 'audit-video-model-2',
    },
  });
  await expectToast(page, '模型选择已保存');

  const beforeSync = await markCalls(audit);
  await main.getByRole('button', { name: '同步模型' }).click();
  await expectProxyIntent(audit, beforeSync, { method: 'POST', path: '/api/account/sync', body: null });
  await expectToast(page, '模型已同步');

  await main.getByRole('button', { name: '自定义', exact: true }).click();
  await main.locator('[data-model-custom-provider-select]').selectOption('custom');
  await main.getByRole('textbox', { name: '默认文本模型' }).fill('audit-custom-text');
  await main.getByRole('textbox', { name: 'Provider 名称' }).fill('Audit Provider');
  await main.getByRole('textbox', { name: '自定义 URL' }).fill('https://models.example.invalid/v1');
  await main.getByLabel('API Key').fill('audit-key-never-sent');
  await main.getByRole('textbox', { name: '图像模型' }).fill('audit-custom-image');
  await main.getByRole('textbox', { name: '手机模型' }).fill('audit-custom-phone');
  await main.getByRole('textbox', { name: '视频模型草案' }).fill('audit-custom-video');
  const beforeCustom = await markCalls(audit);
  await main.getByRole('button', { name: '应用第三方配置' }).click();
  await expectProxyIntent(audit, beforeCustom, {
    method: 'POST',
    path: '/api/wire/custom',
    body: {
      provider: 'Audit Provider',
      baseUrl: 'https://models.example.invalid/v1',
      apiKey: 'audit-key-never-sent',
      textModel: 'audit-custom-text',
      imageModel: 'audit-custom-image',
      phoneModel: 'audit-custom-phone',
      videoModel: 'audit-custom-video',
    },
  });
  await expectToast(page, '第三方模型配置已应用');
});

test('startup splash plays the packaged brand video and exits cleanly', async ({ audit, page }, testInfo) => {
  await audit.openAuthorizedShell();
  const splash = page.locator('[data-loom-splash]');
  const video = splash.locator('[data-loom-splash-video]');
  await expect(splash).toBeVisible();
  await expect(video).toHaveAttribute('src', '/loom-motion/luming-splash-v2.mp4');
  await expect(video).toHaveAttribute('poster', '/loom-motion/luming-splash-v2-poster.jpg');
  await expect(splash.locator('iframe')).toHaveCount(0);
  await expect.poll(() => video.evaluate((element) => (element as HTMLVideoElement).currentTime)).toBeGreaterThan(0);
  await page.screenshot({ path: testInfo.outputPath('loom-splash-video.png'), fullPage: false });
  await expect(splash).toBeHidden({ timeout: 7_000 });
});

test('web registration opener failures stay visible in the logged-out account page', async ({ audit, page }, testInfo) => {
  await audit.registerRoute('GET', '/api/account/current', { value: { account: AUDIT_LOGGED_OUT_ACCOUNT } });
  await audit.registerRoute('GET', '/api/account/capabilities', {
    value: {
      capabilities: {
        passwordLogin: true,
        inlineEmailCode: false,
        inlineRegistration: false,
        webRegistrationRequired: true,
        registrationUrl: 'https://account.example.invalid/register',
        emailVerificationEnabled: false,
        turnstileRequired: false,
        emailConfigured: false,
        emailReason: '请使用网页注册',
      },
    },
  });
  await audit.registerCommand('plugin:shell|open', { error: 'isolated shell open denied' });
  await navigateTo(audit, 'license');
  await expect(page.locator('[data-loom-splash]')).toBeHidden({ timeout: 7_000 });

  const main = appMain(page);
  const loginLogo = main.locator('[data-loom-logo] img').first();
  await expect(loginLogo).toBeVisible();
  await expect
    .poll(() =>
      loginLogo.evaluate(
        (image) => image instanceof HTMLImageElement && image.complete && image.naturalWidth > 0,
      ),
    )
    .toBe(true);
  await expect(main.getByRole('button', { name: '验证码登录' })).toBeVisible();
  await expect(main.getByRole('button', { name: '密码登录' })).toBeVisible();
  await expect(main.getByRole('button', { name: '邮箱注册' })).toHaveCount(0);
  await page.screenshot({ path: testInfo.outputPath('loom-account-login.png'), fullPage: false });
  await main.getByRole('button', { name: '还没有账户？网页注册' }).click();
  await expectToast(page, /网页注册打开失败.*isolated shell open denied/);
});

test('account and subscription controls refresh, navigate, sync, open mocked payment URLs, and log out', async ({ audit, page }) => {
  const subscriptionUrl = AUDIT_SUBSCRIPTION.purchaseUrl;
  await audit.registerRoute('GET', '/api/account/current', { value: { account: AUDIT_ACCOUNT_WITH_CHOICES } });
  await audit.registerRoute('GET', '/api/account/subscription', { value: { subscription: AUDIT_SUBSCRIPTION } });
  await audit.registerRoute('POST', '/api/account/sync', {
    value: { account: AUDIT_ACCOUNT_WITH_CHOICES, syncResults: [] },
  });
  await audit.registerRoute('POST', '/api/account/logout', {
    value: { account: AUDIT_LOGGED_OUT_ACCOUNT, loggedOut: true },
  });
  await audit.registerCommand('plugin:shell|open', { value: null });
  await navigateTo(audit, 'license');
  const main = appMain(page);
  const accountLogo = main.locator('[data-loom-logo] img').first();
  await expect(accountLogo).toBeVisible();
  await expect
    .poll(() =>
      accountLogo.evaluate(
        (image) => image instanceof HTMLImageElement && image.complete && image.naturalWidth > 0,
      ),
    )
    .toBe(true);
  await expect(main.getByRole('heading', { name: '账户与用量' })).toBeVisible();

  const beforeRefresh = await markCalls(audit);
  await main.getByRole('button', { name: '刷新账号' }).click();
  await expectProxyIntent(audit, beforeRefresh, { method: 'GET', path: '/api/account/current', body: null });

  const beforeSync = await markCalls(audit);
  await main.getByRole('button', { name: '同步模型' }).click();
  await expectProxyIntent(audit, beforeSync, { method: 'POST', path: '/api/account/sync', body: null });
  await expectToast(page, '模型已同步');

  await expect(main.getByRole('button', { name: '刷新订阅', exact: true })).toHaveCount(0);
  await expect(main.getByRole('button', { name: '刷新订阅信息', exact: true })).toHaveCount(0);
  const beforeBalanceRefresh = await markCalls(audit);
  await main.getByRole('button', { name: '刷新余额', exact: true }).click();
  await expectProxyIntent(audit, beforeBalanceRefresh, {
    method: 'GET', path: '/api/account/subscription', body: null,
  });
  await expectToast(page, '订阅信息已更新');

  await expect(main.getByRole('button', { name: '打开订阅页', exact: true })).toHaveCount(0);
  await expect(main.getByRole('button', { name: '微信开通 VIP', exact: true })).toHaveCount(0);
  const beforeOpenAccount = await markCalls(audit);
  await main.getByRole('button', { name: '打开账户中心', exact: true }).click();
  await expectInvokeIntent(audit, beforeOpenAccount, {
    command: 'plugin:shell|open',
    args: { path: subscriptionUrl },
  });
  await expectToast(page, '订阅页已在浏览器打开');

  await main.getByRole('button', { name: '模型选择' }).click();
  await expect(appMain(page).getByRole('heading', { name: '模型选择' })).toBeVisible();
  await navigateTo(audit, 'license');

  const beforeLogout = await markCalls(audit);
  await appMain(page).getByRole('button', { name: '退出登录' }).click();
  await expectProxyIntent(audit, beforeLogout, { method: 'POST', path: '/api/account/logout', body: null });
  await expectToast(page, '已退出模型账号');
  await expect(appMain(page).getByRole('heading', { name: '登录模型账户' })).toBeVisible();
});
