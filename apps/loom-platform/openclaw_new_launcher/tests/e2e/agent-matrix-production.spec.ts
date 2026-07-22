import { expect, test, type AuditHarness } from './support/audit-fixture';
import {
  appMain,
  confirmDialog,
  expectProxyIntent,
  markCalls,
  navigateTo,
  proxyIntents,
} from './support/control-audit';
import { AUDIT_MATRIX_WITH_DEVICE } from './support/control-audit-data';

const NATIVE_AGENT_BOOTSTRAP = {
  runtimeProfiles: [
    { runtimeProfileId: 'loom-native', name: '麓鸣原生智能体', available: true, isDefault: true },
  ],
  defaultRuntimeProfileId: 'loom-native',
  models: [
    { modelId: 'glm-5', name: 'GLM-5', available: true },
    { modelId: 'qwen3.7-plus', name: 'Qwen 3.7 Plus', available: true },
  ],
  defaultModelId: 'glm-5',
  capabilities: [],
};

const SESSION = {
  schema: 'loom.agent.session.v1',
  sessionId: 'session-agent-audit',
  title: 'Recruitment Agent Demo',
  status: 'active',
  runtimeProfileId: 'loom-native',
  createdAt: '2026-07-15T00:00:00.000Z',
  updatedAt: '2026-07-15T00:10:00.000Z',
  activeRunId: 'run-agent-audit',
};

const ARCHIVE_SESSION = {
  ...SESSION,
  sessionId: 'session-archive-audit',
  title: 'Archive Candidate',
  activeRunId: undefined,
};

const RUN = {
  schema: 'loom.agent.run.v1',
  runId: 'run-agent-audit',
  sessionId: SESSION.sessionId,
  status: 'waiting_approval',
  checkpoint: 'approval:approval-agent-audit',
  campaignIds: ['campaign-audit-1'],
  startedAt: '2026-07-15T00:01:00.000Z',
};

const RUNNING_MATRIX_STATUS = {
  ...AUDIT_MATRIX_WITH_DEVICE,
  campaigns: [{
    schema: 'loom.matrix.campaign.v2',
    campaignId: 'campaign-audit-1',
    status: 'running',
    concurrency: 1,
    counts: { total: 2, queued: 0, running: 2, completed: 0, failed: 0, needsHuman: 0 },
    deviceTasks: [{
      assignmentId: 'assignment-audit-1',
      deviceTaskId: 'task-agent-audit',
      deviceId: 'phone-audit-1',
      jobId: 'job-agent-audit',
      status: 'running',
      attempt: 1,
    }, {
      assignmentId: 'assignment-audit-decoy',
      deviceTaskId: 'task-agent-decoy',
      deviceId: 'phone-audit-decoy',
      jobId: 'job-agent-decoy',
      status: 'running',
      attempt: 1,
    }],
  }],
};

async function registerAgentSession(audit: AuditHarness, run = RUN) {
  await audit.registerRoute('GET', '/api/agent/bootstrap', { value: NATIVE_AGENT_BOOTSTRAP });
  await audit.registerRoute('GET', '/api/agent/sessions?limit=100', { value: { sessions: [SESSION, ARCHIVE_SESSION] } });
  await audit.registerRoute('GET', `/api/agent/sessions/${SESSION.sessionId}?limit=200`, {
    value: {
      session: SESSION,
      runs: [run],
      messages: [
        {
          schema: 'loom.agent.message.v1',
          messageId: 'message-agent-user',
          sessionId: SESSION.sessionId,
          role: 'user',
          status: 'completed',
          createdAt: '2026-07-15T00:01:00.000Z',
          blocks: [{ type: 'text', data: { text: '筛选今天新增的招聘简历' } }],
        },
        {
          schema: 'loom.agent.message.v1',
          messageId: 'message-agent-assistant',
          sessionId: SESSION.sessionId,
          role: 'assistant',
          status: 'completed',
          createdAt: '2026-07-15T00:02:00.000Z',
          blocks: [
            {
              type: 'tool',
              data: {
                runId: RUN.runId,
                toolCallId: 'tool-agent-audit',
                capability: 'loom.matrix.dispatch',
                status: 'completed',
              },
            },
            {
              type: 'matrix',
              data: {
                runId: RUN.runId,
                campaignId: 'campaign-audit-1',
                deviceIds: ['phone-audit-1'],
                status: 'running',
                total: 1,
                completed: 0,
                failed: 0,
              },
            },
            {
              type: 'approval',
              data: {
                approvalId: 'approval-agent-audit',
                status: 'pending',
                risk: 'outbound',
                actionSummary: '向候选人发送邀约草稿',
                capability: 'boss.message.draft',
                targets: { deviceIds: ['phone-audit-1'] },
                riskReason: '外发动作需要一次人工确认',
                expiresAt: '2099-12-31T23:59:59.000Z',
              },
            },
          ],
        },
      ],
    },
  });
  await audit.registerRoute('GET', `/api/agent/runs/${RUN.runId}/trace`, {
    value: {
      run,
      trace: [{
        traceId: 'trace-agent-audit',
        runId: RUN.runId,
        kind: 'runtime',
        name: '麓鸣原生智能体',
        status: 'completed',
        startedAt: '2026-07-15T00:01:00.000Z',
        durationMs: 420,
        inputSummary: {
          promptSnapshot: {
            snapshotId: 'snapshot-agent-audit',
            hash: 'sha256:audit-only',
            runtimeProfileId: 'loom-native',
            messageCount: 2,
            toolCount: 1,
          },
        },
      }],
      approvals: [],
    },
  });
  await audit.registerRoute('POST', '/api/agent/approvals/approval-agent-audit', {
    value: {
      approval: { approvalId: 'approval-agent-audit', status: 'rejected', decision: 'rejected' },
      run: { ...RUN, status: 'running', checkpoint: 'approval_rejected' },
    },
  });
  await audit.registerRoute('POST', '/api/matrix/tasks/task-agent-audit/pause', {
    value: { status: 'applied', deviceTask: { ...RUNNING_MATRIX_STATUS.campaigns[0].deviceTasks[0], status: 'paused' } },
  });
  await audit.registerRoute('POST', '/api/matrix/cancel', {
    value: { status: 'applied', campaign: { ...RUNNING_MATRIX_STATUS.campaigns[0], status: 'cancelled' } },
  });
  await audit.registerRoute('PATCH', `/api/agent/sessions/${SESSION.sessionId}`, {
    value: { session: { ...SESSION, title: '招聘筛选总控' } },
  });
  await audit.registerRoute('PATCH', `/api/agent/sessions/${ARCHIVE_SESSION.sessionId}`, {
    value: { session: { ...ARCHIVE_SESSION, status: 'archived' } },
  });
}

