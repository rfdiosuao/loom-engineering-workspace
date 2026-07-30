import React from 'react';
import { open } from '@tauri-apps/plugin-shell';

import { LoomLogoMark } from '../brand/LoomBrand';
import { showToast } from '../common';
import { diagnosticsApi, licenseApi, parseErrorText } from '../../services/api';
import { useAppStore } from '../../stores/appStore';
import { APP_DISPLAY_NAME } from '../../version';
import type { LicenseGateStatus } from './licenseGate';

const FALLBACK_COMMERCIAL_URL = 'https://license.heang.top/';

const STATUS_COPY: Record<LicenseGateStatus, { eyebrow: string; title: string; action: string; tone: string }> = {
  checking: {
    eyebrow: '正在检查授权',
    title: '正在核验这台电脑的商业授权',
    action: '检查通常只需要几秒，超时后会显示可处理的原因。',
    tone: 'border-info bg-info-soft text-info-ink',
  },
  authorized: {
    eyebrow: '授权有效',
    title: '商业能力已经解锁',
    action: '正在进入工作台。',
    tone: 'border-status-success bg-status-success-soft text-status-success-ink',
  },
  unauthorized: {
    eyebrow: '等待激活',
    title: '输入授权码后进入获客工作台',
    action: '授权码会绑定当前电脑，激活后重启仍然有效。',
    tone: 'border-status-warning bg-status-warning-soft text-status-warning-ink',
  },
  expired: {
    eyebrow: '授权已到期',
    title: '续费或更换授权码后继续使用',
    action: '本机数据不会删除，重新激活后可继续进入工作台。',
    tone: 'border-status-warning bg-status-warning-soft text-status-warning-ink',
  },
  disabled: {
    eyebrow: '授权已停用',
    title: '请联系服务方核对授权状态',
    action: '可以复制机器码或导出脱敏诊断，便于售后定位。',
    tone: 'border-status-danger bg-status-danger-soft text-status-danger-ink',
  },
  device_mismatch: {
    eyebrow: '设备不匹配',
    title: '当前电脑尚未绑定这份授权',
    action: '复制本机机器码，联系服务方重新绑定或更换授权码。',
    tone: 'border-status-warning bg-status-warning-soft text-status-warning-ink',
  },
  offline_grace: {
    eyebrow: '离线授权可用',
    title: '本机签名有效，授权服务暂时离线',
    action: '可以继续使用；网络恢复后建议重新检查授权状态。',
    tone: 'border-info bg-info-soft text-info-ink',
  },
  service_error: {
    eyebrow: '授权服务暂不可用',
    title: '没有卡死，可以重试或导出诊断',
    action: '请检查网络和 Bridge 状态；没有有效本机授权时不会进入核心功能。',
    tone: 'border-status-danger bg-status-danger-soft text-status-danger-ink',
  },
};

const CAPABILITIES = [
  ['多台手机矩阵', '统一查看设备状态与执行任务'],
  ['线索与客户池', '把真实发现结果持续沉淀'],
  ['AI 跟进草稿', '先生成草稿，再由人工确认'],
  ['飞书多维表格', '将获客结果写入团队表格'],
  ['模板云端沉淀', '复用行业 SOP 与知识库'],
  ['安全发布链路', '白名单、频控与日志留痕'],
] as const;

const PHONE_MATRIX_CAPABILITIES = [
  ['手机连接', '配置、检测并区分每一台真实设备'],
  ['矩阵任务', '向选定设备或设备组并行下发任务'],
  ['实时画面', '查看截图、运行状态与失败原因'],
  ['人工接管', '在需要时切换到真实手机控制协议'],
  ['素材传输', '将图片和视频发送到指定手机相册'],
  ['安全急停', '保留任务急停、诊断与审计能力'],
] as const;

