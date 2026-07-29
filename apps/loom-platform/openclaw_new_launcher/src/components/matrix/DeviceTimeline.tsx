import React from 'react';

import type { MatrixEvent } from '../../types/matrix';

interface DeviceTimelineProps {
  events: MatrixEvent[];
  loading: boolean;
}

function eventTime(value?: string): string {
  if (!value) return '--:--:--';
  return value.slice(11, 19) || value;
}

export const DeviceTimeline: React.FC<DeviceTimelineProps> = ({ events, loading }) => (
  <section data-matrix-device-timeline className="min-h-[120px] border-t border-border p-2.5">
    <div className="mb-2 flex items-center justify-between">
      <h3 className="text-[10px] font-black text-text">设备时间线</h3>
      <span className="text-[9px] text-text-muted" role={loading ? 'status' : undefined}>{loading ? '加载中' : `${events.length} 条`}</span>
    </div>
    <div className="max-h-[164px] space-y-1 overflow-auto">
      {events.length ? events.slice().reverse().map((event, index) => (
        <div key={event.eventId || `${event.type}-${event.timestamp}-${index}`} className="grid grid-cols-[48px_1fr] gap-2 border-l border-border py-1 pl-2 text-[9px]">
          <span className="font-mono text-text-subtle">{eventTime(event.timestamp)}</span>
          <div className="min-w-0">
            <div className="truncate font-bold text-text">{event.type}</div>
            <div className="truncate text-text-muted">{event.message || event.deviceTaskId || event.campaignId || '状态已更新'}</div>
          </div>
        </div>
      )) : <div className="py-5 text-center text-[10px] text-text-subtle">暂无真实设备事件</div>}
    </div>
  </section>
);
