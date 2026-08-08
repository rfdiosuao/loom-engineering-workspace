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
  for (const componentId of ['claude-code', 'opencode', 'openclaw-companion', 'grok-build', 'pi']) {
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
    ['codex-desktop', 'Codex Desktop'],
    ['codex-cli', 'Codex CLI'],
    ['claude-code', 'Claude Code'],
    ['opencode', 'opencode'],
    ['openclaw-companion', 'OpenClaw'],
    ['hermes', 'Hermes'],
    ['grok-build', 'Grok Build'],
    ['pi', 'Pi'],
    ['goose', 'Goose'],
    ['gemini-cli', 'Gemini CLI'],
  ] as const;
  for (const [componentId, heading] of agents) {
    await main.locator(`[data-agent-component-id="${componentId}"]`).click();
    await expect(main.getByRole('heading', { name: heading, exact: true })).toBeVisible();
  }
  await main.locator('[data-agent-component-id="codex-desktop"]').click();

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
  await expectToast(page, 'Codex Desktop 检测完成');

  const beforeInstall = await markCalls(audit);
  await main.getByRole('button', { name: '安装原版' }).click();
  await confirmDialog(page, '安装 Codex Desktop', '安装原版');
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
  await confirmDialog(page, '安装 Codex Desktop', '安装原版');
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
  await expect(main.locator('[data-account-avatar]')).toBeVisible();
  await expect(main.locator('[data-loom-logo]')).toHaveCount(0);
  await expect(main.getByRole('heading', { name: '账户与用量' })).toBeVisible();

  const beforeRefresh = await markCalls(audit);
  await main.getByRole('button', { name: '刷新账号' }).click();
  await expectProxyIntent(audit, beforeRefresh, { method: 'POST', path: '/api/account/sync', body: null });

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
  await expectToast(page, '余额与套餐已更新');

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

