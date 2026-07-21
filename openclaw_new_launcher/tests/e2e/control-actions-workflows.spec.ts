import { expect, test, type AuditHarness } from './support/audit-fixture';
import {
  appMain,
  completedJob,
  confirmDialog,
  expectProxyIntent,
  expectToast,
  markCalls,
  navigateTo,
  proxyIntents,
} from './support/control-audit';
import {
  AUDIT_FEISHU_STATUS,
  AUDIT_MATRIX_WITH_DEVICE,
  AUDIT_PHONE_CONFIG,
} from './support/control-audit-data';

const MEDIA_CONFIG = {
  image: {
    baseUrl: 'https://api.heang.top/v1',
    model: 'audit-image-model',
    size: '1024x1024',
    count: 1,
    hasApiKey: false,
    updatedAt: '2026-07-15T00:00:00.000Z',
  },
  video: {
    providerId: 'custom',
    apiBase: '',
    model: 'audit-video-model',
    mode: 't2v',
    resolution: '720P',
    duration: 5,
    ratio: '16:9',
    hasApiKey: false,
    updatedAt: '2026-07-15T00:00:00.000Z',
  },
};

test.beforeEach(async ({ audit }) => {
  await audit.openAuthorizedShell();
});

test('creative image controls edit, test, save, submit, poll, and refresh through strict mocks', async ({ audit, page }) => {
  const imageJob = completedJob('image-audit-job', { images: [], files: [], count: 0 });
  const imageConfig = {
    ...MEDIA_CONFIG,
    image: {
      ...MEDIA_CONFIG.image,
      baseUrl: 'https://image.example.invalid/v1',
      model: 'audit-image-model-2',
      size: '1536x1152',
      count: 2,
      hasApiKey: true,
    },
  };
  await audit.registerRoute('POST', '/api/media/test', {
    value: { ok: true, message: '图片配置审计通过', config: imageConfig },
  });
  await audit.registerRoute('POST', '/api/media/config', { value: { config: imageConfig } });
  await audit.registerRoute('POST', '/api/image/generate/submit', {
    value: { jobId: imageJob.id, job: imageJob },
  });
  await audit.registerRoute('GET', `/api/jobs/${imageJob.id}`, { value: { job: imageJob } });
  await navigateTo(audit, 'creative');

  const details = appMain(page).locator('[data-creative-config-details]');
  await expect(details).not.toHaveAttribute('open', '');
  await details.locator('summary').click();
  await expect(details).toHaveAttribute('open', '');

  await details.getByLabel('Base URL').fill('https://image.example.invalid/v1');
  await details.getByLabel('API Key').fill('audit-image-key');
  await details.getByLabel('模型').fill('audit-image-model-2');
  await details.getByLabel('数量').fill('2');
  await appMain(page).locator('[data-creative-mode-i2i]').click();
  await expect(appMain(page).getByRole('button', { name: '上传图片' })).toBeVisible();
  await appMain(page).locator('[data-creative-mode-t2i]').click();
  const imageRatio = appMain(page).getByRole('button', { name: '4:3', exact: true });
  await imageRatio.click();
  await expect(imageRatio).toHaveAttribute('aria-pressed', 'true');

  const beforeTest = await markCalls(audit);
  await details.getByRole('button', { name: '测试配置' }).click();
  await expectProxyIntent(audit, beforeTest, {
    method: 'POST',
    path: '/api/media/test',
    body: {
      kind: 'image',
      image: {
        baseUrl: 'https://image.example.invalid/v1',
        apiKey: 'audit-image-key',
        model: 'audit-image-model-2',
        size: '1536x1152',
        count: 2,
      },
      video: {
        providerId: 'custom',
        apiBase: '',
        apiKey: '',
        dashKey: '',
        model: 'audit-video-model',
        mode: 't2v',
        resolution: '720P',
        duration: 5,
        ratio: '16:9',
      },
    },
  });
  await expectToast(page, '图片配置审计通过');

  await details.getByLabel('API Key').fill('audit-image-key');
  const beforeSave = await markCalls(audit);
  await details.getByRole('button', { name: '保存配置' }).click();
  await expectProxyIntent(audit, beforeSave, {
    method: 'POST',
    path: '/api/media/config',
    body: expect.objectContaining({
      image: expect.objectContaining({ apiKey: 'audit-image-key' }),
    }),
  } as never);
  await expectToast(page, '创作配置已保存');
  await expect(details.getByLabel('API Key')).toHaveValue('');

  await details.getByLabel('API Key').fill('audit-image-key');
  await appMain(page).getByLabel('提示词').fill('isolated image intent');
  const beforeSubmit = await markCalls(audit);
  await appMain(page).getByRole('button', { name: '生成图片' }).click();
  await expectProxyIntent(audit, beforeSubmit, {
    method: 'POST',
    path: '/api/image/generate/submit',
    body: {
      baseUrl: 'https://image.example.invalid/v1',
      apiKey: 'audit-image-key',
      model: 'audit-image-model-2',
      size: '1536x1152',
      count: 2,
      prompt: 'isolated image intent',
      ratio: '4:3',
      source: 'ui',
    },
  });
  await expectProxyIntent(audit, beforeSubmit, {
    method: 'GET',
    path: `/api/jobs/${imageJob.id}`,
    body: null,
  });
  await expectToast(page, '图片生成完成');

  const beforeRefresh = await markCalls(audit);
  await appMain(page).getByRole('button', { name: '刷新配置' }).click();
  await expectProxyIntent(audit, beforeRefresh, { method: 'GET', path: '/api/media/config', body: null });
  await details.locator('summary').click();
  await expect(details).not.toHaveAttribute('open', '');
});