async function registerMatrixDeepLinkRoutes(audit: AuditHarness) {
  await audit.registerRoute('GET', '/api/matrix/status', { value: RUNNING_MATRIX_STATUS });
  await audit.registerRoute('GET', '/api/matrix/devices/phone-audit-1/timeline?limit=80', { value: { events: [] } });
  await audit.registerRoute('GET', '/api/matrix/devices/phone-audit-1/lease', { value: { lease: null } });
  await registerBatchScreens(audit, ['phone-audit-1']);
}

test.beforeEach(async ({ audit }) => {
  await audit.openAuthorizedShell();
});

test('central agent debugs runs, resolves approvals, manages sessions, and deep-links to the exact phone', async ({ audit, page }) => {
  await registerAgentSession(audit);
  await registerMatrixDeepLinkRoutes(audit);
  await navigateTo(audit, 'agent');

  const main = appMain(page);
  await expect(main.getByRole('heading', { name: '中枢智能体' })).toBeVisible();
  await expect(main.getByText('筛选今天新增的招聘简历')).toBeVisible();
  await expect(main.locator('[data-agent-matrix-attachment]')).toBeVisible();
  await expect(main.getByText('矩阵任务已分发', { exact: true })).toBeVisible();
  await expect(main.getByText('loom.matrix.dispatch', { exact: true })).toHaveCount(0);
  await expect(main.getByRole('button', { name: '打开调试器' })).toHaveCount(0);
  await expect(main.getByRole('button', { name: '新对话', exact: true })).toHaveCount(0);
  await expect(main.getByRole('button', { name: '新建对话' })).toHaveCount(1);

  const runDetailsButton = main.locator('[data-agent-matrix-attachment]').getByRole('button', { name: '运行详情' });
  await runDetailsButton.click();
  const debuggerPanel = main.locator('[data-agent-debugger]');
  await expect(debuggerPanel.getByText('麓鸣原生智能体')).toBeVisible();
  await expect(debuggerPanel.getByText('sha256:audit-only').first()).toBeVisible();
  const debuggerBackground = await debuggerPanel.evaluate((element) => getComputedStyle(element).backgroundColor);
  expect(debuggerBackground).not.toBe('transparent');
  expect(debuggerBackground).not.toMatch(/rgba\([^)]*,\s*(?:0|0?\.\d+)\)$/);
  await page.keyboard.press('Escape');
  await expect(debuggerPanel).toBeHidden();
  await expect(runDetailsButton).toBeFocused();

  const beforeApproval = await markCalls(audit);
  const approvalCard = main.locator('[data-agent-approval="approval-agent-audit"]');
  await approvalCard.getByRole('button', { name: '拒绝' }).click();
  await expectProxyIntent(audit, beforeApproval, {
    method: 'POST',
    path: '/api/agent/approvals/approval-agent-audit',
    body: { decision: 'reject' },
  });
  await expect(approvalCard.getByRole('button', { name: '拒绝' })).toBeHidden();
  await expect(approvalCard).toContainText('已拒绝');
  const resolvedApproval = main.locator('[data-agent-approval="approval-agent-audit"]');
  await expect(resolvedApproval.getByText('已拒绝', { exact: true })).toBeVisible();
  await expect(resolvedApproval.getByRole('button', { name: '批准' })).toHaveCount(0);
  await expect(resolvedApproval.getByRole('button', { name: '拒绝' })).toHaveCount(0);

  const beforePause = await markCalls(audit);
  await main.locator('[data-agent-matrix-attachment]').getByRole('button', { name: '暂停' }).click();
  await expectProxyIntent(audit, beforePause, {
    method: 'POST',
    path: '/api/matrix/tasks/task-agent-audit/pause',
    body: null,
  });

  const beforeCancel = await markCalls(audit);
  await main.locator('[data-agent-matrix-attachment]').getByRole('button', { name: '中断' }).click();
  await confirmDialog(page, '取消任务', '确认中断');
  await expectProxyIntent(audit, beforeCancel, {
    method: 'POST',
    path: '/api/matrix/cancel',
    body: { campaignId: 'campaign-audit-1' },
  });

  const beforeRename = await markCalls(audit);
  await main.getByRole('button', { name: '重命名 Recruitment Agent Demo' }).click();
  const renameInput = main.locator('aside input').nth(1);
  await expect(renameInput).toHaveValue('Recruitment Agent Demo');
  await renameInput.fill('招聘筛选总控');
  await renameInput.press('Enter');
  await expectProxyIntent(audit, beforeRename, {
    method: 'PATCH',
    path: `/api/agent/sessions/${SESSION.sessionId}`,
    body: { title: '招聘筛选总控' },
  });

  const beforeArchive = await markCalls(audit);
  await main.getByRole('button', { name: '归档 Archive Candidate' }).click();
  await confirmDialog(page, '归档对话', '归档');
  await expectProxyIntent(audit, beforeArchive, {
    method: 'PATCH',
    path: `/api/agent/sessions/${ARCHIVE_SESSION.sessionId}`,
    body: { status: 'archived' },
  });

  await main.locator('[data-agent-matrix-attachment]').getByRole('button', { name: '打开工作台' }).click();
  await expect(appMain(page).locator('[data-matrix-device-inspector][data-device-id="phone-audit-1"]')).toBeVisible();
  await expect(appMain(page).locator('[data-matrix-action-result]')).toContainText('campaign-audit-1');
});

