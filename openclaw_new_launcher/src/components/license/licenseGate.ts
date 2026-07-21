import type { License } from '../../types';
import type {
  LicenseClientConfig,
  LicenseCurrentResponse,
} from '../../services/api';

export const LICENSE_CHECK_TIMEOUT_MS = 15_000;

export type LicenseGateStatus =
  | 'checking'
  | 'authorized'
  | 'unauthorized'
  | 'expired'
  | 'disabled'
  | 'device_mismatch'
  | 'offline_grace'
  | 'service_error';

export interface LicenseGateSnapshot {
  status: LicenseGateStatus;
  authorized: boolean;
  reason: string;
  code: string;
  license: License | null;
  installId: string;
  deviceId: string;
  purchaseUrl: string;
  supportUrl: string;
}

export interface LicenseGateInput {
  response?: LicenseCurrentResponse | null;
  config?: LicenseClientConfig | null;
  error?: unknown;
  configUnavailable?: boolean;
}

const DEFAULT_COMMERCIAL_URL = 'https://license.heang.top/';

const EXPIRED_CODES = new Set(['EXPIRED', 'LICENSE_EXPIRED']);
const DISABLED_CODES = new Set(['DISABLED', 'LICENSE_DISABLED', 'LICENSE_REVOKED']);
const DEVICE_CODES = new Set([
  'DEVICE_MISMATCH',
  'DEVICE_ID_MISMATCH',
  'INSTALL_ID_MISMATCH',
]);

function objectValue(value: unknown, key: string): unknown {
  return value && typeof value === 'object'
    ? (value as Record<string, unknown>)[key]
    : undefined;
}

function textValue(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}

function errorText(error: unknown): string {
  return (
    textValue(objectValue(error, 'error'))
    || textValue(objectValue(error, 'message'))
    || textValue(error)
  );
}

function errorCode(error: unknown): string {
  return (
    textValue(objectValue(error, 'code'))
    || textValue(objectValue(objectValue(error, '_meta'), 'code'))
  ).toUpperCase();
}

function normalizedLicense(license: License | null | undefined): License | null {
  if (!license || typeof license !== 'object') return null;
  const expires = textValue(license.expiresAt) || textValue(license.expires) || null;
  return { ...license, expires, expiresAt: expires };
}

function commercialUrl(config: LicenseClientConfig | null | undefined, key: 'purchaseUrl' | 'supportUrl'): string {
  const direct = textValue(config?.[key]);
  if (direct) return direct;
  if (key === 'purchaseUrl') {
    const cardUrl = textValue(config?.cardSite?.url);
    if (cardUrl) return cardUrl;
  }
  return DEFAULT_COMMERCIAL_URL;
}

function gateStatus(code: string, reason: string): LicenseGateStatus {
  if (EXPIRED_CODES.has(code) || /expired|过期/i.test(reason)) return 'expired';
  if (DISABLED_CODES.has(code) || /disabled|revoked|停用|禁用/i.test(reason)) return 'disabled';
  if (DEVICE_CODES.has(code) || /device.*mismatch|install.*mismatch|设备.*不匹配|机器码.*不匹配/i.test(reason)) {
    return 'device_mismatch';
  }
  if (/network|fetch|connect|timeout|service unavailable|网络|连接|超时|服务异常/i.test(reason)) {
    return 'service_error';
  }
  return 'unauthorized';
}

export const CHECKING_LICENSE_GATE: LicenseGateSnapshot = {
  status: 'checking',
  authorized: false,
  reason: '正在检查本机授权',
  code: 'CHECKING',
  license: null,
  installId: '',
  deviceId: '',
  purchaseUrl: DEFAULT_COMMERCIAL_URL,
  supportUrl: DEFAULT_COMMERCIAL_URL,
};

export function normalizeLicenseGate(input: LicenseGateInput = {}): LicenseGateSnapshot {
  const response = input.response || null;
  const license = normalizedLicense(response?.license);
  const responseStatus = textValue(response?.status).toUpperCase();
  const responseCode = textValue(response?.code).toUpperCase();
  const failureCode = responseCode || responseStatus || errorCode(input.error) || 'LICENSE_REQUIRED';
  const reason = (
    textValue(response?.reason)
    || textValue(response?.message)
    || errorText(input.error)
    || '当前电脑尚未激活商业授权'
  );
  const purchaseUrl = commercialUrl(input.config, 'purchaseUrl');
  const supportUrl = commercialUrl(input.config, 'supportUrl');
  const installId = textValue(response?.installId) || textValue(license?.installId);
  const deviceId = textValue(response?.deviceId) || textValue(license?.deviceId);

  if (license?.signature) {
    const offline = Boolean(input.configUnavailable || response?.offline);
    return {
      status: offline ? 'offline_grace' : 'authorized',
      authorized: true,
      reason: offline ? '本机签名授权有效，授权服务暂时不可用' : '商业授权有效',
      code: offline ? 'OFFLINE_GRACE' : 'AUTHORIZED',
      license,
      installId,
      deviceId,
      purchaseUrl,
      supportUrl,
    };
  }

  return {
    status: gateStatus(failureCode, reason),
    authorized: false,
    reason,
    code: failureCode,
    license: null,
    installId,
    deviceId,
    purchaseUrl,
    supportUrl,
  };
}

export async function withLicenseCheckTimeout<T>(
  promise: Promise<T>,
  timeoutMs = LICENSE_CHECK_TIMEOUT_MS,
): Promise<T> {
  let timeoutId: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<never>((_, reject) => {
    timeoutId = setTimeout(() => {
      reject({ code: 'LICENSE_CHECK_TIMEOUT', error: '授权检查超时，请重试或导出诊断信息' });
    }, timeoutMs);
  });

  try {
    return await Promise.race([promise, timeout]);
  } finally {
    if (timeoutId) clearTimeout(timeoutId);
  }
}
