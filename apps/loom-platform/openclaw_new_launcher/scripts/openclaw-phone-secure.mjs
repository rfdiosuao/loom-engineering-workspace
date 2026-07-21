import crypto from 'node:crypto';
import { createReadStream } from 'node:fs';
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const REQUEST_TIMEOUT_MS = 615_000;
const DEFAULT_PHONE_PORT = '9527';
const PAIRING_FAILURE_COOLDOWN_MS = 30_000;
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const PROJECT_ROOT = path.resolve(__dirname, '..');
const pairingCache = new Map();
const pairingInflight = new Map();
const pairingFailures = new Map();
const pairingRepairInflight = new Map();
const pairingAuthRetryTails = new Map();
const PHONE_RUNTIME_CONFIG_ENV = 'LOOM_PHONE_RUNTIME_CONFIG_JSON';
const LEGACY_JSON_MEDIA_FALLBACK_BYTES = 8 * 1024 * 1024;
const PHONE_CONFIG_REMEDIATION = Object.freeze([
  '请打开 APKClaw -> Settings -> LAN Config，并确认局域网服务已开启。',
  '确认手机和电脑在同一网络，端口通常为 9527。',
  "PowerShell 示例：$env:OPENCLAW_PHONE_BASE_URL='http://手机IP:9527'; $env:OPENCLAW_PHONE_TOKEN='<连接令牌>'",
  'CLI 示例：node scripts\\openclaw-phone-agent.mjs metrics --phone-url http://手机IP:9527 --phone-token <连接令牌> --json',
]);
const PHONE_AUTH_REMEDIATION = Object.freeze([
  '手机已经可以连接，但保存的连接令牌无效或已经变更。',
  '请打开 APKClaw -> Settings -> LAN Config，重新复制当前连接令牌。',
  '回到麓鸣手机连接配置，替换旧令牌并保存，然后重新检测。',
]);

export class PhoneBridgeError extends Error {
  constructor(code, message, options = {}) {
    super(message);
    this.name = 'PhoneBridgeError';
    this.code = code || 'phone_bridge_error';
    this.errorCode = this.code;
    this.retryable = options.retryable !== false;
    this.phase = options.phase || '';
    this.currentStep = options.currentStep || 'preflight';
    this.details = options.details && typeof options.details === 'object' ? options.details : {};
    this.remediation = Array.isArray(options.remediation) && options.remediation.length
      ? options.remediation
      : PHONE_CONFIG_REMEDIATION;
    if (options.cause) this.cause = options.cause;
  }
}

export function phoneBridgeErrorPayload(error, config = {}, phase = 'phone') {
  const normalized = normalizeBridgeError(error);
  const configSource = String(config?.source || config?.configSource || '').trim();
  const configSourceKind = configSourceKindForPath(configSource);
  return {
    ok: false,
    errorCode: normalized.errorCode,
    error: normalized.errorCode,
    message: normalized.message,
    retryable: normalized.retryable,
    phase: normalized.phase || phase,
    currentStep: normalized.currentStep || 'preflight',
    remediation: normalized.remediation,
    config: {
      phoneUrlConfigured: Boolean(config?.phoneUrl),
      phoneTokenConfigured: Boolean(config?.phoneToken),
      phoneUrl: safePhoneUrl(config?.phoneUrl),
      source: configSource,
      sourceKind: config?.sourceKind || configSourceKind,
    },
    details: normalized.details,
  };
}

export function normalizePhoneUrl(url) {
  let text = String(url || '')
    .trim()
    .replace(/[：﹕꞉]/g, ':')
    .replace(/[／⁄]/g, '/')
    .replace(/[。．｡]/g, '.')
    .replace(/\s+/g, '')
    .replace(/^http:\/(?!\/)/i, 'http://')
    .replace(/^https:\/(?!\/)/i, 'https://');
  if (!text) return '';
  if (text.startsWith('//')) text = `http:${text}`;
  if (!/^[a-z][a-z0-9+.-]*:\/\//i.test(text)) text = `http://${text}`;
  const parsed = new URL(text);
  if (!['http:', 'https:'].includes(parsed.protocol)) throw new Error('invalid_phone_url');
  if (!parsed.hostname || isMalformedIpv4Like(parsed.hostname)) throw new Error('invalid_phone_url');
  if (!parsed.port && isLikelyLanHost(parsed.hostname)) parsed.port = DEFAULT_PHONE_PORT;
  parsed.username = '';
  parsed.password = '';
  parsed.pathname = '';
  parsed.search = '';
  parsed.hash = '';
  return parsed.toString().replace(/\/+$/, '');
}

function isLikelyLanHost(hostname) {
  const host = String(hostname || '').replace(/^\[|\]$/g, '').toLowerCase();
  if (host === 'localhost' || host === '::1') return true;
  if (/^192\.168\.\d{1,3}\.\d{1,3}$/.test(host)) return true;
  if (/^10\.\d{1,3}\.\d{1,3}\.\d{1,3}$/.test(host)) return true;
  if (/^172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}$/.test(host)) return true;
  return /^127\.\d{1,3}\.\d{1,3}\.\d{1,3}$/.test(host);
}

