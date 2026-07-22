import { invoke } from '@tauri-apps/api/core';
import { APP_DISPLAY_NAME } from '../version';
import type { License } from '../types';
import { saveCachedComponentSnapshot } from './componentStatusCache';
import type {
  AgentApproval,
  AgentBootstrapResponse,
  AgentRun,
  AgentRunTraceResponse,
  AgentSession,
  AgentSessionDetailResponse,
  AgentSessionListResponse,
  CreateAgentSessionRequest,
  ResolveAgentApprovalRequest,
  SendAgentMessageRequest,
  SendAgentMessageResponse,
  UpdateAgentSessionRequest,
} from '../types/agent';
import type {
  AcquireMatrixLeaseRequest,
  LegacyMatrixDispatchRequest,
  MatrixCommandResponse,
  MatrixControlRequest,
  MatrixDeviceLease,
  MatrixDeviceSummary,
  MatrixDispatchRequest,
  MatrixDispatchResponse,
  MatrixEvent,
  MatrixScreen,
  MatrixScreenBatchRequest,
  MatrixScreenBatchResponse,
  MatrixStatusSnapshot,
} from '../types/matrix';
import type { RealtimeStreamTopic, StreamTicketRequest, StreamTicketResponse } from '../types/realtime';

export type { AgentApproval, AgentRun, AgentSession } from '../types/agent';
export type {
  MatrixCampaign,
  MatrixDeviceLease,
  MatrixDeviceSummary,
  MatrixEvent,
  MatrixScreen,
  MatrixStatusSnapshot,
} from '../types/matrix';

let bridgeStartup: Promise<void> | null = null;
let bridgeHttpBase = '';
const BRIDGE_STARTUP_RETRIES = 480;
const BRIDGE_STARTUP_INTERVAL_MS = 500;
const BRIDGE_PORT_STORAGE_KEY = 'loom.bridge.port';

function getErrorMessage(error: unknown): string {
  if (typeof error === 'string') return error;
  if (error && typeof error === 'object') {
    const record = error as Record<string, unknown>;
    if (typeof record.error === 'string') return record.error;
    if (typeof record.message === 'string') return record.message;
  }
  return '';
}

function isApiErrorResponse(value: unknown): value is Record<string, unknown> {
  if (!value || typeof value !== 'object' || !('error' in value)) return false;
  const error = (value as Record<string, unknown>).error;
  return typeof error !== 'string' || error.trim().length > 0;
}

export function parseApiErrorPayload(value: unknown): Record<string, unknown> | null {
  if (value && typeof value === 'object') {
    const record = value as Record<string, unknown>;
    if ('errorCode' in record || Array.isArray(record.remediation)) return record;
  }
  const text = typeof value === 'string' ? value : getErrorMessage(value);
  const jsonStart = text.indexOf('{');
  if (jsonStart < 0) return null;
  try {
    const payload = JSON.parse(text.slice(jsonStart));
    return payload && typeof payload === 'object' && !Array.isArray(payload)
      ? payload as Record<string, unknown>
      : null;
  } catch {
    return null;
  }
}

export function parseErrorText(value: unknown): string {
  const text = getErrorMessage(value).trim();
  if (!text) return '';
  const jsonStart = text.indexOf('{');
  if (jsonStart >= 0) {
    const candidate = text.slice(jsonStart);
    try {
      const payload = JSON.parse(candidate) as Record<string, any>;
      const metaMessage = payload?._meta?.error?.message;
      if (typeof metaMessage === 'string' && metaMessage.trim()) return friendlyErrorText(metaMessage.trim());
      if (typeof payload.error === 'string' && payload.error.trim()) return friendlyErrorText(payload.error.trim());
      if (typeof payload.message === 'string' && payload.message.trim()) return friendlyErrorText(payload.message.trim());
    } catch {
      // Keep the original text below.
    }
  }
  return friendlyErrorText(text.replace(/^\[\d+\]\s*/, '').trim());
}

function friendlyErrorText(text: string): string {
  if (/cannot read properties of undefined \(reading 'invoke'\)/i.test(text) || /__tauri(_internals)?__/i.test(text)) {
    return `当前不在 ${APP_DISPLAY_NAME} 桌面运行环境中，无法连接本地 Bridge。请使用桌面应用运行，或打开诊断查看 Bridge 状态。`;
  }
  if (/ipc.*not.*available/i.test(text) || /tauri.*not.*available/i.test(text)) {
    return `桌面通信通道不可用，请使用 ${APP_DISPLAY_NAME} 桌面应用运行。`;
  }
  if (/username or password is incorrect|invalid username or password/i.test(text)) {
    return '用户名、邮箱或密码错误，或账号已被禁用';
  }
  if (/^newapi_network_error:/i.test(text)) {
    return '无法连接模型服务，请检查网络、服务地址或稍后重试';
  }
  if (/launcher_token_bridge_no_key/i.test(text)) {
    return '模型服务未返回可用的 API Key，请确认账号权限或手动提供 API Token';
  }
  if (/bind ticket is required/i.test(text)) {
    return '请输入网站绑定码';
  }
  if (/bind_ticket_no_key/i.test(text)) {
    return '网站绑定成功但未返回可用 API Key，请重新生成绑定码后再试';
  }
  if (/not_logged_in/i.test(text)) {
    return '尚未登录模型账号';
  }
  if (/invalid parameters?/i.test(text)) {
    return '请求参数无效，请检查用户名/邮箱、密码和模型服务地址';
  }
  if (/unauthorized, not logged in/i.test(text)) {
    return '未登录或访问令牌无效';
  }
  return text;
}

function isTransientStatusReadError(error: unknown): boolean {
  const message = getErrorMessage(error).toLowerCase();
  if (!message) return false;
  return [
    'live_bridge_unavailable',
    'bridge unavailable',
    'bridge not available',
    'bridge not ready',
    'bridge未启动',
    'bridge unavailable',
    'failed to fetch',
    'fetch failed',
    'econnrefused',
    'connection refused',
    'service unavailable',
    '502',
    '503',
    '504',
  ].some((token) => message.includes(token));
}

async function ensureBridgeStarted(invoke: <T>(cmd: string, args?: Record<string, unknown>) => Promise<T>) {
  const currentPort = await invoke<number>('get_bridge_port');
  if (currentPort > 0) {
    rememberBridgePort(currentPort);
    return;
  }

  if (!bridgeStartup) {
    bridgeStartup = (async () => {
      await invoke<string>('start_bridge');
      for (let i = 0; i < BRIDGE_STARTUP_RETRIES; i += 1) {
        const port = await invoke<number>('get_bridge_port');
        if (port > 0) {
          rememberBridgePort(port);
          return;
        }
        await new Promise((resolve) => setTimeout(resolve, BRIDGE_STARTUP_INTERVAL_MS));
      }
      throw new Error('Bridge 启动超时，请到环境诊断里查看 Bridge 启动失败快照');
    })().finally(() => {
      bridgeStartup = null;
    });
  }
  await bridgeStartup;
}

function rememberBridgePort(port: number) {
  if (!Number.isFinite(port) || port <= 0) return;
  bridgeHttpBase = `http://127.0.0.1:${port}`;
  try {
    window.localStorage.setItem(BRIDGE_PORT_STORAGE_KEY, String(port));
  } catch {
    // localStorage can be unavailable in tests or restricted webviews.
  }
}

function bridgeStreamUrl(path: string): string {
  let base = bridgeHttpBase;
  if (!base) {
    try {
      const port = Number(window.localStorage.getItem(BRIDGE_PORT_STORAGE_KEY) || 0);
      if (port > 0) base = `http://127.0.0.1:${port}`;
    } catch {
      base = '';
    }
  }
  return base ? `${base}${path}` : path;
}

