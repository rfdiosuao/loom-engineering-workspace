import type { TransportMode } from '../types';
import { normalizePhoneBaseUrl } from '../lib/phoneUrl';

export interface LiveRequestOptions {
  baseUrl?: string;
  token?: string;
  mode?: TransportMode;
}

function getTextValue(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}

function parseJson(text: string): any {
  if (!text.trim()) return {};
  try {
    return JSON.parse(text);
  } catch {
    return { raw: text };
  }
}

function throwIfBridgeError(payload: any, fallback = 'bridge_request_failed'): void {
  if (payload && typeof payload === 'object' && typeof payload.error === 'string') {
    throw new Error(payload.error || fallback);
  }
}

let tauriCorePromise: Promise<typeof import('@tauri-apps/api/core')> | null = null;

async function getTauriInvoke() {
  tauriCorePromise ??= import('@tauri-apps/api/core');
  return (await tauriCorePromise).invoke;
}

export function isTauriRuntime(): boolean {
  return typeof window !== 'undefined' && Boolean((window as Window & { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__);
}

// --- Launcher self-update (desktop only) ---------------------------------
export interface LauncherUpdateInfo {
  available: boolean;
  current: string;
  latest: string;
  url: string;
  sha256: string;
  notes: string;
  configured: boolean;
}

export async function checkLauncherUpdate(): Promise<LauncherUpdateInfo> {
  if (!isTauriRuntime()) {
    return { available: false, current: '', latest: '', url: '', sha256: '', notes: '仅桌面版支持启动器自更新', configured: false };
  }
  const invoke = await getTauriInvoke();
  return invoke('check_launcher_update') as Promise<LauncherUpdateInfo>;
}

export async function applyLauncherUpdate(url: string, sha256: string): Promise<void> {
  if (!isTauriRuntime()) throw new Error('仅桌面版支持启动器自更新');
  const invoke = await getTauriInvoke();
  await invoke('apply_launcher_update', { url, sha256 });
}

export async function installDistributionLayer(layerId: string): Promise<void> {
  if (!isTauriRuntime()) throw new Error('仅桌面版支持组件安装');
  const invoke = await getTauriInvoke();
  await invoke('install_distribution_layer', { layerId });
}

const LUMI_PAIRING_STORE_KEY = 'openclaw-lumi-secure-pairings-v1';
const LUMI_LAUNCHER_ID_STORE_KEY = 'openclaw-lumi-launcher-ids-v1';
const LUMI_LAUNCHER_ID_HEADER = 'X-LUMI-LAUNCHER-ID';
const LUMI_TIMESTAMP_HEADER = 'X-LUMI-TIMESTAMP';
const LUMI_NONCE_HEADER = 'X-LUMI-NONCE';
const LUMI_SIGNATURE_HEADER = 'X-LUMI-SIGNATURE';
const LUMI_BODY_SHA256_HEADER = 'X-LUMI-BODY-SHA256';
const LUMI_PAIRING_MAX_AGE_MS = 30 * 24 * 60 * 60 * 1000;
const DEFAULT_PHONE_REQUEST_TIMEOUT_MS = 30_000;
const DEFAULT_BRIDGE_REQUEST_TIMEOUT_MS = 90_000;
const LUMI_SIGNATURE_REPAIR_ATTEMPTS = 2;

export interface PhoneRequestOptions {
  timeoutMs?: number;
}

interface LumiPairing {
  baseUrl: string;
  tokenHash: string;
  launcherId: string;
  launcherSecret: string;
  pairedAt: string;
  lastUsedAt?: string;
}

export interface PhonePairingSummary {
  baseUrl: string;
  launcherId: string;
  pairedAt: string;
  expiresAt: string;
}

const lumiPairingInflight = new Map<string, Promise<LumiPairing>>();
const lumiSecureQueues = new Map<string, Promise<void>>();

// 手机↔电脑时钟偏差(毫秒),按 baseUrl 记录。来源:device/status 响应里的 serverTime。
// 签名时用 Date.now()+offset,让 Lumi 时间戳落在手机的时间窗口内,
// 避免客户手机时间不准导致签名 403(手机端容差仅 120 秒)。
const phoneClockOffsets = new Map<string, number>();

function recordPhoneServerTime(baseUrl: string, payload: unknown): void {
  const data = payload as any;
  const serverTime = Number(data?.data?.serverTime ?? data?.serverTime);
  if (Number.isFinite(serverTime) && serverTime > 0) {
    phoneClockOffsets.set(baseUrl, serverTime - Date.now());
  }
}

function phoneClockOffset(baseUrl: string): number {
  return phoneClockOffsets.get(baseUrl) ?? 0;
}

export function resolveBridgeBaseUrl(explicitBaseUrl = ''): string {
  const envBase = getTextValue(import.meta.env.VITE_OPENCLAW_API_BASE_URL);
  const proxyTarget = getTextValue(import.meta.env.VITE_OPENCLAW_PROXY_TARGET);
  return getTextValue(explicitBaseUrl) || envBase || (proxyTarget ? '/api' : '');
}

export async function bridgeRequest<T = unknown>(
  path: string,
  method = 'GET',
  body?: Record<string, unknown>,
  options: LiveRequestOptions = {}
): Promise<T> {
  const baseUrl = resolveBridgeBaseUrl(options.baseUrl);
  const token = getTextValue(options.token || import.meta.env.VITE_OPENCLAW_BRIDGE_TOKEN);

  if (isTauriRuntime()) {
    try {
      const invoke = await getTauriInvoke();
      const payload = await withTimeout(
        invoke<string>('proxy_request', {
          path,
          method,
          body: body ? JSON.stringify(body) : null,
        }),
        DEFAULT_BRIDGE_REQUEST_TIMEOUT_MS,
        'bridge_request_timeout',
      );
      const parsed = parseJson(String(payload));
      throwIfBridgeError(parsed);
      return parsed as T;
    } catch (error) {
      if (!baseUrl) throw error;
    }
  }

  if (!baseUrl) {
    throw new Error('live_bridge_unavailable');
  }

  const url = `${baseUrl.replace(/\/+$/, '')}/${path.replace(/^\/+/, '')}`;
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), DEFAULT_BRIDGE_REQUEST_TIMEOUT_MS);
  const response = await fetch(url, {
    method,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { 'X-Bridge-Token': token } : {}),
    },
    signal: controller.signal,
    body: body ? JSON.stringify(body) : undefined,
  }).finally(() => window.clearTimeout(timeout));

  const payload = parseJson(await response.text());
  if (!response.ok) {
    const message = typeof payload?.error === 'string' ? payload.error : `http_${response.status}`;
    throw new Error(message);
  }
  throwIfBridgeError(payload);
  return payload as T;
}