test('creative video controls switch tab and submit only a mocked video intent', async ({ audit, page }) => {
  const videoJob = completedJob('video-audit-job', { video: '', path: '', filename: '', size: 0 });
  const videoConfig = {
    ...MEDIA_CONFIG,
    video: {
      ...MEDIA_CONFIG.video,
      providerId: 'seedance',
      apiBase: 'https://video.example.invalid/v1',
      model: 'audit-video-model-2',
      resolution: '1080P',
      duration: 8,
      ratio: '9:16',
      hasApiKey: true,
    },
  };
  await audit.registerRoute('POST', '/api/media/test', {
    value: { ok: true, message: '视频配置审计通过', config: videoConfig },
  });
  await audit.registerRoute('POST', '/api/media/config', { value: { config: videoConfig } });
  await audit.registerRoute('POST', '/api/video/generate/submit', {
    value: { jobId: videoJob.id, job: videoJob },
  });
  await audit.registerRoute('GET', `/api/jobs/${videoJob.id}`, { value: { job: videoJob } });
  await navigateTo(audit, 'creative');

  await page.locator('[data-creative-tab-video]').click();
  await appMain(page).locator('[data-creative-mode-i2v]').click();
  await expect(appMain(page).getByRole('button', { name: '上传图片' })).toBeVisible();
  await appMain(page).locator('[data-creative-mode-t2v]').click();
  const details = appMain(page).locator('[data-creative-config-details]');
  await details.locator('summary').click();
  await details.getByLabel('Provider').selectOption('seedance');
  await details.getByLabel('API Base').fill('https://video.example.invalid/v1');
  await details.getByLabel('API Key').fill('audit-video-key');
  await details.getByLabel('模型').fill('audit-video-model-2');
  await details.getByLabel('清晰度').selectOption('1080P');
  await details.getByLabel('秒数').fill('8');
  await details.getByLabel('比例').selectOption('9:16');

  const beforeTest = await markCalls(audit);
  await details.getByRole('button', { name: '测试配置' }).click();
  await expectProxyIntent(audit, beforeTest, {
    method: 'POST',
    path: '/api/media/test',
    body: expect.objectContaining({
      kind: 'video',
      video: expect.objectContaining({
        providerId: 'seedance',
        apiBase: 'https://video.example.invalid/v1',
        apiKey: 'audit-video-key',
        model: 'audit-video-model-2',
        resolution: '1080P',
        duration: 8,
        ratio: '9:16',
      }),
    }),
  } as never);
  await expectToast(page, '视频配置审计通过');

  await details.getByLabel('API Key').fill('audit-video-key');
  await appMain(page).getByLabel('提示词').fill('isolated video intent');
  const beforeSubmit = await markCalls(audit);
  await appMain(page).getByRole('button', { name: '生成视频' }).click();
  await expectProxyIntent(audit, beforeSubmit, {
    method: 'POST',
    path: '/api/video/generate/submit',
    body: {
      providerId: 'seedance',
      apiBase: 'https://video.example.invalid/v1',
      apiKey: 'audit-video-key',
      dashKey: 'audit-video-key',
      model: 'audit-video-model-2',
      mode: 't2v',
      resolution: '1080P',
      duration: 8,
      ratio: '9:16',
      prompt: 'isolated video intent',
      source: 'ui',
    },
  });
  await expectProxyIntent(audit, beforeSubmit, {
    method: 'GET',
    path: `/api/jobs/${videoJob.id}`,
    body: null,
  });
  await expectToast(page, '视频生成完成');

  await page.locator('[data-creative-tab-image]').click();
  await expect(appMain(page).getByRole('button', { name: '生成图片' })).toBeVisible();
});

test('creative results without a local path render status instead of a dead copy button', async ({ audit, page }) => {
  const imageJob = completedJob('image-no-path-audit', {
    images: ['iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9ZQmcAAAAASUVORK5CYII='],
    files: [{ filename: 'audit-no-path.png', mime: 'image/png' }],
    count: 1,
  });
  await audit.registerRoute('POST', '/api/media/config', { value: { config: MEDIA_CONFIG } });
  await audit.registerRoute('POST', '/api/image/generate/submit', {
    value: { jobId: imageJob.id, job: imageJob },
  });
  await audit.registerRoute('GET', `/api/jobs/${imageJob.id}`, { value: { job: imageJob } });
  await navigateTo(audit, 'creative');

  const details = appMain(page).locator('[data-creative-config-details]');
  await details.locator('summary').click();
  await details.getByLabel('API Key').fill('audit-image-key');
  await appMain(page).getByRole('button', { name: '生成图片' }).click();

  await expect(appMain(page).getByText('未返回本地路径')).toBeVisible();
  await expect(appMain(page).getByRole('button', { name: '复制路径' })).toHaveCount(0);
});