test('native model subscription checkout renders qrcode and never grants matrix rights', async ({ audit, page }) => {
  const paymentPlan = {
    planKey: 'newapi-plan-basic-audit',
    displayName: '基础模型订阅',
    description: '服务端原生模型套餐',
    durationDays: 30,
    amountMinor: 5000,
    amount: '50.00',
    currency: 'CNY',
    sourceCurrency: 'USD',
    pricingRule: 'nominal_1_to_1',
    benefits: ['模型调用额度', '服务端原生订阅'],
  };
  const alternatePlan = {
    ...paymentPlan,
    planKey: 'newapi-plan-pro-audit',
    displayName: '专业模型订阅',
    amountMinor: 10000,
    amount: '100.00',
  };
  const pendingOrder = {
    orderId: 'pay_order_audit_001',
    outTradeNo: 'LM20260802AUDIT001',
    planKey: paymentPlan.planKey,
    displayName: paymentPlan.displayName,
    paymentType: 'alipay',
    amountMinor: paymentPlan.amountMinor,
    amount: paymentPlan.amount,
    currency: paymentPlan.currency,
    status: 'pending',
    providerOrderReference: 'provider_create_reference_only',
    qrcode: 'https://qr.example.invalid/opaque-token-for-qr-only',
    payUrl: 'https://pay.example.invalid/submit/pay_order_audit_001',
    expiresAt: '2099-12-31T23:59:59.000Z',
  };
  const paidOrder = {
    ...pendingOrder,
    status: 'paid',
    paidAt: '2026-08-02T08:00:00.000Z',
  };

  await audit.registerRoute('GET', '/api/account/current', { value: { account: AUDIT_ACCOUNT_WITH_CHOICES } });
  await audit.registerRoute('GET', '/api/account/subscription', { value: { subscription: AUDIT_SUBSCRIPTION } });
  await audit.registerRoute('GET', '/api/account/payments/plans', {
    value: {
      plans: [paymentPlan, alternatePlan],
      payment: { provider: 'newapi-epay', configured: true, channels: ['alipay', 'wxpay'] },
    },
  });
  await audit.registerRoute('POST', '/api/account/payments/order', { delayMs: 500, value: { order: pendingOrder } });
  await audit.registerRoute('POST', '/api/account/payments/order/status', { value: { order: pendingOrder } });
  await audit.registerCommand('plugin:shell|open', { value: null });
  await navigateTo(audit, 'license');

  const main = appMain(page);
  await expect(main.locator('[data-native-payment-catalog]')).toBeVisible();
  await expect(main.getByText(paymentPlan.displayName, { exact: true })).toBeVisible();
  await expect(main.getByText(alternatePlan.displayName, { exact: true })).toBeVisible();
  await expect(main.getByText('直接购买服务端原生订阅；服务端 USD 数值按 1:1 显示为人民币，不做汇率换算。矩阵授权仍独立管理。')).toBeVisible();
  await expect(main.getByText('¥50.00', { exact: true })).toBeVisible();

  const beforeCreate = await markCalls(audit);
  const selectedPlanCard = main.locator('article').filter({ hasText: paymentPlan.displayName });
  const alternatePlanCard = main.locator('article').filter({ hasText: alternatePlan.displayName });
  await selectedPlanCard.getByRole('button', { name: '支付宝扫码购买' }).click();
  await expect(selectedPlanCard.getByRole('button', { name: '正在创建订单...' })).toBeVisible();
  await expect(alternatePlanCard.getByRole('button', { name: '支付宝扫码购买' })).toBeVisible();
  await expectToast(page, '订单已创建，请使用手机扫码支付。');
  await expect(main.getByText(`订单号：${pendingOrder.orderId}`, { exact: true })).toBeVisible();
  const qrImage = main.getByRole('img', { name: '麓鸣套餐支付二维码' });
  await expect(qrImage).toBeVisible();
  await expect(qrImage).toHaveAttribute('src', /^data:image\/gif;base64,/);

  await expect.poll(async () => {
    await audit.sync();
    return proxyIntents(callsAfter(audit, beforeCreate))
      .filter(({ method, path }) => method === 'POST' && path === '/api/account/payments/order');
  }).toHaveLength(1);
  await audit.sync();
  const createIntent = proxyIntents(callsAfter(audit, beforeCreate))
    .find(({ method, path }) => method === 'POST' && path === '/api/account/payments/order');
  expect(createIntent?.body).toMatchObject({
    planKey: paymentPlan.planKey,
    paymentType: 'alipay',
  });
  expect(String((createIntent?.body as Record<string, unknown>)?.requestId || ''))
    .toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i);

  const beforeOpen = await markCalls(audit);
  await main.getByRole('button', { name: '打开直达支付' }).click();
  await expectInvokeIntent(audit, beforeOpen, {
    command: 'plugin:shell|open',
    args: { path: pendingOrder.payUrl },
  });

  const beforePendingQuery = await markCalls(audit);
  await main.getByRole('button', { name: '我已付款，查询状态' }).click();
  await expectProxyIntent(audit, beforePendingQuery, {
    method: 'POST', path: '/api/account/payments/order/status', body: { orderId: pendingOrder.orderId, reconcile: true },
  });
  await expectToast(page, '等待扫码支付');
  await audit.sync();
  expect(proxyIntents(callsAfter(audit, beforePendingQuery)))
    .not.toContainEqual(expect.objectContaining({ path: '/api/license/authorized' }));

  await audit.registerRoute('POST', '/api/account/payments/order/status', {
    delayMs: 500,
    value: {
      order: paidOrder,
      account: AUDIT_ACCOUNT_WITH_CHOICES,
      subscriptionSyncPending: false,
    },
  });
  const beforePaidQuery = await markCalls(audit);
  await main.getByRole('button', { name: '我已付款，查询状态' }).click();
  await expect(main.getByRole('button', { name: '查询中...' })).toBeVisible();
  await expect(selectedPlanCard.getByRole('button', { name: '支付宝扫码购买' })).toBeVisible();
  await expect(alternatePlanCard.getByRole('button', { name: '支付宝扫码购买' })).toBeVisible();
  await expectProxyIntent(audit, beforePaidQuery, {
    method: 'POST', path: '/api/account/payments/order/status', body: { orderId: paidOrder.orderId, reconcile: true },
  });
  await expectToast(page, '支付已确认，模型订阅已同步。');
  await expect(main.getByText('支付成功，模型订阅已同步', { exact: true })).toBeVisible();
  await audit.sync();
  expect(proxyIntents(callsAfter(audit, beforePaidQuery)))
    .not.toContainEqual(expect.objectContaining({ path: '/api/license/authorized' }));
});