test('Matrix attachment renders the valid device-task transition from authoritative campaign status', async ({ audit, page }) => {
  await registerAgentSession(audit);
  const pausedStatus = {
    ...RUNNING_MATRIX_STATUS,
    campaigns: RUNNING_MATRIX_STATUS.campaigns.map((campaign) => ({
      ...campaign,
      counts: { ...campaign.counts, running: 1 },
      deviceTasks: campaign.deviceTasks.map((deviceTask) => (
        deviceTask.deviceTaskId === 'task-agent-audit' ? { ...deviceTask, status: 'paused' } : deviceTask
      )),
    })),
  };
  await audit.registerRoute('GET', '/api/matrix/status', { value: pausedStatus });
  await audit.registerRoute('POST', '/api/matrix/tasks/task-agent-audit/resume', {
    value: { status: 'applied', deviceTask: { ...pausedStatus.campaigns[0].deviceTasks[0], status: 'running' } },
  });
  await navigateTo(audit, 'agent');

  const attachment = appMain(page).locator('[data-agent-matrix-attachment]');
  await expect(attachment.getByRole('button', { name: '继续' })).toBeVisible();
  await expect(attachment.getByRole('button', { name: '暂停' })).toHaveCount(0);

  const beforeResume = await markCalls(audit);
  await attachment.getByRole('button', { name: '继续' }).click();
  await expectProxyIntent(audit, beforeResume, {
    method: 'POST',
    path: '/api/matrix/tasks/task-agent-audit/resume',
    body: null,
  });
});

test('central agent creates a durable conversation and sends a frozen device scope with internal capability routing', async ({ audit, page }, testInfo) => {
  const newSession = {
    ...SESSION,
    sessionId: 'session-agent-new',
    title: '新对话',
    runtimeProfileId: 'loom-native',
    activeRunId: undefined,
  };
  await audit.registerRoute('GET', '/api/agent/bootstrap', {
    value: {
      ...NATIVE_AGENT_BOOTSTRAP,
      capabilities: [{ name: 'audit.crm.lookup', source: 'mcp', permission: 'read', risk: 'safe', available: true }],
    },
  });
  await audit.registerRoute('POST', '/api/agent/sessions', { value: { session: newSession } });
  await audit.registerRoute('PATCH', `/api/agent/sessions/${newSession.sessionId}`, {
    value: { session: { ...newSession, modelId: 'qwen3.7-plus' } },
  });
  await audit.registerRoute('POST', '/api/account/models/select', {
    value: { account: { loggedIn: true, selectedModels: { text: 'qwen3.7-plus' } } },
  });
  await audit.registerRoute('GET', '/api/matrix/status', { value: RUNNING_MATRIX_STATUS });
  await audit.registerRoute('GET', `/api/agent/sessions/${newSession.sessionId}?limit=200`, {
    value: { session: newSession, messages: [], runs: [] },
  });
  await audit.registerRoute('POST', `/api/agent/sessions/${newSession.sessionId}/messages`, {
    delayMs: 450,
    value: {
      message: {
        schema: 'loom.agent.message.v1',
        messageId: 'message-agent-new',
        sessionId: newSession.sessionId,
        role: 'user',
        status: 'completed',
        createdAt: '2026-07-15T00:20:00.000Z',
        blocks: [{ type: 'text', data: { text: '筛选两组设备里的新简历' } }],
      },
      run: {
        schema: 'loom.agent.run.v1',
        runId: 'run-agent-new',
        sessionId: newSession.sessionId,
        status: 'queued',
        campaignIds: [],
      },
    },
  });
  await navigateTo(audit, 'agent');

  const main = appMain(page);
  await expect(main.getByText('麓鸣原生智能体', { exact: true })).toBeVisible();
  await expect(main.getByText('模型已就绪', { exact: true })).toBeVisible();
  await expect(main.getByLabel('运行时')).toHaveCount(0);
  const beforeCreate = await markCalls(audit);
  await main.getByRole('button', { name: '新建对话' }).click();
  await expectProxyIntent(audit, beforeCreate, {
    method: 'POST',
    path: '/api/agent/sessions',
    body: { title: '新对话', runtimeProfileId: 'loom-native' },
  });

  const beforeModel = await markCalls(audit);
  await main.getByRole('button', { name: '选择模型' }).click();
  await page.screenshot({ path: testInfo.outputPath('agent-model-menu.png'), fullPage: false });
  await main.getByRole('button', { name: 'Qwen 3.7 Plus' }).click();
  await expectProxyIntent(audit, beforeModel, {
    method: 'PATCH',
    path: `/api/agent/sessions/${newSession.sessionId}`,
    body: { modelId: 'qwen3.7-plus' },
  });
  await main.getByRole('button', { name: '选择模型' }).click();
  const beforeDefaultModel = await markCalls(audit);
  await main.getByRole('button', { name: '设为麓鸣默认模型' }).click();
  await expectProxyIntent(audit, beforeDefaultModel, {
    method: 'POST',
    path: '/api/account/models/select',
    body: { textModel: 'qwen3.7-plus' },
  });

  await main.getByLabel('消息内容').fill('筛选两组设备里的新简历');
  await main.getByRole('button', { name: '选择任务范围' }).click();
  await page.screenshot({ path: testInfo.outputPath('agent-scope-menu.png'), fullPage: false });
  await main.getByRole('button', { name: /default/ }).click();
  await main.getByLabel('消息内容').click();
  await expect(main.getByText('audit.crm.lookup', { exact: true })).toHaveCount(0);
  const attachmentInput = main.locator('input[type="file"]');
  await attachmentInput.setInputFiles({
    name: 'candidate-notes.txt',
    mimeType: 'text/plain',
    buffer: Buffer.from('Candidate evidence line.\n'.repeat(2_000)),
  });
  const beforeSend = await markCalls(audit);
  await main.getByRole('button', { name: '发送', exact: true }).click();
  await expect(main.locator('[data-agent-thinking]')).toBeVisible({ timeout: 100 });

  await expect.poll(async () => {
    await audit.sync();
    return proxyIntents(audit.callLogs.slice(beforeSend)).some((intent) => {
      if (intent.path !== `/api/agent/sessions/${newSession.sessionId}/messages`) return false;
      const body = intent.body as Record<string, any>;
      return body.text === '筛选两组设备里的新简历'
        && body.runtimeProfileId === 'loom-native'
        && body.scopeMode === 'manual'
        && body.scope?.groups?.join(',') === 'default'
        && body.scope?.deviceIds?.length === 0
        && body.scope?.allOnline === false
        && !('targets' in body)
        && !('capabilityHints' in body)
        && body.attachments?.[0]?.name === 'candidate-notes.txt'
        && body.attachments?.[0]?.content?.startsWith('Candidate evidence line.')
        && body.attachments?.[0]?.content?.length <= 32_768
        && body.attachments?.[0]?.contentTruncated === true
        && typeof body.clientMessageId === 'string';
    });
  }).toBe(true);
  await expect(main.locator('[data-agent-message="message-agent-new"]').getByText('筛选两组设备里的新简历')).toBeVisible();
  await expect(main.locator('[data-agent-thinking]')).toBeVisible();
  await page.evaluate(({ sessionId, runId }) => {
    const storePath = '/src/stores/agentStore.ts';
    return import(storePath).then(({ useAgentStore }) => {
      useAgentStore.getState().mergeRealtimeEvent(sessionId, {
        schema: 'loom.realtime.event.v1',
        eventId: 'event-agent-first-delta',
        seq: 1,
        timestamp: '2026-07-15T00:20:01.000Z',
        topic: 'agent.run',
        entityId: runId,
        type: 'message.delta',
        data: {
          sessionId,
          runId,
          messageId: 'message-agent-first-delta',
          role: 'assistant',
          delta: '已开始处理',
        },
      });
    });
  }, { sessionId: newSession.sessionId, runId: 'run-agent-new' });
  await expect(main.locator('[data-agent-thinking]')).toBeHidden();

  await attachmentInput.setInputFiles({
    name: 'candidate-photo.png',
    mimeType: 'image/png',
    buffer: Buffer.from([0x89, 0x50, 0x4e, 0x47]),
  });
  await expect(main.getByText(/candidate-photo\.png/)).toBeHidden();
});

