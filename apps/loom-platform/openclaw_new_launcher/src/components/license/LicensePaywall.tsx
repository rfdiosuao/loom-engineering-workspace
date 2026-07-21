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
    tone: 'border-[#9db8ae] bg-[#edf5f2] text-[#16483d]',
  },
  authorized: {
    eyebrow: '授权有效',
    title: '商业能力已经解锁',
    action: '正在进入工作台。',
    tone: 'border-[#7ec9b0] bg-[#e5f7f0] text-[#075f4b]',
  },
  unauthorized: {
    eyebrow: '等待激活',
    title: '输入授权码后进入获客工作台',
    action: '授权码会绑定当前电脑，激活后重启仍然有效。',
    tone: 'border-[#d2b96f] bg-[#fff8df] text-[#6e5310]',
  },
  expired: {
    eyebrow: '授权已到期',
    title: '续费或更换授权码后继续使用',
    action: '本机数据不会删除，重新激活后可继续进入工作台。',
    tone: 'border-[#e5a45d] bg-[#fff2e3] text-[#81410b]',
  },
  disabled: {
    eyebrow: '授权已停用',
    title: '请联系服务方核对授权状态',
    action: '可以复制机器码或导出脱敏诊断，便于售后定位。',
    tone: 'border-[#dd8792] bg-[#fff0f2] text-[#8c2535]',
  },
  device_mismatch: {
    eyebrow: '设备不匹配',
    title: '当前电脑尚未绑定这份授权',
    action: '复制本机机器码，联系服务方重新绑定或更换授权码。',
    tone: 'border-[#d6a073] bg-[#fff3e8] text-[#76431c]',
  },
  offline_grace: {
    eyebrow: '离线授权可用',
    title: '本机签名有效，授权服务暂时离线',
    action: '可以继续使用；网络恢复后建议重新检查授权状态。',
    tone: 'border-[#7cb6c1] bg-[#eaf7fa] text-[#165765]',
  },
  service_error: {
    eyebrow: '授权服务暂不可用',
    title: '没有卡死，可以重试或导出诊断',
    action: '请检查网络和 Bridge 状态；没有有效本机授权时不会进入核心功能。',
    tone: 'border-[#d78c96] bg-[#fff0f2] text-[#842d3b]',
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
    title: '正在核验这台电脑的矩阵使用资格',
    action: '麓鸣其他功能不受影响，检查完成后会自动进入手机连接。',
  },
  authorized: {
    eyebrow: '手机矩阵授权有效',
    title: '手机连接与矩阵控制已经解锁',
    action: '正在载入设备和任务状态。',
  },
  unauthorized: {
    eyebrow: '手机矩阵等待激活',
    title: '激活后连接和控制手机',
    action: '授权只解锁手机连接、矩阵任务和手机素材传输，麓鸣其他功能可继续使用。',
  },
  expired: {
    eyebrow: '手机矩阵授权已到期',
    title: '续费或更换授权码后继续控制手机',
    action: '设备配置和任务记录不会删除，诊断能力仍然保留。',
  },
  disabled: {
    eyebrow: '手机矩阵授权已停用',
    title: '请联系服务方核对授权状态',
    action: '可以复制机器码或导出脱敏诊断，麓鸣其他功能仍可使用。',
  },
  device_mismatch: {
    eyebrow: '手机矩阵设备不匹配',
    title: '当前电脑尚未绑定这份授权',
    action: '复制本机机器码，联系服务方重新绑定或更换授权码。',
  },
  offline_grace: {
    eyebrow: '离线手机矩阵授权可用',
    title: '本机签名有效，授权服务暂时离线',
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
  featureDenied = false,
  featureChecking = false,
  gateError = '',
  onAccessRefresh,
  onEmergencyStop,
  emergencyStopping = false,
}) => {
  const { licenseGate, isLicenseChecking, checkLicense } = useAppStore();
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
      className="h-full min-h-0 flex-1 overflow-y-auto bg-[#edf2ef] text-[#17221e]"
    >
      <div className="mx-auto grid min-h-full w-full max-w-[1440px] grid-cols-1 md:grid-cols-[minmax(0,1.08fr)_minmax(350px,0.92fr)]">
        <section className="flex min-h-[390px] flex-col justify-between bg-[#08242b] px-6 py-8 text-white sm:px-10 lg:min-h-full lg:px-14 lg:py-12">
          <div>
            <div className="flex items-center gap-3">
              <LoomLogoMark className="h-11 w-11 border border-white/10" />
              <div>
                <div className="text-[12px] font-bold uppercase text-[#7ce3bd]">
                  {phoneMatrixScope ? 'Phone Matrix Access' : 'Commercial Access'}
                </div>
                <div className="mt-1 text-[15px] font-black">{APP_DISPLAY_NAME}</div>
              </div>
            </div>

            <div className="mt-10 max-w-[680px]">
              <p className="text-[13px] font-bold text-[#7ce3bd]">
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
          <div className="w-full border border-[#cad7d1] bg-white p-5 shadow-[0_18px_55px_rgba(21,48,40,0.11)] sm:p-7">
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

            <form className="mt-6" onSubmit={activateLicense}>
              <label htmlFor="commercial-license-code" className="text-[12px] font-black text-[#34564c]">
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
                  className="h-11 min-w-0 flex-1 border border-[#aebfb8] bg-[#fbfdfc] px-3 text-[14px] font-semibold outline-none transition focus:border-[#08745d] focus:ring-2 focus:ring-[#08745d]/15"
                />
                <button
                  data-license-activate
                  type="submit"
                  disabled={activating || isLicenseChecking}
                  className="h-11 shrink-0 bg-[#075f4b] px-5 text-[13px] font-black text-white transition hover:bg-[#064c3d] disabled:cursor-not-allowed disabled:opacity-55"
                >
                  {activating ? '激活中...' : phoneMatrixScope ? '激活手机矩阵' : '激活并进入'}
                </button>
              </div>
            </form>

            <div className="mt-5 grid grid-cols-2 border-l border-t border-[#d9e2de] text-[12px]">
              <div className="min-w-0 border-b border-r border-[#d9e2de] p-3">
                <div className="font-bold text-[#6a7d75]">当前套餐</div>
                <div className="mt-1 truncate font-black text-[#1d332b]">{plan}</div>
              </div>
              <div className="min-w-0 border-b border-r border-[#d9e2de] p-3">
                <div className="font-bold text-[#6a7d75]">到期时间</div>
                <div className="mt-1 truncate font-black text-[#1d332b]">{displayDate(expires)}</div>
              </div>
              <div className="col-span-2 min-w-0 border-b border-r border-[#d9e2de] p-3" data-license-install-id>
                <div className="font-bold text-[#6a7d75]">本机机器码 / 安装 ID</div>
                <div className="mt-1 break-all font-mono text-[11px] font-bold text-[#1d332b]">
                  {machineId || '等待 Bridge 返回本机标识'}
                </div>
              </div>
            </div>

            {actionError || gateError ? (
              <div className="mt-4 border border-[#e3a3ac] bg-[#fff2f4] px-3 py-2.5 text-[12px] font-bold leading-5 text-[#8a2838]" role="alert">
                {actionError || gateError}
              </div>
            ) : null}

            <div className="mt-5 grid grid-cols-2 gap-2 lg:grid-cols-3">
              <button
                data-license-copy-install-id
                type="button"
                onClick={copyInstallId}
                className="h-10 border border-[#bac8c2] bg-white px-3 text-[12px] font-black text-[#24483e] hover:bg-[#f1f6f4]"
              >
                复制机器码
              </button>
              <button
                type="button"
                onClick={() => void refreshAccess()}
                disabled={isLicenseChecking}
                className="h-10 border border-[#bac8c2] bg-white px-3 text-[12px] font-black text-[#24483e] hover:bg-[#f1f6f4] disabled:opacity-55"
              >
                {isLicenseChecking ? '检查中...' : '重新检查'}
              </button>
              <button
                data-license-diagnostics-export
                type="button"
                onClick={exportDiagnostics}
                disabled={diagnosing}
                className="col-span-2 h-10 border border-[#bac8c2] bg-white px-3 text-[12px] font-black text-[#24483e] hover:bg-[#f1f6f4] disabled:opacity-55 lg:col-span-1"
              >
                {diagnosing ? '导出中...' : '导出脱敏诊断'}
              </button>
            </div>

            <div className="mt-6 flex flex-col gap-2 border-t border-[#d9e2de] pt-5 sm:flex-row">
              <button
                data-license-purchase-link
                type="button"
                onClick={() => openCommercialLink(licenseGate.purchaseUrl)}
                className="h-10 flex-1 bg-[#d9b45c] px-4 text-[12px] font-black text-[#2b2517] hover:bg-[#cda647]"
              >
                购买或续费授权
              </button>
              <button
                data-license-support-link
                type="button"
                onClick={() => openCommercialLink(licenseGate.supportUrl)}
                className="h-10 flex-1 border border-[#075f4b] bg-white px-4 text-[12px] font-black text-[#075f4b] hover:bg-[#edf7f3]"
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
                className="mt-2 h-10 w-full border border-[#c64c5f] bg-white px-4 text-[12px] font-black text-[#9a2738] hover:bg-[#fff1f3] disabled:cursor-not-allowed disabled:opacity-55"
              >
                {emergencyStopping ? '正在停止全部手机任务...' : '紧急停止全部手机任务'}
              </button>
            ) : null}

            <p className="mt-4 text-[11px] font-medium leading-5 text-[#75847e]">
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