function withTimeout<T>(promise: Promise<T>, timeoutMs: number, message: string): Promise<T> {
  let timer: number | undefined;
  return Promise.race([
    promise,
    new Promise<T>((_, reject) => {
      timer = window.setTimeout(() => reject(new Error(message)), timeoutMs);
    }),
  ]).finally(() => {
    if (timer) window.clearTimeout(timer);
  });
}

export async function phoneRequest<T = unknown>(
  baseUrl: string,
  token: string,
  path: string,
  method = 'GET',
  body?: Record<string, unknown>,
  options: PhoneRequestOptions = {},
): Promise<T> {
  const rawBase = getTextValue(baseUrl);
  const normalizedBase = normalizePhoneBaseUrl(rawBase);
  const normalizedToken = getTextValue(token);
  if (!rawBase) throw new Error('missing_base_url');
  if (!normalizedBase) throw new Error('invalid_phone_base_url');
  if (!normalizedToken) throw new Error('missing_token');
  const normalizedMethod = method.toUpperCase();
  const bodyText = body ? JSON.stringify(body) : '';
  const timeoutMs = normalizeTimeoutMs(options.timeoutMs);

  if (isLumiSecurePath(path)) {
    const requestSigned = async (forcePair = false, rotateLauncherId = false) => {
      const pairing = await getOrCreateLumiPairing(normalizedBase, normalizedToken, forcePair, rotateLauncherId);
      const extraHeaders = await buildLumiHeaders(pairing, normalizedMethod, path, bodyText);
      return rawPhoneRequest<T>(normalizedBase, normalizedToken, path, normalizedMethod, bodyText, extraHeaders, timeoutMs);
    };

    return enqueueLumiSecureRequest(lumiPairingKey(normalizedBase, normalizedToken), async () => {
      let lastPairingError: unknown = null;
      for (let attempt = 0; attempt <= LUMI_SIGNATURE_REPAIR_ATTEMPTS; attempt += 1) {
        try {
          return await requestSigned(attempt > 0, attempt === LUMI_SIGNATURE_REPAIR_ATTEMPTS);
        } catch (error) {
          if (!isLumiPairingError(error)) throw error;
          lastPairingError = error;
          await clearLumiPairing(normalizedBase, normalizedToken);
        }
      }
      throw createLumiRepairError(lastPairingError);
    });
  }

  return rawPhoneRequest<T>(normalizedBase, normalizedToken, path, normalizedMethod, bodyText, null, timeoutMs);
}

