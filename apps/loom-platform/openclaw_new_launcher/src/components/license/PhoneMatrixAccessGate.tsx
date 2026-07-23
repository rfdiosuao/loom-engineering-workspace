import React from 'react';

import { licenseApi, matrixApi, parseErrorText } from '../../services/api';
import { useAppStore } from '../../stores/appStore';
import { showConfirm, showToast } from '../common';
import { LicensePaywall } from './LicensePaywall';

interface PhoneMatrixAccessGateProps {
  children: React.ReactNode;
}

export const PhoneMatrixAccessGate: React.FC<PhoneMatrixAccessGateProps> = ({ children }) => {
  const licenseGate = useAppStore((state) => state.licenseGate);
  const checkLicense = useAppStore((state) => state.checkLicense);
  const [featureAuthorized, setFeatureAuthorized] = React.useState<boolean | null>(null);
  const [featureError, setFeatureError] = React.useState('');
  const [stopping, setStopping] = React.useState(false);

  const refreshFeatureAccess = React.useCallback(async (): Promise<boolean> => {
    const currentGate = useAppStore.getState().licenseGate;
    if (!currentGate.authorized) {
      setFeatureAuthorized(false);
      return false;
    }

    setFeatureAuthorized(null);
    setFeatureError('');
    try {
      const result = await licenseApi.authorized('matrix.devices');
      const granted = Boolean(result.authorized);
      setFeatureAuthorized(granted);
      return granted;
    } catch (error) {
      setFeatureAuthorized(false);
      setFeatureError(parseErrorText(error) || '无法核验手机矩阵授权，请检查 Bridge 后重试');
      return false;
    }
  }, []);

  React.useEffect(() => {
    if (!licenseGate.authorized) {
      setFeatureAuthorized(false);
      setFeatureError('');
      return;
    }
    void refreshFeatureAccess();
  }, [licenseGate.authorized, licenseGate.license?.signature, refreshFeatureAccess]);

  const refreshAllAccess = React.useCallback(async (): Promise<boolean> => {
    await checkLicense();
    return refreshFeatureAccess();
  }, [checkLicense, refreshFeatureAccess]);

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
        featureDenied={licenseGate.authorized && featureAuthorized === false}
        featureChecking={licenseGate.authorized && featureAuthorized === null}
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
          className="flex min-h-10 shrink-0 flex-wrap items-center justify-between gap-2 border-b border-[#c7a75d] bg-[#fff5d8] px-4 py-2 text-[12px] font-bold text-[#6a4d0b]"
        >
          <span>本机签名授权有效，授权服务暂时离线；手机矩阵可继续使用。</span>
          <button
            type="button"
            onClick={() => void refreshAllAccess()}
            className="h-8 border border-[#9b7927] bg-white px-3 text-[11px] font-black text-[#6a4d0b] hover:bg-[#fffaf0]"
          >
            重新检查
          </button>
        </div>
      ) : null}
      <div className="flex min-h-0 flex-1 flex-col overflow-hidden">{children}</div>
    </div>
  );
};