test('agent sends with native runtime plus bounded readable attachments only', async ({ audit, page }) => {
  await registerAgentSession(audit);
  const idleSession = { ...SESSION, activeRunId: undefined };
  await audit.registerRoute('GET', `/api/agent/sessions/${SESSION.sessionId}?limit=200`, {
    value: { session: idleSession, messages: [], runs: [] },
  });
  await audit.registerRoute('POST', `/api/agent/sessions/${SESSION.sessionId}/messages`, {
    value: {
      message: {
        schema: 'loom.agent.message.v1',
        messageId: 'message-agent-attachment',
        sessionId: SESSION.sessionId,
        role: 'user',
        status: 'completed',
        createdAt: '2026-07-15T00:20:00.000Z',
        blocks: [{ type: 'text', data: { text: '读取附件' } }],
      },
      run: {
        schema: 'loom.agent.run.v1',
        runId: 'run-agent-attachment',
        sessionId: SESSION.sessionId,
        status: 'queued',
        campaignIds: [],
      },
    },
  });
  await navigateTo(audit, 'agent');

  const main = appMain(page);
  await expect(main.getByText('麓鸣原生智能体', { exact: true })).toBeVisible();
  await expect(main.getByText('模型已就绪', { exact: true })).toBeVisible();
  await expect(main.getByLabel('运行时')).toHaveCount(0);
  await main.getByLabel('消息内容').fill('读取附件');
  await main.locator('input[type="file"]').setInputFiles([
    { name: 'notes.md', mimeType: 'text/markdown', buffer: Buffer.from('第一行\n第二行', 'utf8') },
    { name: 'archive.zip', mimeType: 'application/zip', buffer: Buffer.from([0x50, 0x4b, 0x03, 0x04]) },
  ]);
  await expect(main.getByText('notes.md', { exact: true })).toBeVisible();
  await expect(main.getByText('archive.zip', { exact: true })).toHaveCount(0);

  const beforeSend = await markCalls(audit);
  await main.getByRole('button', { name: '发送', exact: true }).click();
  await expect.poll(async () => {
    await audit.sync();
    return proxyIntents(audit.callLogs.slice(beforeSend)).find((intent) => (
      intent.path === `/api/agent/sessions/${SESSION.sessionId}/messages`
    ))?.body as Record<string, any> | undefined;
  }).toMatchObject({
    text: '读取附件',
    runtimeProfileId: 'loom-native',
    attachments: [{
      name: 'notes.md',
      type: 'text/markdown',
      content: '第一行\n第二行',
      truncated: false,
    }],
  });
});

const SQUARE_MATRIX_SCREEN = {
  schema: 'loom.matrix.screen.v1',
  capturedAt: '2026-07-15T00:00:00.000Z',
  screenHash: 'square-audit-screen',
  mime: 'image/png',
  width: 1,
  height: 1,
  notModified: false,
  image: 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=',
};

async function registerBatchScreens(audit: AuditHarness, deviceIds: string[]) {
  await audit.registerRoute('POST', '/api/matrix/screens', {
    value: {
      schema: 'loom.matrix.screens.v1',
      screens: deviceIds.map((deviceId) => ({
        ...SQUARE_MATRIX_SCREEN,
        deviceId,
        screenHash: `${deviceId}-square`,
      })),
      errors: [],
    },
  });
}

