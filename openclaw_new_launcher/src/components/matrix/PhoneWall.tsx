import React from 'react';

import { Button } from '../common';
import type { MatrixScreenFrame } from './screenScheduler';
import type { MatrixDensity, MatrixDeviceView } from './matrixViewModel';
import { PhoneTile } from './PhoneTile';

interface PhoneWallProps {
  devices: MatrixDeviceView[];
  frames: Readonly<Record<string, MatrixScreenFrame>>;
  screenErrors: Readonly<Record<string, string>>;
  focusedId?: string;
  selectedIds: ReadonlySet<string>;
  density: MatrixDensity;
  query: string;
  loading: boolean;
  refreshing: boolean;
  actionDeviceId?: string;
  onDensityChange: (density: MatrixDensity) => void;
  onQueryChange: (query: string) => void;
  onRefresh: () => void;
  onFocus: (deviceId: string) => void;
  onToggleSelected: (deviceId: string) => void;
  onVisibleChange: (deviceIds: Set<string>) => void;
  onTaskAction: (device: MatrixDeviceView, action: 'pause' | 'resume' | 'retry') => void;
}

const DENSITY_LABELS: Array<[MatrixDensity, string]> = [
  ['compact', '紧凑'],
  ['balanced', '标准'],
  ['comfortable', '宽松'],
];

export const PhoneWall: React.FC<PhoneWallProps> = ({
  devices,
  frames,
  screenErrors,
  focusedId,
  selectedIds,
  density,
  query,
  loading,
  refreshing,
  actionDeviceId,
  onDensityChange,
  onQueryChange,
  onRefresh,
  onFocus,
  onToggleSelected,
  onVisibleChange,
  onTaskAction,
}) => {
  const scrollRef = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    const root = scrollRef.current;
    if (!root) return undefined;
    const visible = new Set<string>();
    const observer = new IntersectionObserver((entries) => {
      for (const entry of entries) {
        const deviceId = (entry.target as HTMLElement).dataset.screenDevice;
        if (!deviceId) continue;
        if (entry.isIntersecting) visible.add(deviceId);
        else visible.delete(deviceId);
      }
      onVisibleChange(new Set(visible));
    }, { root, rootMargin: '160px 0px', threshold: 0.01 });
    root.querySelectorAll<HTMLElement>('[data-screen-device]').forEach((node) => observer.observe(node));
    return () => observer.disconnect();
  }, [density, devices, onVisibleChange]);

  const gridClass = density === 'compact'
    ? 'grid-cols-[repeat(auto-fill,minmax(112px,1fr))]'
    : density === 'comfortable'
      ? 'grid-cols-[repeat(auto-fill,minmax(190px,1fr))]'
      : 'grid-cols-[repeat(auto-fill,minmax(148px,1fr))]';

  return (
    <section data-matrix-phone-wall className="flex min-h-0 min-w-0 flex-1 flex-col bg-[#07131B]">
      <div className="flex shrink-0 items-center gap-2 border-b border-white/[0.08] px-3 py-2">
        <input
          type="search"
          value={query}
          onChange={(event) => onQueryChange(event.target.value)}
          placeholder="搜索设备、账号、应用"
          className="min-w-0 flex-1 rounded-[6px] border border-white/10 bg-[#06131C] px-3 py-1.5 text-[11px] text-slate-100 outline-none focus:border-cyan-300/40"
        />
        <div className="flex rounded-[6px] border border-white/10 p-0.5">
          {DENSITY_LABELS.map(([value, label]) => (
            <button
              key={value}
              type="button"
              onClick={() => onDensityChange(value)}
              className={`px-2 py-1 text-[9px] font-bold ${density === value ? 'rounded-[4px] bg-cyan-300/15 text-cyan-100' : 'text-slate-500'}`}
            >
              {label}
            </button>
          ))}
        </div>
        <Button variant="quiet" onClick={onRefresh} disabled={refreshing} className="!rounded-[6px] !px-2.5 !py-1.5 !text-[10px]">
          {refreshing ? '刷新中' : '刷新'}
        </Button>
      </div>
      <div ref={scrollRef} className="min-h-0 flex-1 overflow-auto p-3">
        {loading ? (
          <div className="flex h-full min-h-[240px] items-center justify-center text-center text-xs text-slate-400">
            <div><div className="font-bold text-slate-200">正在加载矩阵设备</div><div className="mt-1">正在同步设备与任务状态</div></div>
          </div>
        ) : devices.length ? (
          <div className={`grid items-start gap-2 ${gridClass}`}>
            {devices.map((device) => (
              <PhoneTile
                key={device.deviceId}
                device={device}
                density={density}
                frame={frames[device.deviceId]}
                screenError={screenErrors[device.deviceId]}
                focused={focusedId === device.deviceId}
                selected={selectedIds.has(device.deviceId)}
                actionPending={actionDeviceId === device.deviceId}
                onFocus={() => onFocus(device.deviceId)}
                onToggleSelected={() => onToggleSelected(device.deviceId)}
                onTaskAction={(action) => onTaskAction(device, action)}
              />
            ))}
          </div>
        ) : (
          <div className="flex h-full min-h-[240px] items-center justify-center border border-dashed border-white/10 text-center text-xs text-slate-500">
            <div><div className="font-bold text-slate-300">没有匹配的真实设备</div><div className="mt-1">调整分组或搜索条件</div></div>
          </div>
        )}
      </div>
    </section>
  );
};
