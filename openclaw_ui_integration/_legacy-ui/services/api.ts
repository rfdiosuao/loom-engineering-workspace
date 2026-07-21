import { invoke } from '@tauri-apps/api/core';

let bridgeStartup: Promise<void> | null = null;
const BRIDGE_STARTUP_RETRIES = 480;
const BRIDGE_STARTUP_INTERVAL_MS = 500;

function getErrorMessage(error: unknown): string {
  if (typeof error === 'string') return error;
  if (error && typeof error === 'object') {
    const record = error as Record<string, unknown>;
    if (typeof record.error === 'string') return record.error;
    if (typeof record.message === 'string') return record.message;
  }
  return '';
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
  if (currentPort > 0) return;

  if (!bridgeStartup) {
    bridgeStartup = (async () => {
      await invoke<string>('start_bridge');
      for (let i = 0; i < BRIDGE_STARTUP_RETRIES; i += 1) {
        const port = await invoke<number>('get_bridge_port');
        if (port > 0) return;
        await new Promise((resolve) => setTimeout(resolve, BRIDGE_STARTUP_INTERVAL_MS));
      }
      throw new Error('Bridge 启动超时，请到环境诊断里查看 Bridge 启动失败快照');
    })().finally(() => {
      bridgeStartup = null;
    });
  }
  await bridgeStartup;
}

async function proxyRequest(path: string, method: string = 'GET', body?: Record<string, unknown>) {
  await ensureBridgeStarted(invoke);

  let responseText: string;
  try {
    responseText = await invoke<string>('proxy_request', {
      path,
      method,
      body: body ? JSON.stringify(body) : null,
    });
  } catch (error: any) {
    if (isTransientStatusReadError(error)) {
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

export async function api<T = unknown>(path: string, method: string = 'GET', body?: Record<string, unknown>): Promise<T> {
  try {
    const result = await proxyRequest(path, method, body);
    if (result && typeof result === 'object' && 'error' in result) {
      throw { error: (result as any).error };
    }
    return result as T;
  } catch (e: any) {
    if (e && typeof e === 'object' && 'error' in e) {
      throw e;
    }
    const msg = typeof e === 'string' ? e : (e?.message || '未知错误');
    const cleanMsg = msg.replace(/^\[\d+\]\s*/, '');
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
      throw { error: status.startupError || 'OpenClaw 启动失败' };
    }

    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }

  if (lastStatus?.processAlive || lastStatus?.starting) {
    return lastStatus;
  }

  throw { error: 'OpenClaw 启动超时，进程没有保持运行，请导出诊断包查看失败快照' };
}

// === Log API ===
export interface LogResponse {
  log: string;
  offset: number;
  total?: number;
  reset?: boolean;
}

export const logApi = {
  get: (offset: number = 0): Promise<LogResponse> => api(`/api/log/get?offset=${Math.max(0, offset)}`),
  clear: () => api('/api/log/clear', 'POST'),
};

// === License API ===
export const licenseApi = {
  current: (): Promise<{ license: object | null; gatewayProfile?: object | null; member?: object | null }> => api('/api/license/current'),
  clientConfig: (): Promise<{ cardSite?: { enabled?: boolean; label?: string; url?: string } }> => api('/api/license/client-config'),
  activate: (code: string): Promise<{ license: object }> => api('/api/license/activate', 'POST', { code }),
  authorized: (feature?: string): Promise<{ authorized: boolean }> => api('/api/license/authorized', 'POST', { feature }),
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
  }): Promise<{
    images: string[];
    count: number;
    files?: Array<{ path: string; directory: string; filename: string; size: number; mime?: string }>;
  }> =>
    api('/api/image/generate', 'POST', params),
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
  }): Promise<{ video: string; mime?: string; size?: number; path?: string; directory?: string; filename?: string }> =>
    api('/api/video/generate', 'POST', params),
};

// === Update API ===
export const updateApi = {
  check: (): Promise<{ current: string; latest: string; hasUpdate: boolean }> => api('/api/update/check'),
  do: (): Promise<{ success: boolean; current_version: string; log: string[] }> => api('/api/update/do', 'POST'),
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
  info: (): Promise<{ node_path: string; base_path: string; openclaw_version: string }> => api('/api/system/info'),
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
}

