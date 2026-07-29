import React from 'react';

import type { MatrixScreenFrame } from './screenScheduler';
import { supportedMatrixTaskActions, type MatrixDensity, type MatrixDeviceView } from './matrixViewModel';

interface PhoneTileProps {
  device: MatrixDeviceView;
  density: MatrixDensity;
  frame?: MatrixScreenFrame;
  screenError?: string;
  focused: boolean;
  selected: boolean;
  actionPending: boolean;
  onFocus: () => void;
  onToggleSelected: () => void;
  onTaskAction: (action: 'pause' | 'resume' | 'retry') => void;
}

const STATUS_LABELS = {
  online_idle: '在线空闲',
  running: '运行中',
  waiting: '等待中',
  error: '异常',
  offline: '离线',
};

const STATUS_TONES = {
  online_idle: 'border-status-success bg-status-success-soft text-status-success-ink',
  running: 'border-info bg-info-soft text-info-ink',
  waiting: 'border-status-warning bg-status-warning-soft text-status-warning-ink',
  error: 'border-status-danger bg-status-danger-soft text-status-danger-ink',
  offline: 'border-border bg-disabled text-disabled',
};

function frameTime(value?: string): string {
  if (!value) return '暂无画面';
  const parsed = new Date(value);
  return Number.isNaN(parsed.valueOf()) ? value : parsed.toLocaleTimeString('zh-CN', { hour12: false });
}

export const PhoneTile: React.FC<PhoneTileProps> = ({
  device,
  density,
  frame,
  screenError,
  focused,
  selected,
  actionPending,
  onFocus,
  onToggleSelected,
  onTaskAction,
}) => {
  const compact = density === 'compact';
  const supportedActions = device.task ? supportedMatrixTaskActions(device.task.status) : { pause: false, resume: false };
  const taskAction = supportedActions.resume ? 'resume' : device.task?.status === 'failed' ? 'retry' : 'pause';
  const taskActionLabel = taskAction === 'resume' ? '继续' : taskAction === 'retry' ? '重试' : '暂停';
  const canAct = supportedActions.pause || supportedActions.resume || device.task?.status === 'failed';

  return (
    <article
      data-screen-device={device.deviceId}
      className={`relative min-w-0 overflow-hidden rounded-[7px] border transition ${STATUS_TONES[device.status]} ${(focused || selected) ? 'ring-2 ring-focus' : ''}`}
    >
      <button type="button" onClick={onFocus} className="block w-full text-left" title={`聚焦 ${device.name || device.deviceId}`}>
        <div className={`relative overflow-hidden bg-surface-deeper ${compact ? 'aspect-[9/12]' : 'aspect-[9/14]'}`}>
          {frame ? (
            <img src={frame.url} alt={`${device.name || device.deviceId} 实时画面`} className="h-full w-full object-cover object-top" draggable={false} />
          ) : (
            <div className="flex h-full items-center justify-center px-2 text-center text-[10px] text-white/45">{screenError || (device.status === 'offline' ? '设备离线' : '等待真实画面')}</div>
          )}
          {screenError && frame ? <div data-matrix-screen-error className="absolute inset-x-0 top-0 bg-status-danger px-2 py-1 text-[9px] font-bold text-white" role="alert">{screenError}</div> : null}
          {!screenError && device.status === 'error' ? <div className="absolute inset-x-0 top-0 bg-status-danger px-2 py-1 text-[9px] font-black text-white">设备异常</div> : null}
          <div className="absolute inset-x-0 bottom-0 bg-overlay px-2 py-1 text-[9px] text-white/75">画面 {frameTime(frame?.capturedAt || device.lastScreenAt)}</div>
        </div>
        <div className="p-2">
          <div className="flex items-start justify-between gap-1.5">
            <div className="min-w-0">
              <div className="truncate font-mono text-[11px] font-black text-current">{device.name || device.deviceId}</div>
              {!compact ? <div className="mt-0.5 truncate text-[9px] opacity-70">{device.model || device.platform || device.deviceId}</div> : null}
            </div>
            <span className="shrink-0 text-[9px] font-bold">{STATUS_LABELS[device.status]}</span>
          </div>
          {!compact ? (
            <>
              <div className="mt-1.5 truncate text-[10px] font-semibold text-current">{device.taskLabel}</div>
              <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-disabled">
                <div className={`h-full ${device.status === 'error' ? 'bg-status-danger' : 'bg-info'}`} style={{ width: `${device.progressValue}%` }} />
              </div>
            </>
          ) : null}
        </div>
      </button>
      <div className="flex items-center justify-between border-t border-current/15 px-2 py-1.5">
        <label className="flex cursor-pointer items-center gap-1 text-[9px] opacity-75">
          <input type="checkbox" checked={selected} onChange={onToggleSelected} /> 任务目标
        </label>
        {canAct && !compact ? (
          <button type="button" disabled={actionPending} onClick={() => onTaskAction(taskAction)} className="text-[9px] font-bold text-info disabled:text-disabled">
            {actionPending ? '处理中' : taskActionLabel}
          </button>
        ) : null}
      </div>
    </article>
  );
};