test('creative local library filters, reuses, reveals, paginates, and deletes assets', async ({ audit, page }) => {
  const imageAsset = {
    id: 'asset-image-audit',
    kind: 'image',
    path: 'C:\\LOOM\\media\\audit-image.png',
    filename: 'audit-image.png',
    mime: 'image/png',
    size: 128,
    createdAt: '2026-07-16T00:00:00.000Z',
    prompt: 'isolated image asset',
    ratio: '1:1',
    source: 'ui',
  };
  const imagePage = { items: [imageAsset], nextCursor: 'asset-cursor-1', hasMore: true };
  const transferJob = completedJob('media-transfer-audit-job', {
    status: 'succeeded',
    message: '已传到 1 台手机相册',
    attempted: true,
    succeededDeviceCount: 1,
    failedDeviceCount: 0,
    deviceResults: [{ status: 'succeeded', deviceId: 'phone-b', deviceName: '招聘二号机' }],
  });

  await audit.registerRoute('GET', '/api/media/assets?limit=20', { value: imagePage });
  await audit.registerRoute('GET', '/api/phone/config', {
    value: {
      selectedDeviceId: 'phone-a',
      configured: true,
      devices: [
        { id: 'phone-a', name: '招聘一号机', baseUrl: 'http://192.0.2.10:9527', tokenAvailable: true },
        { id: 'phone-b', name: '招聘二号机', baseUrl: 'http://192.0.2.11:9527', tokenAvailable: true },
      ],
    },
  });
  await audit.registerRoute('POST', `/api/media/assets/${imageAsset.id}/transfer`, {
    value: { jobId: transferJob.id, job: transferJob },
  });
  await audit.registerRoute('GET', `/api/jobs/${transferJob.id}`, { value: { job: transferJob } });
  await audit.registerRoute('GET', '/api/media/assets?limit=20&kind=image', {
    value: { items: [imageAsset], nextCursor: '', hasMore: false },
  });
  await audit.registerRoute('GET', '/api/media/assets?limit=20&kind=video', {
    value: { items: [], nextCursor: '', hasMore: false },
  });
  await audit.registerRoute('GET', '/api/media/assets?limit=20&cursor=asset-cursor-1', {
    value: { items: [], nextCursor: '', hasMore: false },
  });
  await audit.registerRoute('POST', `/api/media/assets/${imageAsset.id}/reveal`, {
    value: { opened: true, id: imageAsset.id },
  });
  await audit.registerRoute('DELETE', `/api/media/assets/${imageAsset.id}`, {
    value: { deleted: true, id: imageAsset.id },
  });
  await navigateTo(audit, 'creative');

  const library = appMain(page).locator('[data-local-media-library]');
  await expect(library.getByText(imageAsset.filename)).toBeVisible();

  let before = await markCalls(audit);
  await library.getByRole('button', { name: '传到手机' }).click();
  await library.getByRole('checkbox', { name: /招聘一号机/ }).uncheck();
  await library.getByRole('button', { name: '传输到 1 台' }).click();
  await expectProxyIntent(audit, before, {
    method: 'POST',
    path: `/api/media/assets/${imageAsset.id}/transfer`,
    body: { deviceIds: ['phone-b'] },
  });
  await expectProxyIntent(audit, before, {
    method: 'GET',
    path: `/api/jobs/${transferJob.id}`,
    body: null,
  });
  await expect(library.getByText('已传到 1 台手机相册')).toBeVisible();

  before = await markCalls(audit);
  await library.getByRole('button', { name: '图片', exact: true }).click();
  await expectProxyIntent(audit, before, {
    method: 'GET',
    path: '/api/media/assets?limit=20&kind=image',
    body: null,
  });

  before = await markCalls(audit);
  await library.getByRole('button', { name: '视频', exact: true }).click();
  await expectProxyIntent(audit, before, {
    method: 'GET',
    path: '/api/media/assets?limit=20&kind=video',
    body: null,
  });

  before = await markCalls(audit);
  await library.getByRole('button', { name: '全部', exact: true }).click();
  await expectProxyIntent(audit, before, {
    method: 'GET',
    path: '/api/media/assets?limit=20',
    body: null,
  });

  before = await markCalls(audit);
  await library.getByRole('button', { name: '刷新', exact: true }).click();
  await expectProxyIntent(audit, before, {
    method: 'GET',
    path: '/api/media/assets?limit=20',
    body: null,
  });

  before = await markCalls(audit);
  await library.getByRole('button', { name: '加载更多' }).click();
  await expectProxyIntent(audit, before, {
    method: 'GET',
    path: '/api/media/assets?limit=20&cursor=asset-cursor-1',
    body: null,
  });
  await expect(library.getByRole('button', { name: '加载更多' })).toHaveCount(0);

  await library.getByRole('button', { name: '用作图生图' }).click();
  await expect(appMain(page).locator('[data-creative-mode-i2i]')).toHaveAttribute('aria-pressed', 'true');
  await expect(appMain(page).getByTitle(imageAsset.filename)).toBeVisible();
  await appMain(page).getByRole('button', { name: '移除' }).click();
  await appMain(page).getByRole('button', { name: '最近生成' }).click();

  const fileChooserPromise = page.waitForEvent('filechooser');
  await appMain(page).getByRole('button', { name: '上传图片' }).click();
  const fileChooser = await fileChooserPromise;
  await fileChooser.setFiles({
    name: 'audit-upload.png',
    mimeType: 'image/png',
    buffer: Buffer.from('audit-image'),
  });
  await expect(appMain(page).getByText('audit-upload.png')).toBeVisible();

  await library.getByRole('button', { name: '用作图生视频' }).click();
  await expect(appMain(page).locator('[data-creative-mode-i2v]')).toHaveAttribute('aria-pressed', 'true');

  before = await markCalls(audit);
  await library.getByRole('button', { name: '打开位置' }).first().click();
  await expectProxyIntent(audit, before, {
    method: 'POST',
    path: `/api/media/assets/${imageAsset.id}/reveal`,
    body: {},
  });

  await audit.registerRoute('GET', '/api/media/assets?limit=20', {
    value: { items: [], nextCursor: '', hasMore: false },
  });
  before = await markCalls(audit);
  await library.getByRole('button', { name: '删除' }).first().click();
  await confirmDialog(page, '删除本地素材', '删除');
  await expectProxyIntent(audit, before, {
    method: 'DELETE',
    path: `/api/media/assets/${imageAsset.id}`,
    body: null,
  });
  await expect(library.getByText(imageAsset.filename)).toHaveCount(0);
});