export interface DiagnosticRepairResult {
  actions: Array<{
    label: string;
    status: DiagnosticStatus;
    message: string;
    count?: number;
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
  bridgeStartupReport: (): Promise<DiagnosticReport> => invoke<DiagnosticReport>('bridge_startup_report'),
  repair: (): Promise<DiagnosticRepairResult> => api('/api/diagnostics/repair', 'POST'),
  export: (): Promise<DiagnosticExportResult> => api('/api/diagnostics/export', 'POST'),
};

// === Desktop Agent API ===
export interface DesktopAgentConfig {
  enabled: boolean;
  agentDir: string;
  resolvedAgentDir?: string;
  port: number;
  tokenAvailable?: boolean;
  tokenPreview?: string;
  appType: 'weixin' | 'wework' | string;
  autoStartHttpApi: boolean;
  policy?: {
    allowScreenshot: boolean;
    allowClick: boolean;
    allowType: boolean;
    allowWechatSend: boolean;
    requireConfirmForClick: boolean;
    requireConfirmForType: boolean;
    requireConfirmForSend: boolean;
    blockedWindowKeywords: string[];
  };
  capture?: {
    format: string;
    quality: number;
    maxWidth: number;
  };
  action?: {
    clickDelayMs: number;
    typeDelayMs: number;
    timeoutMs: number;
  };
  wechat?: {
    sendMode: string;
    detectUnreadMode: string;
  };
  configPath?: string;
}

export interface DesktopAgentStatus {
  configured: boolean;
  present: boolean;
  running: boolean;
  pid: number | null;
  apiReady: boolean;
  health?: Record<string, unknown>;
  command?: string[];
  config: DesktopAgentConfig;
}

export const desktopAgentApi = {
  status: (): Promise<DesktopAgentStatus> => api('/api/desktop-agent/status'),
  config: (config: Partial<DesktopAgentConfig>): Promise<{ config: DesktopAgentConfig }> =>
    api('/api/desktop-agent/config', 'POST', config as Record<string, unknown>),
  start: (): Promise<DesktopAgentStatus> => api('/api/desktop-agent/start', 'POST'),
  stop: (): Promise<DesktopAgentStatus> => api('/api/desktop-agent/stop', 'POST'),
  health: (): Promise<Record<string, unknown>> => api('/api/desktop-agent/health'),
  screenshot: (): Promise<{ success?: boolean; screenshot?: string; error?: string }> =>
    api('/api/desktop-agent/screenshot', 'POST'),
  click: (x: number, y: number, confirmed = false): Promise<Record<string, unknown>> =>
    api('/api/desktop-agent/click', 'POST', { x, y, confirmed }),
  type: (text: string, confirmed = false): Promise<Record<string, unknown>> =>
    api('/api/desktop-agent/type', 'POST', { text, confirmed }),
  wechatUnread: (): Promise<Record<string, unknown>> =>
    api('/api/desktop-agent/wechat/unread', 'POST'),
  wechatSend: (text: string, confirmed = false): Promise<Record<string, unknown>> =>
    api('/api/desktop-agent/wechat/send', 'POST', { text, confirmed }),
};

// === Skills API ===
export interface SkillDirectory {
  key: string;
  label: string;
  path: string;
  writable: boolean;
}

export interface SkillSite {
  name: string;
  url: string;
}

export interface SkillItem {
  id: string;
  name: string;
  version: string;
  description: string;
  category: string;
  runtime: string;
  icon: string;
  source: string;
  sourceLabel: string;
  path: string;
  installed: boolean;
  enabled: boolean;
  writable: boolean;
  hasReadme?: boolean;
  installedAt?: string;
}

export interface SkillsListResponse {
  skills: SkillItem[];
  directories: SkillDirectory[];
  sites: SkillSite[];
  statePath?: string;
}

export const skillsApi = {
  list: (): Promise<SkillsListResponse> => api('/api/skills/list'),
  installZip: (filename: string, data: string): Promise<{ skill: SkillItem }> =>
    api('/api/skills/install_zip', 'POST', { filename, data }),
  setEnabled: (id: string, enabled: boolean): Promise<{ skill: SkillItem }> =>
    api('/api/skills/enable', 'POST', { id, enabled }),
  uninstall: (id: string): Promise<{ status: string; id: string }> =>
    api('/api/skills/uninstall', 'POST', { id }),
  readme: (id: string): Promise<{ id: string; path: string; content: string }> =>
    api('/api/skills/readme', 'POST', { id }),
  paths: (): Promise<{ directories: SkillDirectory[]; sites: SkillSite[] }> => api('/api/skills/paths'),
};