export async function ensureBridgeReadyForStreaming(): Promise<string> {
  await ensureBridgeStarted(invoke);
  const port = await invoke<number>('get_bridge_port');
  rememberBridgePort(port);
  return bridgeStreamUrl('');
}

async function proxyRequest(path: string, method: string = 'GET', body?: unknown) {
  await ensureBridgeStarted(invoke);
  const canRetry = method === 'GET';

  let responseText: string;
  try {
    responseText = await invoke<string>('proxy_request', {
      path,
      method,
      body: body ? JSON.stringify(body) : null,
    });
  } catch (error: any) {
    if (canRetry && isTransientStatusReadError(error)) {
      await ensureBridgeStarted(invoke);
      responseText = await invoke<string>('proxy_request', {
        path,
        method,
        body: body ? JSON.stringify(body) : null,
      });
    } else {
      throw error;
    }
  }
  try {
    return JSON.parse(responseText);
  } catch {
    return { raw: responseText };
  }
}

export async function api<T = unknown>(path: string, method: string = 'GET', body?: unknown): Promise<T> {
  try {
    const result = await proxyRequest(path, method, body);
    if (isApiErrorResponse(result)) {
      throw { ...result, error: parseErrorText((result as any).error || result) };
    }
    return result as T;
  } catch (e: any) {
    const structured = parseApiErrorPayload(e);
    if (structured) {
      throw {
        ...structured,
        error: parseErrorText(structured) || getErrorMessage(structured) || '未知错误',
      };
    }
    if (e && typeof e === 'object' && 'error' in e) {
      throw { ...e, error: parseErrorText(e) || e.error };
    }
    const msg = typeof e === 'string' ? e : (e?.message || '未知错误');
    const cleanMsg = parseErrorText(msg) || '未知错误';
    throw { error: cleanMsg };
  }
}

// === Process API ===
export interface ProcessStatus {
  running: boolean;
  processAlive?: boolean;
  starting?: boolean;
  startupState?: 'idle' | 'starting' | 'running' | 'failed' | string;
  startupElapsedSec?: number;
  startupTimeoutSec?: number;
  startupError?: string;
  startupStage?: string | null;
  startupDurationMs?: number | null;
  pid: number | null;
  portReady?: boolean;
  status?: string;
}

export const processApi = {
  start: (): Promise<ProcessStatus> => api('/api/process/start', 'POST'),
  stop: () => api('/api/process/stop', 'POST'),
  status: (): Promise<ProcessStatus> => api('/api/process/status'),
};

export interface WaitForProcessReadyOptions {
  timeoutMs?: number;
  intervalMs?: number;
  onProgress?: (status: ProcessStatus) => void;
}

export async function waitForProcessReady(options: WaitForProcessReadyOptions = {}): Promise<ProcessStatus> {
  const timeoutMs = options.timeoutMs ?? 10 * 60 * 1000;
  const intervalMs = options.intervalMs ?? 1500;
  const deadline = Date.now() + timeoutMs;
  let lastStatus: ProcessStatus | null = null;

  while (Date.now() < deadline) {
    let status: ProcessStatus;
    try {
      status = await processApi.status();
    } catch (error) {
      if (!isTransientStatusReadError(error)) {
        throw error;
      }
      await new Promise((resolve) => setTimeout(resolve, intervalMs));
      continue;
    }

    lastStatus = status;
    options.onProgress?.(status);

    if (status.running) {
      return status;
    }

    if (status.startupState === 'failed' || (!status.processAlive && !status.starting && status.startupError)) {
      throw { error: status.startupError || '核心服务启动失败' };
    }

    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }

  if (lastStatus?.processAlive || lastStatus?.starting) {
    return lastStatus;
  }

  throw { error: '核心服务启动超时，进程没有保持运行，请导出诊断包查看失败快照' };
}

// === Log API ===
export interface LogRequest {
  offset?: number;
  generation?: string;
}

export interface LogResponse {
  log: string;
  offset: number;
  generation: string;
  total?: number;
  reset?: boolean;
  totalBytes: number;
  windowStartBytes: number;
  windowBytes: number;
  omittedBytes: number;
  truncated: boolean;
}

export interface LogClearResponse {
  status: 'cleared' | 'clear_failed';
  generation: string;
}

export const logApi = {
  get: ({ offset = 0, generation = '' }: LogRequest = {}): Promise<LogResponse> => {
    const query = new URLSearchParams({ offset: String(Math.max(0, offset)) });
    if (generation) query.set('generation', generation);
    return api(`/api/log/get?${query.toString()}`);
  },
  clear: (): Promise<LogClearResponse> => api('/api/log/clear', 'POST'),
};

// === License API ===
export interface LicenseCurrentResponse {
  license: License | null;
  gatewayProfile?: object | null;
  member?: object | null;
  status?: string;
  code?: string;
  reason?: string;
  message?: string;
  installId?: string;
  deviceId?: string;
  offline?: boolean;
}

export interface LicenseClientConfig {
  purchaseUrl?: string;
  supportUrl?: string;
  cardSite?: { enabled?: boolean; label?: string; url?: string };
}

export interface LicenseAuthorizationResponse {
  authorized: boolean;
  feature?: string;
  code?: string;
  reason?: string;
}

export interface LicenseActivationResponse {
  license: License;
  status?: string;
  code?: string;
  message?: string;
}

export const licenseApi = {
  current: (): Promise<LicenseCurrentResponse> => api('/api/license/current'),
  clientConfig: (): Promise<LicenseClientConfig> => api('/api/license/client-config'),
  activate: (code: string): Promise<LicenseActivationResponse> => api('/api/license/activate', 'POST', { code }),
  authorized: (feature?: string): Promise<LicenseAuthorizationResponse> => api('/api/license/authorized', 'POST', { feature }),
};

// === Media config API ===
export interface MediaConfigSnapshot {
  image: {
    baseUrl?: string;
    model?: string;
    size?: string;
    count?: number;
    hasApiKey?: boolean;
    updatedAt?: string;
  };
  video: {
    providerId?: import('../types').VideoProviderId | string;
    apiBase?: string;
    model?: string;
    mode?: string;
    resolution?: string;
    duration?: number;
    ratio?: string;
    hasApiKey?: boolean;
    updatedAt?: string;
  };
}

export interface MediaAsset {
  id: string;
  kind: 'image' | 'video';
  path: string;
  filename: string;
  mime: string;
  size: number;
  generationSize?: string;
  createdAt: string;
  prompt?: string;
  mode?: string;
  ratio?: string;
  model?: string;
  source?: string;
  duration?: number;
  resolution?: string;
}

export interface MediaAssetPage {
  items: MediaAsset[];
  nextCursor: string;
  hasMore: boolean;
}

export interface MediaPhoneTransferResult {
  status: 'succeeded' | 'skipped' | 'failed' | string;
  reason?: string;
  message?: string;
  attempted?: boolean;
  deviceCount?: number;
  succeededDeviceCount?: number;
  failedDeviceCount?: number;
  uploadedCount?: number;
  totalCount?: number;
  deviceId?: string;
  deviceName?: string;
  album?: string;
  deviceResults?: Array<{
    status?: string;
    reason?: string;
    message?: string;
    deviceId?: string;
    deviceName?: string;
    album?: string;
    uploadedCount?: number;
    totalCount?: number;
  }>;
}

