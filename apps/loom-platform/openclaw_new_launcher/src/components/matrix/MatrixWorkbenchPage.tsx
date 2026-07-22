import React from 'react';

import { matrixApi, parseErrorText, waitForJob } from '../../services/api';
import { useAppStore, type FeatureNavigationContext } from '../../stores/appStore';
import type {
  MatrixCampaign,
  MatrixControlRequest,
  MatrixDeviceLease,
  MatrixEvent,
  MatrixExecutionMode,
  MatrixExecutionProfile,
} from '../../types/matrix';
import { showConfirm, showToast } from '../common';
import { DeviceGroupRail } from './DeviceGroupRail';
import { DeviceInspector } from './DeviceInspector';
import type { MatrixManualAction } from './ManualControls';
import { MatrixCommandBar } from './MatrixCommandBar';
import { MatrixMetrics } from './MatrixMetrics';
import { MatrixTaskDrawer } from './MatrixTaskDrawer';
import { PhoneWall } from './PhoneWall';
import { resolveScreenRequestOutcome } from './screenScheduler';
import {
  buildDeviceGroups,
  buildDeviceViews,
  matrixDispatchFingerprint,
  normalizeMatrixCampaigns,
  resolveCampaignAtomicEmergencyScope,
  resolveMatrixNavigation,
  supportedMatrixTaskActions,
  visibleDeviceViews,
  type MatrixDensity,
  type MatrixDeviceView,
} from './matrixViewModel';
import { useMatrixStream } from './useMatrixStream';
import { useVisibleScreens } from './useVisibleScreens';

function campaignForDeviceTask(campaigns: MatrixCampaign[], deviceTaskId: string): MatrixCampaign | undefined {
  return campaigns.find((campaign) => campaign.deviceTasks.some((task) => task.deviceTaskId === deviceTaskId));
}