test('matrix confirmation is scoped to the current dispatch inputs and supported task actions', async ({ audit, page }) => {
  const preflightStatus = {
    ...RUNNING_MATRIX_STATUS,
    campaigns: RUNNING_MATRIX_STATUS.campaigns.map((campaign) => ({
      ...campaign,
      deviceTasks: campaign.deviceTasks.map((deviceTask) => ({ ...deviceTask, status: 'preflight' })),
    })),
  };
  await audit.registerRoute('GET', '/api/matrix/status', { value: preflightStatus });
  await audit.registerRoute('GET', '/api/matrix/devices/phone-audit-1/timeline?limit=80', { value: { events: [] } });
  await audit.registerRoute('GET', '/api/matrix/devices/phone-audit-1/lease', { value: { lease: null } });
  await registerBatchScreens(audit, ['phone-audit-1']);
  await audit.registerRoute('POST', '/api/matrix/dispatch', { value: { campaign: RUNNING_MATRIX_STATUS.campaigns[0] } });
  await navigateTo(audit, 'workbench');

  const main = appMain(page);
  const inspector = main.locator('[data-matrix-device-inspector]');
  await expect(inspector.getByRole('button', { name: '暂停', exact: true })).toHaveCount(0);
  await expect(inspector.getByRole('button', { name: '继续', exact: true })).toHaveCount(0);

  const target = main.getByRole('checkbox', { name: '任务目标' });
  await target.check();
  await main.getByPlaceholder('输入要在已选设备上执行的真实任务').fill('发布审核任务');
  await main.getByRole('button', { name: '高级参数' }).click();
  const drawer = main.locator('[data-matrix-task-drawer]');
  const confirmation = drawer.getByRole('checkbox');
  const template = drawer.getByLabel('模板 ID（留空为直接任务）');
  const mode = drawer.getByLabel('执行模式');
  const profile = drawer.getByLabel('执行档位');

  await template.fill('template-one');
  await mode.selectOption('full');
  await profile.selectOption('deep');
  await confirmation.check();
  await template.fill('template-two');
  await expect(confirmation).not.toBeChecked();
  await confirmation.check();
  await mode.selectOption('safe');
  await expect(confirmation).not.toBeChecked();
  await mode.selectOption('full');
  await confirmation.check();
  await profile.selectOption('fast');
  await expect(confirmation).not.toBeChecked();
  await profile.selectOption('deep');
  await confirmation.check();
  await drawer.getByRole('button', { name: '完成' }).click();

  await main.getByPlaceholder('输入要在已选设备上执行的真实任务').fill('发布更新后的审核任务');
  await main.getByRole('button', { name: '高级参数' }).click();
  await expect(confirmation).not.toBeChecked();
  await confirmation.check();
  await drawer.getByRole('button', { name: '完成' }).click();
  await target.uncheck();
  await target.check();
  await main.getByRole('button', { name: '高级参数' }).click();
  await expect(confirmation).not.toBeChecked();
  await confirmation.check();
  await drawer.getByRole('button', { name: '完成' }).click();

  const beforeDispatch = await markCalls(audit);
  await main.getByRole('button', { name: '下发任务' }).click();
  await expectProxyIntent(audit, beforeDispatch, {
    method: 'POST',
    path: '/api/matrix/dispatch',
    body: {
      prompt: '发布更新后的审核任务',
      templateId: 'template-two',
      target: { deviceIds: ['phone-audit-1'] },
      mode: 'full',
      profile: 'deep',
      confirmed: true,
    },
  });
  await main.getByRole('button', { name: '高级参数' }).click();
  await expect(confirmation).not.toBeChecked();
});

test('matrix manual touch maps to the contained image and ignores letterbox padding', async ({ audit, page }) => {
  await audit.registerRoute('GET', '/api/matrix/status', { value: AUDIT_MATRIX_WITH_DEVICE });
  await audit.registerRoute('GET', '/api/matrix/devices/phone-audit-1/timeline?limit=80', { value: { events: [] } });
  await audit.registerRoute('GET', '/api/matrix/devices/phone-audit-1/lease', { value: { lease: null } });
  await audit.registerRoute('POST', '/api/matrix/devices/phone-audit-1/lease', {
    value: {
      lease: {
        schema: 'loom.matrix.device_lease.v1',
        leaseId: 'lease-touch-audit',
        deviceId: 'phone-audit-1',
        holderType: 'human',
        holderId: 'touch-audit',
        mode: 'control',
        expiresAt: '2099-12-31T23:59:59.000Z',
      },
    },
  });
  await audit.registerRoute('POST', '/api/matrix/devices/phone-audit-1/control', { value: { status: 'applied' } });
  await registerBatchScreens(audit, ['phone-audit-1']);
  await navigateTo(audit, 'workbench');

  const main = appMain(page);
  await main.locator('[data-matrix-device-inspector]').getByRole('button', { name: '人工' }).click();
  await expect(main.getByRole('button', { name: '主页' })).toBeEnabled();
  const focus = main.locator('[data-matrix-focus-screen]');
  await expect(focus.getByRole('img', { name: 'Audit Phone 聚焦画面' })).toBeVisible();
  const box = await focus.boundingBox();
  expect(box).not.toBeNull();
  if (!box) throw new Error('focus screen did not produce a layout box');

  const beforePadding = await markCalls(audit);
  await page.mouse.click(box.x + box.width / 2, box.y + 8);
  await page.waitForTimeout(80);
  await audit.sync();
  expect(proxyIntents(audit.callLogs.slice(beforePadding)).filter((intent) => intent.path.endsWith('/control'))).toEqual([]);

  const renderedSize = Math.min(box.width, box.height);
  const imageTop = box.y + (box.height - renderedSize) / 2;
  const beforeTap = await markCalls(audit);
  await page.mouse.click(box.x + box.width / 2, imageTop + renderedSize * 0.25);
  await expect.poll(async () => {
    await audit.sync();
    return proxyIntents(audit.callLogs.slice(beforeTap)).filter((intent) => intent.path.endsWith('/control')).length;
  }).toBe(1);
  const tap = proxyIntents(audit.callLogs.slice(beforeTap)).find((intent) => intent.path.endsWith('/control'))?.body as Record<string, number | string>;
  expect(tap.action).toBe('tap');
  expect(tap.x).toBeCloseTo(0.5, 2);
  expect(tap.y).toBeCloseTo(0.25, 2);
});