export const mediaApi = {
  config: (): Promise<{ config: MediaConfigSnapshot }> => api('/api/media/config'),
  saveConfig: (params: {
    image?: {
      baseUrl?: string;
      apiKey?: string;
      model?: string;
      size?: string;
      count?: number;
    };
    video?: {
      providerId?: import('../types').VideoProviderId | string;
      apiBase?: string;
      apiKey?: string;
      dashKey?: string;
      model?: string;
      mode?: string;
      resolution?: string;
      duration?: number;
      ratio?: string;
    };
  }): Promise<{ config: MediaConfigSnapshot }> => api('/api/media/config', 'POST', params),
  testConfig: (params: {
    kind: 'image' | 'video';
    image?: {
      baseUrl?: string;
      apiKey?: string;
      model?: string;
      size?: string;
      count?: number;
    };
    video?: {
      providerId?: import('../types').VideoProviderId | string;
      apiBase?: string;
      apiKey?: string;
      dashKey?: string;
      model?: string;
      mode?: string;
      resolution?: string;
      duration?: number;
      ratio?: string;
    };
  }): Promise<{ ok: boolean; message?: string; error?: string; config?: MediaConfigSnapshot }> =>
    api('/api/media/test', 'POST', params),
  assets: (kind?: 'image' | 'video', cursor = '', limit = 20): Promise<MediaAssetPage> => {
    const query = new URLSearchParams({ limit: String(limit) });
    if (kind) query.set('kind', kind);
    if (cursor) query.set('cursor', cursor);
    return api(`/api/media/assets?${query.toString()}`);
  },
  reveal: (id: string): Promise<{ opened: boolean; id: string }> =>
    api(`/api/media/assets/${encodeURIComponent(id)}/reveal`, 'POST', {}),
  transferAsset: (id: string, deviceIds: string[]): Promise<{ jobId: string; job: BridgeJob<MediaPhoneTransferResult> }> =>
    api(`/api/media/assets/${encodeURIComponent(id)}/transfer`, 'POST', { deviceIds }),
  deleteAsset: (id: string): Promise<{ deleted: boolean; id: string }> =>
    api(`/api/media/assets/${encodeURIComponent(id)}`, 'DELETE'),
};

// === Image API ===
export const imageApi = {
  generate: (params: {
    baseUrl: string;
    apiKey: string;
    prompt: string;
    size: string;
    count?: number;
    editImagePath?: string;
    ratio?: string;
    source?: string;
  }): Promise<{
    images: string[];
    count: number;
    ratio?: string;
    size?: string;
    files?: Array<{ path: string; directory: string; filename: string; size: number; mime?: string }>;
  }> =>
    api('/api/image/generate', 'POST', params),
  submit: (params: {
    baseUrl?: string;
    apiKey?: string;
    prompt: string;
    size: string;
    count?: number;
    model?: string;
    editImagePath?: string;
    ratio?: string;
    source?: string;
  }): Promise<{ jobId: string; job: BridgeJob }> =>
    api('/api/image/generate/submit', 'POST', params),
};

// === Video API ===
export const videoApi = {
  generate: (params: {
    providerId?: import('../types').VideoProviderId;
    apiBase?: string;
    model?: string;
    dashKey: string;
    prompt: string;
    mode: string;
    resolution: string;
    duration: number;
    ratio: string;
    imagePath?: string;
    source?: string;
  }): Promise<{ video: string; mime?: string; size?: number; path?: string; directory?: string; filename?: string }> =>
    api('/api/video/generate', 'POST', params),
  submit: (params: {
    providerId?: import('../types').VideoProviderId;
    apiBase?: string;
    model?: string;
    dashKey?: string;
    prompt: string;
    mode: string;
    resolution: string;
    duration: number;
    ratio: string;
    imagePath?: string;
    source?: string;
  }): Promise<{ jobId: string; job: BridgeJob }> =>
    api('/api/video/generate/submit', 'POST', params),
};

// === Update API ===
export type UpdateOutcome = 'ready' | 'already_current' | 'cancelled' | 'failed';

export interface UpdateCheckResponse {
  current: string;
  latest: string;
  hasUpdate: boolean;
  notes: string;
  publishedAt: string;
  releaseUrl: string;
  size: number;
}

export interface UpdateProgressResponse {
  phase: string;
  downloaded: number;
  total: number;
  percent: number;
  version: string;
  message: string;
  errorCode: string;
  retryable: boolean;
  remediation: string[];
}

export interface UpdateResultReceipt {
  status: 'success' | 'failed';
  version: string;
  confirmedAt: string;
  message: string;
  rollbackState: string;
  remediation: string[];
}

export interface UpdateDoResponse {
  success: boolean;
  outcome: UpdateOutcome;
  current_version: string;
  log: string[];
  installer_path: string;
  errorCode: string;
  retryable: boolean;
  remediation: string[];
}

export function resolveUpdateDisposition(
  result: Pick<UpdateDoResponse, 'success' | 'outcome' | 'installer_path'>,
): 'prepare_install' | 'already_current' {
  if (result.success && result.outcome === 'already_current' && !result.installer_path.trim()) {
    return 'already_current';
  }
  if (result.success && result.outcome === 'ready' && result.installer_path.trim()) {
    return 'prepare_install';
  }
  throw new Error('Update result is missing a verified installer path or has an invalid outcome.');
}

export function shouldPresentUpdate(latest: string, skipped: string, manual: boolean): boolean {
  return manual || !latest.trim() || latest.trim() !== skipped.trim();
}

export const updateApi = {
  check: (): Promise<UpdateCheckResponse> => api('/api/update/check'),
  status: (): Promise<UpdateProgressResponse> => api('/api/update/status'),
  do: (): Promise<UpdateDoResponse> => api('/api/update/do', 'POST'),
  cancel: (): Promise<{ cancelRequested: boolean; status: UpdateProgressResponse }> =>
    api('/api/update/cancel', 'POST'),
  result: (): Promise<{ pending: boolean; result: UpdateResultReceipt | null }> => api('/api/update/result'),
  prepareInstall: (installerPath: string): Promise<string> =>
    invoke('prepare_update_install', { installerPath }),
};

// === Config API ===
export const configApi = {
  read: (path: string, defaultValue: unknown = {}): Promise<{ data: unknown }> =>
    api('/api/config/read', 'POST', { path, default: defaultValue }),
  write: (path: string, data: unknown): Promise<{ status: string }> =>
    api('/api/config/write', 'POST', { path, data }),
};

// === Theme API ===
export const themeApi = {
  current: (): Promise<{ theme: import('../types/theme').ThemeConfig; isCustom: boolean; merchantId: string | null }> =>
    api('/api/theme/current'),
};

// === System API ===
export const systemApi = {
  info: (): Promise<{
    node_path: string;
    base_path: string;
    openclaw_version: string;
    launcher_version: string;
    api_contract_version: string;
    capabilities: string[];
    bridge: { version: string; apiContractVersion: string; capabilities: string[] };
  }> => api('/api/system/info'),
};

// === Runtime API ===
export const runtimeApi = {
  basePath: (): Promise<string> => invoke<string>('get_portable_base_path'),
};

// === Diagnostics API ===
export type DiagnosticStatus = 'ok' | 'warn' | 'fail';

export interface DiagnosticCheck {
  id: string;
  label: string;
  status: DiagnosticStatus;
  message: string;
  detail?: string;
  repairable?: boolean;
}

export interface DiagnosticSummary {
  status: DiagnosticStatus;
  ok: number;
  warnings: number;
  failed: number;
  total: number;
}

export interface DiagnosticReport {
  basePath: string;
  serviceRunning: boolean;
  servicePid: number | null;
  startupState?: string;
  startupElapsedSec?: number;
  startupTimeoutSec?: number;
  startupError?: string;
  startupDurationMs?: number | null;
  startupStage?: string | null;
  startupSnapshotPath?: string;
  checks: DiagnosticCheck[];
  summary: DiagnosticSummary;
  repairAvailable: boolean;
  timing?: {
    totalMs: number;
    checksMs: Record<string, number>;
    measuredAt: string;
  };
}

export interface DiagnosticRepairResult {
  ok?: boolean;
  restartRequired?: boolean;
  actions: Array<{
    label: string;
    status: DiagnosticStatus;
    message: string;
    count?: number;
    restartRequired?: boolean;
  }>;
  diagnostics: DiagnosticReport;
}