function commandId(): string {
  return `matrix-ui-${typeof crypto.randomUUID === 'function' ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`}`;
}

export const MatrixWorkbenchPage = () => {
  const consumeNavigationContext = useAppStore((state) => state.consumeNavigationContext);
  const [prompt, setPrompt] = React.useState('');
  const [templateId, setTemplateId] = React.useState('');
  const [mode, setMode] = React.useState<MatrixExecutionMode>('safe');
  const [profile, setProfile] = React.useState<MatrixExecutionProfile>('standard');
  const [confirmedFingerprint, setConfirmedFingerprint] = React.useState<string | null>(null);
  const [drawerOpen, setDrawerOpen] = React.useState(false);
  const [activeGroupId, setActiveGroupId] = React.useState('all');
  const [query, setQuery] = React.useState('');
  const [density, setDensity] = React.useState<MatrixDensity>('balanced');
  const [selectedIds, setSelectedIds] = React.useState<Set<string>>(() => new Set());
  const [focusedId, setFocusedId] = React.useState<string>();
  const [visibleIds, setVisibleIds] = React.useState<Set<string>>(() => new Set());
  const [dispatching, setDispatching] = React.useState(false);
  const [stopping, setStopping] = React.useState(false);
  const [refreshing, setRefreshing] = React.useState(false);
  const [actionDeviceId, setActionDeviceId] = React.useState<string>();
  const [actionResult, setActionResult] = React.useState('');
  const [pendingScreenRefresh, setPendingScreenRefresh] = React.useState<{
    deviceId: string;
    deviceName: string;
    generation: number;
  }>();
  const [navigationTarget, setNavigationTarget] = React.useState<FeatureNavigationContext | null>(null);
  const [navigationResolved, setNavigationResolved] = React.useState(false);
  const [navigationError, setNavigationError] = React.useState<string>();
  const [timeline, setTimeline] = React.useState<MatrixEvent[]>([]);
  const [timelineLoading, setTimelineLoading] = React.useState(false);
  const [controlMode, setControlMode] = React.useState<'ai' | 'manual'>('ai');
  const [lease, setLease] = React.useState<MatrixDeviceLease | null>(null);
  const [leaseBusy, setLeaseBusy] = React.useState(false);
  const [controlBusy, setControlBusy] = React.useState(false);
  const orderRef = React.useRef<string[]>([]);
  const leaseRef = React.useRef<{ deviceId: string; lease: MatrixDeviceLease } | null>(null);
  const focusedIdRef = React.useRef<string>();
  const timelineRequestIdRef = React.useRef(0);
  const leaseRequestIdRef = React.useRef(0);
  const controlQueueRef = React.useRef<Promise<void>>(Promise.resolve());
  const humanHolderIdRef = React.useRef(`launcher-${commandId()}`);
  const latestDispatchJobIdRef = React.useRef('');

  React.useEffect(() => {
    const context = consumeNavigationContext('workbench');
    if (!context) return;
    setNavigationTarget(context);
    setNavigationResolved(false);
    setNavigationError(undefined);
    setFocusedId(undefined);
    setSelectedIds(new Set());
  }, [consumeNavigationContext]);

  const stream = useMatrixStream(true);
  const devices = React.useMemo(() => {
    const result = buildDeviceViews(stream.snapshot, orderRef.current);
    orderRef.current = result.map((device) => device.deviceId);
    return result;
  }, [stream.snapshot]);
  const campaigns = React.useMemo(() => normalizeMatrixCampaigns(stream.snapshot?.campaigns), [stream.snapshot?.campaigns]);
  const groups = React.useMemo(() => {
    const result = buildDeviceGroups(devices);
    const abnormalIds = devices.filter((device) => device.status === 'error' || device.status === 'offline').map((device) => device.deviceId);
    const withoutAbnormal = result.filter((group) => group.id !== 'abnormal');
    return abnormalIds.length ? [...withoutAbnormal, { id: 'abnormal', label: '异常设备', deviceIds: abnormalIds, abnormal: true }] : withoutAbnormal;
  }, [devices]);
  const navigationResolution = React.useMemo(() => (
    navigationTarget
      ? resolveMatrixNavigation(devices, campaigns, groups, navigationTarget)
      : null
  ), [campaigns, devices, groups, navigationTarget]);
  const activeGroup = groups.find((group) => group.id === activeGroupId) || groups[0];
  const wallDevices = React.useMemo(() => visibleDeviceViews(devices, activeGroup, query), [activeGroup, devices, query]);
  const focusedDevice = devices.find((device) => device.deviceId === focusedId);
  const screens = useVisibleScreens(devices, visibleIds, focusedId);

  React.useEffect(() => {
    if (!pendingScreenRefresh) return;
    const resolution = resolveScreenRequestOutcome(
      pendingScreenRefresh.generation,
      screens.outcomes[pendingScreenRefresh.deviceId],
    );
    if (resolution.status === 'pending') return;
    if (resolution.status === 'error') {
      setActionResult(`${pendingScreenRefresh.deviceName}：${resolution.error}`);
      showToast(resolution.error, 'error');
    } else {
      setActionResult(`${pendingScreenRefresh.deviceName}：画面已刷新`);
    }
    setPendingScreenRefresh(undefined);
  }, [pendingScreenRefresh, screens.outcomes]);

  React.useEffect(() => {
    focusedIdRef.current = focusedId;
  }, [focusedId]);

  React.useEffect(() => {
    if (!navigationTarget || !navigationResolution || navigationResolved || stream.loading || !stream.snapshot) return;
    if (navigationResolution.missingDeviceId) {
      const message = `目标设备 ${navigationResolution.missingDeviceId} 当前不在线或未登记，已保留任务定位条件。`;
      setNavigationError(message);
      setActionResult(message);
      setNavigationResolved(true);
      return;
    }
    if (navigationTarget.campaignId && !navigationResolution.campaignFound) {
      setActionResult(`正在等待矩阵任务 ${navigationTarget.campaignId} 出现在本机状态流中...`);
      return;
    }
    if (!navigationResolution.focusedId) {
      const target = navigationTarget.campaignId || navigationTarget.runId || '指定任务';
      const message = `${target} 没有可定位的已登记设备，未切换到其他手机。`;
      setNavigationError(message);
      setActionResult(message);
      setNavigationResolved(true);
      return;
    }
    setSelectedIds(new Set(navigationResolution.selectedIds));
    setFocusedId(navigationResolution.focusedId);
    setActiveGroupId(navigationResolution.groupId);
    setNavigationError(undefined);
    setActionResult(navigationTarget.campaignId
      ? `已定位矩阵任务 ${navigationTarget.campaignId}`
      : `已定位设备 ${navigationResolution.focusedId}`);
    setNavigationResolved(true);
  }, [navigationResolution, navigationResolved, navigationTarget, stream.loading]);

  React.useEffect(() => {
    const knownIds = new Set(devices.map((device) => device.deviceId));
    setSelectedIds((current) => new Set([...current].filter((deviceId) => knownIds.has(deviceId))));
    const suppressFallback = Boolean(navigationTarget && (!navigationResolved || navigationError));
    if ((!focusedId || !knownIds.has(focusedId)) && !suppressFallback) setFocusedId(devices[0]?.deviceId);
  }, [devices, focusedId, navigationError, navigationResolved, navigationTarget]);

  const loadTimeline = React.useCallback(async (deviceId: string) => {
    const requestId = ++timelineRequestIdRef.current;
    setTimelineLoading(true);
    try {
      const result = await matrixApi.timeline(deviceId, 80);
      if (requestId === timelineRequestIdRef.current && focusedIdRef.current === deviceId) {
        setTimeline(result.events || []);
      }
    } catch (reason) {
      if (requestId === timelineRequestIdRef.current && focusedIdRef.current === deviceId) {
        setTimeline([]);
        showToast(parseErrorText(reason) || '设备时间线加载失败', 'error');
      }
    } finally {
      if (requestId === timelineRequestIdRef.current) setTimelineLoading(false);
    }
  }, []);

  React.useEffect(() => {
    if (!focusedId) {
      timelineRequestIdRef.current += 1;
      leaseRequestIdRef.current += 1;
      setTimeline([]);
      setTimelineLoading(false);
      setLease(null);
      return;
    }
    void loadTimeline(focusedId);
    const leaseRequestId = ++leaseRequestIdRef.current;
    void matrixApi.lease(focusedId).then((result) => {
      if (leaseRequestId === leaseRequestIdRef.current && focusedIdRef.current === focusedId) setLease(result.lease);
    }).catch(() => {
      if (leaseRequestId === leaseRequestIdRef.current && focusedIdRef.current === focusedId) setLease(null);
    });
  }, [focusedId, loadTimeline]);

  const releaseCurrentLease = React.useCallback(async () => {
    const current = leaseRef.current;
    leaseRequestIdRef.current += 1;
    leaseRef.current = null;
    setLease(null);
    setControlMode('ai');
    if (!current) return;
    try {
      await matrixApi.releaseLease(current.deviceId, current.lease.leaseId);
    } catch (reason) {
      showToast(parseErrorText(reason) || '人工租约释放失败，将等待租约自动到期', 'error');
    }
  }, []);

  React.useEffect(() => {
    const current = leaseRef.current;
    if (current && current.deviceId !== focusedId) void releaseCurrentLease();
  }, [focusedId, releaseCurrentLease]);

  React.useEffect(() => {
    if (controlMode !== 'manual' || !leaseRef.current) return undefined;
    const timer = window.setInterval(() => {
      const current = leaseRef.current;
      if (!current) return;
      void matrixApi.acquireLease(current.deviceId, {
        holderType: 'human',
        holderId: humanHolderIdRef.current,
        mode: 'control',
        leaseId: current.lease.leaseId,
      }).then((result) => {
        leaseRef.current = { deviceId: current.deviceId, lease: result.lease };
        setLease(result.lease);
      }).catch((reason) => {
        leaseRef.current = null;
        setLease(null);
        setControlMode('ai');
        showToast(parseErrorText(reason) || '人工租约续租失败，控制已停用', 'error');
      });
    }, 10_000);
    return () => window.clearInterval(timer);
  }, [controlMode]);

  React.useEffect(() => {
    const releaseOnExit = () => {
      const current = leaseRef.current;
      if (current) void matrixApi.releaseLease(current.deviceId, current.lease.leaseId).catch(() => undefined);
      leaseRef.current = null;
    };
    window.addEventListener('pagehide', releaseOnExit);
    return () => {
      window.removeEventListener('pagehide', releaseOnExit);
      releaseOnExit();
    };
  }, []);

  const refresh = React.useCallback(async () => {
    setRefreshing(true);
    try {
      await stream.refresh();
      if (focusedId) await loadTimeline(focusedId);
    } catch (reason) {
      showToast(parseErrorText(reason) || '矩阵刷新失败', 'error');
    } finally {
      setRefreshing(false);
    }
  }, [focusedId, loadTimeline, stream]);

  const trackDispatchJob = React.useCallback((jobId: string, campaignLabel: string) => {
    latestDispatchJobIdRef.current = jobId;
    void waitForJob(jobId, {
      timeoutMs: 30 * 60 * 1000,
      intervalMs: 1000,
      onProgress: (job) => {
        if (latestDispatchJobIdRef.current !== jobId) return;
        const message = String(job.progress?.message || job.message || '后台执行中');
        setActionResult(`${campaignLabel}：${message}`);
      },
    }).then(() => {
      if (latestDispatchJobIdRef.current !== jobId) return;
      setActionResult(`${campaignLabel} 执行完成`);
      showToast(`${campaignLabel}执行完成`, 'success');
    }).catch((reason) => {
      if (latestDispatchJobIdRef.current !== jobId) return;
      const message = parseErrorText(reason) || '矩阵任务执行失败，请检查设备连接和任务详情';
      setActionResult(`${campaignLabel} 失败：${message}`);
      showToast(message, 'error');
    }).finally(() => {
      void refresh();
    });
  }, [refresh]);

  const selectGroup = (deviceIds: string[], selected: boolean) => {
    setSelectedIds((current) => {
      const next = new Set(current);
      for (const deviceId of deviceIds) selected ? next.add(deviceId) : next.delete(deviceId);
      return next;
    });
  };

  const toggleSelected = (deviceId: string) => {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (next.has(deviceId)) next.delete(deviceId); else next.add(deviceId);
      return next;
    });
  };

  const selectedOnlineIds = devices.filter((device) => selectedIds.has(device.deviceId) && device.online).map((device) => device.deviceId);
  const dispatchFingerprint = matrixDispatchFingerprint({
    prompt,
    templateId,
    mode,
    profile,
    selectedDeviceIds: selectedOnlineIds,
  });
  const previousDispatchFingerprintRef = React.useRef(dispatchFingerprint);
  React.useEffect(() => {
    if (previousDispatchFingerprintRef.current === dispatchFingerprint) return;
    previousDispatchFingerprintRef.current = dispatchFingerprint;
    setConfirmedFingerprint(null);
  }, [dispatchFingerprint]);
  const confirmed = confirmedFingerprint === dispatchFingerprint;
  const emergencyScope = React.useMemo(
    () => resolveCampaignAtomicEmergencyScope(campaigns, selectedIds),
    [campaigns, selectedIds],
  );

  const dispatchTask = async () => {
    if (!selectedOnlineIds.length) {
      showToast('请选择至少一台在线设备', 'info');
      return;
    }
    const needsConfirmation = mode === 'full' || /发布|评论|私信|支付|删除|批量/.test(prompt);
    if (needsConfirmation && !confirmed) {
      const accepted = await showConfirm({
        title: '确认任务范围',
        message: `任务将作用于 ${selectedOnlineIds.length} 台在线设备，可能包含外部或高风险动作。请确认目标和授权。`,
        confirmText: '确认下发',
        tone: 'danger',
      });
      if (!accepted) return;
      setConfirmedFingerprint(dispatchFingerprint);
    }
    setDispatching(true);
    setActionResult('正在向后端提交任务...');
    try {
      const advanced = { mode, profile, confirmed: needsConfirmation ? true : confirmed };
      const result = await matrixApi.dispatch(templateId.trim()
        ? { prompt: prompt.trim(), templateId: templateId.trim(), target: { deviceIds: selectedOnlineIds }, ...advanced }
        : { prompt: prompt.trim(), target: { deviceIds: selectedOnlineIds }, ...advanced });
      const campaignId = result.campaign?.campaignId || String(result.task?.campaignId || '');
      setConfirmedFingerprint(null);
      const campaignLabel = campaignId ? `任务 ${campaignId}` : '矩阵任务';
      setActionResult(`${campaignLabel} 已提交，等待执行`);
      showToast(`已向 ${selectedOnlineIds.length} 台设备提交任务`, 'success');
      if (result.jobId) {
        trackDispatchJob(result.jobId, campaignLabel);
      }
      void refresh();
    } catch (reason) {
      const message = parseErrorText(reason) || '任务下发失败';
      setActionResult(message);
      showToast(message, 'error');
    } finally {
      setDispatching(false);
    }
  };

  const emergencyStop = async () => {
    if (!emergencyScope.requestDeviceIds.length) return;
    const accepted = await showConfirm({
      title: '确认紧急停止',
      message: `急停按 campaign 原子生效：将停止 ${emergencyScope.campaignIds.length} 个 campaign 内 ${emergencyScope.affectedTaskCount} 个活动任务，涉及 ${emergencyScope.affectedDeviceIds.length} 台设备。已完成的外部动作无法撤回。`,
      confirmText: '立即急停',
      tone: 'danger',
    });
    if (!accepted) return;
    setStopping(true);
    setActionResult('急停请求处理中...');
    try {
      const result = await matrixApi.emergencyStop({ deviceIds: emergencyScope.requestDeviceIds });
      const message = result.cancelled
        ? `急停完成：${result.affectedTaskCount} 个任务，${result.affectedDeviceCount} 台设备`
        : '急停完成：作用范围内没有可停止任务';
      setActionResult(message);
      showToast(message, result.cancelled ? 'success' : 'info');
      void refresh();
    } catch (reason) {
      const message = parseErrorText(reason) || '急停失败';
      setActionResult(message);
      showToast(message, 'error');
    } finally {
      setStopping(false);
    }
  };

  const performTaskAction = React.useCallback(async (
    device: MatrixDeviceView,
    action: 'pause' | 'resume' | 'cancel' | 'retry',
  ) => {
    if (!device.task) return;
    const supportedActions = supportedMatrixTaskActions(device.task.status);
    if ((action === 'pause' && !supportedActions.pause) || (action === 'resume' && !supportedActions.resume)) {
      showToast(`任务状态 ${device.task.status} 不支持 ${action === 'pause' ? '暂停' : '继续'}`, 'info');
      return;
    }
    if (action === 'retry' && device.task.status !== 'failed') {
      showToast(`任务状态 ${device.task.status} 不支持重试`, 'info');
      return;
    }
    const campaign = campaignForDeviceTask(campaigns, device.task.deviceTaskId);
    if ((action === 'cancel' || action === 'retry') && !campaign) {
      showToast('当前状态未包含任务所属 campaign，刷新后重试', 'error');
      return;
    }
    if (action === 'cancel') {
      const accepted = await showConfirm({
        title: '取消任务',
        message: `后端取消接口按 campaign 生效，将取消 ${campaign!.campaignId} 内仍活动的任务，而不只当前设备。`,
        confirmText: '确认取消 campaign',
        tone: 'danger',
      });
      if (!accepted) return;
    }
    setActionDeviceId(device.deviceId);
    setActionResult(`${device.name || device.deviceId}：${action} 请求处理中...`);
    try {
      if (action === 'pause') await matrixApi.pauseTask(device.task.deviceTaskId);
      if (action === 'resume') await matrixApi.resumeTask(device.task.deviceTaskId);
      if (action === 'cancel') await matrixApi.cancel(campaign!.campaignId);
      if (action === 'retry') await matrixApi.retry({ campaignId: campaign!.campaignId, deviceTaskIds: [device.task.deviceTaskId] });
      const labels = { pause: '已暂停', resume: '已继续', cancel: '已取消', retry: '已提交重试' };
      setActionResult(`${device.name || device.deviceId}：${labels[action]}`);
      showToast(`${device.name || device.deviceId} ${labels[action]}`, 'success');
      await refresh();
    } catch (reason) {
      const message = parseErrorText(reason) || `${action} 操作失败`;
      setActionResult(`${device.name || device.deviceId}：${message}`);
      showToast(message, 'error');
    } finally {
      setActionDeviceId(undefined);
    }
  }, [campaigns, refresh]);

  const changeControlMode = async (nextMode: 'ai' | 'manual') => {
    if (nextMode === 'ai') {
      await releaseCurrentLease();
      return;
    }
    if (!focusedDevice?.online || leaseBusy) return;
    const targetDevice = focusedDevice;
    const targetDeviceId = targetDevice.deviceId;
    setLeaseBusy(true);
    try {
      const current = await matrixApi.lease(targetDeviceId);
      if (focusedIdRef.current !== targetDeviceId) return;
      if (current.lease?.holderType === 'human' && current.lease.holderId !== humanHolderIdRef.current) {
        throw new Error(`设备正由 ${current.lease.holderId} 人工控制，租约到期时间 ${current.lease.expiresAt}`);
      }
      if (current.lease?.holderType === 'agent') {
        const taskActions = targetDevice.task ? supportedMatrixTaskActions(targetDevice.task.status) : null;
        if (!targetDevice.task || !taskActions?.pause) {
          throw new Error('当前 Agent 任务阶段不支持安全暂停，暂时不能人工接管');
        }
        const accepted = await showConfirm({
          title: '暂停 Agent 并接管',
          message: `${focusedDevice.name || focusedDevice.deviceId} 当前由 Agent 控制。将先暂停当前设备任务，再申请人工租约。`,
          confirmText: '暂停并接管',
          tone: 'danger',
        });
        if (!accepted) return;
        if (focusedIdRef.current !== targetDeviceId) return;
        await matrixApi.pauseTask(targetDevice.task.deviceTaskId);
      }
      const acquired = await matrixApi.acquireLease(targetDeviceId, {
        holderType: 'human',
        holderId: humanHolderIdRef.current,
        mode: 'control',
        leaseId: current.lease?.holderId === humanHolderIdRef.current ? current.lease.leaseId : undefined,
      });
      if (focusedIdRef.current !== targetDeviceId) {
        await matrixApi.releaseLease(targetDeviceId, acquired.lease.leaseId).catch(() => undefined);
        return;
      }
      leaseRef.current = { deviceId: targetDeviceId, lease: acquired.lease };
      setLease(acquired.lease);
      setControlMode('manual');
      setActionResult(`${targetDevice.name || targetDeviceId}：人工接管已生效`);
    } catch (reason) {
      const message = parseErrorText(reason) || '人工接管失败';
      setLease(null);
      setControlMode('ai');
      showToast(message, 'error');
    } finally {
      setLeaseBusy(false);
    }
  };

  const sendControl = (action: MatrixManualAction) => {
    if (action.action === 'screenshot') {
      if (!focusedDevice) return;
      const deviceName = focusedDevice.name || focusedDevice.deviceId;
      const generation = screens.requestNow(focusedDevice.deviceId);
      setPendingScreenRefresh({ deviceId: focusedDevice.deviceId, deviceName, generation });
      setActionResult(`${deviceName}：正在刷新画面`);
      return;
    }
    const current = leaseRef.current;
    if (!focusedDevice || !current || current.deviceId !== focusedDevice.deviceId) {
      showToast('没有当前设备的有效人工租约', 'error');
      return;
    }
    const deviceId = focusedDevice.deviceId;
    const request = { ...action, leaseId: current.lease.leaseId, clientCommandId: commandId() } as MatrixControlRequest;
    controlQueueRef.current = controlQueueRef.current.then(async () => {
      setControlBusy(true);
      try {
        const result = await matrixApi.control(deviceId, request);
        if (result.status === 'failed') {
          const message = result.error || result.code || '人工控制失败';
          setActionResult(`${focusedDevice.name || deviceId}：${message}`);
          showToast(message, 'error');
          await loadTimeline(deviceId);
          return;
        }
        setActionResult(`${focusedDevice.name || deviceId}：${action.action} ${result.status}`);
        await loadTimeline(deviceId);
      } catch (reason) {
        const message = parseErrorText(reason) || '人工控制失败';
        setActionResult(`${focusedDevice.name || deviceId}：${message}`);
        showToast(message, 'error');
      } finally {
        setControlBusy(false);
      }
    });
  };

  return (
    <div data-white-label-layout="phone-matrix" className="loom-matrix-shell relative flex min-h-0 flex-1 flex-col overflow-hidden bg-[#07131B] text-slate-100">
      <header className="flex shrink-0 items-center justify-between gap-4 border-b border-white/[0.08] bg-[#091722] px-3 py-2">
        <div className="min-w-0"><div className="text-[9px] font-black tracking-[0.2em] text-cyan-200/60">LOOM CONTROL PLANE</div><h1 className="truncate text-[17px] font-black text-white">超级矩阵工作台</h1></div>
        <div className="flex items-center gap-3">
          {stream.error ? <span className="max-w-[220px] truncate text-[10px] text-rose-200">{stream.error}</span> : stream.loading ? <span className="text-[10px] font-bold text-slate-300">正在加载矩阵状态</span> : stream.reconnecting ? <span className="text-[10px] font-bold text-amber-200">实时流正在重连</span> : stream.connected ? <span className="text-[10px] font-bold text-emerald-200">实时状态已连接</span> : <span className="text-[10px] font-bold text-slate-400">实时状态未连接</span>}
          <MatrixMetrics devices={devices} />
        </div>
      </header>

      <MatrixCommandBar
        prompt={prompt}
        selectedCount={selectedOnlineIds.length}
        dispatching={dispatching}
        stopping={stopping}
        canStop={emergencyScope.affectedTaskCount > 0}
        result={actionResult}
        onPromptChange={setPrompt}
        onDispatch={() => void dispatchTask()}
        onEmergencyStop={() => void emergencyStop()}
        onOpenAdvanced={() => setDrawerOpen(true)}
      />

      <main className="loom-matrix-layout grid min-h-0 flex-1 grid-cols-[132px_minmax(320px,1fr)_300px] overflow-hidden">
        <DeviceGroupRail
          groups={groups}
          activeGroupId={activeGroupId}
          selectedIds={selectedIds}
          searchResultCount={wallDevices.length}
          onGroupChange={setActiveGroupId}
          onSelectGroup={selectGroup}
        />
        <PhoneWall
          devices={wallDevices}
          frames={screens.frames}
          screenErrors={screens.errors}
          focusedId={focusedId}
          selectedIds={selectedIds}
          density={density}
          query={query}
          loading={stream.loading}
          refreshing={refreshing || stream.loading}
          actionDeviceId={actionDeviceId}
          onDensityChange={setDensity}
          onQueryChange={setQuery}
          onRefresh={() => void refresh()}
          onFocus={(deviceId) => {
            setFocusedId(deviceId);
            setNavigationError(undefined);
            setNavigationTarget(null);
          }}
          onToggleSelected={toggleSelected}
          onVisibleChange={setVisibleIds}
          onTaskAction={(device, action) => void performTaskAction(device, action)}
        />
        <DeviceInspector
          device={focusedDevice}
          frame={focusedId ? screens.frames[focusedId] : undefined}
          screenError={focusedId ? screens.errors[focusedId] : undefined}
          timeline={timeline}
          timelineLoading={timelineLoading}
          mode={controlMode}
          lease={lease}
          leaseBusy={leaseBusy}
          controlBusy={controlBusy}
          taskActionBusy={actionDeviceId === focusedId}
          actionResult={actionResult}
          onModeChange={(nextMode) => void changeControlMode(nextMode)}
          onControl={sendControl}
          onScreenRetry={() => { if (focusedId) screens.requestNow(focusedId); }}
          onTaskAction={(action) => { if (focusedDevice) void performTaskAction(focusedDevice, action); }}
          onSelect={() => { if (focusedId) setSelectedIds((current) => new Set(current).add(focusedId)); }}
        />
      </main>

      <MatrixTaskDrawer
        open={drawerOpen}
        templateId={templateId}
        mode={mode}
        profile={profile}
        confirmed={confirmed}
        campaigns={campaigns}
        onTemplateIdChange={setTemplateId}
        onModeChange={setMode}
        onProfileChange={setProfile}
        onConfirmedChange={(checked) => setConfirmedFingerprint(checked ? dispatchFingerprint : null)}
        onClose={() => setDrawerOpen(false)}
      />
    </div>
  );
};