function isMalformedIpv4Like(hostname) {
  const host = String(hostname || '').replace(/^\[|\]$/g, '').toLowerCase();
  if (!/^[a-z0-9.-]+$/i.test(host)) return false;
  const parts = host.split('.');
  const onlyDigitsAndDots = /^[\d.]+$/.test(host);
  if (onlyDigitsAndDots) return parts.length !== 4 || parts.some((part) => !part || Number(part) > 255);
  if (parts.length !== 4) return false;
  return parts.filter((part) => /\d/.test(part)).length >= 3;
}

function normalizeStoredPhoneUrl(value) {
  try {
    return normalizePhoneUrl(value);
  } catch {
    return String(value || '').trim().replace(/\/+$/, '');
  }
}

function normalizeBridgeError(error) {
  if (error?.payload && typeof error.payload === 'object' && error.payload.ok === false) {
    return {
      errorCode: error.payload.errorCode || error.payload.error || error.code || 'phone_bridge_error',
      message: error.payload.message || error.message || '手机桥接请求失败。',
      retryable: error.payload.retryable !== false,
      phase: error.payload.phase || error.phase || '',
      currentStep: error.payload.currentStep || error.currentStep || 'preflight',
      remediation: Array.isArray(error.payload.remediation) && error.payload.remediation.length ? error.payload.remediation : PHONE_CONFIG_REMEDIATION,
      details: error.payload.details && typeof error.payload.details === 'object' ? error.payload.details : {},
    };
  }
  if (error instanceof PhoneBridgeError || error?.name === 'PhoneBridgeError') {
    return {
      errorCode: error.errorCode || error.code || 'phone_bridge_error',
      message: error.message || '手机桥接请求失败。',
      retryable: error.retryable !== false,
      phase: error.phase || '',
      currentStep: error.currentStep || 'preflight',
      remediation: Array.isArray(error.remediation) && error.remediation.length ? error.remediation : PHONE_CONFIG_REMEDIATION,
      details: error.details && typeof error.details === 'object' ? error.details : {},
    };
  }
  const message = String(error?.message || error || '').trim();
  if (/Missing phone URL/i.test(message)) {
    return normalizeBridgeError(new PhoneBridgeError(
      'missing_phone_url',
      '手机连接地址缺失。请在麓鸣手机页保存手机 IP，或打开 APKClaw -> Settings -> LAN Config 后复制地址。',
      { retryable: true },
    ));
  }
  if (/Missing phone token/i.test(message)) {
    return normalizeBridgeError(new PhoneBridgeError(
      'missing_phone_token',
      '手机连接令牌缺失。请在 APKClaw -> Settings -> LAN Config 中复制连接令牌，再回到麓鸣保存。',
      { retryable: true },
    ));
  }
  if (looksLikePhoneAuthFailure(message)) {
    return normalizeBridgeError(new PhoneBridgeError(
      'auth_failed',
      '已连接到手机端 APKClaw，但连接令牌无效或已经变更。请重新复制并保存 LAN Config 中的当前连接令牌。',
      {
        retryable: true,
        remediation: PHONE_AUTH_REMEDIATION,
        details: { reason: 'invalid_phone_token' },
      },
    ));
  }
  if (looksLikeConnectionFailure(error)) {
    return normalizeBridgeError(new PhoneBridgeError(
      'phone_config_server_unreachable',
      '无法连接手机端 APKClaw ConfigServer。请打开 APKClaw -> Settings -> LAN Config，并确认手机和电脑在同一网络。',
      { retryable: true, details: { reason: errorMessageWithCause(error) } },
    ));
  }
  const prefix = message.match(/^([a-z][a-z0-9_:-]{2,64}):/i)?.[1]?.replace(/[:-]+$/, '');
  return {
    errorCode: prefix || 'phone_bridge_error',
    message: message || '手机桥接请求失败。',
    retryable: true,
    phase: '',
    currentStep: 'error',
    remediation: PHONE_CONFIG_REMEDIATION,
    details: {},
  };
}

function looksLikePhoneAuthFailure(value) {
  const text = String(value || '');
  return /(unauthorized|forbidden|invalid or missing token|invalid token|token mismatch|HTTP\s*(401|403)\b)/i.test(text);
}

function looksLikeConnectionFailure(error) {
  const text = errorMessageWithCause(error);
  return /(fetch failed|failed to fetch|ECONNREFUSED|ECONNRESET|ECONNABORTED|EHOSTUNREACH|ENETUNREACH|ETIMEDOUT|socket hang up|networkerror|network error|terminated)/i.test(text);
}

function errorMessageWithCause(error) {
  const values = [
    error?.message,
    error?.code,
    error?.cause?.message,
    error?.cause?.code,
    error?.cause?.errno,
  ];
  return values.filter(Boolean).map((value) => String(value)).join(' ');
}

function safePhoneUrl(value) {
  try {
    return normalizePhoneUrl(value);
  } catch {
    return String(value || '').trim().replace(/\/+$/, '');
  }
}