test('acquisition controls refresh, bind, confirm Feishu writes, copy payloads, and capture external intent', async ({ audit, page }) => {
  await audit.registerRoute('GET', '/api/matrix/acquisition/feishu/status', { value: AUDIT_FEISHU_STATUS });
  await audit.registerRoute('POST', '/api/matrix/acquisition/feishu/login', {
    value: {
      ok: true,
      loginUrl: 'https://open.feishu.cn/device/audit-login',
      verificationUrl: 'https://open.feishu.cn/device/audit-login',
      userCode: 'AUDIT-CODE',
      qrAscii: '',
      message: 'isolated login intent',
    },
  });
  await audit.registerRoute('POST', '/api/matrix/acquisition/feishu/bind-table', {
    value: { table: AUDIT_FEISHU_STATUS.table, status: AUDIT_FEISHU_STATUS },
  });
  await audit.registerRoute('POST', '/api/matrix/acquisition/feishu/create-table', {
    value: { fields: ['线索', '状态'], table: AUDIT_FEISHU_STATUS.table, status: AUDIT_FEISHU_STATUS },
  });
  await audit.registerRoute('POST', '/api/matrix/acquisition/feishu/test-write', {
    value: { ok: true, recordId: 'record-audit-1' },
  });
  await audit.registerRoute('POST', '/api/matrix/acquisition/feishu/retry-sync', {
    value: { ok: true, retried: 0 },
  });
  await navigateTo(audit, 'acquisition');

  const beforeRefresh = await markCalls(audit);
  await appMain(page).getByRole('button', { name: '刷新总览' }).click();
  await expectProxyIntent(audit, beforeRefresh, { method: 'GET', path: '/api/matrix/acquisition', body: null });
  await expectProxyIntent(audit, beforeRefresh, { method: 'GET', path: '/api/matrix/status', body: null });

  const beforeCheck = await markCalls(audit);
  await appMain(page).getByRole('button', { name: '检查', exact: true }).click();
  await expectProxyIntent(audit, beforeCheck, {
    method: 'GET', path: '/api/matrix/acquisition/feishu/status', body: null,
  });
  await expectToast(page, '已刷新飞书状态');

  const beforeLogin = await markCalls(audit);
  await appMain(page).getByRole('button', { name: '扫码登录' }).click();
  await expectProxyIntent(audit, beforeLogin, {
    method: 'POST', path: '/api/matrix/acquisition/feishu/login', body: null,
  });
  await expect(page.getByText('AUDIT-CODE', { exact: false }).first()).toBeVisible();

  await appMain(page).getByRole('button', { name: '复制登录链接' }).click();
  await expect.poll(() => page.evaluate(() => navigator.clipboard.readText()))
    .toBe('https://open.feishu.cn/device/audit-login');
  await appMain(page).getByRole('link', { name: '打开链接' }).click();
  await expect.poll(async () => {
    await audit.sync();
    return audit.externalOpenIntents;
  }).toContainEqual({
    source: 'anchor',
    url: 'https://open.feishu.cn/device/audit-login',
    target: '_blank',
  });

  const tableUrl = 'https://example.feishu.cn/base/audit?table=tblAudit';
  await appMain(page).getByRole('textbox', { name: '飞书多维表格链接' }).fill(tableUrl);
  const beforeBind = await markCalls(audit);
  await appMain(page).getByRole('button', { name: '绑定线索表' }).click();
  await expectProxyIntent(audit, beforeBind, {
    method: 'POST',
    path: '/api/matrix/acquisition/feishu/bind-table',
    body: { url: tableUrl, name: '麓鸣获客线索表' },
  });
  await expectToast(page, '已绑定飞书线索表');

  const beforeCreate = await markCalls(audit);
  await appMain(page).getByRole('button', { name: '新建表' }).click();
  await confirmDialog(page, '新建飞书多维表格', '确认新建');
  await expect.poll(async () => {
    await audit.sync();
    return proxyIntents(audit.callLogs.slice(beforeCreate)).filter(({ path }) => path === '/api/matrix/acquisition/feishu/create-table');
  }).toEqual([
    { method: 'POST', path: '/api/matrix/acquisition/feishu/create-table', body: { confirmed: false } },
    { method: 'POST', path: '/api/matrix/acquisition/feishu/create-table', body: { confirmed: true } },
  ]);
  await expectToast(page, '已创建并绑定新的飞书线索表');

  for (const [name, path, toast] of [
    ['测试写入', '/api/matrix/acquisition/feishu/test-write', '已提交飞书测试写入'],
    ['重试同步', '/api/matrix/acquisition/feishu/retry-sync', '已重试同步本地缓存线索'],
  ] as const) {
    const before = await markCalls(audit);
    await appMain(page).getByRole('button', { name }).click();
    await expectProxyIntent(audit, before, { method: 'POST', path, body: null });
    await expectToast(page, toast);
  }

  await appMain(page).getByRole('button', { name: '复制 AI 接入提示词' }).click();
  await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toContain('BEGIN_SKILL_LIBRARY');
  const promptDetails = appMain(page).locator('[data-acquisition-agent-prompt] details');
  await promptDetails.locator('summary').click();
  await expect(promptDetails).toHaveAttribute('open', '');
  await expect(promptDetails.getByRole('textbox', { name: 'AI 接入提示词预览' })).toHaveAttribute('readonly', '');
});

test('phone baseline controls own form, mode, profile, quick-task, clipboard, and refresh state', async ({ audit, page }) => {
  await navigateTo(audit, 'phone');

  await appMain(page).getByRole('button', { name: '下载手机端 App' }).click();
  const downloadHeading = page.getByRole('heading', { name: '下载手机端 App' });
  await expect(downloadHeading).toBeVisible();
  await page.getByRole('button', { name: '复制', exact: true }).click();
  await expectToast(page, '下载链接已复制');
  await expect.poll(() => page.evaluate(() => navigator.clipboard.readText()))
    .toContain('OpenClaw-AgentPhone.apk');
  await page.getByRole('button', { name: '关闭下载手机端 App' }).click();
  await expect(downloadHeading).toBeHidden();

  const name = appMain(page).getByLabel('设备名称');
  const address = appMain(page).getByLabel('手机 IP');
  const token = appMain(page).getByLabel('连接令牌');
  await name.fill('Temporary Phone');
  await address.fill('192.0.2.20');
  await token.fill('temporary-token');
  await appMain(page).getByRole('button', { name: '添加手机' }).click();
  await expect(name).toHaveValue('Android Phone 1');
  await expect(address).toHaveValue('');
  await expect(token).toHaveValue('');

  const beforeReadConfig = await markCalls(audit);
  await appMain(page).getByRole('button', { name: '读取配置' }).click();
  await expectProxyIntent(audit, beforeReadConfig, { method: 'GET', path: '/api/phone/config', body: null });

  for (const selector of [/^只读\s+observe/, /^受控\s+safe/, /^完整控制\s+full/]) {
    await appMain(page).getByRole('button', { name: selector }).click();
  }
  for (const name of ['快速', '标准', '深度']) {
    await appMain(page).getByRole('button', { name, exact: true }).click();
  }

  const prompt = appMain(page).getByRole('textbox', { name: '手机任务描述' });
  const quickTasks = [
    ['读取当前屏幕，告诉我页面名称和三个可...', '读取当前屏幕，告诉我页面名称和三个可见内容。'],
    ['返回上一页，然后告诉我现在停留在哪个...', '返回上一页，然后告诉我现在停留在哪个页面。'],
    ['回到桌面，并告诉我桌面上能看到哪些主...', '回到桌面，并告诉我桌面上能看到哪些主要应用。'],
    ['打开系统设置，停在设置首页后返回页面...', '打开系统设置，停在设置首页后返回页面名称。'],
  ] as const;
  for (const [buttonName, value] of quickTasks) {
    await appMain(page).getByRole('button', { name: buttonName }).click();
    await expect(prompt).toHaveValue(value);
  }

  const beforeMatrixRefresh = await markCalls(audit);
  await appMain(page).getByRole('button', { name: '刷新状态' }).click();
  await expectProxyIntent(audit, beforeMatrixRefresh, { method: 'GET', path: '/api/matrix/status', body: null });
  const beforeJobsRefresh = await markCalls(audit);
  await appMain(page).getByRole('button', { name: '刷新', exact: true }).click();
  await expectProxyIntent(audit, beforeJobsRefresh, { method: 'GET', path: '/api/jobs/list?limit=40', body: null });
});