async function rawPhoneRequest<T>(
  baseUrl: string,
  token: string,
  path: string,
  method: string,
  bodyText: string,
  extraHeaders: Record<string, string> | null,
  timeoutMs = DEFAULT_PHONE_REQUEST_TIMEOUT_MS,
): Promise<T> {
  if (isTauriRuntime()) {
    const invoke = await getTauriInvoke();
    const payload = await invoke<string>('phone_proxy_request', {
      baseUrl,
      path,
      method,
      body: bodyText || null,
      token,
      timeoutMs,
      extraHeaders,
    });
    const parsed = parseJson(String(payload));
    recordPhoneServerTime(baseUrl, parsed);
    return parsed as T;
  }

  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
  const response = await fetch(`${baseUrl}/${path.replace(/^\/+/, '')}`, {
    method,
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
      'X-AGENT-PHONE-TOKEN': token,
      'X-APKCLAW-TOKEN': token,
      ...(extraHeaders || {}),
    },
    signal: controller.signal,
    body: bodyText || undefined,
  }).finally(() => window.clearTimeout(timeout));

  const payload = parseJson(await response.text());
  recordPhoneServerTime(baseUrl, payload);
  if (!response.ok) {
    const message = typeof payload?.error === 'string' ? payload.error : `http_${response.status}`;
    throw new Error(message);
  }
  if (payload && typeof payload === 'object' && typeof payload.error === 'string') {
    throw new Error(payload.error);
  }
  return payload as T;
}

function normalizeTimeoutMs(value: unknown): number {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return DEFAULT_PHONE_REQUEST_TIMEOUT_MS;
  return Math.max(1000, Math.min(615_000, numeric));
}

function enqueueLumiSecureRequest<T>(key: string, task: () => Promise<T>): Promise<T> {
  const previous = lumiSecureQueues.get(key) || Promise.resolve();
  const run = previous.catch(() => undefined).then(task);
  const next = run.then(() => undefined, () => undefined);
  lumiSecureQueues.set(key, next);
  next.finally(() => {
    if (lumiSecureQueues.get(key) === next) {
      lumiSecureQueues.delete(key);
    }
  });
  return run;
}

function isLumiSecurePath(path: string): boolean {
  const route = path.split('?')[0];
  return route.startsWith('/api/lumi/') && route !== '/api/lumi/security/pair';
}

function isLumiPairingError(error: unknown): boolean {
  const message = String((error as Error)?.message || error || '').toLowerCase();
  return (
    message.includes('[403]') ||
    message.includes('missing lumi security headers') ||
    message.includes('missing_lumi_pairing') ||
    message.includes('unknown lumi launcher') ||
    message.includes('unknown_lumi_launcher') ||
    message.includes('invalid lumi launcher') ||
    message.includes('invalid_lumi_launcher') ||
    message.includes('launcher_not_found') ||
    message.includes('lumi signature')
  );
}

function createLumiRepairError(error: unknown): Error {
  const message = extractPhoneErrorMessage(error);
  if (!message) return new Error('lumi_signature_repair_failed');
  if (message.toLowerCase().includes('lumi_signature_repair_failed')) {
    return new Error(message);
  }
  return new Error(`lumi_signature_repair_failed: ${message}`);
}

function extractPhoneErrorMessage(error: unknown): string {
  const raw = String((error as Error)?.message || error || '').trim();
  if (!raw) return '';
  const jsonStart = raw.indexOf('{');
  if (jsonStart >= 0) {
    try {
      const payload = JSON.parse(raw.slice(jsonStart));
      if (typeof payload?.error === 'string' && payload.error.trim()) return payload.error.trim();
      if (typeof payload?.message === 'string' && payload.message.trim()) return payload.message.trim();
    } catch {
      // Keep the original transport text when the phone returns non-JSON content.
    }
  }
  return raw;
}

function lumiPairingKey(baseUrl: string, token: string): string {
  return `${baseUrl}\n${token}`;
}