function configSourceKindForPath(filePath) {
  const normalized = String(filePath || '').replace(/\\/g, '/');
  if (!normalized) return 'none';
  if (normalized.includes('/LOOMFiles/')) return 'packaged-loom';
  if (normalized.includes('/OpenClawFiles/')) return 'packaged-openclaw';
  if (normalized.includes('/data/.openclaw/launcher/')) return 'source';
  return 'custom';
}

function launcherConfigCandidates(fileName) {
  const relative = ['data', '.openclaw', 'launcher', fileName];
  const candidates = [];
  for (const root of configSearchRoots()) {
    candidates.push(path.join(root, ...relative));
    candidates.push(path.join(root, 'LOOMFiles', ...relative));
    candidates.push(path.join(root, 'OpenClawFiles', ...relative));
  }
  return uniquePaths(candidates);
}

function configSearchRoots() {
  const roots = [
    PROJECT_ROOT,
    path.resolve(PROJECT_ROOT, '..'),
    process.cwd(),
    process.env.LOOM_LAUNCHER_ROOT,
    process.env.OPENCLAW_LAUNCHER_ROOT,
    process.env.LOOM_HOME,
  ].filter(Boolean);
  if (path.basename(PROJECT_ROOT).toLowerCase() === '_up_') {
    roots.push(path.resolve(PROJECT_ROOT, '..'));
    roots.push(path.resolve(PROJECT_ROOT, '..', '..'));
  }
  return uniquePaths(roots.map((root) => path.resolve(String(root))));
}

function uniquePaths(values) {
  const seen = new Set();
  const result = [];
  for (const value of values) {
    const resolved = path.resolve(String(value || ''));
    const key = resolved.toLowerCase();
    if (!resolved || seen.has(key)) continue;
    seen.add(key);
    result.push(resolved);
  }
  return result;
}

export function ensurePhoneConfig(config) {
  if (!config.phoneUrl) {
    throw new PhoneBridgeError(
      'missing_phone_url',
      '手机连接地址缺失。请在麓鸣手机页保存手机 IP，或打开 APKClaw -> Settings -> LAN Config 后复制地址。',
      { retryable: true, remediation: PHONE_CONFIG_REMEDIATION },
    );
  }
  if (!config.phoneToken) {
    throw new PhoneBridgeError(
      'missing_phone_token',
      '手机连接令牌缺失。请在 APKClaw -> Settings -> LAN Config 中复制连接令牌，再回到麓鸣保存。',
      { retryable: true, remediation: PHONE_CONFIG_REMEDIATION },
    );
  }
}

export async function readLauncherPhoneConfig() {
  const selected = await readLauncherPhoneConfigByDevice();
  return selected;
}

export async function readLauncherPhoneLlmConfig() {
  const candidates = launcherConfigCandidates('phone-agent.json');

  for (const filePath of candidates) {
    try {
      const parsed = JSON.parse(await fs.readFile(filePath, 'utf8'));
      const llm = parsed?.llm && typeof parsed.llm === 'object' ? parsed.llm : {};
      const baseUrl = typeof llm.baseUrl === 'string' ? llm.baseUrl.trim() : '';
      const apiKey = typeof llm.apiKey === 'string' ? llm.apiKey.trim() : '';
      const model = typeof llm.model === 'string' ? llm.model.trim() : '';
      if (!baseUrl || !apiKey || !model) continue;
      return { baseUrl, apiKey, model, source: filePath };
    } catch (error) {
      if (error?.code !== 'ENOENT') throw new Error(`Failed to read launcher phone model config: ${filePath}: ${error.message}`);
    }
  }

  return { baseUrl: '', apiKey: '', model: '', source: '' };
}

export async function readLauncherPhoneStore() {
  const runtimeStore = readRuntimePhoneStore();
  if (runtimeStore.devices.length) return runtimeStore;
  const candidates = launcherConfigCandidates('phone-agents.json');

  for (const filePath of candidates) {
    try {
      const parsed = JSON.parse(await fs.readFile(filePath, 'utf8'));
      if (!Array.isArray(parsed?.devices) || !parsed.devices.length) continue;
      return {
        selectedDeviceId: typeof parsed?.selectedDeviceId === 'string' ? parsed.selectedDeviceId : '',
        devices: parsed.devices
          .filter((item) => item && typeof item === 'object')
          .map((item) => ({
            id: typeof item.id === 'string' ? item.id.trim() : '',
            name: typeof item.name === 'string' ? item.name.trim() : '',
            phoneUrl: normalizeStoredPhoneUrl(item.baseUrl),
            phoneToken: typeof item.token === 'string' ? item.token.trim() : '',
            lumiLauncherId: typeof item.launcherId === 'string' ? item.launcherId.trim() : '',
            lumiLauncherSecret: typeof item.launcherSecret === 'string' ? item.launcherSecret.trim() : '',
            album: typeof item.album === 'string' ? item.album.trim() : '',
            tags: Array.isArray(item.tags) ? item.tags.map((tag) => String(tag).trim()).filter(Boolean) : [],
            priority: Number.isFinite(Number(item.priority)) ? Number(item.priority) : 0,
          }))
          .filter((item) => item.id || item.phoneUrl || item.name),
        source: filePath,
      };
    } catch (error) {
      if (error?.code !== 'ENOENT') throw new Error(`Failed to read launcher phone config: ${filePath}: ${error.message}`);
    }
  }

  return { selectedDeviceId: '', devices: [], source: '' };
}