test('phone save-and-detect path records config, matrix registration, and status without touching a device', async ({ audit, page }) => {
  const statusJob = completedJob('phone-save-status', {
    stdout: JSON.stringify({ ok: true, success: true, deviceId: 'phone-audit-1' }),
  });
  await audit.registerRoute('POST', '/api/phone/config/device', { value: AUDIT_PHONE_CONFIG });
  await audit.registerRoute('POST', '/api/matrix/device/register', {
    value: { device: AUDIT_MATRIX_WITH_DEVICE.devices[0], status: AUDIT_MATRIX_WITH_DEVICE },
  });
  await audit.registerRoute('POST', '/api/phone/status', {
    value: { jobId: statusJob.id, job: statusJob },
  });
  await audit.registerRoute('GET', `/api/jobs/${statusJob.id}`, { value: { job: statusJob } });
  await navigateTo(audit, 'phone');

  await appMain(page).getByLabel('设备名称').fill('Audit Phone');
  await appMain(page).getByLabel('手机 IP').fill('192.0.2.10');
  await appMain(page).getByLabel('连接令牌').fill('audit-token-not-real');
  const before = await markCalls(audit);
  await appMain(page).getByRole('button', { name: '保存并检测' }).click();
  await expectProxyIntent(audit, before, {
    method: 'POST',
    path: '/api/phone/config/device',
    body: {
      id: 'phone-1',
      name: 'Audit Phone',
      baseUrl: '192.0.2.10',
      token: 'audit-token-not-real',
      selectedDeviceId: 'phone-1',
    },
  });
  await expectProxyIntent(audit, before, { method: 'POST', path: '/api/phone/status', body: { deviceId: 'phone-1' } });
  await expectProxyIntent(audit, before, { method: 'GET', path: `/api/jobs/${statusJob.id}`, body: null });
  await expectToast(page, '手机连接配置已保存');
});

test('configured phone controls mock all device, read, task, screenshot, model, history, and delete intents', async ({ audit, page }) => {
  const alternatePhone = {
    id: 'phone-audit-2',
    name: 'Audit Phone Two',
    baseUrl: 'http://192.0.2.11:9527',
    tokenAvailable: false,
  };
  await audit.registerRoute('GET', '/api/phone/config', {
    value: { ...AUDIT_PHONE_CONFIG, devices: [...AUDIT_PHONE_CONFIG.devices, alternatePhone] },
  });
  await audit.registerRoute('GET', '/api/matrix/status', { value: AUDIT_MATRIX_WITH_DEVICE });
  await audit.registerRoute('POST', '/api/phone/config/device', { value: AUDIT_PHONE_CONFIG });
  await audit.registerRoute('POST', '/api/matrix/device/register', {
    value: { device: AUDIT_MATRIX_WITH_DEVICE.devices[0], status: AUDIT_MATRIX_WITH_DEVICE },
  });

  const jobs = {
    status: completedJob('phone-status-audit', { stdout: JSON.stringify({ ok: true, success: true }) }),
    screenshot: completedJob('phone-screenshot-audit', { stdout: JSON.stringify({ path: 'C:\\LOOM\\playwright-audit\\frame.png' }) }),
    sync: completedJob('phone-sync-audit', { wire: { models: { phone: 'audit-text-model' } }, syncResults: [] }),
    history: completedJob('phone-history-audit', { rows: [] }),
    read: completedJob('phone-read-audit', { message: 'isolated read intent accepted' }),
    task: completedJob('phone-task-audit', { message: 'isolated full-control intent accepted' }),
  };
  for (const [path, job] of [
    ['/api/phone/status', jobs.status],
    ['/api/phone/screenshot', jobs.screenshot],
    ['/api/phone/sync-model', jobs.sync],
    ['/api/phone/history', jobs.history],
    ['/api/phone/read', jobs.read],
    ['/api/phone/task', jobs.task],
  ] as const) {
    await audit.registerRoute('POST', path, { value: { jobId: job.id, job } });
    await audit.registerRoute('GET', `/api/jobs/${job.id}`, { value: { job } });
  }
  await audit.registerRoute('DELETE', '/api/phone/config/device/phone-audit-1', {
    value: { selectedDeviceId: '', configured: false, devices: [] },
  });
  await navigateTo(audit, 'phone');

  const deviceCard = appMain(page).getByRole('button', { name: /Audit Phone Two.*192\.0\.2\.11/ });
  const beforeSelect = await markCalls(audit);
  await deviceCard.click();
  await expectProxyIntent(audit, beforeSelect, {
    method: 'POST',
    path: '/api/phone/config/device',
    body: {
      id: 'phone-audit-2',
      name: 'Audit Phone Two',
      baseUrl: 'http://192.0.2.11:9527',
      selectedDeviceId: 'phone-audit-2',
    },
  });

  const simpleActions = [
    ['检测连接', '/api/phone/status', jobs.status.id, { deviceId: 'phone-audit-1' }],
    ['截图', '/api/phone/screenshot', jobs.screenshot.id],
    ['同步模型到手机', '/api/phone/sync-model', jobs.sync.id],
    ['读取历史', '/api/phone/history', jobs.history.id],
  ] as const;
  for (const [name, path, jobId, body = null] of simpleActions) {
    const before = await markCalls(audit);
    await appMain(page).getByRole('button', { name, exact: true }).click();
    await expectProxyIntent(audit, before, { method: 'POST', path, body });
    await expectProxyIntent(audit, before, { method: 'GET', path: `/api/jobs/${jobId}`, body: null });
  }

  await appMain(page).getByRole('textbox', { name: '手机任务描述' }).fill('read only isolated intent');
  const beforeRead = await markCalls(audit);
  await appMain(page).getByRole('button', { name: '读取屏幕' }).click();
  await expectProxyIntent(audit, beforeRead, {
    method: 'POST',
    path: '/api/phone/read',
    body: { prompt: 'read only isolated intent', profile: 'fast' },
  });

  await appMain(page).getByRole('button', { name: /^完整控制\s+full/ }).click();
  await appMain(page).getByRole('button', { name: '深度', exact: true }).click();
  await appMain(page).getByRole('textbox', { name: '手机任务描述' }).fill('full-control isolated intent');
  const beforeTask = await markCalls(audit);
  await appMain(page).getByRole('button', { name: '执行', exact: true }).click();
  await confirmDialog(page, '确认完整控制', '开始执行');
  await expectProxyIntent(audit, beforeTask, {
    method: 'POST',
    path: '/api/phone/task',
    body: {
      prompt: 'full-control isolated intent',
      mode: 'full',
      profile: 'deep',
      timeoutSec: 900,
      maxRounds: 90,
      maxWaitSec: 930,
      pollMs: 1200,
    },
  });

  const beforeDelete = await markCalls(audit);
  await appMain(page).getByRole('button', { name: '删除手机' }).click();
  await confirmDialog(page, '删除手机连接', '删除手机');
  await expectProxyIntent(audit, beforeDelete, {
    method: 'DELETE',
    path: '/api/phone/config/device/phone-audit-1',
    body: null,
  });
  await expectToast(page, '手机连接已删除，历史记录已保留');
});