export interface DiagnosticExportResult {
  path: string;
  directory: string;
  filename: string;
  size: number;
}

export const diagnosticsApi = {
  run: (): Promise<DiagnosticReport> => api('/api/diagnostics/run'),
  prerequisites: (): Promise<DiagnosticReport> => api('/api/diagnostics/prerequisites'),
  bridgeStartupReport: (): Promise<DiagnosticReport> => invoke<DiagnosticReport>('bridge_startup_report'),
  repair: (params: { confirmed?: boolean } = {}): Promise<DiagnosticRepairResult> =>
    api('/api/diagnostics/repair', 'POST', params),
  repairPrerequisites: (): Promise<DiagnosticRepairResult> =>
    api('/api/diagnostics/repair', 'POST', { confirmed: true, scope: 'prerequisites' }),
  export: (): Promise<DiagnosticExportResult> => api('/api/diagnostics/export', 'POST'),
};

// === Account / NewAPI ===
export interface AccountSnapshot {
  loggedIn: boolean;
  source?: string;
  account?: string;
  memberId?: string;
  plan?: string;
  status?: string;
  baseUrl?: string;
  gatewayBaseUrl?: string;
  tokenMasked?: string;
  models?: {
    text?: string[];
    image?: string[];
    video?: string[];
  };
  selectedModels?: {
    text?: string;
    image?: string;
    videoDraft?: string;
  };
  usage?: Record<string, unknown>;
  offline?: boolean;
  stale?: boolean;
  lastOnlineAt?: string;
  graceExpiresAt?: string;
  subscription?: AccountSubscriptionSnapshot;
  purchaseUrl?: string;
  syncResults?: Array<{ target?: string; ok?: boolean; error?: string }>;
}

export interface AccountSubscriptionSnapshot {
  loggedIn?: boolean;
  mode?: 'native' | 'webview' | string;
  plan?: string;
  balance?: string | number;
  expiresAt?: string;
  purchaseUrl?: string;
  webViewUrl?: string;
  offline?: boolean;
  stale?: boolean;
  message?: string;
  usage?: {
    usedQuota?: string | number;
    requestCount?: string | number;
    [key: string]: unknown;
  };
  [key: string]: unknown;
}

export interface AccountAuthCapabilities {
  passwordLogin: boolean;
  inlineEmailCode: boolean;
  inlineRegistration?: boolean;
  webRegistrationRequired: boolean;
  registrationUrl?: string;
  emailReason?: string;
  emailVerificationEnabled?: boolean;
  turnstileRequired?: boolean;
  emailConfigured?: boolean;
}

export interface AccountLoginResponse {
  account: AccountSnapshot;
  syncResults?: Array<{ target?: string; ok?: boolean; error?: string }>;
  syncPending?: boolean;
}

export const accountApi = {
  current: (): Promise<{ account: AccountSnapshot }> => api('/api/account/current'),
  capabilities: (): Promise<{ capabilities: AccountAuthCapabilities }> => api('/api/account/capabilities'),
  sendEmailCode: (params: { email: string; baseUrl?: string; purpose?: 'login' | 'register' }): Promise<{ sent: boolean; email?: string; maskedEmail?: string; retryAfter?: number; expiresIn?: number; message?: string }> =>
    api('/api/account/email-code/send', 'POST', params),
  loginWithEmailCode: (params: { email: string; code: string; baseUrl?: string }): Promise<AccountLoginResponse> =>
    api('/api/account/email-code/login', 'POST', params),
  register: (params: { email: string; password: string; code: string; baseUrl?: string }): Promise<AccountLoginResponse> =>
    api('/api/account/register', 'POST', params),
  login: (params: { email?: string; username?: string; password: string; baseUrl?: string; apiToken?: string }): Promise<AccountLoginResponse> =>
    api('/api/account/login', 'POST', params),
  bindTicket: (params: { ticket: string; baseUrl?: string }): Promise<{ account: AccountSnapshot; syncResults?: Array<{ target?: string; ok?: boolean; error?: string }> }> =>
    api('/api/account/bind-ticket', 'POST', params),
  sync: (): Promise<{ account: AccountSnapshot; syncResults?: Array<{ target?: string; ok?: boolean; error?: string }> }> => api('/api/account/sync', 'POST'),
  subscription: (): Promise<{ subscription: AccountSubscriptionSnapshot }> => api('/api/account/subscription'),
  selectModels: (params: { textModel?: string; imageModel?: string; videoModel?: string }): Promise<{ account: AccountSnapshot; syncResults?: Array<{ target?: string; ok?: boolean; error?: string }> }> =>
    api('/api/account/models/select', 'POST', params),
  logout: (): Promise<{ account: AccountSnapshot; loggedOut?: boolean }> => api('/api/account/logout', 'POST'),
};

// === Jobs ===
export interface BridgeJob<T = unknown> {
  id: string;
  kind?: string;
  label?: string;
  status: 'queued' | 'running' | 'succeeded' | 'failed' | string;
  message?: string;
  result?: T;
  error?: string;
  progress?: {
    message?: string;
    tone?: string;
    phase?: string;
    commandId?: string;
    executionLayer?: string;
    currentStep?: string;
    stepTimeoutSec?: number;
    history?: Array<{ message?: string; tone?: string; updatedAt?: number }>;
    [key: string]: unknown;
  };
}

function isJobDone(status: string): boolean {
  return ['succeeded', 'success', 'completed', 'complete'].includes(status.toLowerCase());
}

function isJobFailed(status: string): boolean {
  return ['failed', 'error', 'cancelled', 'canceled'].includes(status.toLowerCase());
}

export const jobApi = {
  get: (jobId: string): Promise<{ job: BridgeJob }> => api(`/api/jobs/${encodeURIComponent(jobId)}`),
  list: (limit = 30): Promise<{ jobs: BridgeJob[] }> => api(`/api/jobs/list?limit=${Math.max(1, limit)}`),
};

const COMPONENT_START_TIMEOUT_MS = 45_000;

export async function waitForJob<T = unknown>(
  jobId: string,
  options: { timeoutMs?: number; intervalMs?: number; onProgress?: (job: BridgeJob<T>) => void } = {},
): Promise<BridgeJob<T>> {
  const timeoutMs = options.timeoutMs ?? 60 * 60 * 1000;
  const intervalMs = options.intervalMs ?? 1500;
  const deadline = Date.now() + timeoutMs;
  let lastJob: BridgeJob<T> | null = null;

  while (Date.now() < deadline) {
    const { job } = await jobApi.get(jobId) as { job: BridgeJob<T> };
    lastJob = job;
    options.onProgress?.(job);
    if (isJobDone(String(job.status || ''))) return job;
    if (isJobFailed(String(job.status || ''))) {
      throw { error: job.error || job.message || `任务失败: ${jobId}` };
    }
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }

  throw { error: lastJob?.progress?.message || lastJob?.message || `任务超时: ${jobId}` };
}

// === Components / Agent installer ===
export interface ComponentSummary {
  id: string;
  name: string;
  version: string;
  installedVersion?: string | null;
  previousVersion?: string | null;
  status: string;
  jobId?: string | null;
  platform: string;
  arch: string;
  type: string;
  size: number;
  entry?: string | null;
  installPath: string;
  installCommand?: string[];
  uninstallCommand?: string[];
  commandTimeoutMs?: number;
  category: string;
  officialUrl?: string | null;
  description?: string | null;
  urls: string[];
  updatedAt?: string | null;
  errorCode?: string | null;
  errorMessage?: string | null;
}

