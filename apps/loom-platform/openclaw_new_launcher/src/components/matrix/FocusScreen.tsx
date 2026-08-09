import React from 'react';

import type { MatrixScreenFrame } from './screenScheduler';
import type { MatrixManualAction } from './ManualControls';
import { normalizeObjectContainPoint } from './matrixViewModel';
import type { PhoneVideoStreamView } from './usePhoneVideoStream';

interface FocusScreenProps {
  deviceName: string;
  frame?: MatrixScreenFrame;
  video?: PhoneVideoStreamView;
  manualEnabled: boolean;
  controlsEnabled: boolean;
  error?: string;
  onSelect: () => void;
  onRetry: () => void;
  onAction: (action: MatrixManualAction) => void;
}

interface PointerStart {
  x: number;
  y: number;
  at: number;
}

function normalizedPoint(
  event: React.PointerEvent<HTMLDivElement>,
  frame?: MatrixScreenFrame,
  video?: PhoneVideoStreamView,
) {
  const media = video?.status === 'active' && video.width > 0 && video.height > 0
    ? { width: video.width, height: video.height }
    : frame;
  if (!media) return null;
  const bounds = event.currentTarget.getBoundingClientRect();
  return normalizeObjectContainPoint(
    { left: bounds.left, top: bounds.top, width: bounds.width, height: bounds.height },
    { width: media.width, height: media.height },
    { x: event.clientX, y: event.clientY },
  );
}

export const FocusScreen: React.FC<FocusScreenProps> = ({
  deviceName,
  frame,
  video,
  manualEnabled,
  controlsEnabled,
  error,
  onSelect,
  onRetry,
  onAction,
}) => {
  const pointerStart = React.useRef<PointerStart | null>(null);
  const stopOverlayPointer = (event: React.PointerEvent<HTMLElement>) => {
    pointerStart.current = null;
    event.stopPropagation();
  };

  return (
    <div
      data-matrix-focus-screen
      data-phone-actions-enabled={controlsEnabled ? 'true' : 'false'}
      className={`relative mx-auto aspect-[9/19.5] w-full max-w-[222px] touch-none overflow-hidden rounded-[8px] border bg-surface-deeper ${controlsEnabled ? 'cursor-crosshair border-info' : 'cursor-default border-border-strong'}`}
      onPointerDown={(event) => {
        onSelect();
        if (!controlsEnabled) return;
        const point = normalizedPoint(event, frame, video);
        if (!point) return;
        event.currentTarget.setPointerCapture(event.pointerId);
        pointerStart.current = { ...point, at: Date.now() };
      }}
      onPointerUp={(event) => {
        if (!controlsEnabled || !pointerStart.current) return;
        const start = pointerStart.current;
        const end = normalizedPoint(event, frame, video);
        pointerStart.current = null;
        if (!end) return;
        const distance = Math.hypot(end.x - start.x, end.y - start.y);
        if (distance < 0.025) onAction({ action: 'tap', x: end.x, y: end.y });
        else onAction({ action: 'swipe', x: start.x, y: start.y, endX: end.x, endY: end.y, durationMs: Math.max(120, Date.now() - start.at) });
      }}
      onPointerCancel={() => { pointerStart.current = null; }}
    >
      {video?.status === 'active' ? (
        <canvas ref={video.canvasRef} aria-label={`${deviceName} 低延迟画面`} className="h-full w-full select-none object-contain" />
      ) : frame ? (
        <img src={frame.url} alt={`${deviceName} 聚焦画面`} draggable={false} className="h-full w-full select-none object-contain" />
      ) : (
        <div className="flex h-full items-center justify-center px-5 text-center text-[11px] text-white/55" role="status">等待设备返回聚焦画面</div>
      )}
      {error && !frame ? (
        <div
          data-matrix-screen-error
          role="alert"
          onPointerDown={stopOverlayPointer}
          onPointerUp={stopOverlayPointer}
          className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-2 bg-black/80 px-4 text-center"
        >
          <span className="text-[10px] leading-4 text-status-danger-ink">{error}</span>
          <button
            type="button"
            onClick={onRetry}
            className="rounded-[5px] border border-status-danger bg-status-danger-soft px-2.5 py-1 text-[9px] font-bold text-status-danger-ink hover:brightness-95"
          >
            重试画面
          </button>
        </div>
      ) : null}
      {error && frame ? (
        <div className="pointer-events-none absolute inset-x-1 bottom-1 z-20 flex items-center justify-between gap-2 rounded-[5px] bg-status-warning-soft px-2 py-1 text-[9px] text-status-warning-ink" role="status">
          <span className="min-w-0 truncate">画面刷新较慢，暂时显示上一帧</span>
          <button
            type="button"
            onPointerDown={stopOverlayPointer}
            onPointerUp={stopOverlayPointer}
            onClick={onRetry}
            className="pointer-events-auto shrink-0 font-bold text-info"
          >
            重试
          </button>
        </div>
      ) : null}
      {video && video.status !== 'idle' ? (
        <div
          data-phone-video-state={video.status}
          className={`pointer-events-none absolute inset-x-1 bottom-1 z-20 truncate rounded-[5px] px-2 py-1 text-[9px] ${video.status === 'active' ? 'bg-status-success-soft text-status-success-ink' : 'bg-status-warning-soft text-status-warning-ink'}`}
          role="status"
        >
          {video.message || (video.status === 'active' ? '低延迟视频已连接' : '当前使用截图画面')}
        </div>
      ) : null}
      <div
        data-matrix-focus-status
        onPointerDown={stopOverlayPointer}
        onPointerUp={stopOverlayPointer}
        className="absolute inset-x-0 top-0 z-20 flex items-center justify-between bg-overlay px-2 py-1 text-[9px] text-white/75"
      >
        <span className="truncate">{deviceName}</span>
        <span>{manualEnabled ? '人工控制' : 'AI 观察'}</span>
      </div>
    </div>
  );
};