const MATRIX_SCREEN = {
  schema: 'loom.matrix.screen.v1',
  deviceId: 'phone-audit-1',
  capturedAt: '2026-07-15T00:00:00.000Z',
  screenHash: 'audit-screen-hash',
  mime: 'image/png',
  width: 1,
  height: 1,
  notModified: false,
  image: 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=',
};

function runningMatrixStatus(campaignId = 'campaign-audit-1', deviceTaskId = 'task-audit-1') {
  return {
    ...AUDIT_MATRIX_WITH_DEVICE,
    devices: AUDIT_MATRIX_WITH_DEVICE.devices.map((device) => ({ ...device, busy: true, currentTaskId: deviceTaskId })),
    summary: { total: 1, online: 1, busy: 1, failed: 0 },
    campaigns: [{
      schema: 'loom.matrix.campaign.v2',
      campaignId,
      status: 'running',
      concurrency: 1,
      counts: { total: 1, queued: 0, running: 1, completed: 0, failed: 0, needsHuman: 0 },
      deviceTasks: [{
        assignmentId: 'assignment-audit-1',
        deviceTaskId,
        deviceId: 'phone-audit-1',
        jobId: 'job-audit-1',
        status: 'running',
        attempt: 1,
      }],
    }],
  };
}

async function registerMatrixDeviceRoutes(audit: AuditHarness) {
  await audit.registerRoute('GET', '/api/matrix/devices/phone-audit-1/timeline?limit=80', { value: { events: [] } });
  await audit.registerRoute('GET', '/api/matrix/devices/phone-audit-1/lease', { value: { lease: null } });
  await audit.registerRoute('GET', '/api/matrix/devices/phone-audit-1/screen', { value: MATRIX_SCREEN });
  await audit.registerRoute('GET', '/api/matrix/devices/phone-audit-1/screen?*', {
    value: { ...MATRIX_SCREEN, notModified: true, image: undefined },
  });
  await audit.registerRoute('POST', '/api/matrix/devices/phone-audit-1/lease', {
    value: {
      lease: {
        schema: 'loom.matrix.device_lease.v1',
        leaseId: 'lease-audit-1',
        deviceId: 'phone-audit-1',
        holderType: 'human',
        holderId: 'playwright-audit',
        mode: 'control',
        expiresAt: '2099-12-31T23:59:59.000Z',
      },
    },
  });
  await audit.registerRoute('DELETE', '/api/matrix/devices/phone-audit-1/lease', { value: { released: true } });
  await audit.registerRoute('POST', '/api/matrix/devices/phone-audit-1/control', { value: { status: 'applied' } });
}

test('matrix dispatch tracks the shared job until completion', async ({ audit, page }) => {
  await audit.registerRoute('GET', '/api/matrix/status', { value: AUDIT_MATRIX_WITH_DEVICE });
  await registerMatrixDeviceRoutes(audit);
  await audit.registerRoute('POST', '/api/matrix/dispatch', {
    value: {
      jobId: 'job-matrix-dispatch',
      job: { id: 'job-matrix-dispatch', status: 'queued' },
      campaign: runningMatrixStatus().campaigns[0],
    },
  });
  await audit.registerRoute('GET', '/api/jobs/job-matrix-dispatch', {
    delayMs: 1500,
    value: {
      job: {
        id: 'job-matrix-dispatch',
        status: 'succeeded',
        message: 'Matrix task completed',
        result: { success: true },
      },
    },
  });
  await navigateTo(audit, 'workbench');

  const main = appMain(page);
  await main.getByRole('checkbox', { name: '任务目标' }).check();
  await main.getByPlaceholder('输入要在已选设备上执行的真实任务').fill('打开系统设置');
  const beforeDispatch = await markCalls(audit);
  await main.getByRole('button', { name: '下发任务' }).click();

  await expect(main.getByRole('button', { name: '下发任务' })).toBeEnabled({ timeout: 700 });
  await expect(main.locator('[data-matrix-action-result]')).toContainText('等待执行', { timeout: 700 });

  await expectProxyIntent(audit, beforeDispatch, {
    method: 'GET',
    path: '/api/jobs/job-matrix-dispatch',
    body: null,
  });
  await expect(main.locator('[data-matrix-action-result]')).toContainText('campaign-audit-1');
});