async function getOrCreateLumiPairing(baseUrl: string, token: string, forcePair = false, rotateLauncherId = false): Promise<LumiPairing> {
  if (!forcePair) {
    const cached = await readLumiPairing(baseUrl, token);
    if (cached?.launcherId && cached.launcherSecret) {
      await saveLumiPairing({ ...cached, lastUsedAt: new Date().toISOString() });
      return cached;
    }
  }

  const key = `${lumiPairingKey(baseUrl, token)}\n${rotateLauncherId ? 'rotate' : 'stable'}`;
  const existing = lumiPairingInflight.get(key);
  if (existing) return existing;

  const pairingPromise = pairLumiSecureChannel(baseUrl, token, rotateLauncherId).finally(() => {
    if (lumiPairingInflight.get(key) === pairingPromise) {
      lumiPairingInflight.delete(key);
    }
  });
  lumiPairingInflight.set(key, pairingPromise);
  return pairingPromise;
}

async function pairLumiSecureChannel(baseUrl: string, token: string, rotateLauncherId = false): Promise<LumiPairing> {
  const tokenHashValue = await tokenHash(baseUrl, token);
  const launcherId = rotateLauncherId ? createLumiLauncherId() : getStableLumiLauncherId(baseUrl, tokenHashValue);
  const payload = await rawPhoneRequest<any>(
    baseUrl,
    token,
    '/api/lumi/security/pair',
    'POST',
    JSON.stringify({
      launcherId,
      launcherName: 'OpenClaw Starfield Launcher',
      clientVersion: 'openclaw-ui-integration',
    }),
    null,
    15_000,
  );
  const data = payload && typeof payload === 'object' && payload.data && typeof payload.data === 'object' ? payload.data : payload;
  const next: LumiPairing = {
    baseUrl,
    tokenHash: tokenHashValue,
    launcherId: getTextValue(data?.launcherId) || launcherId,
    launcherSecret: getTextValue(data?.launcherSecret),
    pairedAt: new Date(Number(data?.pairedAt) || Date.now()).toISOString(),
    lastUsedAt: new Date().toISOString(),
  };
  if (!next.launcherId || !next.launcherSecret) throw new Error('lumi_pair_failed');
  await saveLumiPairing(next);
  return next;
}

async function readLumiPairing(baseUrl: string, token: string): Promise<LumiPairing | null> {
  if (typeof window === 'undefined') return null;
  const expectedHash = await tokenHash(baseUrl, token);
  const items = readLumiPairings();
  const freshItems = items.filter((item) => !isPairingExpired(item));
  if (freshItems.length !== items.length) {
    window.localStorage.setItem(LUMI_PAIRING_STORE_KEY, JSON.stringify(freshItems.slice(0, 12)));
  }
  return freshItems.find((item) => item.baseUrl === baseUrl && item.tokenHash === expectedHash) || null;
}

async function saveLumiPairing(pairing: LumiPairing) {
  if (typeof window === 'undefined') return;
  saveStableLumiLauncherId(pairing.baseUrl, pairing.tokenHash, pairing.launcherId);
  const items = readLumiPairings().filter((item) => !(item.baseUrl === pairing.baseUrl && item.tokenHash === pairing.tokenHash));
  items.unshift(pairing);
  window.localStorage.setItem(LUMI_PAIRING_STORE_KEY, JSON.stringify(items.slice(0, 12)));
}

async function clearLumiPairing(baseUrl: string, token: string) {
  if (typeof window === 'undefined') return;
  const expectedHash = await tokenHash(baseUrl, token);
  const items = readLumiPairings().filter((item) => !(item.baseUrl === baseUrl && item.tokenHash === expectedHash));
  window.localStorage.setItem(LUMI_PAIRING_STORE_KEY, JSON.stringify(items));
}

function readLumiPairings(): LumiPairing[] {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(LUMI_PAIRING_STORE_KEY) || '[]');
    return Array.isArray(parsed) ? parsed.filter(isStoredLumiPairing) : [];
  } catch {
    return [];
  }
}

function isStoredLumiPairing(value: unknown): value is LumiPairing {
  const item = value as Partial<LumiPairing>;
  return Boolean(item && typeof item.baseUrl === 'string' && typeof item.tokenHash === 'string' && typeof item.launcherId === 'string' && typeof item.launcherSecret === 'string');
}

function isPairingExpired(pairing: LumiPairing): boolean {
  const pairedAt = Date.parse(pairing.pairedAt);
  if (!Number.isFinite(pairedAt)) return true;
  return Date.now() - pairedAt > LUMI_PAIRING_MAX_AGE_MS;
}

function pairingSummary(pairing: LumiPairing): PhonePairingSummary {
  const pairedAt = Date.parse(pairing.pairedAt);
  return {
    baseUrl: pairing.baseUrl,
    launcherId: pairing.launcherId,
    pairedAt: pairing.pairedAt,
    expiresAt: new Date((Number.isFinite(pairedAt) ? pairedAt : Date.now()) + LUMI_PAIRING_MAX_AGE_MS).toISOString(),
  };
}