export interface ComponentSnapshot {
  manifest: {
    schemaVersion: number;
    product: string;
    channel: string;
    version: string;
    publishedAt: string;
    minLauncherVersion: string;
  } | null;
  components: ComponentSummary[];
  error?: string | null;
  warning?: string | null;
  manifestErrorCode?: string | null;
  installLocked?: boolean;
}

export interface AgentModelConfigStatus {
  componentId: string;
  supported: boolean;
  configured: boolean;
  installed?: boolean;
  status: 'unsupported' | 'not_installed' | 'no_wire' | 'unconfigured' | 'configured' | 'failed' | string;
  message: string;
  model?: string;
  provider?: string;
  baseUrl?: string;
  managedBy?: string;
  wireManagedBy?: string;
  channelMode?: 'official' | 'managed' | 'custom' | 'unconfigured' | string;
  availableModels?: string[];
  configPath?: string;
  userConfigPath?: string;
  expectedModel?: string;
  actualModel?: string;
  backupAvailable?: boolean;
  rollbackAvailable?: boolean;
  transactionId?: string;
  transactionState?: string;
  remoteVerified?: boolean;
  remoteValidation?: {
    baseUrl?: string;
    endpoint?: string;
    httpStatus?: number;
    model?: string;
    modelsVerified?: boolean;
    responsesVerified?: boolean;
    toolCallsVerified?: boolean;
    verifiedAt?: string;
  };
  officialAuthUnchanged?: boolean;
  updatedAt?: string;
  componentStatus?: string;
}

function sanitizeComponentSnapshot(snapshot: ComponentSnapshot): ComponentSnapshot {
  const warning = snapshot.warning || '';
  if (
    snapshot.manifestErrorCode === 'manifest_unavailable' ||
    warning.includes('All manifest sources') ||
    warning.includes('release-manifest.json')
  ) {
    return {
      ...snapshot,
      warning: '正式组件清单未就绪。当前仅支持本机检测；安装前请确认发布通道可访问。',
    };
  }
  return snapshot;
}

function rememberComponentSnapshot(snapshot: ComponentSnapshot): ComponentSnapshot {
  return saveCachedComponentSnapshot(sanitizeComponentSnapshot(snapshot));
}

function cacheComponentSnapshotOrRefresh(
  snapshot: ComponentSnapshot | undefined,
): ComponentSnapshot | Promise<ComponentSnapshot> {
  return snapshot ? rememberComponentSnapshot(snapshot) : componentApi.status();
}

export const componentApi = {
  status: (): Promise<ComponentSnapshot> => api<ComponentSnapshot>('/api/components/status').then(rememberComponentSnapshot),
  modelConfigStatus: (componentId: string): Promise<{ status: AgentModelConfigStatus }> =>
    api(`/api/components/model-config/status?componentId=${encodeURIComponent(componentId)}`),
  applyModelConfig: (params: { componentId: string; model?: string }): Promise<{ status: AgentModelConfigStatus }> =>
    api('/api/components/model-config/apply', 'POST', { ...params, confirmed: true }),
  applyCustomModelConfig: (params: { componentId: string; provider: string; baseUrl: string; apiKey: string; model: string }): Promise<{ status: AgentModelConfigStatus }> =>
    api('/api/components/model-config/apply-custom', 'POST', { ...params, confirmed: true }),
  rollbackModelConfig: (componentId: string): Promise<{ status: AgentModelConfigStatus }> =>
    api('/api/components/model-config/rollback', 'POST', { componentId, confirmed: true }),
  disableModelConfig: (componentId: string): Promise<{ status: AgentModelConfigStatus }> =>
    api('/api/components/model-config/disable', 'POST', { componentId, confirmed: true }),
  install: async (
    componentId: string,
    options: { simulate?: boolean; confirmed?: boolean; onProgress?: (job: BridgeJob<{ catalog?: ComponentSnapshot }>) => void } = {},
  ): Promise<ComponentSnapshot> => {
    const submitted = await api<{
      jobId?: string;
      job?: BridgeJob<{ catalog?: ComponentSnapshot }>;
      catalog?: ComponentSnapshot;
    }>('/api/components/install', 'POST', {
      componentId,
      ...(options.simulate ? { mode: 'simulate', dryRun: true } : {}),
      ...(options.confirmed ? { confirmed: true } : {}),
    });
    const jobId = submitted.jobId || submitted.job?.id;
    if (jobId) {
      const job = await waitForJob<{ catalog?: ComponentSnapshot }>(jobId, { onProgress: options.onProgress });
      return cacheComponentSnapshotOrRefresh(job.result?.catalog || submitted.catalog);
    }
    return cacheComponentSnapshotOrRefresh(submitted.catalog);
  },
  rollback: async (
    componentId: string,
    options: { onProgress?: (job: BridgeJob<{ catalog?: ComponentSnapshot }>) => void } = {},
  ): Promise<ComponentSnapshot> => {
    const submitted = await api<{
      jobId?: string;
      job?: BridgeJob<{ catalog?: ComponentSnapshot }>;
      catalog?: ComponentSnapshot;
    }>('/api/components/rollback', 'POST', { componentId, confirmed: true });
    const jobId = submitted.jobId || submitted.job?.id;
    if (jobId) {
      const job = await waitForJob<{ catalog?: ComponentSnapshot }>(jobId, { onProgress: options.onProgress });
      return cacheComponentSnapshotOrRefresh(job.result?.catalog || submitted.catalog);
    }
    return cacheComponentSnapshotOrRefresh(submitted.catalog);
  },
  uninstall: async (
    componentId: string,
    options: { onProgress?: (job: BridgeJob<{ catalog?: ComponentSnapshot }>) => void } = {},
  ): Promise<ComponentSnapshot> => {
    const submitted = await api<{
      jobId?: string;
      job?: BridgeJob<{ catalog?: ComponentSnapshot }>;
      catalog?: ComponentSnapshot;
    }>('/api/components/uninstall', 'POST', { componentId, confirmed: true });
    const jobId = submitted.jobId || submitted.job?.id;
    if (jobId) {
      const job = await waitForJob<{ catalog?: ComponentSnapshot }>(jobId, { onProgress: options.onProgress });
      return cacheComponentSnapshotOrRefresh(job.result?.catalog || submitted.catalog);
    }
    return cacheComponentSnapshotOrRefresh(submitted.catalog);
  },
  detect: async (
    componentId: string,
    options: { force?: boolean; onProgress?: (job: BridgeJob<{ catalog?: ComponentSnapshot }>) => void } = {},
  ): Promise<ComponentSnapshot> => {
    const submitted = await api<{
      jobId?: string;
      job?: BridgeJob<{ catalog?: ComponentSnapshot }>;
      catalog?: ComponentSnapshot;
    }>('/api/components/detect', 'POST', { componentId, force: options.force });
    const jobId = submitted.jobId || submitted.job?.id;
    if (jobId) {
      const job = await waitForJob<{ catalog?: ComponentSnapshot }>(jobId, { onProgress: options.onProgress });
      return cacheComponentSnapshotOrRefresh(job.result?.catalog || submitted.catalog);
    }
    return cacheComponentSnapshotOrRefresh(submitted.catalog);
  },
  start: async (
    componentId: string,
    options: { onProgress?: (job: BridgeJob<{ catalog?: ComponentSnapshot }>) => void } = {},
  ): Promise<ComponentSnapshot> => {
    const submitted = await api<{
      jobId?: string;
      job?: BridgeJob<{ catalog?: ComponentSnapshot }>;
      catalog?: ComponentSnapshot;
    }>('/api/components/start', 'POST', { componentId, confirmed: true });
    const jobId = submitted.jobId || submitted.job?.id;
    if (jobId) {
      const job = await waitForJob<{ catalog?: ComponentSnapshot }>(jobId, {
        timeoutMs: COMPONENT_START_TIMEOUT_MS,
        intervalMs: 250,
        onProgress: options.onProgress,
      });
      return cacheComponentSnapshotOrRefresh(job.result?.catalog || submitted.catalog);
    }
    return cacheComponentSnapshotOrRefresh(submitted.catalog);
  },
  restart: async (
    componentId: string,
    options: { onProgress?: (job: BridgeJob<{ catalog?: ComponentSnapshot }>) => void } = {},
  ): Promise<ComponentSnapshot> => {
    const submitted = await api<{
      jobId?: string;
      job?: BridgeJob<{ catalog?: ComponentSnapshot }>;
      catalog?: ComponentSnapshot;
    }>('/api/components/restart', 'POST', { componentId, confirmed: true });
    const jobId = submitted.jobId || submitted.job?.id;
    if (jobId) {
      const job = await waitForJob<{ catalog?: ComponentSnapshot }>(jobId, {
        timeoutMs: COMPONENT_START_TIMEOUT_MS,
        intervalMs: 250,
        onProgress: options.onProgress,
      });
      return cacheComponentSnapshotOrRefresh(job.result?.catalog || submitted.catalog);
    }
    return cacheComponentSnapshotOrRefresh(submitted.catalog);
  },
};