test('checkout reuses the same idempotency key after an uncertain create result', async ({ audit, page }) => {
  const plan = {
    planKey: 'matrix-retry-audit', displayName: '矩阵恢复测试套餐', description: '',
    durationDays: 31, amountMinor: 9900, amount: '99.00', currency: 'CNY', benefits: [],
  };
  const order = {
    orderId: 'pay_retry_audit_001', outTradeNo: 'LMRETRYAUDIT001', planKey: plan.planKey,
    displayName: plan.displayName, paymentType: 'alipay', amountMinor: plan.amountMinor,
    amount: plan.amount, currency: plan.currency, status: 'pending',
    providerOrderReference: 'provider-retry-reference', qrcode: 'retry-qr-content',
    payUrl: '', expiresAt: '2099-12-31T23:59:59.000Z',
  };
  await audit.registerRoute('GET', '/api/account/current', { value: { account: AUDIT_ACCOUNT_WITH_CHOICES } });
  await audit.registerRoute('GET', '/api/account/subscription', { value: { subscription: AUDIT_SUBSCRIPTION } });
  await audit.registerRoute('GET', '/api/account/payments/plans', {
    value: { plans: [plan], payment: { provider: 'zpay', configured: true, channels: ['alipay'] } },
  });
  await audit.registerRoute('POST', '/api/account/payments/order', {
    error: 'HTTP_503: 支付订单创建结果待确认',
  });
  await audit.registerRoute('POST', '/api/account/payments/order/status', { value: { order } });
  await navigateTo(audit, 'license');
  const main = appMain(page);
  const beforeCreate = await markCalls(audit);

  await main.getByRole('button', { name: '支付宝扫码购买' }).click();
  await expectToast(page, /支付订单创建结果待确认/);
  await audit.registerRoute('POST', '/api/account/payments/order', { value: { order } });
  await main.getByRole('button', { name: '支付宝扫码购买' }).click();
  await expect(main.getByText(`订单号：${order.orderId}`, { exact: true })).toBeVisible();

  await expect.poll(async () => {
    await audit.sync();
    return proxyIntents(callsAfter(audit, beforeCreate))
      .filter(({ method, path }) => method === 'POST' && path === '/api/account/payments/order');
  }).toHaveLength(2);
  await audit.sync();
  const attempts = proxyIntents(callsAfter(audit, beforeCreate))
    .filter(({ method, path }) => method === 'POST' && path === '/api/account/payments/order');
  expect((attempts[0]?.body as Record<string, unknown>)?.requestId).toBe(
    (attempts[1]?.body as Record<string, unknown>)?.requestId,
  );
});

