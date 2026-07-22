import type { TauriMockSeed } from './tauri-ipc-mock';

export const AUDIT_ACCOUNT = {
  loggedIn: true,
  source: 'playwright-audit',
  account: 'audit@example.invalid',
  memberId: 'audit-member',
  plan: 'team',
  status: 'active',
  models: {
    text: ['audit-text-model'],
    image: ['audit-image-model'],
    video: ['audit-video-model'],
  },
  selectedModels: {
    text: 'audit-text-model',
    image: 'audit-image-model',
    videoDraft: 'audit-video-model',
  },
  subscription: {
    loggedIn: true,
    mode: 'native',
    plan: 'Audit Team',
    balance: '100.00',
    expiresAt: '2099-12-31',
    usage: { usedQuota: 0, requestCount: 0 },
  },
};

export const AUDIT_DIAGNOSTICS = {
  basePath: 'C:\\LOOM\\playwright-audit',
  serviceRunning: false,
  servicePid: null,
  startupState: 'idle',
  checks: [
    {
      id: 'python_runtime',
      label: 'Python runtime',
      status: 'ok',
      message: 'Available in isolated audit fixture',
      repairable: false,
    },
    {
      id: 'node',
      label: 'Node.js',
      status: 'ok',
      message: 'Available in isolated audit fixture',
      repairable: false,
    },
    {
      id: 'data_dir',
      label: 'Data directory',
      status: 'ok',
      message: 'Local mock only',
      repairable: false,
    },
  ],
  summary: { status: 'ok', ok: 3, warnings: 0, failed: 0, total: 3 },
  repairAvailable: false,
  timing: { totalMs: 1, checksMs: {}, measuredAt: '2026-07-15T00:00:00.000Z' },
};

export const AUDIT_MATRIX_STATUS = {
  schema: 'loom.matrix.status.v1',
  updatedAt: '2026-07-15T00:00:00.000Z',
  devices: [],
  campaigns: [],
  summary: { total: 0, online: 0, busy: 0, failed: 0 },
};

export const AUDIT_AGENT_BOOTSTRAP = {
  runtimeProfiles: [
    { runtimeProfileId: 'audit-runtime', name: 'Audit Runtime', available: true, isDefault: true },
  ],
  defaultRuntimeProfileId: 'audit-runtime',
  models: [{ modelId: 'audit-text-model', name: 'Audit Text Model', available: true }],
  defaultModelId: 'audit-text-model',
  capabilities: [
    { name: 'loom.matrix.dispatch', source: 'internal', permission: 'control_safe', risk: 'safe', available: true },
    { name: 'audit.crm.lookup', source: 'mcp', permission: 'read', risk: 'safe', available: true },
  ],
  permissions: { matrix: true, mcp: true },
};