// === CLI capability gateway ===
export interface CliCommandSummary {
  id: string;
  title: string;
  examples: string[];
}

export const cliApi = {
  catalog: (): Promise<{ commands: CliCommandSummary[] }> => api('/api/cli/catalog'),
  run: (params: { command: string; args?: string[]; confirmed?: boolean; timeoutSec?: number }): Promise<{ jobId: string; job: BridgeJob }> =>
    api('/api/cli/run', 'POST', params),
};

// === Phone demo API ===
export interface PhoneDeviceSummary {
  id: string;
  name: string;
  baseUrl: string;
  tokenAvailable: boolean;
  paired?: boolean;
  album?: string;
  lastSeenAt?: string;
}

export interface PhoneConfigSnapshot {
  selectedDeviceId: string;
  configured: boolean;
  devices: PhoneDeviceSummary[];
}

export type PhoneTaskMode = 'observe' | 'safe' | 'full';
export type PhoneTaskProfile = 'fast' | 'standard' | 'deep';

export const phoneApi = {
  config: (): Promise<PhoneConfigSnapshot> => api('/api/phone/config'),
  saveDevice: (params: {
    id?: string;
    deviceId?: string;
    name?: string;
    baseUrl: string;
    token?: string;
    selectedDeviceId?: string;
  }): Promise<PhoneConfigSnapshot> => api('/api/phone/config/device', 'POST', params),
  deleteDevice: (deviceId: string): Promise<PhoneConfigSnapshot> =>
    api(`/api/phone/config/device/${encodeURIComponent(deviceId)}`, 'DELETE'),
  syncModel: (): Promise<{ jobId: string; job: BridgeJob }> => api('/api/phone/sync-model', 'POST'),
  devices: (): Promise<{ jobId: string; job: BridgeJob }> => api('/api/phone/devices', 'POST'),
  status: (params: { deviceId?: string } = {}): Promise<{ jobId: string; job: BridgeJob }> =>
    api('/api/phone/status', 'POST', params),
  screenshot: (): Promise<{ jobId: string; job: BridgeJob }> => api('/api/phone/screenshot', 'POST'),
  read: (params: { prompt: string; profile?: PhoneTaskProfile; deviceId?: string }): Promise<{ jobId: string; job: BridgeJob }> =>
    api('/api/phone/read', 'POST', params),
  task: (params: {
    prompt: string;
    deviceId?: string;
    mode?: PhoneTaskMode;
    profile?: PhoneTaskProfile;
    timeoutSec?: number;
    maxWaitSec?: number;
    maxRounds?: number;
    pollMs?: number;
    template?: string;
    templateId?: string;
    executionLayer?: 'direct' | 'template' | 'agent';
    stepTimeoutSec?: number;
    action?: 'back' | 'home' | string;
    directAction?: 'back' | 'home' | string;
  }): Promise<{ jobId: string; job: BridgeJob }> => api('/api/phone/task', 'POST', params),
  history: (): Promise<{ jobId: string; job: BridgeJob }> => api('/api/phone/history', 'POST'),
};

// === Agent, Matrix, and realtime platform APIs ===
export const realtimeApi = {
  issueTicket: async (request: StreamTicketRequest): Promise<StreamTicketResponse> => {
    await ensureBridgeReadyForStreaming();
    return api('/api/realtime/tickets', 'POST', request);
  },
  eventsStreamUrl: (topic: RealtimeStreamTopic): string =>
    bridgeStreamUrl(topic === 'agent' ? '/api/agent/events/stream' : '/api/matrix/events/stream'),
};

export const agentApi = {
  bootstrap: (): Promise<AgentBootstrapResponse> => api('/api/agent/bootstrap'),
  sessions: (params: { query?: string; cursor?: string; limit?: number } = {}): Promise<AgentSessionListResponse> => {
    const query = new URLSearchParams();
    if (params.query) query.set('query', params.query);
    if (params.cursor) query.set('cursor', params.cursor);
    if (params.limit) query.set('limit', String(params.limit));
    const suffix = query.size ? `?${query.toString()}` : '';
    return api(`/api/agent/sessions${suffix}`);
  },
  createSession: (request: CreateAgentSessionRequest): Promise<{ session: AgentSession }> =>
    api('/api/agent/sessions', 'POST', request),
  updateSession: (sessionId: string, request: UpdateAgentSessionRequest): Promise<{ session: AgentSession }> =>
    api(`/api/agent/sessions/${encodeURIComponent(sessionId)}`, 'PATCH', request),
  session: (sessionId: string, params: { cursor?: string; limit?: number } = {}): Promise<AgentSessionDetailResponse> => {
    const query = new URLSearchParams();
    if (params.cursor) query.set('cursor', params.cursor);
    if (params.limit) query.set('limit', String(params.limit));
    const suffix = query.size ? `?${query.toString()}` : '';
    return api(`/api/agent/sessions/${encodeURIComponent(sessionId)}${suffix}`);
  },
  sendMessage: (sessionId: string, request: SendAgentMessageRequest): Promise<SendAgentMessageResponse> =>
    api(`/api/agent/sessions/${encodeURIComponent(sessionId)}/messages`, 'POST', request),
  run: (runId: string): Promise<{ run: AgentRun }> =>
    api(`/api/agent/runs/${encodeURIComponent(runId)}`),
  trace: (runId: string): Promise<AgentRunTraceResponse> =>
    api(`/api/agent/runs/${encodeURIComponent(runId)}/trace`),
  pause: (runId: string): Promise<{ run: AgentRun }> =>
    api(`/api/agent/runs/${encodeURIComponent(runId)}/pause`, 'POST'),
  resume: (runId: string): Promise<{ run: AgentRun }> =>
    api(`/api/agent/runs/${encodeURIComponent(runId)}/resume`, 'POST'),
  cancel: (runId: string): Promise<{ run: AgentRun }> =>
    api(`/api/agent/runs/${encodeURIComponent(runId)}/cancel`, 'POST'),
  resolveApproval: (approvalId: string, request: ResolveAgentApprovalRequest): Promise<{ approval: AgentApproval; run?: AgentRun }> =>
    api(`/api/agent/approvals/${encodeURIComponent(approvalId)}`, 'POST', request),
};

type MatrixEmergencyStopExclusive = {
  all?: never;
  campaignId?: never;
  deviceIds?: never;
  deviceTaskIds?: never;
};

export type MatrixEmergencyStopRequest =
  | ({ all: true } & Omit<MatrixEmergencyStopExclusive, 'all'>)
  | ({ campaignId: string } & Omit<MatrixEmergencyStopExclusive, 'campaignId'>)
  | ({ deviceIds: string[] } & Omit<MatrixEmergencyStopExclusive, 'deviceIds'>)
  | ({ deviceTaskIds: string[] } & Omit<MatrixEmergencyStopExclusive, 'deviceTaskIds'>);

