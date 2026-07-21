import React from 'react';

import type { MatrixDeviceLease, MatrixEvent } from '../../types/matrix';
import { Button } from '../common';
import { DeviceTimeline } from './DeviceTimeline';
import { FocusScreen } from './FocusScreen';
import { ManualControls, type MatrixManualAction } from './ManualControls';
import type { MatrixScreenFrame } from './screenScheduler';
import { canUseMatrixManualControls, supportedMatrixTaskActions, type MatrixDeviceView } from './matrixViewModel';

interface DeviceInspectorProps {
  device?: MatrixDeviceView;
  frame?: MatrixScreenFrame;
  screenError?: string;
  timeline: MatrixEvent[];
  timelineLoading: boolean;
  mode: 'ai' | 'manual';
  lease: MatrixDeviceLease | null;
  leaseBusy: boolean;
  controlBusy: boolean;
  taskActionBusy: boolean;
  actionResult: string;
  onModeChange: (mode: 'ai' | 'manual') => void;
  onControl: (action: MatrixManualAction) => void;
  onScreenRetry: () => void;
  onTaskAction: (action: 'pause' | 'resume' | 'cancel' | 'retry') => void;
  onSelect: () => void;
}

export const DeviceInspector: React.FC<DeviceInspectorProps> = ({
  device,
  frame,
  screenError,
  timeline,
  timelineLoading,
  mode,
  lease,
  leaseBusy,
  controlBusy,
  taskActionBusy,
  actionResult,
  onModeChange,
  onControl,
  onScreenRetry,
  onTaskAction,
  onSelect,
}) => {
  if (!device) {
    return <aside data-matrix-device-inspector className="flex min-h-0 items-center justify-center border-l border-white/[0.08] bg-[#081620] p-5 text-center text-xs text-slate-500">选择一台设备查看聚焦画面</aside>;
  }
  const manualEnabled = mode === 'manual' && lease?.deviceId === device.deviceId;
  const controlsEnabled = canUseMatrixManualControls({
    mode,
    leasedDeviceId: lease?.deviceId,
    deviceId: device.deviceId,
    hasFrame: Boolean(frame),
    screenError,
  });
  const supportedActions = device.task ? supportedMatrixTaskActions(device.task.status) : { pause: false, resume: false };
  const retryable = device.task?.status === 'failed';
  const cancellable = Boolean(device.task && ['queued', 'preflight', 'running', 'retrying', 'paused'].includes(device.task.status));

  return (
    <aside data-matrix-device-inspector data-device-id={device.deviceId} className="min-h-0 overflow-auto border-l border-white/[0.08] bg-[#081620]">
      <div className="sticky top-0 z-10 border-b border-white/[0.08] bg-[#081620] p-2.5">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <div className="truncate font-mono text-xs font-black text-white">{device.name || device.deviceId}</div>
            <div className="mt-0.5 truncate text-[9px] text-slate-500">{device.deviceId} · {device.status}</div>
          </div>
          <div className="flex rounded-[5px] border border-white/10 p-0.5">
            <button type="button" disabled={leaseBusy} onClick={() => onModeChange('ai')} className={`px-2 py-1 text-[9px] font-bold ${mode === 'ai' ? 'rounded-[3px] bg-white/10 text-white' : 'text-slate-500'}`}>AI</button>
            <button type="button" disabled={leaseBusy || !device.online} onClick={() => onModeChange('manual')} className={`px-2 py-1 text-[9px] font-bold ${mode === 'manual' ? 'rounded-[3px] bg-cyan-300/15 text-cyan-100' : 'text-slate-500'}`}>{leaseBusy ? '接管中' : '人工'}</button>
          </div>
        </div>
        {mode === 'manual' && !manualEnabled ? <div className="mt-1.5 text-[9px] text-amber-200">等待有效人工租约，控制命令保持禁用</div> : null}
      </div>

      <div className="p-3">
        <FocusScreen
          deviceName={device.name || device.deviceId}
          frame={frame}
          error={screenError}
          manualEnabled={manualEnabled}
          controlsEnabled={controlsEnabled}
          onSelect={onSelect}
          onRetry={onScreenRetry}
          onAction={onControl}
        />
      </div>

      <div className="grid grid-cols-2 gap-x-3 gap-y-1 border-t border-white/[0.08] px-3 py-2 text-[9px]">
        <span className="text-slate-600">前台应用</span><span className="truncate text-right text-slate-300">{device.foregroundApp || device.currentPackage || '-'}</span>
        <span className="text-slate-600">无障碍</span><span className="text-right text-slate-300">{device.accessibilityRunning == null ? '-' : device.accessibilityRunning ? '正常' : '断开'}</span>
        <span className="text-slate-600">屏幕</span><span className="text-right text-slate-300">{device.screenOn == null ? '-' : device.screenOn ? '亮屏' : '熄屏'}</span>
        <span className="text-slate-600">流延迟</span><span className="text-right text-slate-300">{device.streamLatencyMs == null ? '-' : `${device.streamLatencyMs} ms`}</span>
        <span className="text-slate-600">任务</span><span className="truncate text-right text-slate-300">{device.task?.deviceTaskId || '-'}</span>
        <span className="text-slate-600">租约</span><span className="truncate text-right text-slate-300">{lease ? `${lease.holderType} / ${lease.expiresAt.slice(11, 19)}` : '无'}</span>
      </div>

      {device.task ? (
        <div className="border-t border-white/[0.08] p-2.5">
          <div className="mb-2 truncate text-[10px] font-bold text-slate-300">{device.taskLabel}</div>
          {device.task.failureReason ? (
            <div data-matrix-task-failure className="mb-2 rounded-[6px] border border-rose-300/20 bg-rose-300/10 px-2 py-1.5 text-[9px] leading-4 text-rose-100">
              <span className="font-black">{device.task.failureCode || '任务失败'}</span>：{device.task.failureReason}
            </div>
          ) : null}
          <div className="flex flex-wrap gap-1">
            {supportedActions.pause ? <Button variant="quiet" disabled={taskActionBusy} onClick={() => onTaskAction('pause')} className="!min-w-[48px] !rounded-[5px] !px-2 !py-1 !text-[9px]">暂停</Button> : null}
            {supportedActions.resume ? <Button variant="quiet" disabled={taskActionBusy} onClick={() => onTaskAction('resume')} className="!min-w-[48px] !rounded-[5px] !px-2 !py-1 !text-[9px]">继续</Button> : null}
            {retryable ? <Button variant="quiet" disabled={taskActionBusy} onClick={() => onTaskAction('retry')} className="!min-w-[48px] !rounded-[5px] !px-2 !py-1 !text-[9px]">重试</Button> : null}
            {cancellable ? <Button variant="danger" disabled={taskActionBusy} onClick={() => onTaskAction('cancel')} className="!min-w-[48px] !rounded-[5px] !px-2 !py-1 !text-[9px]">取消</Button> : null}
          </div>
          {actionResult ? <div className="mt-2 text-[9px] text-cyan-100">{actionResult}</div> : null}
        </div>
      ) : null}

      <ManualControls
        enabled={controlsEnabled}
        busy={controlBusy}
        disabledMessage={manualEnabled && screenError ? '画面刷新成功前，触控和系统命令保持禁用' : undefined}
        onAction={onControl}
      />
      <DeviceTimeline events={timeline} loading={timelineLoading} />
    </aside>
  );
};
