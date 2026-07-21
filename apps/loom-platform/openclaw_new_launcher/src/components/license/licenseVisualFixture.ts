import type { License } from '../../types';
import type { LicenseGateSnapshot, LicenseGateStatus } from './licenseGate';

const FIXTURE_STATES = new Set<LicenseGateStatus>([
  'authorized',
  'unauthorized',
  'expired',
  'disabled',
  'device_mismatch',
  'offline_grace',
  'service_error',
]);

const REASONS: Record<LicenseGateStatus, string> = {
  checking: '正在检查本机授权',
  authorized: '商业授权有效',
  unauthorized: '当前电脑尚未激活商业授权',
  expired: '当前授权已于 2026-07-01 到期',
  disabled: '当前授权已被服务方停用',
  device_mismatch: '当前电脑未绑定此授权',
  offline_grace: '本机签名授权有效，授权服务暂时不可用',
  service_error: '暂时无法连接授权服务',
};

export function getDevLicenseFixture(): LicenseGateSnapshot | null {
  if (!import.meta.env.DEV || typeof window === 'undefined') return null;
  const raw = new URLSearchParams(window.location.search).get('licenseState') || '';
  if (!FIXTURE_STATES.has(raw as LicenseGateStatus)) return null;

  const status = raw as LicenseGateStatus;
  const authorized = status === 'authorized' || status === 'offline_grace';
  const license: License | null = authorized
    ? {
        licensee: '发布验证客户',
        edition: 'team',
        plan: 'team_monthly',
        expires: '2027-07-10',
        expiresAt: '2027-07-10',
        features: [
          'acquisition.workbench',
          'acquisition.feishu',
          'matrix.devices',
          'templates.cloud',
        ],
        installId: 'install-visual-2-1-56',
        deviceId: 'device-visual-2-1-56',
        deviceLimit: 8,
        signature: 'development-visual-fixture',
      }
    : null;

  return {
    status,
    authorized,
    reason: REASONS[status],
    code: status.toUpperCase(),
    license,
    installId: license?.installId || 'install-visual-2-1-56',
    deviceId: license?.deviceId || 'device-visual-2-1-56',
    purchaseUrl: 'https://license.heang.top/',
    supportUrl: 'https://license.heang.top/',
  };
}