function stableLumiLauncherKey(baseUrl: string, tokenHashValue: string): string {
  return `${baseUrl}\n${tokenHashValue}`;
}

function createLumiLauncherId(): string {
  return `openclaw-${randomHex(8)}`;
}

function getStableLumiLauncherId(baseUrl: string, tokenHashValue: string): string {
  if (typeof window === 'undefined') return createLumiLauncherId();
  const key = stableLumiLauncherKey(baseUrl, tokenHashValue);
  const items = readStableLumiLauncherIds();
  const existing = getTextValue(items[key]);
  if (existing) return existing;
  const launcherId = createLumiLauncherId();
  saveStableLumiLauncherId(baseUrl, tokenHashValue, launcherId);
  return launcherId;
}

function saveStableLumiLauncherId(baseUrl: string, tokenHashValue: string, launcherId: string) {
  if (typeof window === 'undefined') return;
  const key = stableLumiLauncherKey(baseUrl, tokenHashValue);
  const items = readStableLumiLauncherIds();
  items[key] = launcherId;
  window.localStorage.setItem(LUMI_LAUNCHER_ID_STORE_KEY, JSON.stringify(items));
}

function readStableLumiLauncherIds(): Record<string, string> {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(LUMI_LAUNCHER_ID_STORE_KEY) || '{}');
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed as Record<string, string> : {};
  } catch {
    return {};
  }
}

export async function warmPhoneSecurePairing(baseUrl: string, token: string, forcePair = false, rotateLauncherId = false): Promise<PhonePairingSummary> {
  const normalizedBase = normalizePhoneBaseUrl(getTextValue(baseUrl));
  const normalizedToken = getTextValue(token);
  if (!normalizedBase) throw new Error('invalid_phone_base_url');
  if (!normalizedToken) throw new Error('missing_token');
  return pairingSummary(await getOrCreateLumiPairing(normalizedBase, normalizedToken, forcePair, rotateLauncherId));
}

export async function clearPhoneSecurePairing(baseUrl: string, token: string): Promise<void> {
  const normalizedBase = normalizePhoneBaseUrl(getTextValue(baseUrl));
  const normalizedToken = getTextValue(token);
  if (!normalizedBase || !normalizedToken) return;
  await clearLumiPairing(normalizedBase, normalizedToken);
}

async function tokenHash(baseUrl: string, token: string): Promise<string> {
  return sha256Hex(`${baseUrl}\n${token}`);
}

function randomHex(bytes = 8): string {
  const data = new Uint8Array(bytes);
  window.crypto.getRandomValues(data);
  return Array.from(data).map((value) => value.toString(16).padStart(2, '0')).join('');
}

function arrayBufferToBase64Url(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let binary = '';
  for (let index = 0; index < bytes.length; index += 1) {
    binary += String.fromCharCode(bytes[index]);
  }
  return window.btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '');
}

async function sha256Hex(text: string): Promise<string> {
  const digest = await window.crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
  return Array.from(new Uint8Array(digest)).map((value) => value.toString(16).padStart(2, '0')).join('');
}

async function hmacBase64Url(secret: string, text: string): Promise<string> {
  const key = await window.crypto.subtle.importKey(
    'raw',
    new TextEncoder().encode(secret),
    { name: 'HMAC', hash: 'SHA-256' },
    false,
    ['sign'],
  );
  const signature = await window.crypto.subtle.sign('HMAC', key, new TextEncoder().encode(text));
  return arrayBufferToBase64Url(signature);
}

async function buildLumiHeaders(pairing: LumiPairing, method: string, path: string, bodyText: string): Promise<Record<string, string>> {
  // 用手机时钟签名(Date.now() + 手机↔电脑偏差),客户手机时间不准也不会 403。
  const timestamp = String(Date.now() + phoneClockOffset(pairing.baseUrl));
  const nonce = randomHex(16);
  const bodyHash = await sha256Hex(bodyText);
  const signature = await hmacBase64Url(pairing.launcherSecret, [
    method.toUpperCase(),
    path,
    timestamp,
    nonce,
    bodyHash,
  ].join('\n'));
  return {
    [LUMI_LAUNCHER_ID_HEADER]: pairing.launcherId,
    [LUMI_TIMESTAMP_HEADER]: timestamp,
    [LUMI_NONCE_HEADER]: nonce,
    [LUMI_BODY_SHA256_HEADER]: bodyHash,
    [LUMI_SIGNATURE_HEADER]: signature,
  };
}