test('matrix focus ignores stale timeline and lease responses from the previous device', async ({ audit, page }) => {
  const secondDevice = {
    ...AUDIT_MATRIX_WITH_DEVICE.devices[0],
    deviceId: 'phone-audit-2',
    name: 'Audit Phone Two',
    currentScreenSummary: 'second audit screen',
  };
  await audit.registerRoute('GET', '/api/matrix/status', {
    value: {
      ...AUDIT_MATRIX_WITH_DEVICE,
      devices: [...AUDIT_MATRIX_WITH_DEVICE.devices, secondDevice],
      summary: { total: 2, online: 2, busy: 0, failed: 0 },
    },
  });
  await audit.registerRoute('GET', '/api/matrix/devices/phone-audit-1/timeline?limit=80', {
    value: { events: [{ eventId: 'initial-event', type: 'initial.focus', message: 'initial first timeline', timestamp: '2026-07-15T00:00:00.000Z' }] },
  });
  await audit.registerRoute('GET', '/api/matrix/devices/phone-audit-1/lease', {
    value: { lease: null },
  });
  await audit.registerRoute('GET', '/api/matrix/devices/phone-audit-2/timeline?limit=80', {
    value: { events: [{ eventId: 'new-event', type: 'new.focus', message: 'current second timeline', timestamp: '2026-07-15T00:00:01.000Z' }] },
  });
  await audit.registerRoute('GET', '/api/matrix/devices/phone-audit-2/lease', {
    value: { lease: { schema: 'loom.matrix.device_lease.v1', leaseId: 'lease-new', deviceId: 'phone-audit-2', holderType: 'human', holderId: 'new', mode: 'control', expiresAt: '2099-12-31T22:22:22.000Z' } },
  });
  await registerBatchScreens(audit, ['phone-audit-1', 'phone-audit-2']);
  await navigateTo(audit, 'workbench');

  const main = appMain(page);
  await expect(main.locator('[data-matrix-device-inspector]').getByText('initial first timeline')).toBeVisible();
  await main.getByTitle('聚焦 Audit Phone Two').click();
  const inspector = main.locator('[data-matrix-device-inspector][data-device-id="phone-audit-2"]');
  await expect(inspector.getByText('current second timeline')).toBeVisible();
  await expect(inspector.getByText('human / 22:22:22')).toBeVisible();

  await audit.registerRoute('GET', '/api/matrix/devices/phone-audit-1/timeline?limit=80', {
    delayMs: 650,
    value: { events: [{ eventId: 'old-event', type: 'old.focus', message: 'stale first timeline', timestamp: '2026-07-15T00:00:02.000Z' }] },
  });
  await audit.registerRoute('GET', '/api/matrix/devices/phone-audit-1/lease', {
    delayMs: 650,
    value: { lease: { schema: 'loom.matrix.device_lease.v1', leaseId: 'lease-old', deviceId: 'phone-audit-1', holderType: 'human', holderId: 'old', mode: 'control', expiresAt: '2099-12-31T11:11:11.000Z' } },
  });
  const beforeStaleLoad = await markCalls(audit);
  await main.getByTitle('聚焦 Audit Phone', { exact: true }).click();
  await expect.poll(async () => {
    await audit.sync();
    return proxyIntents(audit.callLogs.slice(beforeStaleLoad)).some((intent) => (
      intent.path === '/api/matrix/devices/phone-audit-1/timeline?limit=80'
    ));
  }).toBe(true);
  await main.getByTitle('聚焦 Audit Phone Two').click();
  await expect(inspector.getByText('current second timeline')).toBeVisible();
  await page.waitForTimeout(720);
  await expect(inspector.getByText('stale first timeline')).toHaveCount(0);
  await expect(inspector.getByText('human / 11:11:11')).toHaveCount(0);
  await expect(inspector.getByText('current second timeline')).toBeVisible();
  await expect(inspector.getByText('human / 22:22:22')).toBeVisible();
});

test('agent and matrix never report connected while realtime ticket requests are failing', async ({ audit, page }) => {
  await registerAgentSession(audit);
  await audit.registerRoute('POST', '/api/realtime/tickets', { error: 'audit realtime unavailable' });
  await navigateTo(audit, 'agent');

  const main = appMain(page);
  await expect(main.getByText('连接失败', { exact: true })).toBeVisible({ timeout: 2_000 });
  await expect(main.getByText('实时', { exact: true })).toBeHidden();

  await registerMatrixDeepLinkRoutes(audit);
  await navigateTo(audit, 'workbench');
  await expect(appMain(page).getByText('Realtime connection failed', { exact: true })).toBeVisible({ timeout: 2_000 });
  await expect(appMain(page).getByText('实时状态已连接', { exact: true })).toBeHidden();
});

