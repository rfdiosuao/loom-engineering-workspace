import type {
  DataSource,
  DiagnosticsSnapshot,
  GatewaySnapshot,
  ImageResult,
  AccountSnapshot,
  ComponentSnapshot,
  LicenseSnapshot,
  MemberSnapshot,
  PromptTemplate,
  ServiceSnapshot,
  SkillSnapshot,
  StudioSnapshot,
  DesktopSnapshot,
  SettingsSnapshot,
  TransportMode,
  VideoResult,
} from '../types';
import { bridgeRequest, installDistributionLayer, isTauriRuntime, phoneRequest, resolveBridgeBaseUrl, type PhoneRequestOptions } from './client';
import { cleanArray, maskSecret, pickText, toBool, toNumber, toText } from '../lib/format';
import type { PreviewSettings } from '../store/appStore';

export interface DashboardSnapshot {
  source: DataSource;
  service: ServiceSnapshot;
  license: LicenseSnapshot;
  member: MemberSnapshot;
  gateway: GatewaySnapshot;
  diagnostics: DiagnosticsSnapshot;
  skills: SkillSnapshot;
  update: ServiceSnapshot['update'];
  recentLogs: string[];
  themeName: string;
}

interface RequestResult<T> {
  data: T;
  source: DataSource;
}

export interface BridgeJob<T = any> {
  id?: string;
  status?: string;
  result?: T;
  error?: string;
  message?: string;
  progress?: {
    message?: string;
    tone?: string;
    updatedAt?: number;
    history?: Array<{ message?: string; tone?: string; updatedAt?: number }>;
  };
}

export interface VideoGenerationPayload {
  providerId?: string;
  apiBase?: string;
  model?: string;
  dashKey: string;
  prompt: string;
  mode: string;
  resolution: string;
  duration: number;
  ratio: string;
  imagePath?: string;
}

const DASHBOARD_CACHE_TTL_MS = 2500;
const DASHBOARD_LOG_QUERY = '/api/log/get?offset=0&tail=1&maxBytes=200000';
let dashboardCache: { key: string; expiresAt: number; data: DashboardSnapshot } | null = null;
let dashboardInflight: { key: string; promise: Promise<DashboardSnapshot> } | null = null;

function effectiveMode(settings: PreviewSettings): TransportMode {
  if (settings.transportMode !== 'auto') return settings.transportMode;
  const bridgeBase = resolveBridgeBaseUrl(settings.bridgeBaseUrl);
  return bridgeBase || isTauriRuntime() ? 'live' : 'mock';
}

function mergeSource(a: DataSource, b: DataSource): DataSource {
  if (a === b) return a;
  return 'mixed';
}

