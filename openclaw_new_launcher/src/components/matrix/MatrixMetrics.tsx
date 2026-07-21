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
    ['在线', `${online}/${devices.length}`, 'text-emerald-200'],
    ['运行中', running, 'text-cyan-200'],
    ['待命', waiting, 'text-amber-200'],
    ['异常', errors, errors ? 'text-rose-200' : 'text-slate-300'],
    ['任务完成率', `${successRate}%`, 'text-sky-200'],
  ];

  return (
    <div data-matrix-metrics className="grid min-w-[430px] grid-cols-5 gap-1.5">
      {metrics.map(([label, value, tone]) => (
        <div key={label} className="rounded-[6px] border border-white/[0.08] bg-white/[0.035] px-2 py-1.5">
          <div className="text-[9px] font-bold text-slate-500">{label}</div>
          <div className={`mt-0.5 text-[13px] font-black ${tone}`}>{value}</div>
        </div>
      ))}
    </div>
  );
};