function readRuntimePhoneStore() {
  const raw = String(process.env[PHONE_RUNTIME_CONFIG_ENV] || '').trim();
  if (!raw) return { selectedDeviceId: '', devices: [], source: '' };
  let parsed;
  try {
    parsed = JSON.parse(raw);
  } catch {
    throw new Error('Invalid launcher phone runtime config.');
  }
  const devices = Array.isArray(parsed?.devices)
    ? parsed.devices
      .filter((item) => item && typeof item === 'object')
      .map((item) => ({
        id: typeof item.id === 'string' ? item.id.trim() : '',
        name: typeof item.name === 'string' ? item.name.trim() : '',
        phoneUrl: normalizeStoredPhoneUrl(item.baseUrl ?? item.phoneUrl),
        phoneToken: typeof item.token === 'string' ? item.token.trim() : '',
        lumiLauncherId: typeof item.launcherId === 'string' ? item.launcherId.trim() : '',
        lumiLauncherSecret: typeof item.launcherSecret === 'string' ? item.launcherSecret.trim() : '',
        album: typeof item.album === 'string' ? item.album.trim() : '',
        tags: Array.isArray(item.tags) ? item.tags.map((tag) => String(tag).trim()).filter(Boolean) : [],
        priority: Number.isFinite(Number(item.priority)) ? Number(item.priority) : 0,
      }))
      .filter((item) => item.id || item.phoneUrl || item.name)
    : [];
  return {
    selectedDeviceId: typeof parsed?.selectedDeviceId === 'string' ? parsed.selectedDeviceId.trim() : '',
    devices,
    source: 'bridge-runtime',
  };
}

export async function readLauncherPhoneConfigByDevice(deviceId = '') {
  const store = await readLauncherPhoneStore();
  if (store.devices.length) {
    if (deviceId && !store.devices.some((device) => device.id === deviceId)) {
      throw new Error(`Unknown APKClaw device id: ${deviceId}`);
    }
    const selected =
      (deviceId ? store.devices.find((device) => device.id === deviceId) : undefined) ||
      (store.selectedDeviceId ? store.devices.find((device) => device.id === store.selectedDeviceId) : undefined) ||
      store.devices[0];
    if (selected) {
      return {
        ...selected,
        source: store.source,
      };
    }
  }

  const candidates = [
    ...launcherConfigCandidates('phone-agent.json'),
  ];

  for (const filePath of candidates) {
    try {
      const parsed = JSON.parse(await fs.readFile(filePath, 'utf8'));
      const parsedId = typeof parsed?.id === 'string' ? parsed.id.trim() : '';
      if (deviceId && (!parsedId || parsedId !== deviceId)) {
        throw new Error(`Unknown APKClaw device id: ${deviceId}`);
      }
      return {
        id: parsedId,
        name: typeof parsed?.name === 'string' ? parsed.name.trim() : '',
        phoneUrl: normalizeStoredPhoneUrl(parsed?.baseUrl),
        phoneToken: typeof parsed?.token === 'string' ? parsed.token.trim() : '',
        lumiLauncherId: typeof parsed?.launcherId === 'string' ? parsed.launcherId.trim() : '',
        lumiLauncherSecret: typeof parsed?.launcherSecret === 'string' ? parsed.launcherSecret.trim() : '',
        album: typeof parsed?.album === 'string' ? parsed.album.trim() : '',
        tags: Array.isArray(parsed?.tags) ? parsed.tags.map((tag) => String(tag).trim()).filter(Boolean) : [],
        priority: Number.isFinite(Number(parsed?.priority)) ? Number(parsed.priority) : 0,
        source: filePath,
      };
    } catch (error) {
      if (error?.code !== 'ENOENT') throw new Error(`Failed to read launcher phone config: ${filePath}: ${error.message}`);
    }
  }

  if (deviceId) {
    throw new Error(`Unknown APKClaw device id: ${deviceId}`);
  }
  return { phoneUrl: '', phoneToken: '', source: '' };
}

export function authHeaders(config) {
  return {
    'X-AGENT-PHONE-TOKEN': config.phoneToken,
    'X-APKCLAW-TOKEN': config.phoneToken,
  };
}