const PHONE_MATRIX_COPY: Record<LicenseGateStatus, { eyebrow: string; title: string; action: string }> = {
  checking: {
    eyebrow: '正在检查手机矩阵授权',
    title: '正在核验当前模型账号的矩阵使用资格',
    action: '未激活账号可继续使用麓鸣其他功能，检查完成后会自动进入手机连接。',
  },
  authorized: {
    eyebrow: '手机矩阵授权有效',
    title: '手机连接与矩阵控制已经解锁',
    action: '当前账号下已连接的全部手机均可使用，正在载入设备和任务状态。',
  },
  unauthorized: {
    eyebrow: '手机矩阵等待激活',
    title: '激活后连接和控制手机',
    action: '未激活账号可用 0 台手机；授权码绑定当前模型账号后，该账号下已连接的全部手机均可使用。',
  },
  expired: {
    eyebrow: '手机矩阵授权已到期',
    title: '续费或更换授权码后继续控制手机',
    action: '账号下的设备配置和任务记录不会删除，恢复授权后可继续使用。',
  },
  disabled: {
    eyebrow: '手机矩阵授权已停用',
    title: '请联系服务方核对授权状态',
    action: '可以导出脱敏诊断交给服务方，麓鸣其他功能仍可使用。',
  },
  device_mismatch: {
    eyebrow: '手机矩阵租约不匹配',
    title: '当前登录账号与本机权益租约不一致',
    action: '请重新登录当前账号刷新租约；仍未恢复时导出脱敏诊断交给服务方。',
  },
  offline_grace: {
    eyebrow: '离线手机矩阵授权可用',
    title: '账号签名权益有效，授权服务暂时离线',
    action: '手机矩阵可以继续使用；网络恢复后建议重新检查。',
  },
  service_error: {
    eyebrow: '授权服务暂不可用',
    title: '手机矩阵暂未解锁，可以重试或导出诊断',
    action: '请检查网络和 Bridge 状态，麓鸣其他功能不受影响。',
  },
};

interface LicensePaywallProps {
  scope?: 'application' | 'phone-matrix';
  accountBindingOnly?: boolean;
  featureDenied?: boolean;
  featureChecking?: boolean;
  gateError?: string;
  onAccessRefresh?: () => Promise<boolean | void> | boolean | void;
  onEmergencyStop?: () => Promise<void> | void;
  emergencyStopping?: boolean;
}

export function safeCommercialUrl(value: string): string {
  try {
    const parsed = new URL(value || FALLBACK_COMMERCIAL_URL);
    if (parsed.protocol !== 'https:' || ['localhost', '127.0.0.1', '::1'].includes(parsed.hostname)) {
      return FALLBACK_COMMERCIAL_URL;
    }
    return parsed.toString();
  } catch {
    return FALLBACK_COMMERCIAL_URL;
  }
}

function displayDate(value: string | null | undefined): string {
  const normalized = String(value || '').trim();
  return normalized ? normalized.slice(0, 10) : '未提供';
}

