import React from 'react';

import type { MatrixDeviceView } from './matrixViewModel';

interface MatrixMetricsProps {
  devices: MatrixDeviceView[];
}

export const MatrixMetrics: React.FC<MatrixMetricsProps> = ({ devices }) => {
  const online = devices.filter((device) => device.status !== 'offline').length;
  const running = devices.filter((device) => device.status === 'running').length;
  const waiting = devices.filter((device) => device.status === 'waiting').length;
  const errors = devices.filter((device) => device.status === 'error' || device.status === 'offline').length;
  const completed = devices.filter((device) => device.task?.status === 'completed').length;
  const terminal = devices.filter((device) => device.task && ['completed', 'failed', 'cancelled'].includes(device.task.status)).length;
  const successRate = terminal ? Math.round((completed / terminal) * 100) : 0;
  const metrics = [
    ['在线', `${online}/${devices.length}`, 'text-status-success'],
    ['运行中', running, 'text-info'],
    ['待命', waiting, 'text-status-warning'],
    ['异常', errors, errors ? 'text-status-danger' : 'text-text'],
    ['任务完成率', `${successRate}%`, 'text-info'],
  ];

  return (
    <div data-matrix-metrics className="grid min-w-[430px] grid-cols-5 gap-1.5">
      {metrics.map(([label, value, tone]) => (
        <div key={label} className="rounded-[6px] border border-border bg-surface-alt px-2 py-1.5">
          <div className="text-[9px] font-bold text-text-muted">{label}</div>
          <div className={`mt-0.5 text-[13px] font-black ${tone}`}>{value}</div>
        </div>
      ))}
    </div>
  );
};