function splitLines(value: unknown): string[] {
  return String(value || '')
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .slice(-10);
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

async function softTimeout<T>(promise: Promise<T>, timeoutMs: number, fallback: T): Promise<T> {
  let timer: number | undefined;
  try {
    return await Promise.race([
      promise,
      new Promise<T>((resolve) => {
        timer = window.setTimeout(() => resolve(fallback), timeoutMs);
      }),
    ]);
  } finally {
    if (timer) window.clearTimeout(timer);
  }
}

async function requestBridgeDataSoft<T>(
  settings: PreviewSettings,
  path: string,
  fallback: T,
  timeoutMs = 1500,
): Promise<RequestResult<T>> {
  const source: DataSource = effectiveMode(settings) === 'mock' ? 'mock' : 'live';
  try {
    return await softTimeout(requestBridgeData<T>(settings, path), timeoutMs, { data: fallback, source });
  } catch {
    return { data: fallback, source };
  }
}

function dashboardCacheKey(settings: PreviewSettings): string {
  return [
    effectiveMode(settings),
    resolveBridgeBaseUrl(settings.bridgeBaseUrl),
    settings.bridgeToken ? 'token' : 'none',
  ].join('|');
}

function isJobDone(status: string): boolean {
  return ['succeeded', 'success', 'completed', 'complete'].includes(status.toLowerCase());
}

function isJobFailed(status: string): boolean {
  return ['failed', 'error', 'cancelled', 'canceled'].includes(status.toLowerCase());
}

async function waitForBridgeJob<T>(
  settings: PreviewSettings,
  jobId: string,
  timeoutMs: number,
  onProgress?: (job: BridgeJob<T>) => void,
): Promise<RequestResult<T>> {
  const startedAt = Date.now();
  let attempt = 0;
  let lastJob: BridgeJob<T> = {};
  while (Date.now() - startedAt < timeoutMs) {
    const response = await requestBridgeData<{ job?: BridgeJob<T> }>(settings, `/api/jobs/${encodeURIComponent(jobId)}`);
    const job = response.data?.job || {};
    lastJob = job;
    onProgress?.(job);
    const status = String(job.status || '').toLowerCase();
    if (isJobDone(status)) {
      return { data: job.result as T, source: response.source };
    }
    if (isJobFailed(status)) {
      throw new Error(pickText(job.error, `job_failed:${jobId}`));
    }
    attempt += 1;
    await delay(Math.min(2500, 900 + attempt * 200));
  }
  const lastMessage = pickText(lastJob.progress?.message, lastJob.message);
  throw new Error(lastMessage ? `job_timeout:${jobId} · ${lastMessage}` : `job_timeout:${jobId}`);
}

export async function requestBridgeData<T = any>(
  settings: PreviewSettings,
  path: string,
  method = 'GET',
  body?: Record<string, unknown>
): Promise<RequestResult<T>> {
  const mode = effectiveMode(settings);
  if (mode === 'mock') {
    const { mockBridgeRequest } = await import('./mock');
    return { data: await mockBridgeRequest(path, method, body) as T, source: 'mock' };
  }

  try {
    return {
      data: await bridgeRequest<T>(path, method, body, {
        baseUrl: settings.bridgeBaseUrl,
        token: settings.bridgeToken,
        mode,
      }),
      source: 'live',
    };
  } catch (error) {
    throw error;
  }
}

export async function requestPhoneData<T = any>(
  settings: PreviewSettings,
  phone: { baseUrl: string; token: string },
  path: string,
  method = 'GET',
  body?: Record<string, unknown>,
  options: PhoneRequestOptions = {},
): Promise<RequestResult<T>> {
  const mode = effectiveMode(settings);
  if (mode === 'mock') {
    const { mockPhoneRequest } = await import('./mock');
    return { data: await mockPhoneRequest(phone.baseUrl, phone.token, path, method, body) as T, source: 'mock' };
  }

  try {
    const data = await phoneRequest<T>(phone.baseUrl, phone.token, path, method, body, options);
    return {
      data: unwrapPhonePayload(data) as T,
      source: 'live',
    };
  } catch (error) {
    throw error;
  }
}

function unwrapPhonePayload<T>(payload: T): unknown {
  if (!payload || typeof payload !== 'object') return payload;
  const data = payload as any;
  if (data.success === false) {
    throw new Error(typeof data.error === 'string' ? data.error : 'phone_request_failed');
  }
  if (data.success === true && Object.prototype.hasOwnProperty.call(data, 'data')) {
    return data.data;
  }
  return payload;
}

function normalizeService(raw: any, source: DataSource, logs: string[], update: ServiceSnapshot['update'], system: ServiceSnapshot['system'], licenseGate: string): ServiceSnapshot {
  return {
    source,
    running: Boolean(raw?.running),
    pid: raw?.pid ?? null,
    startupState: toText(raw?.startupState, 'idle'),
    startupElapsedSec: toNumber(raw?.startupElapsedSec, 0),
    startupTimeoutSec: toNumber(raw?.startupTimeoutSec, 420),
    startupStage: toText(raw?.startupStage, 'idle'),
    startupError: toText(raw?.startupError, ''),
    portReady: Boolean(raw?.portReady),
    processAlive: Boolean(raw?.processAlive),
    statusLabel: toText(raw?.status || raw?.startupState || (raw?.running ? 'running' : 'idle'), 'idle'),
    logTail: logs,
    update,
    system,
    licenseGate,
  };
}

function normalizeLicense(raw: any, clientConfig: any, source: DataSource): LicenseSnapshot {
  const license = raw?.license || {};
  const gatewayProfile = raw?.gatewayProfile || {};
  const member = raw?.member || {};
  const quotas = license?.quotas || {};
  const usage = license?.usage || member?.usage || {};
  const cardSite = clientConfig?.cardSite;
  return {
    source,
    authorized: Boolean(license && Object.keys(license).length > 0),
    licensee: pickText(license.licensee, member.licensee, '未命名许可证'),
    edition: pickText(license.edition, 'Pro'),
    expires: pickText(license.expires, license.leaseExpiresAt, '永久'),
    features: cleanArray(license.features),
    installId: pickText(license.installId, 'unknown'),
    memberId: pickText(license.memberId, member.memberId, ''),
    plan: pickText(license.plan, member.plan, ''),
    memberMode: toBool(license.memberMode),
    issuedAt: pickText(license.issuedAt, ''),
    leaseExpiresAt: pickText(license.leaseExpiresAt, member.expiresAt, ''),
    gatewayBaseUrl: pickText(license.gatewayBaseUrl, gatewayProfile.baseUrl, member.gatewayBaseUrl),
    gatewayImageBaseUrl: pickText(license.gatewayImageBaseUrl, gatewayProfile.imageBaseUrl, license.gatewayBaseUrl, gatewayProfile.baseUrl),
    gatewayVideoBaseUrl: pickText(license.gatewayVideoBaseUrl, gatewayProfile.videoBaseUrl, license.gatewayBaseUrl, gatewayProfile.baseUrl),
    gatewayTokenMasked: maskSecret(pickText(license.gatewayAccessToken, license.gatewayToken, gatewayProfile.apiKey, member.gatewayToken)),
    gatewayImageTokenMasked: maskSecret(pickText(license.gatewayImageAccessToken, license.gatewayImageToken, gatewayProfile.imageApiKey, license.gatewayAccessToken, license.gatewayToken)),
    gatewayVideoTokenMasked: maskSecret(pickText(license.gatewayVideoAccessToken, license.gatewayVideoToken, gatewayProfile.videoApiKey, license.gatewayAccessToken, license.gatewayToken)),
    gatewayDefaultModel: pickText(license.gatewayDefaultModel, gatewayProfile.defaultModel, 'gpt-4o'),
    gatewayImageModel: pickText(license.gatewayImageModel, gatewayProfile.imageModel, 'gpt-image-2'),
    gatewayVideoModel: pickText(license.gatewayVideoModel, gatewayProfile.videoModel, 'happyhorse-1.0-t2v'),
    quotas: {
      llm: toNumber(quotas.llm, 0),
      image: toNumber(quotas.image, 0),
      video: toNumber(quotas.video, 0),
      month: toNumber(quotas.month, 0),
    },
    usage: {
      llm: toNumber(usage.llm, 0),
      image: toNumber(usage.image, 0),
      video: toNumber(usage.video, 0),
    },
    cardSite: cardSite?.enabled && cardSite?.url ? { enabled: true, label: pickText(cardSite.label, 'Open site'), url: cardSite.url } : null,
    rawHint: source === 'mock' ? 'mock' : 'live',
  };
}

function normalizeMember(raw: any, source: DataSource): MemberSnapshot {
  const member = raw?.member || raw?.lease || {};
  const usage = raw?.usage || member?.usage || {};
  return {
    source,
    memberId: pickText(member.memberId, ''),
    leaseId: pickText(member.leaseId, ''),
    status: pickText(member.status, 'inactive'),
    usage: {
      llm: toNumber(usage.llm, 0),
      image: toNumber(usage.image, 0),
      video: toNumber(usage.video, 0),
      month: toNumber(usage.month, 0),
    },
    quota: {
      llm: toNumber(member.quota?.llm, 0),
      image: toNumber(member.quota?.image, 0),
      video: toNumber(member.quota?.video, 0),
      month: toNumber(member.quota?.month, 0),
    },
    expiresAt: pickText(member.expiresAt, ''),
    renewAt: pickText(member.renewAt, ''),
    gatewayBaseUrl: pickText(member.gatewayBaseUrl, ''),
    gatewayTokenMasked: maskSecret(pickText(member.gatewayToken, member.token, '')),
  };
}

function normalizeGateway(raw: any, source: DataSource): GatewaySnapshot {
  const gateway = raw?.gatewayProfile || raw?.gateway || raw || {};
  return {
    source,
    hasGateway: Boolean(pickText(gateway.baseUrl, gateway.url, gateway.gatewayBaseUrl) && pickText(gateway.apiKey, gateway.token, gateway.gatewayToken)),
    baseUrl: pickText(gateway.baseUrl, gateway.url, gateway.gatewayBaseUrl),
    imageBaseUrl: pickText(gateway.imageBaseUrl, gateway.imageUrl, gateway.gatewayImageBaseUrl, gateway.baseUrl, gateway.gatewayBaseUrl),
    videoBaseUrl: pickText(gateway.videoBaseUrl, gateway.videoUrl, gateway.gatewayVideoBaseUrl, gateway.baseUrl, gateway.gatewayBaseUrl),
    apiKeyMasked: maskSecret(pickText(gateway.apiKey, gateway.token, gateway.gatewayToken)),
    imageApiKeyMasked: maskSecret(pickText(gateway.imageApiKey, gateway.imageToken, gateway.gatewayImageToken, gateway.apiKey, gateway.token)),
    videoApiKeyMasked: maskSecret(pickText(gateway.videoApiKey, gateway.videoToken, gateway.gatewayVideoToken, gateway.apiKey, gateway.token)),
    defaultModel: pickText(gateway.defaultModel, gateway.gatewayDefaultModel, 'gpt-4o'),
    imageModel: pickText(gateway.imageModel, gateway.gatewayImageModel, 'gpt-image-2'),
    videoModel: pickText(gateway.videoModel, gateway.gatewayVideoModel, 'happyhorse-1.0-t2v'),
    mode: gateway.memberMode === true || gateway.gatewayMode === 'member' ? 'member' : gateway.baseUrl ? 'manual' : 'unknown',
  };
}

function normalizeAccountSnapshot(raw: any): AccountSnapshot {
  const account = raw?.account || raw || {};
  const models = account?.models || {};
  return {
    loggedIn: Boolean(account.loggedIn),
    source: pickText(account.source, ''),
    account: pickText(account.account, ''),
    memberId: pickText(account.memberId, ''),
    plan: pickText(account.plan, ''),
    status: pickText(account.status, account.loggedIn ? 'active' : 'inactive'),
    baseUrl: pickText(account.baseUrl, ''),
    gatewayBaseUrl: pickText(account.gatewayBaseUrl, ''),
    tokenMasked: pickText(account.tokenMasked, ''),
    models: {
      text: cleanArray(models.text),
      image: cleanArray(models.image),
      video: cleanArray(models.video),
    },
    usage: account.usage && typeof account.usage === 'object' ? account.usage : {},
    lastOnlineAt: pickText(account.lastOnlineAt, ''),
    graceExpiresAt: pickText(account.graceExpiresAt, ''),
    offline: Boolean(account.offline),
    stale: Boolean(account.stale),
    lastSyncResults: Array.isArray(account.lastSyncResults)
      ? account.lastSyncResults.map((item: any) => ({
          target: pickText(item.target, ''),
          ok: Boolean(item.ok),
          error: pickText(item.error, ''),
        }))
      : [],
  };
}

function normalizeSkills(raw: any, source: DataSource): SkillSnapshot {
  return {
    source,
    skills: Array.isArray(raw?.skills)
      ? raw.skills.map((item: any) => ({
          id: pickText(item.id, ''),
          name: pickText(item.name, item.id),
          version: pickText(item.version, '0.0.0'),
          description: pickText(item.description, ''),
          category: pickText(item.category, 'general'),
          runtime: pickText(item.runtime, 'node'),
          icon: pickText(item.icon, 'SK'),
          installed: Boolean(item.installed),
          enabled: Boolean(item.enabled),
          writable: Boolean(item.writable),
          hasReadme: Boolean(item.hasReadme),
          path: pickText(item.path, ''),
          source: pickText(item.source, 'openclaw'),
          sourceLabel: pickText(item.sourceLabel, 'OpenClaw'),
        }))
      : [],
    directories: Array.isArray(raw?.directories)
      ? raw.directories.map((item: any) => ({
          key: pickText(item.key, ''),
          label: pickText(item.label, item.key),
          path: pickText(item.path, ''),
          writable: Boolean(item.writable),
        }))
      : [],
    sites: Array.isArray(raw?.sites)
      ? raw.sites.map((item: any) => ({ name: pickText(item.name, ''), url: pickText(item.url, '') }))
      : [],
    statePath: pickText(raw?.statePath, ''),
  };
}

function normalizeDiagnostics(raw: any, source: DataSource): DiagnosticsSnapshot {
  return {
    source,
    basePath: pickText(raw?.basePath, raw?.report?.basePath, ''),
    serviceRunning: Boolean(raw?.serviceRunning ?? raw?.report?.serviceRunning),
    servicePid: raw?.servicePid ?? raw?.report?.servicePid ?? null,
    startupState: pickText(raw?.startupState, raw?.report?.startupState, 'idle'),
    startupElapsedSec: toNumber(raw?.startupElapsedSec ?? raw?.report?.startupElapsedSec, 0),
    startupTimeoutSec: toNumber(raw?.startupTimeoutSec ?? raw?.report?.startupTimeoutSec, 420),
    startupError: pickText(raw?.startupError ?? raw?.report?.startupError, ''),
    startupDurationMs: raw?.startupDurationMs ?? raw?.report?.startupDurationMs ?? null,
    startupStage: pickText(raw?.startupStage ?? raw?.report?.startupStage, ''),
    startupSnapshotPath: pickText(raw?.startupSnapshotPath ?? raw?.report?.startupSnapshotPath, ''),
    summary: raw?.summary || raw?.report?.summary || { status: 'warn', ok: 0, warnings: 0, failed: 0, total: 0 },
    checks: Array.isArray(raw?.checks ?? raw?.report?.checks)
      ? (raw.checks ?? raw.report.checks).map((item: any) => ({
          id: pickText(item.id, ''),
          label: pickText(item.label, ''),
          status: (pickText(item.status, 'warn') as DiagnosticsSnapshot['checks'][number]['status']),
          message: pickText(item.message, ''),
          detail: pickText(item.detail, ''),
          repairable: Boolean(item.repairable),
        }))
      : [],
    reliability: raw?.reliability ?? raw?.report?.reliability ?? undefined,
    repairAvailable: Boolean(raw?.repairAvailable ?? raw?.report?.repairAvailable ?? true),
  };
}

function normalizeDesktop(raw: any, source: DataSource): DesktopSnapshot {
  return {
    source,
    configured: Boolean(raw?.configured),
    present: Boolean(raw?.present),
    running: Boolean(raw?.running),
    pid: raw?.pid ?? null,
    apiReady: Boolean(raw?.apiReady),
    health: raw?.health || null,
    command: Array.isArray(raw?.command) ? raw.command.map((item: any) => String(item)) : [],
    config: raw?.config || {},
  };
}

async function buildDashboardSnapshot(settings: PreviewSettings): Promise<DashboardSnapshot> {
  const [
    serviceResp,
    licenseResp,
    systemResp,
    logsResp,
  ] = await Promise.all([
    requestBridgeDataSoft<any>(settings, '/api/process/status', { running: false }, 1800),
    requestBridgeDataSoft<any>(settings, '/api/license/current', {}, 1800),
    requestBridgeDataSoft<any>(settings, '/api/system/info', {}, 1200),
    requestBridgeDataSoft<any>(settings, DASHBOARD_LOG_QUERY, { log: '' }, 1200),
  ]);

  const license = normalizeLicense(licenseResp.data, {}, licenseResp.source);
  const member = normalizeMember(licenseResp.data, licenseResp.source);
  const gateway = normalizeGateway(licenseResp.data, licenseResp.source);
  const service = normalizeService(
    serviceResp.data,
    serviceResp.source,
    splitLines(logsResp.data?.log),
    { current: systemResp.data?.openclaw_version || '', latest: '', hasUpdate: false },
    { nodePath: systemResp.data?.node_path || '', basePath: systemResp.data?.base_path || '', version: systemResp.data?.openclaw_version || '' },
    license.memberMode ? 'member' : 'manual'
  );
  const skills = normalizeSkills({ skills: [] }, serviceResp.source);
  const diagnostics = normalizeDiagnostics({
    summary: { status: 'warn', ok: 0, warnings: 1, failed: 0, total: 0 },
    checks: [],
  }, serviceResp.source);
  const systemSource = mergeSource(serviceResp.source, systemResp.source);
  const serviceWithSources = {
    ...service,
    source: mergeSource(serviceResp.source, mergeSource(logsResp.source, systemSource)),
  };

  return {
    source: mergeSource(serviceResp.source, mergeSource(licenseResp.source, mergeSource(systemResp.source, logsResp.source))),
    service: serviceWithSources,
    license,
    member,
    gateway,
    diagnostics,
    skills,
    update: service.update,
    recentLogs: splitLines(logsResp.data?.log),
    themeName: 'OpenClaw',
  };
}

export async function loadDashboardSnapshot(settings: PreviewSettings): Promise<DashboardSnapshot> {
  const key = dashboardCacheKey(settings);
  const now = Date.now();
  if (dashboardCache?.key === key && dashboardCache.expiresAt > now) {
    if (dashboardInflight?.key !== key) {
      const promise = buildDashboardSnapshot(settings)
        .then((data) => {
          dashboardCache = { key, expiresAt: Date.now() + DASHBOARD_CACHE_TTL_MS, data };
          return data;
        })
        .finally(() => {
          if (dashboardInflight?.key === key) dashboardInflight = null;
        });
      dashboardInflight = { key, promise };
    }
    return dashboardCache.data;
  }

  if (dashboardInflight?.key !== key) {
    const promise = buildDashboardSnapshot(settings)
      .then((data) => {
        dashboardCache = { key, expiresAt: Date.now() + DASHBOARD_CACHE_TTL_MS, data };
        return data;
      })
      .finally(() => {
        if (dashboardInflight?.key === key) dashboardInflight = null;
      });
    dashboardInflight = { key, promise };
  }
  return dashboardInflight.promise;
}

export async function loadServiceSnapshot(settings: PreviewSettings): Promise<ServiceSnapshot> {
  const [statusResp, logsResp, systemResp] = await Promise.all([
    requestBridgeData<any>(settings, '/api/process/status'),
    requestBridgeData<any>(settings, DASHBOARD_LOG_QUERY),
    requestBridgeData<any>(settings, '/api/system/info'),
  ]);
  return normalizeService(
    statusResp.data,
    mergeSource(statusResp.source, mergeSource(logsResp.source, systemResp.source)),
    splitLines(logsResp.data?.log),
    { current: systemResp.data?.openclaw_version || '', latest: '', hasUpdate: false },
    { nodePath: systemResp.data?.node_path || '', basePath: systemResp.data?.base_path || '', version: systemResp.data?.openclaw_version || '' },
    statusResp.data?.running ? 'running' : 'idle'
  );
}

export async function loadLicenseSnapshot(settings: PreviewSettings): Promise<{ license: LicenseSnapshot; member: MemberSnapshot; gateway: GatewaySnapshot }> {
  const [licenseResp, clientResp, memberResp] = await Promise.all([
    requestBridgeData<any>(settings, '/api/license/current'),
    requestBridgeData<any>(settings, '/api/license/client-config'),
    requestBridgeData<any>(settings, '/api/member/current'),
  ]);
  return {
    license: normalizeLicense(licenseResp.data, clientResp.data, mergeSource(licenseResp.source, clientResp.source)),
    member: normalizeMember(memberResp.data, memberResp.source),
    gateway: normalizeGateway(licenseResp.data, licenseResp.source),
  };
}

export async function loadStudioSnapshot(settings: PreviewSettings): Promise<StudioSnapshot> {
  const [licenseResp, imageConfigResp, videoConfigResp] = await Promise.all([
    requestBridgeData<any>(settings, '/api/license/current'),
    requestBridgeData<any>(settings, '/api/config/read', 'POST', { path: 'imgapi_config.json', default: {} }),
    requestBridgeData<any>(settings, '/api/config/read', 'POST', { path: 'videoapi_config.json', default: {} }),
  ]);
  const imageConfig = imageConfigResp.data?.data || {};
  const videoConfig = videoConfigResp.data?.data || {};
  const gateway = normalizeGateway(licenseResp.data, licenseResp.source);
  const licenseSource = licenseResp.data?.license || {};
  const gatewaySource = licenseResp.data?.gatewayProfile || licenseResp.data?.member?.gateway || licenseResp.data?.license || {};
  return {
    source: mergeSource(licenseResp.source, mergeSource(imageConfigResp.source, videoConfigResp.source)),
    gateway,
    imageDefaults: {
      baseUrl: pickText(
        imageConfig.baseUrl,
        licenseSource.gatewayImageBaseUrl,
        licenseSource.gatewayBaseUrl,
        gatewaySource.imageBaseUrl,
        gatewaySource.gatewayBaseUrl,
        gateway.imageBaseUrl,
        gateway.baseUrl,
      ),
      apiKey: pickText(
        imageConfig.apiKey,
        imageConfig.dashKey,
        licenseSource.gatewayImageAccessToken,
        licenseSource.gatewayImageToken,
        licenseSource.gatewayAccessToken,
        licenseSource.gatewayToken,
        gatewaySource.imageApiKey,
        gatewaySource.imageToken,
        gatewaySource.apiKey,
        gatewaySource.token,
        '',
      ),
      apiKeyMasked: maskSecret(pickText(
        imageConfig.apiKey,
        licenseSource.gatewayImageAccessToken,
        licenseSource.gatewayImageToken,
        licenseSource.gatewayAccessToken,
        licenseSource.gatewayToken,
        gatewaySource.imageApiKey,
        gatewaySource.imageToken,
        gatewaySource.apiKey,
        gatewaySource.token,
      )),
      // 'gpt-image-2' is the placeholder default, not a real Agnes model — treat it
      // as unset so the server (license) image model takes effect, like video does.
      model: pickText(imageConfig.model && imageConfig.model !== 'gpt-image-2' ? imageConfig.model : '', licenseSource.gatewayImageModel, licenseSource.gatewayDefaultModel, gatewaySource.imageModel, gateway.imageModel, gateway.defaultModel, 'gpt-image-2'),
    },
    videoDefaults: {
      apiBase: pickText(
        videoConfig.apiBase,
        licenseSource.gatewayVideoBaseUrl,
        licenseSource.gatewayBaseUrl,
        gatewaySource.videoBaseUrl,
        gatewaySource.gatewayBaseUrl,
        gateway.videoBaseUrl,
        gateway.baseUrl,
      ),
      apiKey: pickText(
        videoConfig.apiKey,
        videoConfig.dashKey,
        imageConfig.apiKey,
        imageConfig.dashKey,
        licenseSource.gatewayVideoAccessToken,
        licenseSource.gatewayVideoToken,
        licenseSource.gatewayAccessToken,
        licenseSource.gatewayToken,
        gatewaySource.videoApiKey,
        gatewaySource.videoToken,
        gatewaySource.apiKey,
        gatewaySource.token,
        '',
      ),
      apiKeyMasked: maskSecret(pickText(
        videoConfig.apiKey,
        videoConfig.dashKey,
        imageConfig.apiKey,
        imageConfig.dashKey,
        licenseSource.gatewayVideoAccessToken,
        licenseSource.gatewayVideoToken,
        licenseSource.gatewayAccessToken,
        licenseSource.gatewayToken,
        gatewaySource.videoApiKey,
        gatewaySource.videoToken,
        gatewaySource.apiKey,
        gatewaySource.token,
      )),
      model: pickText(videoConfig.model, licenseSource.gatewayVideoModel, licenseSource.gatewayDefaultModel, gatewaySource.videoModel, gateway.videoModel, gateway.defaultModel, inferVideoModel(videoConfig, gateway)),
      providerId: inferVideoProviderId(videoConfig.providerId, videoConfig.apiBase || videoConfig.baseUrl || gateway.videoBaseUrl || gateway.baseUrl, videoConfig.model || gateway.videoModel),
    },
    imageHistory: [],
    videoHistory: [],
  };
}

const BUILTIN_TEMPLATES: PromptTemplate[] = [
  { id: -1, kind: 'image', title: '产品白底图', prompt: '一张高清产品摄影，纯白背景，柔和棚拍光，居中构图，电商主图风格，细节锐利', params: { size: '1024x1024' }, coverUrl: '', tags: ['电商', '产品'], sort: 10 },
  { id: -2, kind: 'image', title: '国风插画', prompt: '中国风工笔插画，青绿山水，留白，细腻线条，雅致配色，高分辨率', params: { size: '1024x1536' }, coverUrl: '', tags: ['插画', '国风'], sort: 20 },
  { id: -3, kind: 'video', title: '城市夜景延时', prompt: '繁华都市夜景，车流光轨，霓虹灯，延时摄影质感，电影级色调，运镜平稳', params: { mode: 't2v', resolution: '720P', ratio: '16:9', duration: 5 }, coverUrl: '', tags: ['城市', '延时'], sort: 10 },
];

// Read the desktop's primary LLM gateway (auth-profiles.json) as {baseUrl, apiKey, model}
// so it can be pushed to a paired phone. Mirrors SettingsPage.formFromAuthProfiles.
export async function loadDesktopModelConfig(
  settings: PreviewSettings,
): Promise<{ baseUrl: string; apiKey: string; model: string } | null> {
  // auth-profiles lives under the state dir; the 授权码 sync writes the member
  // gateway here as the primary provider (same source SettingsPage reads).
  const src = (await readConfigValue(settings, 'data/.openclaw/agents/main/agent/auth-profiles.json', { models: { providers: {} } })) || {};
  const providers = (src.models?.providers && typeof src.models.providers === 'object') ? src.models.providers : {};
  const primaryKey = (src.models?.primary && providers[src.models.primary]) ? src.models.primary : Object.keys(providers)[0];
  const provider = primaryKey ? (providers[primaryKey] || {}) : {};
  const models = Array.isArray(provider.models) ? provider.models : [];
  const firstModel = models.map((m: any) => (typeof m === 'string' ? m : m?.id)).find(Boolean);
  const baseUrl = String(provider.baseUrl || provider.url || '').trim();
  const apiKey = String(provider.apiKey || '').trim();
  const model = String(firstModel || provider.model || '').trim();
  if (!baseUrl || !apiKey) return null;
  return { baseUrl, apiKey, model };
}

export async function loadPromptTemplates(settings: PreviewSettings, kind: 'image' | 'video'): Promise<PromptTemplate[]> {
  const result = await requestBridgeDataSoft<{ templates?: PromptTemplate[] }>(
    settings,
    '/api/templates?kind=' + kind,
    { templates: [] },
    4000,
  );
  const list = result?.data?.templates;
  if (Array.isArray(list) && list.length) {
    return list.filter((item) => item && item.kind === kind);
  }
  // License/bridge offline — fall back to the built-in starters so the library is never blank.
  return BUILTIN_TEMPLATES.filter((item) => item.kind === kind);
}

function inferVideoProviderId(providerId: unknown, apiBase: unknown, model: unknown): string {
  const id = pickText(providerId).toLowerCase();
  const base = pickText(apiBase).toLowerCase();
  const modelId = pickText(model).toLowerCase();
  if (id === 'agnes' || base.includes('agnes-ai.com') || modelId.startsWith('agnes-video')) return 'agnes';
  if (id === 'seedance' || base.includes('volces.com') || modelId.includes('seedance')) return 'seedance';
  if (id === 'custom') return 'custom';
  return id || 'dashscope';
}

function inferVideoModel(videoConfig: any, gateway: GatewaySnapshot): string {
  const providerId = inferVideoProviderId(videoConfig?.providerId, videoConfig?.apiBase || videoConfig?.baseUrl || gateway.videoBaseUrl || gateway.baseUrl, videoConfig?.model || gateway.videoModel);
  if (providerId === 'agnes') return 'agnes-video-v2.0';
  return '';
}

export async function generateImage(settings: PreviewSettings, payload: {
  baseUrl: string;
  apiKey: string;
  prompt: string;
  size: string;
  count?: number;
  editImagePath?: string;
  model?: string;
}): Promise<RequestResult<ImageResult>> {
  const mode = effectiveMode(settings);
  const submitResponse = await requestBridgeData<any>(
    settings,
    mode === 'mock' ? '/api/image/generate' : '/api/image/generate_job',
    'POST',
    payload,
  );
  const jobId = pickText(submitResponse.data?.jobId, submitResponse.data?.job?.id);
  const resultResponse = jobId
    ? await waitForBridgeJob<any>(settings, jobId, 10 * 60 * 1000)
    : submitResponse;
  const source = mergeSource(submitResponse.source, resultResponse.source);
  const images = Array.isArray(resultResponse.data?.images) ? resultResponse.data.images : [];
  const files = Array.isArray(resultResponse.data?.files) ? resultResponse.data.files : [];
  return {
    source,
    data: {
      prompt: payload.prompt,
      size: payload.size,
      count: toNumber(resultResponse.data?.count, images.length || 1),
      previewUrls: images.map((base64: string) => `data:image/png;base64,${base64}`),
      files: files.map((item: any) => ({
        path: pickText(item.path, ''),
        filename: pickText(item.filename, ''),
        size: toNumber(item.size, 0),
        mime: pickText(item.mime, 'image/png'),
      })),
      source,
    },
  };
}

function mapVideoResult(payload: VideoGenerationPayload, resultResponse: RequestResult<any>): RequestResult<VideoResult> {
  const source = resultResponse.source;
  const video = pickText(resultResponse.data?.video, '');
  const mime = pickText(resultResponse.data?.mime, 'video/mp4');
  const previewUrl = video ? (video.startsWith('data:') ? video : `data:${mime};base64,${video}`) : '';
  return {
    source,
    data: {
      prompt: payload.prompt,
      mode: payload.mode,
      resolution: payload.resolution,
      ratio: payload.ratio,
      duration: payload.duration,
      previewUrl,
      mime,
      file: resultResponse.data?.path
        ? {
            path: pickText(resultResponse.data.path, ''),
            filename: pickText(resultResponse.data.filename, ''),
            size: toNumber(resultResponse.data.size, 0),
            mime,
          }
        : undefined,
      source,
    },
  };
}

export async function submitVideoGenerationJob(
  settings: PreviewSettings,
  payload: VideoGenerationPayload,
): Promise<RequestResult<any>> {
  const mode = effectiveMode(settings);
  return requestBridgeData<any>(
    settings,
    mode === 'mock' ? '/api/video/generate' : '/api/video/generate_job',
    'POST',
    payload as unknown as Record<string, unknown>,
  );
}

export async function waitForVideoGenerationJob(
  settings: PreviewSettings,
  jobId: string,
  payload: VideoGenerationPayload,
  onProgress?: (job: BridgeJob<any>) => void,
  timeoutMs = 20 * 60 * 1000,
): Promise<RequestResult<VideoResult>> {
  const resultResponse = await waitForBridgeJob<any>(settings, jobId, timeoutMs, onProgress);
  return mapVideoResult(payload, resultResponse);
}

export async function generateVideo(
  settings: PreviewSettings,
  payload: VideoGenerationPayload,
  onProgress?: (job: BridgeJob<any>) => void,
  onJob?: (job: { jobId: string; job?: BridgeJob<any>; source: DataSource }) => void,
): Promise<RequestResult<VideoResult>> {
  const submitResponse = await submitVideoGenerationJob(settings, payload);
  const jobId = pickText(submitResponse.data?.jobId, submitResponse.data?.job?.id);
  if (!jobId) return mapVideoResult(payload, submitResponse);
  onJob?.({ jobId, job: submitResponse.data?.job, source: submitResponse.source });
  const resultResponse = await waitForBridgeJob<any>(settings, jobId, 20 * 60 * 1000, onProgress);
  return mapVideoResult(payload, { ...resultResponse, source: mergeSource(submitResponse.source, resultResponse.source) });
}

export async function loadSkillsSnapshot(settings: PreviewSettings): Promise<SkillSnapshot> {
  const response = await requestBridgeData<any>(settings, '/api/skills/list');
  return normalizeSkills(response.data, response.source);
}

export async function toggleSkill(settings: PreviewSettings, id: string, enabled: boolean) {
  return requestBridgeData(settings, '/api/skills/enable', 'POST', { id, enabled });
}

export async function installSkillZip(settings: PreviewSettings, filename: string, data: string) {
  return requestBridgeData(settings, '/api/skills/install_zip', 'POST', { filename, data });
}

export async function uninstallSkill(settings: PreviewSettings, id: string) {
  return requestBridgeData(settings, '/api/skills/uninstall', 'POST', { id });
}

export async function readSkillReadme(settings: PreviewSettings, id: string) {
  return requestBridgeData(settings, '/api/skills/readme', 'POST', { id });
}

export async function loadComponentsSnapshot(settings: PreviewSettings): Promise<ComponentSnapshot> {
  const response = await requestBridgeData<Omit<ComponentSnapshot, 'source'>>(settings, '/api/components/status');
  return { ...response.data, source: response.source };
}

export async function installComponent(settings: PreviewSettings, componentId: string): Promise<ComponentSnapshot> {
  const response = await requestBridgeData<{ jobId?: string; job?: BridgeJob<any>; catalog?: Omit<ComponentSnapshot, 'source'> }>(
    settings,
    '/api/components/install',
    'POST',
    { componentId },
  );
  const jobId = pickText(response.data?.jobId, response.data?.job?.id);
  if (jobId) {
    const result = await waitForBridgeJob<{ catalog?: Omit<ComponentSnapshot, 'source'> }>(settings, jobId, 60 * 60 * 1000);
    return {
      ...(result.data?.catalog || response.data.catalog || { manifest: null, components: [], error: 'install_response_missing_catalog' }),
      source: mergeSource(response.source, result.source),
    };
  }
  return { ...(response.data.catalog || { manifest: null, components: [], error: 'install_response_missing_catalog' }), source: response.source };
}

export async function rollbackComponent(settings: PreviewSettings, componentId: string): Promise<ComponentSnapshot> {
  const response = await requestBridgeData<{ catalog?: Omit<ComponentSnapshot, 'source'> }>(
    settings,
    '/api/components/rollback',
    'POST',
    { componentId },
  );
  return { ...(response.data.catalog || { manifest: null, components: [], error: 'rollback_response_missing_catalog' }), source: response.source };
}

export async function loadDiagnosticsSnapshot(settings: PreviewSettings): Promise<DiagnosticsSnapshot> {
  const mode = effectiveMode(settings);
  const submitResponse = await requestBridgeData<any>(
    settings,
    mode === 'mock' ? '/api/diagnostics/run' : '/api/diagnostics/run_job',
    'POST',
    {},
  );
  const jobId = pickText(submitResponse.data?.jobId, submitResponse.data?.job?.id);
  const resultResponse = jobId
    ? await waitForBridgeJob<any>(settings, jobId, 3 * 60 * 1000)
    : submitResponse;
  return normalizeDiagnostics(resultResponse.data, mergeSource(submitResponse.source, resultResponse.source));
}

export async function repairDiagnostics(settings: PreviewSettings) {
  const mode = effectiveMode(settings);
  const submitResponse = await requestBridgeData<any>(
    settings,
    mode === 'mock' ? '/api/diagnostics/repair' : '/api/diagnostics/repair_job',
    'POST',
    {},
  );
  const jobId = pickText(submitResponse.data?.jobId, submitResponse.data?.job?.id);
  if (!jobId) return submitResponse;
  const resultResponse = await waitForBridgeJob<any>(settings, jobId, 5 * 60 * 1000);
  return {
    data: resultResponse.data,
    source: mergeSource(submitResponse.source, resultResponse.source),
  };
}

export async function exportDiagnostics(settings: PreviewSettings) {
  return requestBridgeData(settings, '/api/diagnostics/export', 'POST', {});
}

export async function loadDesktopSnapshot(settings: PreviewSettings): Promise<DesktopSnapshot> {
  const response = await requestBridgeData<any>(settings, '/api/desktop-agent/status');
  return normalizeDesktop(response.data, response.source);
}

export async function startDesktopAgent(settings: PreviewSettings) {
  return requestBridgeData(settings, '/api/desktop-agent/start', 'POST', {});
}

export async function stopDesktopAgent(settings: PreviewSettings) {
  return requestBridgeData(settings, '/api/desktop-agent/stop', 'POST', {});
}

export async function saveDesktopAgentConfig(settings: PreviewSettings, config: Record<string, unknown>) {
  return requestBridgeData(settings, '/api/desktop-agent/config', 'POST', config);
}

export async function installDesktopAgentLayer(settings: PreviewSettings) {
  if (effectiveMode(settings) === 'mock') {
    return { data: { installed: true, layerId: 'luminode-desktop' }, source: 'mock' as DataSource };
  }
  await installDistributionLayer('luminode-desktop');
  return { data: { installed: true, layerId: 'luminode-desktop' }, source: 'live' as DataSource };
}

export async function loadSettingsSnapshot(settings: PreviewSettings): Promise<SettingsSnapshot> {
  const bridgeBaseUrl = resolveBridgeBaseUrl(settings.bridgeBaseUrl);
  const envNames = [
    'VITE_OPENCLAW_API_BASE_URL',
    'VITE_OPENCLAW_PROXY_TARGET',
    'VITE_OPENCLAW_BRIDGE_TOKEN',
    'VITE_OPENCLAW_PHONE_BASE_URL',
    'VITE_OPENCLAW_PHONE_TOKEN',
    'VITE_OPENCLAW_IMAGE_BASE_URL',
    'VITE_OPENCLAW_IMAGE_API_KEY',
    'VITE_OPENCLAW_IMAGE_MODEL',
    'VITE_OPENCLAW_VIDEO_BASE_URL',
    'VITE_OPENCLAW_VIDEO_API_KEY',
    'VITE_OPENCLAW_VIDEO_MODEL',
    'OPENCLAW_BRIDGE_REQUIRE_FASTAPI',
    'OPENCLAW_STARTUP_TIMEOUT_SEC',
    'OPENCLAW_STARTUP_DEEP_CLEAN',
    'OPENCLAW_STARTUP_STORAGE_WRITE_TEST',
    'OPENCLAW_PHONE_ALBUM',
    'OPENCLAW_DESKTOP_AGENT_DIR',
    'OPENCLAW_IMAGE_BASE_URL',
    'OPENCLAW_IMAGE_API_KEY',
    'OPENCLAW_IMAGE_MODEL',
    'OPENCLAW_VIDEO_BASE_URL',
    'OPENCLAW_VIDEO_API_KEY',
    'OPENCLAW_VIDEO_MODEL',
    'LICENSE_ADMIN_TOKEN',
    'LICENSE_ADMIN_TOKEN_FILE',
    'MEMBER_GATEWAY_BASE_URL',
    'MEMBER_GATEWAY_IMAGE_BASE_URL',
    'MEMBER_GATEWAY_VIDEO_BASE_URL',
  ];
  const env = envNames.map((key) => ({
    key,
    value: key.includes('TOKEN') || key.includes('KEY') ? maskSecret((import.meta.env as Record<string, string | undefined>)[key] || '') : String((import.meta.env as Record<string, string | undefined>)[key] || '').trim() || '未设置',
    note:
      key.startsWith('VITE_OPENCLAW_PROXY_TARGET')
        ? 'Vite 开发代理'
        : key.startsWith('VITE_OPENCLAW_API_BASE_URL')
          ? '桥接地址'
          : key.startsWith('OPENCLAW_')
            ? '运行时环境'
            : '服务端环境',
  }));
  return {
    source: bridgeBaseUrl ? 'mixed' : 'mock',
    bridgeBaseUrl: bridgeBaseUrl || '/api',
    bridgeTokenMasked: maskSecret(settings.bridgeToken || (import.meta.env.VITE_OPENCLAW_BRIDGE_TOKEN as string) || ''),
    transportMode: settings.transportMode,
    proxyTarget: pickText(import.meta.env.VITE_OPENCLAW_PROXY_TARGET, ''),
    env,
    configPaths: [
      { key: 'authProfiles', path: 'data/.openclaw/agents/main/agent/auth-profiles.json', writable: true },
      { key: 'imageConfig', path: 'imgapi_config.json', writable: true },
      { key: 'videoConfig', path: 'videoapi_config.json', writable: true },
      { key: 'phoneAgent', path: 'data/.openclaw/launcher/phone-agent.json', writable: true },
      { key: 'phoneAgents', path: 'data/.openclaw/launcher/phone-agents.json', writable: true },
      { key: 'platformIntegrations', path: 'data/.openclaw/launcher/platform-integrations.json', writable: true },
      { key: 'publish', path: 'data/.openclaw/launcher/publish.json', writable: true },
      { key: 'openclaw', path: 'data/.openclaw/openclaw.json', writable: true },
    ],
    themeName: '星航玻璃',
  };
}

export async function readConfigValue(settings: PreviewSettings, path: string, defaultValue: unknown = {}) {
  const response = await requestBridgeData<any>(settings, '/api/config/read', 'POST', { path, default: defaultValue });
  return response.data?.data;
}

export async function writeConfigValue(settings: PreviewSettings, path: string, data: unknown) {
  return requestBridgeData(settings, '/api/config/write', 'POST', { path, data });
}

export async function saveAuthProfiles(settings: PreviewSettings, data: Record<string, unknown>) {
  return writeConfigValue(settings, 'data/.openclaw/agents/main/agent/auth-profiles.json', data);
}

export async function loadUpdateSnapshot(settings: PreviewSettings) {
  return requestBridgeData(settings, '/api/update/check');
}

export async function runUpdate(settings: PreviewSettings) {
  return requestBridgeData(settings, '/api/update/do', 'POST', {});
}

export async function activateLicense(settings: PreviewSettings, code: string) {
  return requestBridgeData(settings, '/api/license/activate', 'POST', { code });
}

export async function activateMember(settings: PreviewSettings, code: string) {
  return requestBridgeData(settings, '/api/member/activate', 'POST', { code });
}

export async function refreshMember(settings: PreviewSettings) {
  return requestBridgeData(settings, '/api/member/refresh', 'POST', {});
}

export async function loadAccountSnapshot(settings: PreviewSettings): Promise<AccountSnapshot> {
  const response = await requestBridgeData<any>(settings, '/api/account/current');
  return normalizeAccountSnapshot(response.data);
}

export async function loginAccount(settings: PreviewSettings, payload: {
  username: string;
  password: string;
  baseUrl?: string;
  apiToken?: string;
}): Promise<AccountSnapshot> {
  const response = await requestBridgeData<any>(settings, '/api/account/login', 'POST', {
    username: payload.username,
    password: payload.password,
    baseUrl: payload.baseUrl,
    apiToken: payload.apiToken,
  });
  return normalizeAccountSnapshot(response.data);
}

export async function bindAccountTicket(settings: PreviewSettings, payload: {
  ticket: string;
  baseUrl?: string;
}): Promise<AccountSnapshot> {
  const response = await requestBridgeData<any>(settings, '/api/account/bind-ticket', 'POST', {
    ticket: payload.ticket,
    baseUrl: payload.baseUrl,
  });
  return normalizeAccountSnapshot(response.data);
}

export async function syncAccount(settings: PreviewSettings): Promise<AccountSnapshot> {
  const response = await requestBridgeData<any>(settings, '/api/account/sync', 'POST', {});
  return normalizeAccountSnapshot(response.data);
}

export async function logoutAccount(settings: PreviewSettings): Promise<AccountSnapshot> {
  const response = await requestBridgeData<any>(settings, '/api/account/logout', 'POST', {});
  return normalizeAccountSnapshot(response.data);
}

export async function loadClientConfig(settings: PreviewSettings) {
  return requestBridgeData(settings, '/api/license/client-config');
}

export async function loadThemeSnapshot(settings: PreviewSettings) {
  return requestBridgeData(settings, '/api/theme/current');
}

export async function loadLogSnapshot(settings: PreviewSettings, offset = 0, maxBytes = 500000) {
  const safeOffset = Math.max(0, offset);
  const query = new URLSearchParams({
    offset: String(safeOffset),
    maxBytes: String(Math.max(1, maxBytes)),
  });
  if (safeOffset === 0) query.set('tail', '1');
  return requestBridgeData(settings, `/api/log/get?${query.toString()}`);
}

export async function clearLogs(settings: PreviewSettings) {
  return requestBridgeData(settings, '/api/log/clear', 'POST', {});
}

export async function startProcess(settings: PreviewSettings) {
  return requestBridgeData(settings, '/api/process/start', 'POST', {});
}

export async function stopProcess(settings: PreviewSettings) {
  return requestBridgeData(settings, '/api/process/stop', 'POST', {});
}

export async function loadProcessStatus(settings: PreviewSettings) {
  return requestBridgeData(settings, '/api/process/status');
}

export async function loadLicenseBundle(settings: PreviewSettings) {
  const [license, member, clientConfig] = await Promise.all([
    requestBridgeData<any>(settings, '/api/license/current'),
    requestBridgeData<any>(settings, '/api/member/current'),
    requestBridgeData<any>(settings, '/api/license/client-config'),
  ]);
  return {
    source: mergeSource(license.source, mergeSource(member.source, clientConfig.source)),
    license: normalizeLicense(license.data, clientConfig.data, license.source),
    member: normalizeMember(member.data, member.source),
    gateway: normalizeGateway(license.data, license.source),
  };
}