export async function fetchWithTimeout(
  url,
  options = {},
  timeoutMs = REQUEST_TIMEOUT_MS,
  externalSignal = undefined,
  errorContext = {},
) {
  const controller = new AbortController();
  const upstreamSignal = externalSignal || options.signal;
  let timedOut = false;
  const abortFromUpstream = () => controller.abort(upstreamSignal?.reason);
  if (upstreamSignal?.aborted) abortFromUpstream();
  else upstreamSignal?.addEventListener?.('abort', abortFromUpstream, { once: true });
  const timeout = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } catch (error) {
    if (error?.name === 'AbortError') {
      if (upstreamSignal?.aborted && !timedOut) {
        throw new PhoneBridgeError(
          'phone_request_cancelled',
          'Phone request cancelled.',
          { retryable: false, cause: error, details: { url: safePhoneUrl(url) } },
        );
      }
      throw new PhoneBridgeError(
        'phone_config_server_timeout',
        '连接手机端 APKClaw 超时。请打开 APKClaw -> Settings -> LAN Config，确认局域网服务开启后重试。',
        { retryable: true, cause: error, details: { url: safePhoneUrl(url), timeoutMs } },
      );
    }
    if (looksLikeConnectionFailure(error)) {
      if (errorContext?.operation === 'media_upload') {
        throw new PhoneBridgeError(
          'phone_media_transfer_interrupted',
          '媒体文件传输中断，请保持手机端 APKClaw 在前台或允许后台运行后重试。',
          {
            retryable: true,
            cause: error,
            currentStep: 'media_upload',
            details: {
              url: safePhoneUrl(url),
              sizeBytes: Number(errorContext.sizeBytes || 0),
              reason: errorMessageWithCause(error),
            },
          },
        );
      }
      throw new PhoneBridgeError(
        'phone_config_server_unreachable',
        '无法连接手机端 APKClaw ConfigServer。请打开 APKClaw -> Settings -> LAN Config，并确认手机和电脑在同一网络。',
        { retryable: true, cause: error, details: { url: safePhoneUrl(url), reason: errorMessageWithCause(error) } },
      );
    }
    throw error;
  } finally {
    clearTimeout(timeout);
    upstreamSignal?.removeEventListener?.('abort', abortFromUpstream);
  }
}

export async function pairLumiLauncher(config, options = {}) {
  ensurePhoneConfig(config);
  const forceRefresh = options.forceRefresh === true;
  if (!forceRefresh && config.lumiLauncherId && config.lumiLauncherSecret) {
    return {
      launcherId: config.lumiLauncherId,
      launcherSecret: config.lumiLauncherSecret,
    };
  }

  const key = pairingCacheKey(config);
  const cached = pairingCache.get(key);
  if (!forceRefresh && cached?.launcherId && cached?.launcherSecret) return publicPairing(cached);

  const failure = pairingFailures.get(key);
  if (failure && failure.until > Date.now()) throw new Error(failure.message);
  if (pairingInflight.has(key)) return pairingInflight.get(key);

  const pairingPromise = (async () => {
    const launcherId = config.lumiLauncherId || generatedLumiLauncherId(config);
    const response = await fetchWithTimeout(`${normalizePhoneUrl(config.phoneUrl)}/api/lumi/security/pair`, {
      method: 'POST',
      headers: {
        ...authHeaders(config),
        'Content-Type': 'application/json; charset=utf-8',
        Accept: 'application/json',
      },
      body: JSON.stringify({
        launcherId,
        launcherName: 'LOOM CLI',
        clientVersion: 'loom-cli',
      }),
    }, 30_000);
    const payload = await parseJsonResponse(response, 'Phone pairing returned non-JSON response');
    if (!response.ok || payload?.success === false) {
      throw new Error(payload?.error || payload?.message || `Lumi pairing failed: HTTP ${response.status}`);
    }
    const data = payload?.data || payload;
    if (!data?.launcherId || !data?.launcherSecret) {
      throw new Error('Lumi pairing response did not include launcher credentials.');
    }
    config.lumiLauncherId = data.launcherId;
    config.lumiLauncherSecret = data.launcherSecret;
    await persistLumiPairing(config, data);
    const nextPairing = {
      launcherId: data.launcherId,
      launcherSecret: data.launcherSecret,
      repairedAt: Date.now(),
    };
    pairingCache.set(key, nextPairing);
    pairingFailures.delete(key);
    return publicPairing(nextPairing);
  })();

  pairingInflight.set(key, pairingPromise);
  try {
    return await pairingPromise;
  } catch (error) {
    pairingFailures.set(key, {
      until: Date.now() + PAIRING_FAILURE_COOLDOWN_MS,
      message: error?.message || 'Lumi pairing failed',
    });
    throw error;
  } finally {
    pairingInflight.delete(key);
  }
}