test('matrix workbench selects devices, configures a task, dispatches, and supports manual control', async ({ audit, page }) => {
  await audit.registerRoute('GET', '/api/matrix/status', { value: AUDIT_MATRIX_WITH_DEVICE });
  await registerMatrixDeviceRoutes(audit);
  await audit.registerRoute('POST', '/api/matrix/dispatch', {
    value: { campaign: runningMatrixStatus().campaigns[0] },
  });
  await navigateTo(audit, 'workbench');

  const main = appMain(page);
  await expect(main.getByText('超级矩阵工作台')).toBeVisible();
  await expect(main.getByRole('button', { name: '下发任务' })).toBeDisabled();
  await main.getByRole('checkbox', { name: '任务目标' }).check();
  for (const density of ['紧凑', '标准', '宽松']) await main.getByRole('button', { name: density, exact: true }).click();
  await main.getByPlaceholder('搜索设备、账号、应用').fill('Audit Phone');
  await expect(main.getByTitle('聚焦 Audit Phone')).toBeVisible();
  await main.getByPlaceholder('搜索设备、账号、应用').fill('');

  await main.getByRole('button', { name: '高级参数' }).click();
  const drawer = main.locator('[data-matrix-task-drawer]');
  await drawer.getByLabel('模板 ID（留空为直接任务）').fill('audit-template');
  const modeSelect = drawer.getByLabel('执行模式');
  const profileSelect = drawer.getByLabel('执行档位');
  const riskConfirmation = drawer.getByRole('checkbox');
  await expect(modeSelect).toHaveValue('safe');
  await riskConfirmation.check();
  await modeSelect.selectOption('full');
  await expect(riskConfirmation).not.toBeChecked();
  await riskConfirmation.check();
  await profileSelect.selectOption('deep');
  await expect(riskConfirmation).not.toBeChecked();
  await riskConfirmation.check();
  await drawer.getByLabel('模板 ID（留空为直接任务）').fill('audit-template-v2');
  await expect(riskConfirmation).not.toBeChecked();
  await drawer.getByLabel('模板 ID（留空为直接任务）').fill('audit-template');
  await riskConfirmation.check();
  await drawer.getByRole('button', { name: '复制链接' }).click();
  await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toContain('OpenClaw-AgentPhone.apk');
  await expect(drawer.getByRole('link', { name: '下载 APK' })).toBeVisible();
  await drawer.getByRole('button', { name: '完成' }).click();

  const promptInput = main.getByPlaceholder('输入要在已选设备上执行的真实任务');
  await promptInput.fill('mocked matrix dispatch only');
  await main.getByRole('button', { name: '高级参数' }).click();
  await expect(riskConfirmation).not.toBeChecked();
  await riskConfirmation.check();
  await drawer.getByRole('button', { name: '完成' }).click();
  await main.getByRole('checkbox', { name: '任务目标' }).uncheck();
  await main.getByRole('checkbox', { name: '任务目标' }).check();
  await main.getByRole('button', { name: '高级参数' }).click();
  await expect(riskConfirmation).not.toBeChecked();
  await riskConfirmation.check();
  await drawer.getByRole('button', { name: '完成' }).click();
  const beforeDispatch = await markCalls(audit);
  await main.getByRole('button', { name: '下发任务' }).click();
  await expectProxyIntent(audit, beforeDispatch, {
    method: 'POST',
    path: '/api/matrix/dispatch',
    body: {
      prompt: 'mocked matrix dispatch only',
      templateId: 'audit-template',
      target: { deviceIds: ['phone-audit-1'] },
      mode: 'full',
      profile: 'deep',
      confirmed: true,
    },
  });
  await expect(main.locator('[data-matrix-action-result]')).toContainText('campaign-audit-1');
  await main.getByRole('button', { name: '高级参数' }).click();
  await expect(riskConfirmation).not.toBeChecked();
  await drawer.getByRole('button', { name: '完成' }).click();

  await main.locator('[data-matrix-device-inspector]').getByRole('button', { name: '人工' }).click();
  await expect(main.getByRole('button', { name: '主页' })).toBeEnabled();
  const focusScreen = main.locator('[data-matrix-focus-screen]');
  const focusBox = await focusScreen.boundingBox();
  expect(focusBox).not.toBeNull();
  const beforeLetterboxTap = await markCalls(audit);
  await page.mouse.click(focusBox!.x + focusBox!.width / 2, focusBox!.y + focusBox!.height * 0.1);
  await page.waitForTimeout(80);
  await audit.sync();
  expect(proxyIntents(audit.callLogs.slice(beforeLetterboxTap)).some((intent) => (
    intent.path === '/api/matrix/devices/phone-audit-1/control'
    && (intent.body as { action?: string }).action === 'tap'
  ))).toBe(false);
  const beforeImageTap = await markCalls(audit);
  await page.mouse.click(focusBox!.x + focusBox!.width / 2, focusBox!.y + focusBox!.height / 2);
  await expect.poll(async () => {
    await audit.sync();
    return proxyIntents(audit.callLogs.slice(beforeImageTap)).find((intent) => (
      intent.path === '/api/matrix/devices/phone-audit-1/control'
      && (intent.body as { action?: string }).action === 'tap'
    ))?.body;
  }).toMatchObject({ action: 'tap', x: 0.5, y: 0.5 });
  const beforeControl = await markCalls(audit);
  await main.getByRole('button', { name: '主页' }).click();
  await expect.poll(async () => {
    await audit.sync();
    return proxyIntents(audit.callLogs.slice(beforeControl)).some((intent) => (
      intent.path === '/api/matrix/devices/phone-audit-1/control'
      && (intent.body as { action?: string }).action === 'home'
    ));
  }).toBe(true);
  await main.locator('[data-matrix-device-inspector]').getByRole('button', { name: 'AI', exact: true }).click();
  await expectProxyIntent(audit, beforeControl, {
    method: 'DELETE',
    path: '/api/matrix/devices/phone-audit-1/lease',
    body: { leaseId: 'lease-audit-1' },
  });
});

test('matrix manual control surfaces backend failure while the device is idle', async ({ audit, page }) => {
  await audit.registerRoute('GET', '/api/matrix/status', { value: AUDIT_MATRIX_WITH_DEVICE });
  await registerMatrixDeviceRoutes(audit);
  await audit.registerRoute('POST', '/api/matrix/devices/phone-audit-1/control', {
    value: {
      status: 'failed',
      code: 'matrix_control_unsupported',
      error: 'Recent apps is not supported by the connected phone script',
    },
  });
  await navigateTo(audit, 'workbench');

  const main = appMain(page);
  const inspector = main.locator('[data-matrix-device-inspector]');
  await inspector.getByRole('button', { name: '人工' }).click();
  await inspector.getByRole('button', { name: '最近任务' }).click();

  await expectToast(page, 'Recent apps is not supported by the connected phone script');
  await expect(main.locator('[data-matrix-action-result]')).toContainText('Recent apps is not supported');
});

