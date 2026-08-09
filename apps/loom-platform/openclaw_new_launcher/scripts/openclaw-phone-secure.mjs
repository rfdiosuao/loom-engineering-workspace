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
const PHONE_RELAY_PRODUCER_TOKEN_ENV = 'LOOM_PHONE_RELAY_PRODUCER_TOKEN';
const PHONE_RUNTIME_TEST_ONLY_ENV = 'LOOM_PHONE_RUNTIME_AUTH_TEST_ONLY';
const PHONE_RUNTIME_TEST_PUBLIC_KEY_ENV = 'LOOM_PHONE_RUNTIME_AUTH_TEST_PUBLIC_KEY_B64';
const ENTITLEMENT_SCHEMA = 'loom.entitlement_lease.v1';
const PHONE_SEAT_LEASE_SCHEMA = 'loom.phone_seat_lease.v1';
const ENTITLEMENT_KEY_ID = 'openclaw-ed25519-v1';
const ENTITLEMENT_PUBLIC_KEY_B64 = 'njEIf3io24DAXRYVp37p2gIT5u2KZaWoGvBPD0JlTZ4=';
const MAX_ENTITLEMENT_LEASE_WINDOW_SEC = 8 * 24 * 60 * 60;
const MAX_ENTITLEMENT_CLOCK_SKEW_SEC = 300;
const LEGACY_JSON_MEDIA_FALLBACK_BYTES = 8 * 1024 * 1024;
const PACKAGED_RUNTIME_ROOT_NAMES = new Set(['_up_', 'resources', 'loomfiles', 'openclawfiles']);
const verifiedLauncherPhoneConfigs = new WeakSet();
const PHONE_CONFIG_REMEDIATION = Object.freeze([
  '请在手机端打开“与 LOOM 配对”并生成一次性配对码或完整配对信息。',
  '回到 LOOM 手机连接页完成安全配对，并选择要操作的目标设备。',
  '局域网连接请确认手机与电脑处于同一网络；USB 连接可直接使用 6 位配对码。',
]);
const PHONE_AUTH_REMEDIATION = Object.freeze([
  '手机已经可以连接，但安全配对凭据已失效或不属于当前模型账号。',
  '请在手机端“与 LOOM 配对”页生成新的配对码。',
  '回到 LOOM 手机连接页重新完成安全配对，然后再次检测。',
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
      '手机尚未完成安全配对。请在手机端生成配对码，并回到 LOOM 手机连接页完成配对。',
      { retryable: true },
    ));
  }
  if (looksLikePhoneAuthFailure(message)) {
    return normalizeBridgeError(new PhoneBridgeError(
      'auth_failed',
      '已连接到手机端 APKClaw，但安全配对凭据无效或已经变更。请生成新的配对码并重新配对。',
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
      '手机连接信息缺失。请在手机端生成配对码或完整配对信息，并回到 LOOM 手机连接页完成配对。',
      { retryable: true, remediation: PHONE_CONFIG_REMEDIATION },
    );
  }
  if (!config.phoneToken) {
    throw new PhoneBridgeError(
      'missing_phone_token',
      '手机尚未完成安全配对。请在手机端生成配对码，并回到 LOOM 手机连接页完成配对。',
      { retryable: true, remediation: PHONE_CONFIG_REMEDIATION },
    );
  }
}

function runtimeAuthorizationError(code, message, details = {}) {
  return new PhoneBridgeError(code, message, {
    retryable: false,
    phase: 'runtime_authorization',
    currentStep: 'preflight',
    details,
  });
}