export interface MatrixEmergencyStopAffectedTask {
  campaignId: string;
  missionId: string;
  assignmentId: string;
  deviceTaskId: string;
  deviceId: string;
  previousStatus: string;
  status: 'cancelled';
}

export interface MatrixEmergencyStopResponse {
  schema: 'loom.matrix.emergency_stop.v1';
  cancelled: boolean;
  scope: 'all' | 'campaign' | 'devices' | 'deviceTasks';
  matchedCampaignIds: string[];
  campaignIds: string[];
  cancelledJobIds: string[];
  cancelledCount: number;
  affectedTaskCount: number;
  affectedDeviceCount: number;
  affected: MatrixEmergencyStopAffectedTask[];
}

export const matrixApi = {
  status: (): Promise<MatrixStatusSnapshot> => api('/api/matrix/status'),
  ensureStreamReady: (): Promise<string> => ensureBridgeReadyForStreaming(),
  eventsStreamUrl: (): string => bridgeStreamUrl('/api/matrix/events/stream'),
  registerDevice: (params: {
    deviceId?: string;
    name?: string;
    group?: string;
    online?: boolean;
    busy?: boolean;
    currentTaskId?: string;
    heartbeatAt?: string;
    currentScreenSummary?: string;
    failureCount?: number;
    model?: string;
  }): Promise<{ device: MatrixDeviceSummary; status: MatrixStatusSnapshot }> =>
    api('/api/matrix/device/register', 'POST', params),
  watch: (campaignId?: string): Promise<{ schema: string; events: MatrixEvent[] }> =>
    api(`/api/matrix/watch${campaignId ? `?campaignId=${encodeURIComponent(campaignId)}` : ''}`),
  dispatch: (params: MatrixDispatchRequest | LegacyMatrixDispatchRequest): Promise<MatrixDispatchResponse & { job?: BridgeJob }> =>
    api('/api/matrix/dispatch', 'POST', params),
  cancel: (campaignId: string): Promise<MatrixCommandResponse> =>
    api('/api/matrix/cancel', 'POST', { campaignId }),
  retry: (params: { campaignId: string; deviceTaskIds?: string[]; deviceId?: string; stepId?: string }): Promise<MatrixDispatchResponse & { job?: BridgeJob }> =>
    api('/api/matrix/retry', 'POST', params),
  screen: (deviceId: string, knownHash?: string): Promise<MatrixScreen> => {
    const query = knownHash ? `?knownHash=${encodeURIComponent(knownHash)}` : '';
    return api(`/api/matrix/devices/${encodeURIComponent(deviceId)}/screen${query}`);
  },
  screens: (requests: MatrixScreenBatchRequest[]): Promise<MatrixScreenBatchResponse> =>
    api('/api/matrix/screens', 'POST', { requests }),
  timeline: (deviceId: string, limit = 100): Promise<{ events: MatrixEvent[] }> =>
    api(`/api/matrix/devices/${encodeURIComponent(deviceId)}/timeline?limit=${Math.max(1, limit)}`),
  lease: (deviceId: string): Promise<{ lease: MatrixDeviceLease | null }> =>
    api(`/api/matrix/devices/${encodeURIComponent(deviceId)}/lease`),
  acquireLease: (deviceId: string, request: AcquireMatrixLeaseRequest): Promise<{ lease: MatrixDeviceLease }> =>
    api(`/api/matrix/devices/${encodeURIComponent(deviceId)}/lease`, 'POST', request),
  releaseLease: (deviceId: string, leaseId: string): Promise<{ released: boolean }> =>
    api(`/api/matrix/devices/${encodeURIComponent(deviceId)}/lease`, 'DELETE', { leaseId }),
  control: (deviceId: string, request: MatrixControlRequest): Promise<MatrixCommandResponse> =>
    api(`/api/matrix/devices/${encodeURIComponent(deviceId)}/control`, 'POST', request),
  pauseTask: (deviceTaskId: string): Promise<MatrixCommandResponse> =>
    api(`/api/matrix/tasks/${encodeURIComponent(deviceTaskId)}/pause`, 'POST'),
  resumeTask: (deviceTaskId: string): Promise<MatrixCommandResponse> =>
    api(`/api/matrix/tasks/${encodeURIComponent(deviceTaskId)}/resume`, 'POST'),
  emergencyStop: (params: MatrixEmergencyStopRequest): Promise<MatrixEmergencyStopResponse> =>
    api('/api/matrix/emergency-stop', 'POST', params),
  experience: (): Promise<Record<string, unknown>> => api('/api/matrix/experience'),
};

export interface AcquisitionContentTask {
  taskId: string;
  createdAt?: string;
  title: string;
  platform: string;
  status: string;
  assetPlan?: string[];
}

export interface AcquisitionLead {
  leadId: string;
  title: string;
  summary: string;
  platform?: string;
  channel?: string;
  status: string;
  need?: string;
  intentLevel?: string;
  intentScore?: number;
  qualificationSource?: string;
  recommendedAction?: string;
  syncStatus?: 'pending_sync' | 'sync_failed' | 'synced' | string;
  syncError?: string;
  feishuRecordId?: string;
  tags?: string[];
}

export interface AcquisitionCustomer {
  customerId: string;
  leadId?: string;
  name: string;
  stage: string;
  summary?: string;
  allowedChannels?: string[];
}

export interface AcquisitionDraft {
  draftId: string;
  leadId?: string;
  customerId?: string;
  channel: string;
  status: string;
  body: string;
  requiresHumanReview: boolean;
  sendEnabled: boolean;
  policy: string[];
  manualSend?: {
    outcome?: string;
    operator?: string;
    recordedAt?: string;
    reply?: string;
    note?: string;
    nextFollowUpAt?: string;
  };
}

export interface AcquisitionAgentRun {
  schema?: string;
  dryRun?: boolean;
  taskId?: string;
  deviceId?: string;
  platform?: string;
  action?: string;
  status?: string;
  requiresHumanReview?: boolean;
  sendEnabled?: boolean;
  phoneTask?: {
    schema?: string;
    taskId?: string;
    stopAt?: string;
    resultSchema?: string;
    allowedActions?: string[];
    forbiddenActions?: string[];
    outboundPolicy?: string[];
    bridgeDispatch?: {
      method?: string;
      endpoint?: string;
      body?: {
        taskId?: string;
        mode?: PhoneTaskMode | string;
        prompt?: string;
        target?: { deviceIds?: string[]; groups?: string[] };
        executionLayer?: string;
        resultCallback?: {
          method?: string;
          endpoint?: string;
          payloadField?: string;
        };
      };
    };
  };
}

export interface AcquisitionSnapshot {
  schema: 'loom.customer_acquisition.v1' | string;
  updatedAt?: string;
  contentTasks: AcquisitionContentTask[];
  leads: AcquisitionLead[];
  customers: AcquisitionCustomer[];
  drafts: AcquisitionDraft[];
  agentRuns?: AcquisitionAgentRun[];
  sop: Array<{ id: string; title: string; text: string }>;
  logs: Array<{ logId?: string; timestamp?: string; type?: string; message?: string }>;
  stats: {
    contentTasks: number;
    leads: number;
    customers: number;
    agentRuns?: number;
    draftsPending: number;
    approvedDrafts: number;
    pendingSync?: number;
  };
  outboundPolicy: string[];
  integrations?: {
    feishu?: FeishuStatus;
  };
}