test('Agent presents tool calls as compact run-level execution groups without duplicate failures', async ({ audit, page }, testInfo) => {
  test.skip(testInfo.project.name !== 'edge-1200x800', 'Focused Agent lifecycle audit runs once.');
  const activeRun = { ...RUN, status: 'running', checkpoint: 'synthesizing', campaignIds: [] };
  const failedRun = {
    ...RUN,
    runId: 'run-agent-failed-history',
    status: 'failed',
    checkpoint: 'tool_failed',
    campaignIds: [],
    completedAt: '2026-07-15T00:02:30.000Z',
  };
  const activeSession = { ...SESSION, activeRunId: activeRun.runId };
  await registerAgentSession(audit, activeRun);
  await audit.registerRoute('GET', `/api/agent/sessions/${SESSION.sessionId}?limit=200`, {
    value: {
      session: activeSession,
      runs: [failedRun, activeRun],
      messages: [
        {
          schema: 'loom.agent.message.v1',
          messageId: 'message-agent-tool-user',
          sessionId: SESSION.sessionId,
          role: 'user',
          status: 'completed',
          createdAt: '2026-07-15T00:01:00.000Z',
          blocks: [{ type: 'text', data: { text: '生成一张图片并传到手机' } }],
        },
        {
          schema: 'loom.agent.message.v1',
          messageId: 'tool-run:run-agent-failed-history',
          sessionId: SESSION.sessionId,
          role: 'tool',
          status: 'failed',
          createdAt: '2026-07-15T00:01:30.000Z',
          blocks: [{
            type: 'tool',
            data: {
              runId: failedRun.runId,
              toolCallId: 'tool-failed-phone',
              capability: 'loom.phone.control',
              status: 'failed',
              code: 'device_offline',
              message: 'Device offline',
              recoverable: true,
            },
          }],
        },
        {
          schema: 'loom.agent.message.v1',
          messageId: `tool-run:${activeRun.runId}`,
          sessionId: SESSION.sessionId,
          role: 'tool',
          status: 'completed',
          createdAt: '2026-07-15T00:02:00.000Z',
          blocks: [
            {
              type: 'tool',
              data: { runId: activeRun.runId, toolCallId: 'tool-image', capability: 'loom.media.image.generate', status: 'completed' },
            },
            {
              type: 'tool',
              data: { runId: activeRun.runId, toolCallId: 'tool-transfer', capability: 'loom.phone.control', status: 'completed' },
            },
          ],
        },
      ],
    },
  });

  await navigateTo(audit, 'agent');
  const main = appMain(page);
  const groups = main.locator('[data-agent-tool-group]');
  await expect(groups).toHaveCount(2);
  await expect(groups.filter({ hasText: '1 步未完成' })).toHaveAttribute('data-expanded', 'true');
  await expect(groups.filter({ hasText: '已完成 2 步' })).toHaveAttribute('data-expanded', 'false');
  await expect(main.locator('[data-agent-tool-error]')).toHaveCount(1);
  await expect(main.getByText('设备暂时离线', { exact: true })).toBeVisible();
  await expect(main.getByText('任务执行失败', { exact: true })).toHaveCount(0);
  await expect(main.locator('[data-agent-thinking]')).toContainText('麓鸣正在整理结果');

  await page.evaluate(({ sessionId, runId }) => {
    const storePath = '/src/stores/agentStore.ts';
    return import(storePath).then(({ useAgentStore }) => {
      useAgentStore.getState().mergeRealtimeEvent(sessionId, {
        schema: 'loom.realtime.event.v1',
        eventId: 'event-agent-final-stream',
        seq: 1,
        timestamp: '2026-07-15T00:03:00.000Z',
        topic: 'agent.run',
        entityId: runId,
        type: 'message.delta',
        data: {
          sessionId,
          runId,
          messageId: 'message-agent-final-stream',
          role: 'assistant',
          delta: '图片已经生成并传入手机相册。',
        },
      });
    });
  }, { sessionId: SESSION.sessionId, runId: activeRun.runId });
  await expect(main.locator('[data-agent-thinking]')).toBeHidden();
  await expect(main.getByText('图片已经生成并传入手机相册。', { exact: true })).toBeVisible();
});

test('Agent identity and controls stay framed at the shipped desktop viewports', async ({ audit, page }, testInfo) => {
  test.skip(testInfo.project.name !== 'edge-1200x800', 'Exact Agent viewport audit runs once.');
  await registerAgentSession(audit, { ...RUN, status: 'running', checkpoint: 'executing' });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await expect(page.locator('[data-loom-splash]')).toBeHidden({ timeout: 12_000 });

  for (const viewport of [
    { width: 1200, height: 800 },
    { width: 960, height: 640 },
    { width: 760, height: 640 },
  ]) {
    await page.setViewportSize(viewport);
    await navigateTo(audit, 'agent');

    const main = appMain(page);
    const workbench = main.locator('[data-agent-workbench]');
    const header = workbench.locator('[data-agent-header]');
    const runBadges = header.locator('[data-agent-run-badges]');
    await expect(workbench).toBeVisible();
    await workbench.evaluate(async (element) => {
      await Promise.all(element.getAnimations().map((animation) => animation.finished.catch(() => undefined)));
    });
    await expect(header.locator('[data-loom-agent-mark]').first()).toBeVisible();
    await expect(header.locator('img[src="/loom-motion/agent-core-v1.png"]')).toBeVisible();
    await expect(header.locator('[data-agent-executing="true"]')).toHaveCount(1);
    await expect(main.getByText('AGT', { exact: true })).toHaveCount(0);

    if (viewport.width >= 1200) await expect(runBadges).toBeVisible();
    else await expect(runBadges).toBeHidden();

    for (const label of ['新建对话', `重命名 ${SESSION.title}`, `归档 ${SESSION.title}`]) {
      const control = main.getByRole('button', { name: label });
      await expect(control).toBeVisible();
      await expect(control.locator('svg')).toBeVisible();
    }

    const metrics = await workbench.evaluate((element) => {
      const root = document.documentElement;
      const box = element.getBoundingClientRect();
      const mark = element.querySelector<HTMLElement>('[data-loom-agent-mark]')?.getBoundingClientRect();
      const newButton = element.querySelector<HTMLElement>('button[aria-label="新建对话"]')?.getBoundingClientRect();
      const stream = element.querySelector<HTMLElement>('[data-agent-conversation-stream]')?.getBoundingClientRect();
      return {
        rootOverflow: root.scrollWidth - root.clientWidth,
        bodyOverflow: document.body.scrollWidth - document.body.clientWidth,
        workbenchLeft: box.left,
        workbenchRight: box.right,
        workbenchBottom: box.bottom,
        markWidth: mark?.width || 0,
        markHeight: mark?.height || 0,
        newButtonWidth: newButton?.width || 0,
        newButtonHeight: newButton?.height || 0,
        streamLeft: stream?.left || 0,
        streamRight: stream?.right || 0,
        streamWidth: stream?.width || 0,
        width: window.innerWidth,
        height: window.innerHeight,
      };
    });
    expect(metrics.rootOverflow).toBeLessThanOrEqual(0);
    expect(metrics.bodyOverflow).toBeLessThanOrEqual(0);
    expect(metrics.workbenchLeft).toBeGreaterThanOrEqual(0);
    expect(metrics.workbenchRight).toBeLessThanOrEqual(metrics.width);
    expect(metrics.workbenchBottom).toBeLessThanOrEqual(metrics.height);
    expect(metrics.markWidth).toBe(36);
    expect(metrics.markHeight).toBe(36);
    expect(metrics.newButtonWidth).toBe(36);
    expect(metrics.newButtonHeight).toBe(36);
    expect(metrics.streamLeft).toBeGreaterThanOrEqual(metrics.workbenchLeft);
    expect(metrics.streamRight).toBeLessThanOrEqual(metrics.workbenchRight);
    expect(metrics.streamWidth).toBeGreaterThan(300);
    await page.screenshot({
      path: testInfo.outputPath(`agent-identity-${viewport.width}x${viewport.height}.png`),
      fullPage: false,
    });
  }
});