function canonicalJson(value) {
  if (Array.isArray(value)) {
    return `[${value.map((item) => canonicalJson(item)).join(',')}]`;
  }
  if (value && typeof value === 'object') {
    return `{${Object.keys(value)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${canonicalJson(value[key])}`)
      .join(',')}}`;
  }
  return JSON.stringify(value);
}

function sha256CanonicalJson(value) {
  return crypto.createHash('sha256').update(canonicalJson(value), 'utf8').digest('hex');
}

function strictPositiveInteger(value) {
  return Number.isSafeInteger(value) && value > 0;
}

export function phoneRuntimeTestOverridesAllowed() {
  return (
    !PACKAGED_RUNTIME_ROOT_NAMES.has(path.basename(PROJECT_ROOT).toLowerCase())
    && String(process.env[PHONE_RUNTIME_TEST_ONLY_ENV] || '') === '1'
    && Boolean(process.env.NODE_TEST_CONTEXT)
  );
}

function trustedRuntimePublicKey() {
  if (phoneRuntimeTestOverridesAllowed()) {
    const testKey = String(process.env[PHONE_RUNTIME_TEST_PUBLIC_KEY_ENV] || '').trim();
    if (testKey) return testKey;
  }
  return ENTITLEMENT_PUBLIC_KEY_B64;
}

function ed25519PublicKey(publicKeyB64) {
  let raw;
  try {
    raw = Buffer.from(String(publicKeyB64 || ''), 'base64');
  } catch {
    raw = Buffer.alloc(0);
  }
  if (raw.length !== 32) {
    throw runtimeAuthorizationError(
      'runtime_entitlement_key_invalid',
      'LOOM 手机运行时权益公钥无效，请更新 LOOM。',
    );
  }
  const spkiPrefix = Buffer.from('302a300506032b6570032100', 'hex');
  return crypto.createPublicKey({
    key: Buffer.concat([spkiPrefix, raw]),
    format: 'der',
    type: 'spki',
  });
}

function signatureBytes(value) {
  const text = String(value || '').trim();
  if (!text || text.length % 4 !== 0 || !/^[A-Za-z0-9+/]+={0,2}$/.test(text)) {
    return null;
  }
  const decoded = Buffer.from(text, 'base64');
  return decoded.length === 64 ? decoded : null;
}

function verifyServiceSignature(payload, publicKey, errorCode) {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
    throw runtimeAuthorizationError(errorCode, '缺少服务端签名的手机账号权益。');
  }
  const signature = signatureBytes(payload.signature);
  const signed = { ...payload };
  delete signed.signature;
  if (
    !signature
    || !crypto.verify(
      null,
      Buffer.from(canonicalJson(signed), 'utf8'),
      publicKey,
      signature,
    )
  ) {
    throw runtimeAuthorizationError(
      errorCode,
      '手机运行时账号权益验签失败，请重新登录并刷新权益。',
    );
  }
}

function normalizedRuntimeDevices(runtime) {
  if (!Array.isArray(runtime?.devices)) {
    throw runtimeAuthorizationError(
      'runtime_config_malformed',
      'LOOM 手机运行时设备列表格式无效。',
    );
  }
  const devices = runtime.devices.map((item) => {
    if (!item || typeof item !== 'object' || Array.isArray(item)) {
      throw runtimeAuthorizationError(
        'runtime_config_malformed',
        'LOOM 手机运行时设备配置格式无效。',
      );
    }
    const id = typeof item.id === 'string' ? item.id.trim() : '';
    const phoneUrl = normalizeStoredPhoneUrl(item.baseUrl ?? item.phoneUrl);
    const phoneToken = typeof item.token === 'string' ? item.token.trim() : '';
    if (!id || !phoneUrl || !phoneToken) {
      throw runtimeAuthorizationError(
        'runtime_config_malformed',
        'LOOM 手机运行时设备缺少标识、安全地址或配对凭据。',
      );
    }
    return {
      id,
      entitlementDeviceId: (
        typeof item.entitlementDeviceId === 'string'
          ? item.entitlementDeviceId.trim()
          : typeof item.deviceInstanceId === 'string'
            ? item.deviceInstanceId.trim()
          : id
      ),
      deviceInstanceId: (
        typeof item.deviceInstanceId === 'string'
          ? item.deviceInstanceId.trim()
          : typeof item.entitlementDeviceId === 'string'
            ? item.entitlementDeviceId.trim()
            : ''
      ),
      name: typeof item.name === 'string' ? item.name.trim() : '',
      phoneUrl,
      phoneToken,
      lumiLauncherId: typeof item.launcherId === 'string' ? item.launcherId.trim() : '',
      lumiLauncherSecret: typeof item.launcherSecret === 'string' ? item.launcherSecret.trim() : '',
      album: typeof item.album === 'string' ? item.album.trim() : '',
      tags: Array.isArray(item.tags) ? item.tags.map((tag) => String(tag).trim()).filter(Boolean) : [],
      priority: Number.isFinite(Number(item.priority)) ? Number(item.priority) : 0,
    };
  });
  const ids = devices.map((device) => device.id);
  if (new Set(ids).size !== ids.length) {
    throw runtimeAuthorizationError(
      'runtime_config_malformed',
      'LOOM 手机运行时包含重复设备标识。',
    );
  }
  return devices;
}

function verifyEntitlementLease(lease, publicKey, options = {}) {
  if (!lease || typeof lease !== 'object' || Array.isArray(lease)) {
    throw runtimeAuthorizationError(
      'runtime_entitlement_required',
      '缺少服务端签名的账号权益租约，请重新登录。',
    );
  }
  const required = [
    'schema',
    'accountId',
    'sessionBinding',
    'installId',
    'deviceId',
    'hostDeviceId',
    'features',
    'limits',
    'issuedAt',
    'expiresAt',
    'offlineGraceUntil',
    'entitlementVersion',
    'keyId',
    'signature',
  ];
  const missing = required.filter((field) => !Object.prototype.hasOwnProperty.call(lease, field));
  if (missing.length) {
    throw runtimeAuthorizationError(
      'runtime_entitlement_malformed',
      '服务端账号权益租约字段不完整。',
      { missing },
    );
  }
  if (lease.schema !== ENTITLEMENT_SCHEMA || lease.keyId !== ENTITLEMENT_KEY_ID) {
    throw runtimeAuthorizationError(
      'runtime_entitlement_schema_unsupported',
      '服务端账号权益租约版本或签名密钥不受支持，请更新 LOOM。',
    );
  }
  verifyServiceSignature(lease, publicKey, 'runtime_entitlement_signature_invalid');

  const identityFields = ['accountId', 'sessionBinding', 'installId', 'deviceId', 'hostDeviceId'];
  if (identityFields.some((field) => typeof lease[field] !== 'string' || !lease[field].trim())) {
    throw runtimeAuthorizationError(
      'runtime_entitlement_malformed',
      '服务端账号权益租约身份字段无效。',
    );
  }
  if (lease.deviceId !== lease.hostDeviceId) {
    throw runtimeAuthorizationError(
      'runtime_entitlement_host_mismatch',
      '服务端账号权益租约主机身份不一致。',
    );
  }
  const features = lease.features;
  const limits = lease.limits;
  if (
    !Array.isArray(features)
    || features.some((feature) => typeof feature !== 'string' || !feature.trim())
    || !features.includes('matrix.devices')
    || !limits
    || typeof limits !== 'object'
    || Array.isArray(limits)
    || !strictPositiveInteger(limits.devices)
    || !strictPositiveInteger(limits.concurrentTasks)
    || limits.unlimitedDevices !== true
  ) {
    throw runtimeAuthorizationError(
      'runtime_entitlement_feature_required',
      '当前账号权益未授权手机设备能力。',
    );
  }
  if (
    !strictPositiveInteger(lease.issuedAt)
    || !strictPositiveInteger(lease.expiresAt)
    || !strictPositiveInteger(lease.offlineGraceUntil)
    || !strictPositiveInteger(lease.entitlementVersion)
    || !(lease.issuedAt < lease.expiresAt && lease.expiresAt <= lease.offlineGraceUntil)
    || lease.offlineGraceUntil - lease.issuedAt > MAX_ENTITLEMENT_LEASE_WINDOW_SEC
  ) {
    throw runtimeAuthorizationError(
      'runtime_entitlement_time_invalid',
      '服务端账号权益租约时间窗口无效。',
    );
  }
  const nowSec = Number.isSafeInteger(options.nowSec)
    ? options.nowSec
    : Math.floor(Date.now() / 1000);
  if (lease.issuedAt > nowSec + MAX_ENTITLEMENT_CLOCK_SKEW_SEC) {
    throw runtimeAuthorizationError(
      'runtime_entitlement_not_yet_valid',
      '服务端账号权益租约尚未生效，请同步系统时间。',
    );
  }
  if (nowSec > lease.offlineGraceUntil) {
    throw runtimeAuthorizationError(
      'runtime_entitlement_expired',
      '账号权益离线宽限已结束，请联网刷新账号。',
    );
  }
  const localInstallId = String(options.localInstallId || '').trim();
  if (localInstallId && lease.installId !== localInstallId) {
    throw runtimeAuthorizationError(
      'runtime_entitlement_install_mismatch',
      '账号权益租约不属于当前 LOOM 安装。',
    );
  }
  const activeAccountIds = Array.isArray(options.activeAccountIds)
    ? options.activeAccountIds.map((value) => String(value || '').trim()).filter(Boolean)
    : [];
  if (activeAccountIds.length && !activeAccountIds.includes(lease.accountId)) {
    throw runtimeAuthorizationError(
      'runtime_entitlement_account_mismatch',
      '账号权益租约不属于当前登录账号。',
    );
  }
  return lease;
}

function verifyPhoneSeatLease(seatLease, entitlementLease, publicKey, devices, options = {}) {
  if (!devices.length && (!seatLease || typeof seatLease !== 'object')) return null;
  if (!seatLease || typeof seatLease !== 'object' || Array.isArray(seatLease)) {
    throw runtimeAuthorizationError(
      'runtime_phone_seat_lease_required',
      '缺少服务端签名的手机席位凭证，请联网刷新权益。',
    );
  }
  const required = [
    'schema',
    'accountId',
    'installId',
    'hostDeviceId',
    'phoneDeviceIds',
    'limit',
    'issuedAt',
    'expiresAt',
    'entitlementVersion',
    'keyId',
    'signature',
  ];
  const missing = required.filter((field) => !Object.prototype.hasOwnProperty.call(seatLease, field));
  if (missing.length) {
    throw runtimeAuthorizationError(
      'runtime_phone_seat_lease_malformed',
      '服务端手机席位凭证字段不完整。',
      { missing },
    );
  }
  if (seatLease.schema !== PHONE_SEAT_LEASE_SCHEMA || seatLease.keyId !== ENTITLEMENT_KEY_ID) {
    throw runtimeAuthorizationError(
      'runtime_phone_seat_lease_schema_unsupported',
      '服务端手机席位凭证版本或签名密钥不受支持，请更新 LOOM。',
    );
  }
  verifyServiceSignature(
    seatLease,
    publicKey,
    'runtime_phone_seat_signature_invalid',
  );
  const hostDeviceId = entitlementLease.hostDeviceId || entitlementLease.deviceId;
  if (
    seatLease.accountId !== entitlementLease.accountId
    || seatLease.installId !== entitlementLease.installId
    || seatLease.hostDeviceId !== hostDeviceId
    || seatLease.entitlementVersion !== entitlementLease.entitlementVersion
  ) {
    throw runtimeAuthorizationError(
      'runtime_phone_seat_entitlement_mismatch',
      '服务端手机席位凭证与当前账号权益不一致。',
    );
  }
  if (
    !strictPositiveInteger(seatLease.issuedAt)
    || !strictPositiveInteger(seatLease.expiresAt)
    || !strictPositiveInteger(seatLease.entitlementVersion)
    || !strictPositiveInteger(seatLease.limit)
    || !(seatLease.issuedAt < seatLease.expiresAt)
    || seatLease.expiresAt - seatLease.issuedAt > MAX_ENTITLEMENT_LEASE_WINDOW_SEC
    || !Array.isArray(seatLease.phoneDeviceIds)
  ) {
    throw runtimeAuthorizationError(
      'runtime_phone_seat_lease_malformed',
      '服务端手机席位凭证时间、额度或设备列表无效。',
    );
  }
  const nowSec = Number.isSafeInteger(options.nowSec)
    ? options.nowSec
    : Math.floor(Date.now() / 1000);
  if (seatLease.issuedAt > nowSec + MAX_ENTITLEMENT_CLOCK_SKEW_SEC) {
    throw runtimeAuthorizationError(
      'runtime_phone_seat_not_yet_valid',
      '服务端手机席位凭证尚未生效，请同步系统时间。',
    );
  }
  if (nowSec > seatLease.expiresAt) {
    throw runtimeAuthorizationError(
      'runtime_phone_seat_lease_expired',
      '手机席位离线凭证已过期，请联网刷新。',
    );
  }
  const phoneDeviceIds = seatLease.phoneDeviceIds.map((value) => (
    typeof value === 'string' ? value.trim() : ''
  ));
  if (
    phoneDeviceIds.some((value) => !value)
    || new Set(phoneDeviceIds).size !== phoneDeviceIds.length
    || (
      entitlementLease.limits.unlimitedDevices !== true
      && (
        phoneDeviceIds.length > seatLease.limit
        || seatLease.limit > entitlementLease.limits.devices
      )
    )
  ) {
    throw runtimeAuthorizationError(
      'runtime_phone_seat_lease_malformed',
      '服务端手机席位凭证设备列表或额度无效。',
    );
  }
  const allowedIds = new Set(phoneDeviceIds);
  const unauthorized = devices
    .map((device) => device.entitlementDeviceId)
    .filter((deviceId) => !allowedIds.has(deviceId));
  if (unauthorized.length) {
    throw runtimeAuthorizationError(
      'runtime_phone_device_unauthorized',
      'LOOM 手机运行时包含未获账号权益授权的设备。',
      { deviceIds: unauthorized },
    );
  }
  return seatLease;
}

export function verifyLauncherPhoneRuntimeConfig(runtimeConfig, options = {}) {
  let runtime = runtimeConfig;
  if (typeof runtimeConfig === 'string') {
    try {
      runtime = JSON.parse(runtimeConfig);
    } catch {
      throw runtimeAuthorizationError(
        'runtime_config_malformed',
        'LOOM 手机运行时配置不是有效 JSON。',
      );
    }
  }
  if (!runtime || typeof runtime !== 'object' || Array.isArray(runtime)) {
    throw runtimeAuthorizationError(
      'runtime_config_malformed',
      'LOOM 手机运行时配置格式无效。',
    );
  }
  const devices = normalizedRuntimeDevices(runtime);
  const publicKey = ed25519PublicKey(trustedRuntimePublicKey());
  const entitlementLease = verifyEntitlementLease(
    runtime.entitlementLease,
    publicKey,
    options,
  );
  const producerToken = String(options.producerToken || '').trim();
  if (!producerToken) {
    throw runtimeAuthorizationError(
      'runtime_producer_token_required',
      '手机运行时缺少当前模型账号安全凭据，请重新登录。',
    );
  }
  const expectedSessionBinding = crypto
    .createHash('sha256')
    .update(Buffer.concat([
      Buffer.from('loom-entitlement-session-v1\0', 'utf8'),
      Buffer.from(producerToken, 'utf8'),
    ]))
    .digest('hex');
  const actualSessionBinding = String(
    entitlementLease.sessionBinding || '',
  );
  if (
    actualSessionBinding.length !== expectedSessionBinding.length
    || !crypto.timingSafeEqual(
      Buffer.from(actualSessionBinding, 'utf8'),
      Buffer.from(expectedSessionBinding, 'utf8'),
    )
  ) {
    throw runtimeAuthorizationError(
      'runtime_producer_token_mismatch',
      '当前模型账号安全凭据与签名权益租约不一致，请重新登录。',
    );
  }
  const phoneSeatLease = verifyPhoneSeatLease(
    runtime.phoneSeatLease,
    entitlementLease,
    publicKey,
    devices,
    options,
  );
  const selectedDeviceId = typeof runtime.selectedDeviceId === 'string'
    ? runtime.selectedDeviceId.trim()
    : '';
  if (selectedDeviceId && !devices.some((device) => device.id === selectedDeviceId)) {
    throw runtimeAuthorizationError(
      'runtime_phone_device_unauthorized',
      'LOOM 手机运行时选择了未获授权的设备。',
      { deviceIds: [selectedDeviceId] },
    );
  }
  return {
    selectedDeviceId: selectedDeviceId || devices[0]?.id || '',
    devices,
    source: 'bridge-runtime',
    accountId: entitlementLease.accountId,
    entitlementLease,
    phoneSeatLease,
    configDigest: (
      typeof options.configDigest === 'string'
      && /^[a-f0-9]{64}$/i.test(options.configDigest)
    )
      ? options.configDigest.toLowerCase()
      : sha256CanonicalJson(runtime),
  };
}

export function hasLauncherPhoneRuntimeConfig() {
  return Object.prototype.hasOwnProperty.call(process.env, PHONE_RUNTIME_CONFIG_ENV);
}

export function resolveLauncherPhoneConnection(args = {}, launcherPhone = {}, runtime = {}, options = {}) {
  if (
    !hasLauncherPhoneRuntimeConfig()
    || !launcherPhone
    || typeof launcherPhone !== 'object'
    || !verifiedLauncherPhoneConfigs.has(launcherPhone)
  ) {
    return {
      phoneUrl: '',
      phoneToken: '',
      deviceId: '',
      lumiLauncherId: '',
      lumiLauncherSecret: '',
      source: 'bridge-runtime-required',
    };
  }
  return {
    phoneUrl: launcherPhone.phoneUrl || '',
    phoneToken: launcherPhone.phoneToken || '',
    deviceId: args.deviceId || launcherPhone.id || '',
    lumiLauncherId: launcherPhone.lumiLauncherId || '',
    lumiLauncherSecret: launcherPhone.lumiLauncherSecret || '',
    source: launcherPhone.source || 'bridge-runtime',
  };
}

function firstNonEmptyString(...values) {
  for (const value of values) {
    if (typeof value === 'string' && value.trim()) return value.trim();
  }
  return '';
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

export async function readLauncherPhoneStore(options = {}) {
  if (hasLauncherPhoneRuntimeConfig()) return readRuntimePhoneStore(options);
  return {
    selectedDeviceId: '',
    devices: [],
    source: 'bridge-runtime-required',
  };
}

async function readRuntimePhoneStore(options = {}) {
  const raw = String(process.env[PHONE_RUNTIME_CONFIG_ENV] || '').trim();
  if (!raw) {
    throw runtimeAuthorizationError(
      'runtime_config_malformed',
      'LOOM 手机运行时配置为空。',
    );
  }
  let parsed;
  try {
    parsed = JSON.parse(raw);
  } catch {
    throw runtimeAuthorizationError(
      'runtime_config_malformed',
      'LOOM 手机运行时配置不是有效 JSON。',
    );
  }
  const binding = await readRuntimeAuthorizationBinding();
  const authorizedRuntime = {
    ...parsed,
    entitlementLease: parsed.entitlementLease || binding.entitlementLease,
    phoneSeatLease: parsed.phoneSeatLease || binding.phoneSeatLease,
  };
  return verifyLauncherPhoneRuntimeConfig(authorizedRuntime, {
    ...binding,
    ...options,
    producerToken: (
      options.producerToken
      || process.env[PHONE_RELAY_PRODUCER_TOKEN_ENV]
      || ''
    ),
    configDigest: sha256CanonicalJson(parsed),
  });
}

async function readRuntimeAuthorizationBinding() {
  const roots = trustedRuntimeRoots();
  const [
    entitlementLease,
    phoneSeatLease,
    localInstallId,
    memberSession,
  ] = await Promise.all([
    readFirstRuntimeJson(roots, ['data', 'account-entitlement.json']),
    readFirstRuntimeJson(roots, ['data', 'account-phone-seat-lease.json']),
    readFirstRuntimeText(roots, ['data', 'install_id.txt']),
    readFirstRuntimeJson(roots, ['data', '.openclaw', 'launcher', 'member-session.json']),
  ]);
  return {
    entitlementLease,
    phoneSeatLease,
    localInstallId,
    activeAccountIds: accountIdsFromMemberSession(memberSession),
  };
}

function trustedRuntimeRoots() {
  const roots = [PROJECT_ROOT];
  const name = path.basename(PROJECT_ROOT).toLowerCase();
  if (PACKAGED_RUNTIME_ROOT_NAMES.has(name)) {
    roots.push(path.resolve(PROJECT_ROOT, '..'));
  }
  return uniquePaths(roots);
}

async function readFirstRuntimeJson(roots, relativeParts) {
  for (const root of roots) {
    try {
      const parsed = JSON.parse(await fs.readFile(path.join(root, ...relativeParts), 'utf8'));
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) return parsed;
    } catch (error) {
      if (error?.code !== 'ENOENT' && !(error instanceof SyntaxError)) throw error;
    }
  }
  return null;
}

async function readFirstRuntimeText(roots, relativeParts) {
  for (const root of roots) {
    try {
      const text = String(await fs.readFile(path.join(root, ...relativeParts), 'utf8')).trim();
      if (text) return text;
    } catch (error) {
      if (error?.code !== 'ENOENT') throw error;
    }
  }
  return '';
}

function accountIdsFromMemberSession(session) {
  if (!session || typeof session !== 'object') return [];
  const newApi = session.newApi && typeof session.newApi === 'object' ? session.newApi : {};
  const memberId = String(session.memberId || '').trim();
  return [...new Set([
    String(newApi.userId || '').trim(),
    memberId,
    memberId.replace(/^newapi:/, ''),
  ].filter(Boolean))];
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
      const verified = {
        ...selected,
        source: store.source,
      };
      verifiedLauncherPhoneConfigs.add(verified);
      return verified;
    }
  }
  if (store.source === 'bridge-runtime' || store.source === 'bridge-runtime-required') {
    if (deviceId) {
      throw new Error(`Unknown APKClaw device id: ${deviceId}`);
    }
    return {
      id: '',
      name: '',
      phoneUrl: '',
      phoneToken: '',
      lumiLauncherId: '',
      lumiLauncherSecret: '',
      album: '',
      tags: [],
      priority: 0,
      source: store.source,
    };
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
  assertLegacyPairingUsbOnly(config);

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

function assertLegacyPairingUsbOnly(config) {
  const hostname = new URL(normalizePhoneUrl(config.phoneUrl)).hostname
    .replace(/^\[|\]$/g, '')
    .toLowerCase();
  if (!['127.0.0.1', 'localhost', '::1'].includes(hostname)) {
    throw new PhoneBridgeError(
      'phone_legacy_pairing_usb_required',
      '旧版手机凭据不能通过局域网发送。请连接 USB，并在手机“与 LOOM 配对”页生成 6 位配对码。',
      {
        retryable: false,
        currentStep: 'secure_pairing',
        details: { url: safePhoneUrl(config.phoneUrl) },
      },
    );
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
  }, timeoutMs, config.cancelSignal);
  if (response.status === 403 && retryPairing) {
    return enqueuePairingAuthRetry(config, async () => {
      await repairLumiPairing(config, pairing);
      return signedFetch(config, method, endpoint, timeoutMs, false);
    });
  }
  return response;
}

export async function uploadMediaBuffer(config, bytes, filename, mime, endpoint, requestOptions = {}) {
  const dataUrl = `data:${mime};base64,${Buffer.from(bytes).toString('base64')}`;
  const payload = await signedJsonRequest(config, 'POST', endpoint, {
    dataUrl,
    album: config.album || 'LOOM',
    filename,
  }, 120_000, true, requestOptions);
  return payload.data || payload;
}

export async function uploadImageBuffer(config, bytes, filename, mime = 'image/png', requestOptions = {}) {
  return uploadMediaBuffer(config, bytes, filename, mime, '/api/lumi/media/import_image', requestOptions);
}

export async function uploadVideoBuffer(config, bytes, filename, mime = 'video/mp4', requestOptions = {}) {
  return uploadMediaBuffer(config, bytes, filename, mime, '/api/lumi/media/import_video', requestOptions);
}

export async function uploadMediaFile(
  config,
  filePath,
  filename,
  mime,
  kind,
  retryPairing = true,
  requestOptions = {},
) {
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
  }, 615_000, requestOptions.signal, { operation: 'media_upload', sizeBytes: stat.size });

  const payload = await parseJsonResponse(response, 'Phone media import returned non-JSON response');
  if (retryPairing && isLumiAuthFailure(response, payload)) {
    return enqueuePairingAuthRetry(config, async () => {
      await repairLumiPairing(config, pairing, { forceRefresh: true });
      return uploadMediaFile(config, filePath, filename, mime, normalizedKind, false, requestOptions);
    });
  }
  if (response.status === 404) {
    if (stat.size <= LEGACY_JSON_MEDIA_FALLBACK_BYTES) {
      const bytes = await fs.readFile(filePath);
      return normalizedKind === 'video'
        ? uploadVideoBuffer(config, bytes, filename, mime, requestOptions)
        : uploadImageBuffer(config, bytes, filename, mime, requestOptions);
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
