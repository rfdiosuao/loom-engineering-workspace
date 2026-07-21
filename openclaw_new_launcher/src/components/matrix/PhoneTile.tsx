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
  online_idle: 'border-emerald-300/20 bg-emerald-300/8 text-emerald-100',
  running: 'border-cyan-300/35 bg-cyan-300/10 text-cyan-100',
  waiting: 'border-amber-300/30 bg-amber-300/10 text-amber-100',
  error: 'border-rose-300/45 bg-rose-300/12 text-rose-100',
  offline: 'border-white/10 bg-white/[0.025] text-slate-400',
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
      className={`relative min-w-0 overflow-hidden rounded-[7px] border transition ${STATUS_TONES[device.status]} ${focused ? 'ring-2 ring-cyan-300/50' : ''}`}
    >
      <button type="button" onClick={onFocus} className="block w-full text-left" title={`聚焦 ${device.name || device.deviceId}`}>
        <div className={`relative overflow-hidden bg-[#02080D] ${compact ? 'aspect-[9/12]' : 'aspect-[9/14]'}`}>
          {frame ? (
            <img src={frame.url} alt={`${device.name || device.deviceId} 实时画面`} className="h-full w-full object-cover object-top" draggable={false} />
          ) : (
            <div className="flex h-full items-center justify-center px-2 text-center text-[10px] text-slate-600">{screenError || (device.status === 'offline' ? '设备离线' : '等待真实画面')}</div>
          )}
          {screenError && frame ? <div data-matrix-screen-error className="absolute inset-x-0 top-0 bg-rose-700/95 px-2 py-1 text-[9px] font-bold text-white">{screenError}</div> : null}
          {!screenError && device.status === 'error' ? <div className="absolute inset-x-0 top-0 bg-rose-600/90 px-2 py-1 text-[9px] font-black text-white">设备异常</div> : null}
          <div className="absolute inset-x-0 bottom-0 bg-black/75 px-2 py-1 text-[9px] text-slate-300">画面 {frameTime(frame?.capturedAt || device.lastScreenAt)}</div>
        </div>
        <div className="p-2">
          <div className="flex items-start justify-between gap-1.5">
            <div className="min-w-0">
              <div className="truncate font-mono text-[11px] font-black text-white">{device.name || device.deviceId}</div>
              {!compact ? <div className="mt-0.5 truncate text-[9px] text-slate-400">{device.model || device.platform || device.deviceId}</div> : null}
            </div>
            <span className="shrink-0 text-[9px] font-bold">{STATUS_LABELS[device.status]}</span>
          </div>
          {!compact ? (
            <>
              <div className="mt-1.5 truncate text-[10px] font-semibold text-slate-200">{device.taskLabel}</div>
              <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-white/10">
                <div className={`h-full ${device.status === 'error' ? 'bg-rose-300' : 'bg-cyan-300'}`} style={{ width: `${device.progressValue}%` }} />
              </div>
            </>
          ) : null}
        </div>
      </button>
      <div className="flex items-center justify-between border-t border-white/[0.07] px-2 py-1.5">
        <label className="flex cursor-pointer items-center gap-1 text-[9px] text-slate-400">
          <input type="checkbox" checked={selected} onChange={onToggleSelected} /> 任务目标
        </label>
        {canAct && !compact ? (
          <button type="button" disabled={actionPending} onClick={() => onTaskAction(taskAction)} className="text-[9px] font-bold text-cyan-100 disabled:text-slate-600">
            {actionPending ? '处理中' : taskActionLabel}
          </button>
        ) : null}
      </div>
    </article>
  );
};