export async function signedJsonRequest(
  config,
  method,
  endpoint,
  body = undefined,
  timeoutMs = REQUEST_TIMEOUT_MS,
  retryPairing = true,
  requestOptions = {},
) {
  ensurePhoneConfig(config);
  const bodyText = body === undefined ? '' : JSON.stringify(body);
  const { headers, pairing } = await lumiHeaders(config, method, endpoint, bodyText);
  const response = await fetchWithTimeout(`${normalizePhoneUrl(config.phoneUrl)}${endpoint}`, {
    method,
    headers: {
      ...authHeaders(config),
      ...headers,
      Accept: 'application/json',
      ...(body !== undefined ? { 'Content-Type': 'application/json; charset=utf-8' } : {}),
    },
    body: body === undefined ? undefined : bodyText,
  }, timeoutMs, requestOptions.signal);
  const payload = await parseJsonResponse(response, 'Phone returned non-JSON response');
  if (retryPairing && isLumiAuthFailure(response, payload)) {
    return enqueuePairingAuthRetry(config, async () => {
      await repairLumiPairing(config, pairing, { forceRefresh: shouldForceActionPairingRefresh(config, endpoint) });
      if (requestOptions.signal) {
        return signedJsonRequest(config, method, endpoint, body, timeoutMs, false, requestOptions);
      }
      return signedJsonRequest(config, method, endpoint, body, timeoutMs, false);
    });
  }
  if (!response.ok || payload?.success === false) {
    const remoteData = payload?.data && typeof payload.data === 'object' ? payload.data : {};
    const remoteCode = payload?.errorCode || remoteData?.errorCode || '';
    const detail = payload?.message
      || remoteData?.message
      || payload?.error
      || remoteData?.error
      || `Phone request failed: HTTP ${response.status}`;
    const retryable = typeof payload?.retryable === 'boolean'
      ? payload.retryable
      : (typeof remoteData?.retryable === 'boolean'
        ? remoteData.retryable
        : response.status >= 500 || response.status === 404);
    throw new PhoneBridgeError(
      remoteCode || (response.status === 404 ? 'phone_endpoint_not_found' : 'phone_request_failed'),
      String(detail),
      {
        retryable,
        currentStep: payload?.currentStep || remoteData?.currentStep || 'request',
        details: {
          status: response.status,
          endpoint,
          mode: payload?.mode || remoteData?.mode || '',
          accessibilityState: payload?.accessibilityState || remoteData?.accessibilityState || '',
        },
      },
    );
  }
  return payload;
}

export async function signedFetch(config, method, endpoint, timeoutMs = REQUEST_TIMEOUT_MS, retryPairing = true) {
  ensurePhoneConfig(config);
  const { headers, pairing } = await lumiHeaders(config, method, endpoint, '');
  const response = await fetchWithTimeout(`${normalizePhoneUrl(config.phoneUrl)}${endpoint}`, {
    method,
    headers: {
      ...authHeaders(config),
      ...headers,
    },
  }, timeoutMs);
  if (response.status === 403 && retryPairing) {
    return enqueuePairingAuthRetry(config, async () => {
      await repairLumiPairing(config, pairing);
      return signedFetch(config, method, endpoint, timeoutMs, false);
    });
  }
  return response;
}

export async function uploadMediaBuffer(config, bytes, filename, mime, endpoint) {
  const dataUrl = `data:${mime};base64,${Buffer.from(bytes).toString('base64')}`;
  const payload = await signedJsonRequest(config, 'POST', endpoint, {
    dataUrl,
    album: config.album || 'LOOM',
    filename,
  }, 120_000);
  return payload.data || payload;
}

export async function uploadImageBuffer(config, bytes, filename, mime = 'image/png') {
  return uploadMediaBuffer(config, bytes, filename, mime, '/api/lumi/media/import_image');
}

export async function uploadVideoBuffer(config, bytes, filename, mime = 'video/mp4') {
  return uploadMediaBuffer(config, bytes, filename, mime, '/api/lumi/media/import_video');
}