test('matrix emergency stop confirms the selected running scope and restores controls', async ({ audit, page }) => {
  const status = runningMatrixStatus();
  status.campaigns[0].counts = { ...status.campaigns[0].counts, total: 2, running: 2 };
  status.campaigns[0].deviceTasks.push({
    assignmentId: 'assignment-audit-2',
    deviceTaskId: 'task-audit-2',
    deviceId: 'phone-audit-2',
    jobId: 'job-audit-1',
    status: 'running',
    attempt: 1,
  });
  await audit.registerRoute('GET', '/api/matrix/status', { value: status });
  await registerMatrixDeviceRoutes(audit);
  await audit.registerRoute('POST', '/api/matrix/emergency-stop', {
    delayMs: 120,
    value: {
      schema: 'loom.matrix.emergency_stop.v1',
      cancelled: true,
      scope: 'devices',
      matchedCampaignIds: ['campaign-audit-1'],
      campaignIds: ['campaign-audit-1'],
      cancelledJobIds: ['job-audit-1'],
      cancelledCount: 1,
      affectedTaskCount: 2,
      affectedDeviceCount: 2,
      affected: [],
    },
  });
  await navigateTo(audit, 'workbench');

  const main = appMain(page);
  await main.getByRole('checkbox', { name: '任务目标' }).check();
  const stop = main.locator('[data-matrix-emergency-stop]');
  await expect(stop).toBeEnabled();
  const beforeStop = await markCalls(audit);
  await stop.click();
  await expect(page.getByText('急停按 campaign 原子生效：将停止 1 个 campaign 内 2 个活动任务，涉及 2 台设备。已完成的外部动作无法撤回。')).toBeVisible();
  await confirmDialog(page, '确认紧急停止', '立即急停');
  await expect(stop).toContainText('急停中...');
  await expectProxyIntent(audit, beforeStop, {
    method: 'POST',
    path: '/api/matrix/emergency-stop',
    body: { deviceIds: ['phone-audit-1'] },
  });
  await expectToast(page, '急停完成：2 个任务，2 台设备');
  await expect(stop).toHaveText('急停');
});

test('matrix task controls pause and cancel the exact backend task', async ({ audit, page }) => {
  await audit.registerRoute('GET', '/api/matrix/status', { value: runningMatrixStatus() });
  await registerMatrixDeviceRoutes(audit);
  await audit.registerRoute('POST', '/api/matrix/tasks/task-audit-1/pause', { value: { status: 'applied' } });
  await audit.registerRoute('POST', '/api/matrix/cancel', { value: { status: 'applied' } });
  await navigateTo(audit, 'workbench');

  const inspector = appMain(page).locator('[data-matrix-device-inspector]');
  await expect(inspector.getByRole('button', { name: '继续', exact: true })).toBeHidden();
  const beforePause = await markCalls(audit);
  await inspector.getByRole('button', { name: '暂停', exact: true }).click();
  await expectProxyIntent(audit, beforePause, {
    method: 'POST',
    path: '/api/matrix/tasks/task-audit-1/pause',
    body: null,
  });

  const beforeCancel = await markCalls(audit);
  await inspector.getByRole('button', { name: '取消', exact: true }).click();
  await confirmDialog(page, '取消任务', '确认取消 campaign');
  await expectProxyIntent(audit, beforeCancel, {
    method: 'POST',
    path: '/api/matrix/cancel',
    body: { campaignId: 'campaign-audit-1' },
  });
});

test('matrix focus changes ignore stale timeline and lease responses', async ({ audit, page }) => {
  const twoDeviceStatus = {
    ...AUDIT_MATRIX_WITH_DEVICE,
    devices: [
      AUDIT_MATRIX_WITH_DEVICE.devices[0],
      {
        ...AUDIT_MATRIX_WITH_DEVICE.devices[0],
        deviceId: 'phone-audit-2',
        name: 'Audit Phone Two',
        currentScreenSummary: 'fresh second phone',
      },
    ],
    summary: { total: 2, online: 2, busy: 0, failed: 0 },
  };
  await audit.registerRoute('GET', '/api/matrix/status', { value: twoDeviceStatus });
  await audit.registerRoute('GET', '/api/matrix/devices/phone-audit-1/timeline?limit=80', {
    delayMs: 300,
    value: { events: [{ eventId: 'stale-one', type: 'STALE_PHONE_ONE', timestamp: '2026-07-15T00:00:00.000Z' }] },
  });
  await audit.registerRoute('GET', '/api/matrix/devices/phone-audit-1/lease', {
    delayMs: 300,
    value: {
      lease: {
        schema: 'loom.matrix.device_lease.v1',
        leaseId: 'stale-lease',
        deviceId: 'phone-audit-1',
        holderType: 'human',
        holderId: 'stale-holder',
        mode: 'control',
        expiresAt: '2099-12-31T23:59:59.000Z',
      },
    },
  });
  await audit.registerRoute('GET', '/api/matrix/devices/phone-audit-2/timeline?limit=80', {
    value: { events: [{ eventId: 'fresh-two', type: 'FRESH_PHONE_TWO', timestamp: '2026-07-15T00:00:01.000Z' }] },
  });
  await audit.registerRoute('GET', '/api/matrix/devices/phone-audit-2/lease', { value: { lease: null } });
  for (const deviceId of ['phone-audit-1', 'phone-audit-2']) {
    await audit.registerRoute('GET', `/api/matrix/devices/${deviceId}/screen`, {
      value: { ...MATRIX_SCREEN, deviceId, screenHash: `${deviceId}-screen` },
    });
    await audit.registerRoute('GET', `/api/matrix/devices/${deviceId}/screen?*`, {
      value: { ...MATRIX_SCREEN, deviceId, screenHash: `${deviceId}-screen`, notModified: true, image: undefined },
    });
  }
  await navigateTo(audit, 'workbench');

  const main = appMain(page);
  await main.getByTitle('聚焦 Audit Phone Two').click();
  const inspector = main.locator('[data-matrix-device-inspector][data-device-id="phone-audit-2"]');
  await expect(inspector).toContainText('FRESH_PHONE_TWO');
  await page.waitForTimeout(350);
  await expect(inspector).not.toContainText('STALE_PHONE_ONE');
  await expect(inspector).not.toContainText('human / 23:59:59');
});