export const LicensePaywall: React.FC<LicensePaywallProps> = ({
  scope = 'application',
  accountBindingOnly = false,
  featureDenied = false,
  featureChecking = false,
  gateError = '',
  onAccessRefresh,
  onEmergencyStop,
  emergencyStopping = false,
}) => {
  const { licenseGate, isLicenseChecking, checkLicense, setCurrentPage } = useAppStore();
  const [code, setCode] = React.useState('');
  const [activating, setActivating] = React.useState(false);
  const [diagnosing, setDiagnosing] = React.useState(false);
  const [actionError, setActionError] = React.useState('');
  const phoneMatrixScope = scope === 'phone-matrix';
  const effectiveStatus: LicenseGateStatus = featureChecking
    ? 'checking'
    : featureDenied
      ? 'unauthorized'
      : licenseGate.status;
  const copy = featureDenied ? {
    ...STATUS_COPY.unauthorized,
    eyebrow: '当前套餐不含手机矩阵',
    title: '升级或更换授权码后连接手机',
    action: '这台电脑已经激活，但当前授权范围不包含手机连接与矩阵控制。',
  } : {
    ...STATUS_COPY[effectiveStatus],
    ...(phoneMatrixScope ? PHONE_MATRIX_COPY[effectiveStatus] : {}),
  };
  const capabilities = phoneMatrixScope ? PHONE_MATRIX_CAPABILITIES : CAPABILITIES;
  const installId = licenseGate.installId || licenseGate.license?.installId || '';
  const deviceId = licenseGate.deviceId || licenseGate.license?.deviceId || '';
  const machineId = deviceId || installId;
  const expires = licenseGate.license?.expiresAt || licenseGate.license?.expires;
  const plan = licenseGate.license?.plan || licenseGate.license?.edition || '未激活';

  const activateLicense = async (event: React.FormEvent) => {
    event.preventDefault();
    const normalized = code.trim();
    if (!normalized) {
      setActionError('请输入授权码');
      return;
    }
    setActivating(true);
    setActionError('');
    try {
      await licenseApi.activate(normalized);
      setCode('');
      await checkLicense();
      const accessGranted = await onAccessRefresh?.();
      if (accessGranted === false) {
        setActionError('授权码已激活，但当前套餐未包含手机矩阵，请更换授权码或联系服务方');
        return;
      }
      showToast(phoneMatrixScope ? '手机矩阵授权激活成功' : '授权激活成功', 'success');
    } catch (error) {
      setActionError(parseErrorText(error) || '授权激活失败，请检查授权码后重试');
    } finally {
      setActivating(false);
    }
  };

  const refreshAccess = async () => {
    setActionError('');
    await checkLicense();
    await onAccessRefresh?.();
  };

  const copyInstallId = async () => {
    if (!machineId) {
      setActionError('暂未读取到机器码，请重新检查授权状态');
      return;
    }
    try {
      await navigator.clipboard.writeText(machineId);
      showToast('机器码已复制', 'success');
    } catch {
      setActionError('复制失败，请导出诊断信息交给服务方');
    }
  };

  const exportDiagnostics = async () => {
    setDiagnosing(true);
    setActionError('');
    try {
      const result = await diagnosticsApi.export();
      showToast(`脱敏诊断已导出：${result.filename}`, 'success');
    } catch (error) {
      setActionError(parseErrorText(error) || '诊断导出失败，请稍后重试');
    } finally {
      setDiagnosing(false);
    }
  };

  const openCommercialLink = async (value: string) => {
    try {
      await open(safeCommercialUrl(value));
    } catch {
      setActionError('暂时无法打开网页，请检查系统默认浏览器');
    }
  };

  return (
    <main
      data-license-paywall
      data-license-status={effectiveStatus}
      data-license-scope={scope}
      data-phone-matrix-license-gate={phoneMatrixScope || undefined}
      className="h-full min-h-0 flex-1 overflow-y-auto bg-app-bg text-text"
    >
      <div className="mx-auto grid min-h-full w-full max-w-[1440px] grid-cols-1 md:grid-cols-[minmax(0,1.08fr)_minmax(350px,0.92fr)]">
        <section className="flex min-h-[390px] flex-col justify-between bg-surface-deeper px-6 py-8 text-white sm:px-10 lg:min-h-full lg:px-14 lg:py-12">
          <div>
            <div className="flex items-center gap-3">
              <LoomLogoMark className="h-11 w-11 border border-white/10" />
              <div>
                <div className="text-[12px] font-bold uppercase text-info">
                  {phoneMatrixScope ? 'Phone Matrix Access' : 'Commercial Access'}
                </div>
                <div className="mt-1 text-[15px] font-black">{APP_DISPLAY_NAME}</div>
              </div>
            </div>

            <div className="mt-10 max-w-[680px]">
              <p className="text-[13px] font-bold text-info">
                {phoneMatrixScope ? '手机连接与矩阵控制' : 'AI 矩阵获客商业版'}
              </p>
              <h1 className="mt-3 max-w-[620px] text-[34px] font-black leading-[1.16] sm:text-[42px]">
                {phoneMatrixScope ? '一份授权，管理每一台真实手机' : '多台手机找线索，AI 做判断，飞书沉淀客户'}
              </h1>
              <p className="mt-4 max-w-[620px] text-[15px] font-medium leading-7 text-white/68">
                {phoneMatrixScope
                  ? '授权在手机连接入口完成。激活后可使用设备检测、矩阵任务、实时画面、人工接管与素材传输。'
                  : '将手机 Agent、线索发现、跟进草稿、人工确认和飞书多维表格放进同一条可审计链路。'}
              </p>
              {phoneMatrixScope ? (
                <div className="mt-6 flex flex-wrap gap-2 text-[11px] font-black text-white/80" aria-label="手机矩阵启用步骤">
                  <span className="border border-white/20 px-3 py-2">1 激活矩阵</span>
                  <span className="border border-white/20 px-3 py-2">2 添加手机</span>
                  <span className="border border-white/20 px-3 py-2">3 下发任务</span>
                </div>
              ) : null}
            </div>
          </div>

          <div className="mt-9 grid grid-cols-1 border-l border-t border-white/14 sm:grid-cols-2">
            {capabilities.map(([title, description]) => (
              <div key={title} className="min-h-[86px] border-b border-r border-white/14 px-4 py-3.5">
                <div className="text-[14px] font-black text-white">{title}</div>
                <div className="mt-1 text-[12px] font-medium leading-5 text-white/55">{description}</div>
              </div>
            ))}
          </div>
        </section>

        <section className="flex items-center px-5 py-8 sm:px-10 lg:px-12">
          <div className="w-full rounded-[8px] border border-border bg-surface p-5 shadow-elevation-medium sm:p-7">
            <div className={`border px-4 py-3 ${copy.tone}`}>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <div className="text-[11px] font-black uppercase">{copy.eyebrow}</div>
                  <h2 className="mt-1 text-[22px] font-black leading-tight">{copy.title}</h2>
                </div>
                <span className="border border-current/25 bg-white/55 px-2.5 py-1 text-[11px] font-black">
                  {effectiveStatus}
                </span>
              </div>
              <p className="mt-2 text-[12px] font-semibold leading-5 opacity-80">{copy.action}</p>
            </div>

            {accountBindingOnly ? (
              <div className="mt-6 rounded-[6px] border border-info bg-info-soft p-4">
                <div className="text-[13px] font-black text-text">授权码绑定模型账号</div>
                <p className="mt-1 text-[12px] font-semibold leading-5 text-text-muted">
                  未激活账号可用 0 台手机。请先登录模型账号并绑定一次授权码；激活后该账号下已连接的全部手机均可使用，以后在其他电脑登录同一账号即可恢复权益。
                </p>
                <button
                  data-account-entitlement-link
                  type="button"
                  onClick={() => setCurrentPage('license')}
                  className="mt-3 h-10 rounded-[6px] bg-accent px-4 text-[12px] font-black text-accent-ink transition hover:bg-accent-hover"
                >
                  登录模型账号并绑定授权码
                </button>
              </div>
            ) : (
              <form className="mt-6" onSubmit={activateLicense}>
                <label htmlFor="commercial-license-code" className="text-[12px] font-black text-text">
                  商业授权码
                </label>
                <div className="mt-2 flex flex-col gap-2 sm:flex-row">
                  <input
                    id="commercial-license-code"
                    data-license-code-input
                    type="password"
                    value={code}
                    onChange={(event) => setCode(event.target.value)}
                    autoComplete="off"
                    spellCheck={false}
                    placeholder="请输入服务方提供的授权码"
                    className="h-11 min-w-0 flex-1 rounded-[6px] border border-border-strong bg-input px-3 text-[14px] font-semibold text-text outline-none transition placeholder:text-text-subtle focus:border-info focus:ring-2 focus:ring-[var(--color-focus-soft)]"
                  />
                  <button
                    data-license-activate
                    type="submit"
                    disabled={activating || isLicenseChecking}
                    className="h-11 shrink-0 rounded-[6px] bg-accent px-5 text-[13px] font-black text-accent-ink transition hover:bg-accent-hover disabled:cursor-not-allowed disabled:bg-disabled disabled:text-disabled"
                  >
                    {activating ? '激活中...' : phoneMatrixScope ? '激活手机矩阵' : '激活并进入'}
                  </button>
                </div>
              </form>
            )}

            <div className="mt-5 grid grid-cols-2 border-l border-t border-border text-[12px]">
              <div className="min-w-0 border-b border-r border-border p-3">
                <div className="font-bold text-text-muted">当前套餐</div>
                <div className="mt-1 truncate font-black text-text">{plan}</div>
              </div>
              <div className="min-w-0 border-b border-r border-border p-3">
                <div className="font-bold text-text-muted">到期时间</div>
                <div className="mt-1 truncate font-black text-text">{displayDate(expires)}</div>
              </div>
              <div className="col-span-2 min-w-0 border-b border-r border-border p-3" data-license-install-id>
                <div className="font-bold text-text-muted">本机机器码 / 安装 ID</div>
                <div className="mt-1 break-all font-mono text-[11px] font-bold text-text">
                  {machineId || '等待 Bridge 返回本机标识'}
                </div>
              </div>
            </div>

            {actionError || gateError ? (
              <div className="mt-4 rounded-[6px] border border-status-danger bg-status-danger-soft px-3 py-2.5 text-[12px] font-bold leading-5 text-status-danger-ink" role="alert" aria-live="assertive">
                {actionError || gateError}
              </div>
            ) : null}

            <div className="mt-5 grid grid-cols-2 gap-2 lg:grid-cols-3">
              <button
                data-license-copy-install-id
                type="button"
                onClick={copyInstallId}
                className="h-10 rounded-[6px] border border-border-strong bg-surface px-3 text-[12px] font-black text-text hover:bg-hover"
              >
                复制机器码
              </button>
              <button
                type="button"
                onClick={() => void refreshAccess()}
                disabled={isLicenseChecking}
                className="h-10 rounded-[6px] border border-border-strong bg-surface px-3 text-[12px] font-black text-text hover:bg-hover disabled:cursor-not-allowed disabled:bg-disabled disabled:text-disabled"
              >
                {isLicenseChecking ? '检查中...' : '重新检查'}
              </button>
              <button
                data-license-diagnostics-export
                type="button"
                onClick={exportDiagnostics}
                disabled={diagnosing}
                className="col-span-2 h-10 rounded-[6px] border border-border-strong bg-surface px-3 text-[12px] font-black text-text hover:bg-hover disabled:cursor-not-allowed disabled:bg-disabled disabled:text-disabled lg:col-span-1"
              >
                {diagnosing ? '导出中...' : '导出脱敏诊断'}
              </button>
            </div>

            <div className="mt-6 flex flex-col gap-2 border-t border-border pt-5 sm:flex-row">
              <button
                data-license-purchase-link
                type="button"
                onClick={() => openCommercialLink(licenseGate.purchaseUrl)}
                className="h-10 flex-1 rounded-[6px] border border-status-warning bg-status-warning-soft px-4 text-[12px] font-black text-status-warning-ink hover:brightness-95"
              >
                购买或续费授权
              </button>
              <button
                data-license-support-link
                type="button"
                onClick={() => openCommercialLink(licenseGate.supportUrl)}
                className="h-10 flex-1 rounded-[6px] border border-info bg-surface px-4 text-[12px] font-black text-info hover:bg-info-soft"
              >
                联系服务支持
              </button>
            </div>

            {phoneMatrixScope && onEmergencyStop ? (
              <button
                data-license-emergency-stop
                type="button"
                onClick={() => void onEmergencyStop()}
                disabled={emergencyStopping}
                className="mt-2 h-10 w-full rounded-[6px] border border-status-danger bg-surface px-4 text-[12px] font-black text-status-danger hover:bg-status-danger-soft disabled:cursor-not-allowed disabled:bg-disabled disabled:text-disabled"
              >
                {emergencyStopping ? '正在停止全部手机任务...' : '紧急停止全部手机任务'}
              </button>
            ) : null}

            <p className="mt-4 text-[11px] font-medium leading-5 text-text-muted">
              {phoneMatrixScope
                ? '授权范围仅限手机连接、手机任务、矩阵控制与相关素材传输；急停和脱敏诊断始终保留。'
                : '真实发布、评论、私信、加好友和加微仍默认经过草稿、人工确认、白名单、频控与日志留痕。'}
            </p>
          </div>
        </section>
      </div>
    </main>
  );
};