test('checkout restores a pending order after application reload without creating another order', async ({ audit, page }) => {
  const plan = {
    planKey: 'matrix-reload-audit', displayName: '矩阵重启恢复套餐', description: '',
    durationDays: 31, amountMinor: 9900, amount: '99.00', currency: 'CNY', benefits: [],
  };
  const order = {
    orderId: 'pay_reload_audit_001', outTradeNo: 'LMRELOADAUDIT001', planKey: plan.planKey,
    displayName: plan.displayName, paymentType: 'alipay', amountMinor: plan.amountMinor,
    amount: plan.amount, currency: plan.currency, status: 'pending',
    providerOrderReference: 'provider-reload-reference', qrcode: 'reload-qr-content',
    payUrl: '', expiresAt: '2099-12-31T23:59:59.000Z',
  };
  await audit.registerRoute('GET', '/api/account/current', { value: { account: AUDIT_ACCOUNT_WITH_CHOICES } });
  await audit.registerRoute('GET', '/api/account/subscription', { value: { subscription: AUDIT_SUBSCRIPTION } });
  await audit.registerRoute('GET', '/api/account/payments/plans', {
    value: { plans: [plan], payment: { provider: 'zpay', configured: true, channels: ['alipay'] } },
  });
  await audit.registerRoute('POST', '/api/account/payments/order', { value: { order } });
  await audit.registerRoute('POST', '/api/account/payments/order/status', { value: { order } });
  await navigateTo(audit, 'license');
  const main = appMain(page);
  const beforeCreate = await markCalls(audit);
  await main.getByRole('button', { name: '支付宝扫码购买' }).click();
  await expect(main.getByText(`订单号：${order.orderId}`, { exact: true })).toBeVisible();
  await audit.sync();
  expect(
    proxyIntents(callsAfter(audit, beforeCreate))
      .filter(({ method, path }) => method === 'POST' && path === '/api/account/payments/order'),
  ).toHaveLength(1);

  await page.addInitScript(({ restoredAccount, restoredSubscription, restoredPlan, restoredOrder }) => {
    const registerAfterAuditBoot = () => {
      if (!window.__TAURI_AUDIT__) {
        window.setTimeout(registerAfterAuditBoot, 0);
        return;
      }
      window.__TAURI_AUDIT__.registerRoute('GET /api/account/current', {
        value: { account: restoredAccount },
      });
      window.__TAURI_AUDIT__.registerRoute('GET /api/account/subscription', {
        value: { subscription: restoredSubscription },
      });
      window.__TAURI_AUDIT__.registerRoute('GET /api/account/payments/plans', {
        value: {
          plans: [restoredPlan],
          payment: { provider: 'zpay', configured: true, channels: ['alipay'] },
        },
      });
      window.__TAURI_AUDIT__.registerRoute('POST /api/account/payments/order/status', {
        value: { order: restoredOrder },
      });
    };
    registerAfterAuditBoot();
  }, {
    restoredAccount: AUDIT_ACCOUNT_WITH_CHOICES,
    restoredSubscription: AUDIT_SUBSCRIPTION,
    restoredPlan: plan,
    restoredOrder: order,
  });
  await page.reload();
  await expect(page.locator('[data-commercial-app-shell]')).toBeVisible({ timeout: 15_000 });
  await audit.navigateTo({ key: 'license', readySelector: '[data-account-subscription-page]' });
  await expect(appMain(page).getByText(`订单号：${order.orderId}`, { exact: true })).toBeVisible();
  await audit.sync();
  const restoredStatusCalls = proxyIntents(audit.callLogs)
    .filter(({ method, path }) => method === 'POST' && path === '/api/account/payments/order/status');
  expect(restoredStatusCalls.length).toBeGreaterThan(0);
  expect(restoredStatusCalls.every(({ body }) => (
    body as Record<string, unknown>
  )?.reconcile === false)).toBe(true);
  const createCalls = proxyIntents(audit.callLogs)
    .filter(({ method, path }) => method === 'POST' && path === '/api/account/payments/order');
  expect(createCalls).toHaveLength(0);
});