export async function uploadMediaFile(config, filePath, filename, mime, kind, retryPairing = true) {
  ensurePhoneConfig(config);
  const normalizedKind = String(kind || '').trim().toLowerCase();
  if (!['image', 'video'].includes(normalizedKind)) {
    throw new PhoneBridgeError('invalid_media_kind', `Unsupported media kind: ${normalizedKind || 'unknown'}`, {
      retryable: false,
      currentStep: 'media_upload',
    });
  }

  const stat = await fs.stat(filePath);
  if (!stat.isFile() || stat.size <= 0) {
    throw new PhoneBridgeError('invalid_media_file', '媒体文件为空或不可读取。', {
      retryable: false,
      currentStep: 'media_upload',
    });
  }

  const endpoint = mediaImportEndpoint(config, normalizedKind, filename, mime);
  const bodyHash = await sha256File(filePath);
  const { headers, pairing } = await lumiHeadersForBodyHash(config, 'POST', endpoint, bodyHash);
  const response = await fetchWithTimeout(`${normalizePhoneUrl(config.phoneUrl)}${endpoint}`, {
    method: 'POST',
    headers: {
      ...authHeaders(config),
      ...headers,
      Accept: 'application/json',
      'Content-Type': 'application/octet-stream',
      'Content-Length': String(stat.size),
    },
    body: createReadStream(filePath),
    duplex: 'half',
  }, 615_000, undefined, { operation: 'media_upload', sizeBytes: stat.size });

  const payload = await parseJsonResponse(response, 'Phone media import returned non-JSON response');
  if (retryPairing && isLumiAuthFailure(response, payload)) {
    return enqueuePairingAuthRetry(config, async () => {
      await repairLumiPairing(config, pairing, { forceRefresh: true });
      return uploadMediaFile(config, filePath, filename, mime, normalizedKind, false);
    });
  }
  if (response.status === 404) {
    if (stat.size <= LEGACY_JSON_MEDIA_FALLBACK_BYTES) {
      const bytes = await fs.readFile(filePath);
      return normalizedKind === 'video'
        ? uploadVideoBuffer(config, bytes, filename, mime)
        : uploadImageBuffer(config, bytes, filename, mime);
    }
    throw new PhoneBridgeError(
      'phone_media_streaming_update_required',
      '手机端 APKClaw 版本过旧，无法安全接收较大的媒体文件。请升级手机端后重试。',
      {
        retryable: false,
        currentStep: 'media_upload',
        details: { sizeBytes: stat.size, endpoint },
      },
    );
  }
  if (!response.ok || payload?.success === false) {
    const remoteData = payload?.data && typeof payload.data === 'object' ? payload.data : {};
    const remoteCode = payload?.errorCode || remoteData?.errorCode || '';
    const detail = payload?.message
      || remoteData?.message
      || payload?.error
      || remoteData?.error
      || `Phone media import failed: HTTP ${response.status}`;
    throw new PhoneBridgeError(remoteCode || 'phone_media_import_failed', String(detail), {
      retryable: response.status >= 500,
      currentStep: 'media_upload',
      details: { status: response.status, endpoint, sizeBytes: stat.size },
    });
  }
  return payload.data || payload;
}

async function lumiHeaders(config, method, endpoint, bodyText) {
  const bodyHash = crypto.createHash('sha256').update(bodyText, 'utf8').digest('hex');
  return lumiHeadersForBodyHash(config, method, endpoint, bodyHash);
}

async function lumiHeadersForBodyHash(config, method, endpoint, bodyHash) {
  const pairing = await pairLumiLauncher(config);
  const timestamp = String(Date.now());
  const nonce = crypto.randomBytes(16).toString('hex');
  const signatureInput = [
    method.toUpperCase(),
    endpoint,
    timestamp,
    nonce,
    bodyHash,
  ].join('\n');
  const signature = crypto
    .createHmac('sha256', pairing.launcherSecret)
    .update(signatureInput, 'utf8')
    .digest('base64url');
  return {
    pairing,
    headers: {
      'X-LUMI-LAUNCHER-ID': pairing.launcherId,
      'X-LUMI-TIMESTAMP': timestamp,
      'X-LUMI-NONCE': nonce,
      'X-LUMI-BODY-SHA256': bodyHash,
      'X-LUMI-SIGNATURE': signature,
    },
  };
}

function mediaImportEndpoint(config, kind, filename, mime) {
  const query = new URLSearchParams({
    kind,
    album: String(config.album || 'LOOM'),
    filename: String(filename || `${kind}-${Date.now()}`),
    mime: String(mime || (kind === 'video' ? 'video/mp4' : 'image/png')),
  });
  return `/api/lumi/media/import_file?${query.toString()}`;
}

async function sha256File(filePath) {
  const hash = crypto.createHash('sha256');
  await new Promise((resolve, reject) => {
    const stream = createReadStream(filePath);
    stream.on('data', (chunk) => hash.update(chunk));
    stream.once('end', resolve);
    stream.once('error', reject);
  });
  return hash.digest('hex');
}

function pairingCacheKey(config) {
  const tokenHash = crypto.createHash('sha256').update(String(config.phoneToken || ''), 'utf8').digest('hex');
  return `${normalizePhoneUrl(config.phoneUrl)}:${tokenHash}`;
}

function generatedLumiLauncherId(config) {
  const normalizedUrl = normalizePhoneUrl(config.phoneUrl);
  const urlHash = crypto.createHash('sha256').update(normalizedUrl, 'utf8').digest('hex').slice(0, 8);
  const tokenHash = crypto.createHash('sha256').update(String(config.phoneToken || ''), 'utf8').digest('hex').slice(0, 16);
  return `loom-cli-${urlHash}-${tokenHash}`;
}

function publicPairing(pairing) {
  return {
    launcherId: pairing?.launcherId || pairing?.lumiLauncherId || '',
    launcherSecret: pairing?.launcherSecret || pairing?.lumiLauncherSecret || '',
  };
}

function samePairing(a, b) {
  const left = publicPairing(a);
  const right = publicPairing(b);
  return Boolean(
    left.launcherId
    && left.launcherSecret
    && right.launcherId
    && right.launcherSecret
    && left.launcherId === right.launcherId
    && left.launcherSecret === right.launcherSecret
  );
}

function applyPairingToConfig(config, pairing) {
  if (!pairing?.launcherId || !pairing?.launcherSecret) return;
  config.lumiLauncherId = pairing.launcherId;
  config.lumiLauncherSecret = pairing.launcherSecret;
}

