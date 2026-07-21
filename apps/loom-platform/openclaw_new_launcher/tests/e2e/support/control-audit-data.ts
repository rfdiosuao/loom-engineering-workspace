import { AUDIT_ACCOUNT, AUDIT_DIAGNOSTICS, AUDIT_MATRIX_STATUS } from './mock-responses';

export const AUDIT_SUBSCRIPTION = {
  ...AUDIT_ACCOUNT.subscription,
  purchaseUrl: 'https://account.heang.test/subscription',
  webViewUrl: 'https://account.heang.test/subscription',
  message: 'isolated subscription snapshot',
};

export const AUDIT_ACCOUNT_WITH_CHOICES = {
  ...AUDIT_ACCOUNT,
  purchaseUrl: AUDIT_SUBSCRIPTION.purchaseUrl,
  models: {
    text: ['audit-text-model', 'audit-text-model-2'],
    image: ['audit-image-model', 'audit-image-model-2'],
    video: ['audit-video-model', 'audit-video-model-2'],
  },
  subscription: AUDIT_SUBSCRIPTION,
};

export const AUDIT_LOGGED_OUT_ACCOUNT = {
  loggedIn: false,
  source: 'playwright-audit',
  account: '',
  memberId: '',
  plan: 'guest',
  status: 'logged_out',
  models: { text: [], image: [], video: [] },
  selectedModels: { text: '', image: '', videoDraft: '' },
  subscription: {
    loggedIn: false,
    mode: 'native',
    plan: 'Guest',
    balance: '0.00',
    expiresAt: '',
    purchaseUrl: AUDIT_SUBSCRIPTION.purchaseUrl,
    usage: { usedQuota: 0, requestCount: 0 },
  },
  purchaseUrl: AUDIT_SUBSCRIPTION.purchaseUrl,
};

export const AUDIT_PHONE_CONFIG = {
  selectedDeviceId: 'phone-audit-1',
  configured: true,
  devices: [
    {
      id: 'phone-audit-1',
      deviceId: 'phone-audit-1',
      name: 'Audit Phone',
      baseUrl: 'http://192.0.2.10:9527',
      tokenAvailable: true,
      configured: true,
      selected: true,
      lastSeenAt: '2026-07-15T00:00:00.000Z',
    },
  ],
};

export const AUDIT_MATRIX_WITH_DEVICE = {
  ...AUDIT_MATRIX_STATUS,
  devices: [
    {
      deviceId: 'phone-audit-1',
      name: 'Audit Phone',
      group: 'default',
      online: true,
      busy: false,
      currentTaskId: null,
      heartbeatAt: '2026-07-15T00:00:00.000Z',
      currentScreenSummary: 'isolated audit screen',
      failureCount: 0,
      model: 'audit-text-model',
    },
  ],
  summary: { total: 1, online: 1, busy: 0, failed: 0 },
};

export const AUDIT_MATRIX_EVENT = {
  eventId: 'event-audit-1',
  type: 'device.online',
  deviceId: 'phone-audit-1',
  message: 'Audit Phone entered the isolated event feed',
  timestamp: '2026-07-15T00:00:00.000Z',
};

export const AUDIT_FEISHU_STATUS = {
  schema: 'loom.acquisition.feishu.v1',
  cliInstalled: true,
  connected: true,
  pendingCount: 0,
  auth: {
    loggedIn: true,
    botReady: true,
    identity: 'audit-bot',
    userName: 'Playwright Audit',
    message: 'isolated mock only',
  },
  table: {
    url: 'https://example.feishu.cn/base/audit?table=tblAudit',
    baseToken: 'audit-base-token',
    tableId: 'tblAudit',
    name: '麓鸣获客线索表',
    fields: ['线索', '状态'],
  },
  lastSync: {
    leadId: 'lead-audit-1',
    syncStatus: 'synced',
    syncError: '',
    recordId: 'record-audit-1',
    updatedAt: '2026-07-15T00:00:00.000Z',
  },
};

const COMPONENT_NAMES: Record<string, [string, string]> = {
  'codex-desktop': ['ChatGPT Codex 原版', 'OpenAI 官方 ChatGPT 桌面应用，内含 Codex，由 Microsoft Store 安装和更新'],
  'claude-code': ['Claude Code', 'Anthropic 命令行编程智能体'],
  opencode: ['opencode', '终端优先的 AI 编程工具'],
  'openclaw-companion': ['OpenClaw', '多智能体编程工作台'],
  hermes: ['Hermes', 'Hermes 智能体运行时'],
};

export function componentSnapshot(status = 'not_installed') {
  return {
    manifest: {
      schemaVersion: 1,
      product: 'LOOM',
      channel: 'audit',
      version: '0.0.0-audit',
      publishedAt: '2026-07-15T00:00:00.000Z',
      minLauncherVersion: '0.0.0',
    },
    components: Object.entries(COMPONENT_NAMES).map(([id, [name, description]]) => ({
      id,
      name,
      description,
      version: '1.0.0-audit',
      installedVersion: status === 'not_installed' ? null : '1.0.0-audit',
      previousVersion: null,
      status,
      platform: 'windows',
      arch: 'x64',
      type: 'installer',
      size: 1,
      entry: `${id}.cmd`,
      installPath: `C:\\LOOM\\playwright-audit\\${id}`,
      category: 'agent',
      officialUrl: id === 'codex-desktop' ? 'https://openai.com/chatgpt/desktop/' : '',
      urls: [],
      updatedAt: '2026-07-15T00:00:00.000Z',
      errorCode: null,
      errorMessage: null,
    })),
    installLocked: false,
  };
}

export const AUDIT_MODEL_CONFIG_STATUS = {
  componentId: 'codex-desktop',
  supported: true,
  configured: false,
  installed: true,
  status: 'ready',
  message: 'Managed model is available in the isolated audit fixture',
  availableModels: ['audit-text-model', 'audit-text-model-2'],
  model: 'audit-text-model',
  managedBy: 'heang_account',
  wireManagedBy: 'heang_account',
  channelMode: 'managed',
  provider: 'audit',
  baseUrl: 'https://api.example.invalid/v1',
};

export const AUDIT_REPAIRABLE_DIAGNOSTICS = {
  ...AUDIT_DIAGNOSTICS,
  checks: [
    ...AUDIT_DIAGNOSTICS.checks,
    {
      id: 'audit_repairable',
      label: 'Audit repair target',
      status: 'warn',
      message: 'Repair is mocked and cannot touch the host',
      repairable: true,
    },
  ],
  summary: { status: 'warn', ok: 3, warnings: 1, failed: 0, total: 4 },
  repairAvailable: true,
};