test('account service outage marks cached values as read-only and localizes the default plan', async ({ audit, page }, testInfo) => {
  const paymentPlan = {
    planKey: 'newapi-plan-cache-recovery',
    displayName: '基础模型订阅',
    description: '服务端在线支付套餐',
    durationDays: 30,
    amountMinor: 5000,
    amount: '50.00',
    currency: 'CNY',
  };
  const cachedAccount = {
    ...AUDIT_ACCOUNT_WITH_CHOICES,
    plan: 'default',
    offline: true,
    stale: true,
    subscription: {
      ...AUDIT_SUBSCRIPTION,
      plan: 'default',
      inviteCode: '',
      invitationCode: '',
      referralCode: '',
      offline: true,
      stale: true,
    },
  };
  await page.evaluate((account) => {
    window.localStorage.setItem('loom.startup.account.v1', JSON.stringify({
      schema: 'loom.startup-cache.v1',
      savedAt: Date.now(),
      data: account,
    }));
  }, cachedAccount);
  await audit.registerRoute('POST', '/api/account/sync', {
    error: 'HTTP_404: model account resource not found',
  });
  await audit.registerRoute('GET', '/api/account/subscription', {
    value: { subscription: AUDIT_SUBSCRIPTION },
  });
  await audit.registerRoute('GET', '/api/account/payments/plans', {
    value: {
      plans: [paymentPlan],
      payment: { provider: 'newapi-epay', configured: true, channels: ['alipay'] },
    },
  });
  await expect(page.locator('[data-loom-splash]')).toBeHidden({ timeout: 12_000 });

  await navigateTo(audit, 'license');
  const main = appMain(page);
  const warning = main.locator('[data-account-cache-warning]');
  await expect(warning).toBeVisible();
  await expect(warning).toContainText('当前显示上次安全快照');
  await expect(main.getByText('基础套餐', { exact: true })).toBeVisible();
  await expect(main.getByText('default', { exact: true })).toHaveCount(0);
  await expect(main.getByText('服务暂未返回', { exact: true })).toBeVisible();
  await expect(main.getByRole('button', { name: '同步模型' })).toBeDisabled();
  await expect(main.getByRole('button', { name: '绑定当前账号' })).toBeDisabled();
  await expect(main.getByRole('button', { name: '重试在线验证' }).first()).toBeVisible();
  await expect(main.getByText(paymentPlan.displayName, { exact: true })).toBeVisible();
  await expect(main.getByRole('button', { name: '支付宝扫码购买' })).toBeEnabled();
  await page.screenshot({ path: testInfo.outputPath('account-safe-cache-outage.png'), fullPage: false });
});

test('startup discards a cached login when the local account session is gone', async ({ audit, page }) => {
  await page.evaluate((account) => {
    window.localStorage.setItem('loom.startup.account.v1', JSON.stringify({
      schema: 'loom.startup-cache.v1',
      savedAt: Date.now(),
      data: account,
    }));
  }, AUDIT_ACCOUNT_WITH_CHOICES);
  await audit.registerRoute('GET', '/api/account/current', {
    value: { account: AUDIT_LOGGED_OUT_ACCOUNT },
  });
  await audit.registerRoute('POST', '/api/account/sync', {
    error: '尚未登录模型账号',
  });
  await audit.registerRoute('GET', '/api/account/payments/plans', {
    error: '尚未登录模型账号',
  });
  await expect(page.locator('[data-loom-splash]')).toBeHidden({ timeout: 12_000 });

  await navigateTo(audit, 'license');
  const main = appMain(page);
  await expect(main.getByRole('heading', { name: '登录模型账户' })).toBeVisible();
  await expect(main.locator('[data-account-cache-warning]')).toHaveCount(0);
  await expect(main.getByText('基础套餐', { exact: true })).toHaveCount(0);
  await audit.sync();
  const accountCalls = proxyIntents(audit.callLogs)
    .filter(({ path }) => path.startsWith('/api/account/'));
  expect(accountCalls).toContainEqual(expect.objectContaining({
    method: 'GET', path: '/api/account/current',
  }));
  expect(accountCalls).not.toContainEqual(expect.objectContaining({
    method: 'POST', path: '/api/account/sync',
  }));
});

test('payment catalog shows the server readiness reason instead of a generic blocker', async ({ audit, page }) => {
  await audit.registerRoute('GET', '/api/account/payments/plans', {
    value: {
      plans: [],
      payment: {
        provider: 'zpay',
        configured: false,
        reconciliationConfigured: false,
        channels: [],
        reasonCode: 'online_topup_disabled',
        message: '服务端在线充值尚未启用。',
      },
    },
  });
  await navigateTo(audit, 'license');
  await expect(appMain(page).getByText('服务端在线充值尚未启用。', { exact: true })).toBeVisible();
});

test('payment catalog shows the request error instead of claiming that purchasing is closed', async ({ audit, page }) => {
  await audit.registerRoute('GET', '/api/account/payments/plans', {
    error: '尚未登录模型账号',
  });

  await navigateTo(audit, 'license');
  const main = appMain(page);
  await expect(main.getByText('尚未登录模型账号', { exact: true })).toBeVisible();
  await expect(main.getByText('服务端暂未开放可购买订阅，或支付配置尚未通过安全检查。', { exact: true }))
    .toHaveCount(0);
});