function clearLumiPairingCache(config) {
  try {
    const key = pairingCacheKey(config);
    pairingCache.delete(key);
    pairingFailures.delete(key);
  } catch {
    // Clearing cache should never mask the original request failure.
  }
}

async function repairLumiPairing(config, failedPairing, options = {}) {
  const key = pairingCacheKey(config);
  const cached = pairingCache.get(key);
  if (options.forceRefresh || samePairing(cached, failedPairing)) {
    return startPairingRepair(config, key, failedPairing, options);
  }
  if (cached?.launcherId && cached?.launcherSecret) {
    applyPairingToConfig(config, cached);
    return publicPairing(cached);
  }
  if (pairingRepairInflight.has(key)) {
    const repaired = await pairingRepairInflight.get(key);
    applyPairingToConfig(config, repaired);
    return repaired;
  }
  return startPairingRepair(config, key, failedPairing, options);
}

async function enqueuePairingAuthRetry(config, fn) {
  const key = pairingCacheKey(config);
  const previous = pairingAuthRetryTails.get(key) || Promise.resolve();
  const run = previous.catch(() => {}).then(fn);
  const tail = run.catch(() => {});
  pairingAuthRetryTails.set(key, tail);
  try {
    return await run;
  } finally {
    if (pairingAuthRetryTails.get(key) === tail) {
      pairingAuthRetryTails.delete(key);
    }
  }
}

async function startPairingRepair(config, key, failedPairing, options = {}) {
  if (pairingRepairInflight.has(key)) {
    const repaired = await pairingRepairInflight.get(key);
    applyPairingToConfig(config, repaired);
    return repaired;
  }

  const repairPromise = (async () => {
    const latest = pairingCache.get(key);
    if (!options.forceRefresh && latest?.launcherId && latest?.launcherSecret && !samePairing(latest, failedPairing)) {
      applyPairingToConfig(config, latest);
      return publicPairing(latest);
    }
    clearLumiPairingCache(config);
    if (samePairing(config, failedPairing)) {
      config.lumiLauncherSecret = '';
      config.lumiLauncherId = '';
    }
    return pairLumiLauncher(config, { forceRefresh: true });
  })();

  pairingRepairInflight.set(key, repairPromise);
  try {
    const repaired = await repairPromise;
    applyPairingToConfig(config, repaired);
    return repaired;
  } finally {
    pairingRepairInflight.delete(key);
  }
}

async function persistLumiPairing(config, data) {
  const source = typeof config.source === 'string' ? config.source : '';
  if (!source || !data?.launcherId || !data?.launcherSecret) return;
  const resolved = path.resolve(source);
  const allowedRoots = configSearchRoots();
  if (!allowedRoots.some((root) => {
    const normalizedRoot = root.toLowerCase();
    const normalizedResolved = resolved.toLowerCase();
    return normalizedResolved === normalizedRoot || normalizedResolved.startsWith(`${normalizedRoot}${path.sep}`);
  })) return;

  let payload;
  try {
    payload = JSON.parse(await fs.readFile(resolved, 'utf8'));
  } catch {
    return;
  }

  const nextPairing = {
    launcherId: data.launcherId,
    launcherSecret: data.launcherSecret,
  };
  if (Array.isArray(payload?.devices)) {
    let changed = false;
    payload.devices = payload.devices.map((device) => {
      if (!device || typeof device !== 'object') return device;
      const sameId = config.deviceId && String(device.id || '') === String(config.deviceId);
      const sameUrl = normalizeStoredPhoneUrl(device.baseUrl) === normalizeStoredPhoneUrl(config.phoneUrl);
      if (!sameId && !sameUrl) return device;
      changed = true;
      return { ...device, ...nextPairing };
    });
    if (!changed) return;
  } else if (payload && typeof payload === 'object') {
    payload = { ...payload, ...nextPairing };
  } else {
    return;
  }

  const tempPath = `${resolved}.tmp`;
  await fs.writeFile(tempPath, `${JSON.stringify(payload, null, 2)}\n`, 'utf8');
  await fs.rename(tempPath, resolved);
}

async function parseJsonResponse(response, message) {
  const text = await response.text();
  try {
    return JSON.parse(text);
  } catch {
    throw new PhoneBridgeError(
      'phone_non_json_response',
      `${message}: HTTP ${response.status}`,
      { retryable: true, currentStep: 'parse_response', details: { status: response.status } },
    );
  }
}

function isLumiAuthFailure(response, payload) {
  if (response?.status === 401 || response?.status === 403) return true;
  if (payload?.success !== false) return false;
  const detail = String(payload?.error || payload?.message || '').trim();
  if (!detail) return false;
  return /(invalid lumi signature|invalid signature|unauthorized|forbidden|auth(?:entication|orization)?)/i.test(detail);
}

function isActionFastEndpoint(endpoint) {
  return String(endpoint || '').split('?')[0] === '/api/lumi/agent/action_fast';
}

function shouldForceActionPairingRefresh(config, endpoint) {
  return config?.forceActionPairingRefreshOnAuthFailure === true && isActionFastEndpoint(endpoint);
}