export interface AcquisitionTemplateSummary {
  schema?: string;
  templateId: string;
  version?: number;
  name: string;
  industry?: string;
  platforms?: string[];
  targetCustomer?: string;
  uploadStatus?: 'pending_upload' | 'upload_failed' | 'uploaded' | string;
  uploadError?: string;
  remote?: {
    templateId?: string;
    version?: number;
    url?: string;
    uploadedAt?: string;
    serverUrl?: string;
  };
  updatedAt?: string;
}

export interface AcquisitionTemplateStatus {
  schema?: string;
  updatedAt?: string;
  cloud?: {
    configured?: boolean;
    serverUrl?: string;
    tokenConfigured?: boolean;
    consentGranted?: boolean;
    uploadEnabled?: boolean;
  };
  stats?: {
    total?: number;
    pendingUpload?: number;
    uploaded?: number;
  };
  templates?: AcquisitionTemplateSummary[];
}

export const acquisitionApi = {
  snapshot: (): Promise<AcquisitionSnapshot> => api('/api/matrix/acquisition'),
  runDemo: (params: {
    topic: string;
    platform: string;
    channel: string;
    leadSummary: string;
    knowledge: string;
  }): Promise<{ flow: Record<string, unknown>; snapshot: AcquisitionSnapshot }> =>
    api('/api/matrix/acquisition/demo', 'POST', params),
  importLeads: (params: {
    topic: string;
    platform: string;
    channel: string;
    sourceText: string;
    knowledge: string;
    target?: string;
    owner?: string;
  }): Promise<{ result: Record<string, unknown>; snapshot: AcquisitionSnapshot }> =>
    api('/api/matrix/acquisition/import', 'POST', params),
  runAgent: (params: {
    dryRun?: boolean;
    topic: string;
    platform: string;
    action?: string;
    deviceId?: string;
    knowledge?: string;
    target?: string;
  }): Promise<{ agentRun: Record<string, unknown>; ingest: Record<string, unknown>; snapshot: AcquisitionSnapshot }> =>
    api('/api/matrix/acquisition/agent/run', 'POST', params),
  ingestAgentResult: (params: {
    topic?: string;
    platform?: string;
    action?: string;
    deviceId?: string;
    knowledge?: string;
    target?: string;
    owner?: string;
    agentResult: Record<string, unknown>;
  }): Promise<{ ingest: Record<string, unknown>; snapshot: AcquisitionSnapshot }> =>
    api('/api/matrix/acquisition/agent/result', 'POST', params),
  confirmDraft: (draftId: string): Promise<{ draft: AcquisitionDraft; snapshot: AcquisitionSnapshot }> =>
    api('/api/matrix/acquisition/draft/confirm', 'POST', { draftId, operator: 'launcher-user' }),
  recordManualSend: (params: {
    draftId: string;
    outcome?: 'sent' | 'replied' | 'no_reply' | 'failed' | string;
    reply?: string;
    note?: string;
    nextFollowUpAt?: string;
  }): Promise<{ draft: AcquisitionDraft; snapshot: AcquisitionSnapshot }> =>
    api('/api/matrix/acquisition/draft/manual-send', 'POST', { ...params, operator: 'launcher-user' }),
  templates: (): Promise<AcquisitionTemplateStatus> => api('/api/matrix/acquisition/templates'),
  saveTemplate: (params: {
    name?: string;
    topic?: string;
    industry?: string;
    platforms?: string[];
    platform?: string;
    targetCustomer?: string;
    target?: string;
    keywords?: string[];
    leadRules?: string[];
    replyStyle?: string;
    knowledge?: string;
  }): Promise<{ template: AcquisitionTemplateSummary; upload?: Record<string, unknown>; status?: AcquisitionTemplateStatus }> =>
    api('/api/matrix/acquisition/templates/save', 'POST', params),
  uploadTemplate: (templateId: string): Promise<Record<string, unknown>> =>
    api('/api/matrix/acquisition/templates/upload', 'POST', { templateId }),
  setTemplateCloudConsent: (enabled: boolean, retryPending = false): Promise<Record<string, unknown>> =>
    api('/api/matrix/acquisition/templates/cloud-consent', 'POST', { enabled, retryPending }),
  retryTemplates: (): Promise<Record<string, unknown>> =>
    api('/api/matrix/acquisition/templates/retry', 'POST'),
};

export interface FeishuStatus {
  schema?: string;
  cliInstalled?: boolean;
  connected?: boolean;
  pendingCount?: number;
  pendingVerificationCount?: number;
  auth?: {
    loggedIn?: boolean;
    botReady?: boolean;
    identity?: string;
    userName?: string;
    message?: string;
  };
  table?: {
    url?: string;
    baseToken?: string;
    tableId?: string;
    name?: string;
    fields?: string[];
  };
  lastSync?: {
    leadId?: string;
    syncStatus?: string;
    syncError?: string;
    recordId?: string;
    updatedAt?: string;
  };
}

export const feishuApi = {
  doctor: (): Promise<Record<string, unknown>> => api('/api/matrix/acquisition/feishu/doctor'),
  status: (): Promise<FeishuStatus> => api('/api/matrix/acquisition/feishu/status'),
  install: (confirmed = false): Promise<Record<string, unknown>> =>
    api('/api/matrix/acquisition/feishu/install', 'POST', { confirmed }),
  login: (): Promise<{ ok?: boolean; loginUrl?: string; verificationUrl?: string; userCode?: string; qrAscii?: string; error?: string; message?: string }> =>
    api('/api/matrix/acquisition/feishu/login', 'POST'),
  bindTable: (params: { url?: string; baseToken?: string; tableId?: string; name?: string }): Promise<{ table?: FeishuStatus['table']; status?: FeishuStatus }> =>
    api('/api/matrix/acquisition/feishu/bind-table', 'POST', params),
  createTable: (confirmed = false): Promise<Record<string, unknown>> =>
    api('/api/matrix/acquisition/feishu/create-table', 'POST', { confirmed }),
  testWrite: (): Promise<Record<string, unknown>> => api('/api/matrix/acquisition/feishu/test-write', 'POST'),
  retrySync: (): Promise<Record<string, unknown>> => api('/api/matrix/acquisition/feishu/retry-sync', 'POST'),
  reconcile: (): Promise<Record<string, unknown>> => api('/api/matrix/acquisition/feishu/reconcile', 'POST'),
};

// === Runtime wire API ===
export interface WireSnapshot {
  ok?: boolean;
  managedBy?: string;
  provider?: string;
  baseUrl?: string;
  tokenMasked?: string;
  models?: {
    text?: string;
    phone?: string;
    image?: string;
    video?: string;
  };
  modelLists?: {
    text?: string[];
    phone?: string[];
    image?: string[];
    video?: string[];
  };
  targets?: Record<string, boolean>;
  updatedAt?: string;
}

export const wireApi = {
  current: (): Promise<{ wire: WireSnapshot }> => api('/api/wire/current'),
  sync: (): Promise<{ wire: WireSnapshot; syncResults?: Array<{ target?: string; ok?: boolean; error?: string }> }> =>
    api('/api/wire/sync', 'POST'),
  custom: (params: {
    provider?: string;
    baseUrl: string;
    apiKey: string;
    textModel: string;
    imageModel?: string;
    phoneModel?: string;
    videoModel?: string;
    targets?: string[];
  }): Promise<{ wire: WireSnapshot; syncResults?: Array<{ target?: string; ok?: boolean; error?: string }> }> =>
    api('/api/wire/custom', 'POST', params),
  verify: (): Promise<{ ok: boolean; wire?: WireSnapshot; targets?: Record<string, { ok?: boolean; error?: string }> }> =>
    api('/api/wire/verify', 'POST'),
  rollback: (): Promise<{ wire: WireSnapshot; syncResults?: Array<{ target?: string; ok?: boolean; error?: string }> }> =>
    api('/api/wire/rollback', 'POST'),
};
