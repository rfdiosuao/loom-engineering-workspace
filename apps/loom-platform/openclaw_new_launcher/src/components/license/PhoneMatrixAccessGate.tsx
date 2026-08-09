import React from 'react';

import { licenseApi, matrixApi, parseErrorText } from '../../services/api';
import { useAppStore } from '../../stores/appStore';
import { showConfirm, showToast } from '../common';
import { LicensePaywall, type MatrixEntitlementSurface } from './LicensePaywall';
import { createSingleFlight, resolvePhoneMatrixAccess } from './phoneMatrixAccess';

interface PhoneMatrixAccessGateProps {
  children: React.ReactNode;
  surface?: MatrixEntitlementSurface;
}

const SURFACE_LABELS: Record<MatrixEntitlementSurface, string> = {
  phone: '手机连接',
  workbench: '矩阵工作台',
  skills: 'Skill 中心',
  acquisition: '矩阵获客',
};

function surfaceAccessError(error: unknown, surface: MatrixEntitlementSurface): string {
  const parsed = parseErrorText(error);
  if (parsed && !/(matrix\.devices|account_entitlement|ENTITLEMENT_REQUIRED|AGENT_ENTITLEMENT)/i.test(parsed)) {
    return parsed;
  }
  return `暂时无法核验${SURFACE_LABELS[surface]}权益，请检查网络和 Bridge 后重试`;
}

export const PhoneMatrixAccessGate: React.FC<PhoneMatrixAccessGateProps> = ({ children, surface = 'phone' }) => {
  const licenseGate = useAppStore((state) => state.licenseGate);
  const checkLicense = useAppStore((state) => state.checkLicense);
  const [featureAuthorized, setFeatureAuthorized] = React.useState<boolean | null>(null);
  const [featureError, setFeatureError] = React.useState('');
  const [stopping, setStopping] = React.useState(false);

  const refreshFeatureAccess = React.useMemo(() => createSingleFlight(async (): Promise<boolean> => {
    setFeatureAuthorized(null);
    setFeatureError('');
    try {
      const result = await resolvePhoneMatrixAccess({
        refreshLicense: checkLicense,
        readLicense: () => useAppStore.getState().licenseGate,
        checkFeature: () => licenseApi.authorized('matrix.devices'),
      });
      setFeatureAuthorized(result.authorized);
      return result.authorized;
    } catch (error) {
      setFeatureAuthorized(false);
      setFeatureError(surfaceAccessError(error, surface));
      return false;
    }
  }), [checkLicense, surface]);

  React.useEffect(() => {
    void refreshFeatureAccess();
  }, [refreshFeatureAccess]);

  const refreshAllAccess = refreshFeatureAccess;

  const emergencyStop = React.useCallback(async () => {
    const accepted = await showConfirm({
      title: '确认紧急停止',
      message: '将停止当前电脑管理的全部活动手机任务。已完成的外部动作无法撤回。',
      confirmText: '停止全部任务',
      tone: 'danger',
    });
    if (!accepted) return;
    setStopping(true);
    try {
      const result = await matrixApi.emergencyStop({ all: true });
      showToast(
        result.cancelled ? `已停止 ${result.affectedTaskCount} 个手机任务` : '当前没有需要停止的手机任务',
        result.cancelled ? 'success' : 'info',
      );
    } catch (error) {
      showToast(parseErrorText(error) || '紧急停止失败，请查看诊断日志', 'error');
    } finally {
      setStopping(false);
    }
  }, []);

  if (!licenseGate.authorized || featureAuthorized !== true) {
    return (
      <LicensePaywall
        scope="phone-matrix"
        matrixSurface={surface}
        accountBindingOnly
        featureDenied={featureAuthorized === false}
        featureChecking={featureAuthorized === null}
        gateError={featureError}
        onAccessRefresh={refreshFeatureAccess}
        onEmergencyStop={emergencyStop}
        emergencyStopping={stopping}
      />
    );
  }

  return (
    <div data-phone-matrix-access-granted className="absolute inset-0 flex min-h-0 flex-col overflow-hidden">
      {licenseGate.status === 'offline_grace' ? (
        <div
          data-license-offline-banner
          className="flex min-h-10 shrink-0 flex-wrap items-center justify-between gap-2 border-b border-status-warning bg-status-warning-soft px-4 py-2 text-[12px] font-bold text-status-warning-ink"
          role="status"
          aria-live="polite"
        >
          <span>本机签名授权有效，授权服务暂时离线；{SURFACE_LABELS[surface]}可继续使用。</span>
          <button
            type="button"
            onClick={() => void refreshAllAccess()}
            className="h-8 rounded-[6px] border border-status-warning bg-surface px-3 text-[11px] font-black text-status-warning-ink hover:bg-hover"
          >
            重新检查
          </button>
        </div>
      ) : null}
      <div className="flex min-h-0 flex-1 flex-col overflow-hidden">{children}</div>
    </div>
  );
};