test('agent and matrix production layouts remain framed at the three release viewports', async ({ audit, page }, testInfo) => {
  test.skip(testInfo.project.name !== 'edge-1200x800', 'Exact release viewport audit runs once.');
  await registerAgentSession(audit);
  await registerMatrixDeepLinkRoutes(audit);
  await expect(page.locator('[data-loom-splash]')).toBeHidden({ timeout: 12_000 });

  for (const viewport of [
    { width: 1600, height: 1000 },
    { width: 1280, height: 800 },
    { width: 1100, height: 720 },
  ]) {
    await page.setViewportSize(viewport);
    await navigateTo(audit, 'agent');
    const agentWorkbench = appMain(page).locator('[data-agent-workbench]');
    await expect(agentWorkbench).toBeVisible();
    await agentWorkbench.evaluate(async (element) => {
      await Promise.all(element.getAnimations().map((animation) => animation.finished.catch(() => undefined)));
    });
    await page.screenshot({
      path: testInfo.outputPath(`agent-${viewport.width}x${viewport.height}.png`),
      fullPage: false,
    });
    await appMain(page).locator('[data-agent-matrix-attachment]').getByRole('button', { name: '运行详情' }).click();
    await expect(appMain(page).locator('[data-agent-debugger]')).toBeVisible();
    await page.screenshot({
      path: testInfo.outputPath(`agent-debug-${viewport.width}x${viewport.height}.png`),
      fullPage: false,
    });
    await appMain(page).locator('[data-agent-debugger]').getByRole('button', { name: '关闭运行详情' }).click();

    await appMain(page).locator('[data-agent-matrix-attachment]').getByRole('button', { name: '打开工作台' }).click();
    await expect(appMain(page).locator('[data-matrix-device-inspector][data-device-id="phone-audit-1"]')).toBeVisible();
    const matrixWorkbench = appMain(page).locator('[data-white-label-layout="phone-matrix"]');
    await matrixWorkbench.evaluate(async (element) => {
      await Promise.all(element.getAnimations().map((animation) => animation.finished.catch(() => undefined)));
    });
    const metrics = await page.evaluate(() => {
      const root = document.documentElement;
      const shell = document.querySelector<HTMLElement>('[data-commercial-app-shell]');
      const main = document.querySelector<HTMLElement>('[data-commercial-app-shell] > div > main');
      const accessGate = document.querySelector<HTMLElement>('[data-phone-matrix-access-granted]');
      const workbench = document.querySelector<HTMLElement>('[data-white-label-layout="phone-matrix"]');
      const mainBox = main?.getBoundingClientRect();
      const accessBox = accessGate?.getBoundingClientRect();
      const box = workbench?.getBoundingClientRect();
      return {
        rootOverflow: root.scrollWidth - root.clientWidth,
        bodyOverflow: document.body.scrollWidth - document.body.clientWidth,
        shellRight: shell?.getBoundingClientRect().right || 0,
        mainTop: mainBox?.top || 0,
        mainBottom: mainBox?.bottom || 0,
        accessTop: accessBox?.top || 0,
        accessBottom: accessBox?.bottom || 0,
        workbenchTop: box?.top || 0,
        workbenchLeft: box?.left || 0,
        workbenchRight: box?.right || 0,
        workbenchBottom: box?.bottom || 0,
        width: window.innerWidth,
        height: window.innerHeight,
      };
    });
    expect(metrics.rootOverflow).toBeLessThanOrEqual(0);
    expect(metrics.bodyOverflow).toBeLessThanOrEqual(0);
    expect(metrics.shellRight).toBeLessThanOrEqual(metrics.width);
    expect(metrics.workbenchLeft).toBeGreaterThanOrEqual(0);
    expect(metrics.workbenchRight).toBeLessThanOrEqual(metrics.width);
    expect(metrics.workbenchBottom, JSON.stringify(metrics)).toBeLessThanOrEqual(metrics.height);
    await page.screenshot({
      path: testInfo.outputPath(`matrix-${viewport.width}x${viewport.height}.png`),
      fullPage: false,
    });
  }
});