export function createBaselineSeed(): TauriMockSeed {
  return {
    commands: {
      get_bridge_port: { value: 18_791 },
      get_portable_base_path: { value: 'C:\\LOOM\\playwright-audit' },
      'plugin:event|listen': { value: 1 },
      'plugin:event|unlisten': { value: null },
      'plugin:window|close': { value: null },
      'plugin:window|minimize': { value: null },
      'plugin:window|set_title': { value: null },
      'plugin:window|toggle_maximize': { value: null },
    },
    routes: {
      'POST /api/config/read': {
        value: {
          data: {
            models: {
              providers: {
                audit: { apiKey: 'local-audit-key', baseUrl: 'http://audit.invalid/v1' },
              },
            },
          },
        },
      },
      'GET /api/process/status': {
        value: { running: false, processAlive: false, startupState: 'idle', pid: null, portReady: false },
      },
      'GET /api/update/check': {
        value: {
          current: '2.3.0',
          latest: '2.3.0',
          hasUpdate: false,
          notes: '',
          publishedAt: '',
          releaseUrl: '',
          size: 0,
        },
      },
      'GET /api/update/result': { value: { pending: false, result: null } },
      'GET /api/theme/current': { value: { theme: null, isCustom: false, merchantId: null } },
      'GET /api/account/current': { value: { account: AUDIT_ACCOUNT } },
      'GET /api/account/capabilities': {
        value: {
          capabilities: {
            passwordLogin: true,
            inlineEmailCode: true,
            inlineRegistration: true,
            webRegistrationRequired: false,
            emailVerificationEnabled: true,
            turnstileRequired: false,
            emailConfigured: true,
          },
        },
      },
      'GET /api/components/status': {
        value: {
          manifest: {
            schemaVersion: 1,
            product: 'LOOM',
            channel: 'audit',
            version: '0.0.0-audit',
            publishedAt: '2026-07-15T00:00:00.000Z',
            minLauncherVersion: '0.0.0',
          },
          components: [],
          installLocked: false,
        },
      },
      'GET /api/components/model-config/status?componentId=codex-desktop': {
        value: {
          status: {
            componentId: 'codex-desktop',
            supported: true,
            configured: false,
            installed: false,
            status: 'not_installed',
            message: 'Not installed in the isolated audit fixture',
            availableModels: [],
          },
        },
      },
      'GET /api/jobs/list?limit=20': { value: { jobs: [] } },
      'GET /api/jobs/list?limit=40': { value: { jobs: [] } },
      'GET /api/log/get?*': {
        value: { log: '', offset: 0, generation: 'e2e-empty-log', reset: false },
      },
      'GET /api/diagnostics/prerequisites': { value: AUDIT_DIAGNOSTICS },
      'GET /api/diagnostics/run': { value: AUDIT_DIAGNOSTICS },
      'GET /api/media/config': {
        value: {
          config: {
            image: { baseUrl: '', model: 'audit-image-model', size: '1024x1024', count: 1, hasApiKey: false },
            video: {
              providerId: 'custom',
              apiBase: '',
              model: 'audit-video-model',
              mode: 't2v',
              resolution: '720P',
              duration: 5,
              ratio: '16:9',
              hasApiKey: false,
            },
          },
        },
      },
      'GET /api/media/assets?*': {
        value: { items: [], nextCursor: '', hasMore: false },
      },
      'GET /api/matrix/acquisition': {
        value: {
          schema: 'loom.customer_acquisition.v1',
          updatedAt: '2026-07-15T00:00:00.000Z',
          contentTasks: [],
          leads: [],
          customers: [],
          drafts: [],
          agentRuns: [],
          sop: [],
          logs: [],
          stats: {
            contentTasks: 0,
            leads: 0,
            customers: 0,
            agentRuns: 0,
            draftsPending: 0,
            approvedDrafts: 0,
            pendingSync: 0,
          },
          outboundPolicy: ['draft_only', 'manual_confirm', 'audit_log'],
          integrations: {
            feishu: {
              cliInstalled: false,
              connected: false,
              pendingCount: 0,
              auth: { loggedIn: false, botReady: false },
              table: {},
              lastSync: {},
            },
          },
        },
      },
      'GET /api/matrix/status': { value: AUDIT_MATRIX_STATUS },
      'POST /api/realtime/tickets': {
        value: {
          ticket: 'audit-single-use-ticket',
          streamUrl: '/__loom_audit_stream',
          expiresAt: '2099-12-31T23:59:59.000Z',
        },
      },
      'GET /api/agent/bootstrap': { value: AUDIT_AGENT_BOOTSTRAP },
      'GET /api/agent/sessions?limit=100': { value: { sessions: [] } },
      'GET /api/matrix/watch': { value: { schema: 'loom.matrix.events.v1', events: [] } },
      'GET /api/matrix/experience': {
        value: { summary: { total: 0, success: 0, successRate: 0 }, templateSuggestions: [] },
      },
      'POST /api/license/authorized': { value: { authorized: true, feature: 'matrix.devices' } },
      'GET /api/phone/config': { value: { selectedDeviceId: '', configured: false, devices: [] } },
      'GET /api/wire/current': {
        value: {
          wire: {
            ok: true,
            managedBy: 'heang_account',
            provider: 'audit',
            models: { text: 'audit-text-model', phone: 'audit-text-model', image: 'audit-image-model', video: 'audit-video-model' },
            modelLists: { text: ['audit-text-model'], phone: ['audit-text-model'], image: ['audit-image-model'], video: ['audit-video-model'] },
            targets: {},
            updatedAt: '2026-07-15T00:00:00.000Z',
          },
        },
      },
    },
  };
}
