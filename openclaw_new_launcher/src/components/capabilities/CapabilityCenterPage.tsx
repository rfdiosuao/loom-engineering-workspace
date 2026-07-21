import React from 'react';
import { APP_DISPLAY_NAME } from '../../version';

const CAPABILITIES = [
  {
    title: '桌面 RPA',
    desc: '桌面自动化需要完整安全确认，演示版先保留状态入口。',
    status: '暂未开放',
    nextStep: '后续只通过明确确认的任务入口执行。',
  },
  {
    title: '平台发布',
    desc: '视频发布、评论、私信等外发动作需要账号授权、风控确认和审计记录。',
    status: '暂未开放',
    nextStep: '发布类动作会在人工确认和模板授权后开放。',
  },
  {
    title: '任务库 / 定时任务',
    desc: '任务模板库、计划运行和批量调度还在稳定化。',
    status: '暂未开放',
    nextStep: '当前只保留工作台即时任务，定时和任务库暂不开放。',
  },
  {
    title: '主题配置',
    desc: '换肤和高级外观配置先锁定，避免演示版风格发散。',
    status: '暂未开放',
    nextStep: `当前统一使用${APP_DISPLAY_NAME}白标风格，主题配置后续再开放。`,
  },
];

const statusClass = (status: string) =>
  status === '可检测'
    ? 'border-status-success/30 bg-status-success/10 text-status-success'
    : 'border-status-warning/30 bg-status-warning/10 text-status-warning';

const CapabilityCard: React.FC<{
  title: string;
  desc: string;
  status: string;
  nextStep: string;
}> = ({ title, desc, status, nextStep }) => (
  <li data-capability-status-row className="border-t border-border/70 pt-4">
    <div className="flex items-start justify-between gap-4">
      <div className="min-w-0">
        <h2 className="text-lg font-black text-text">{title}</h2>
        <p className="mt-2 text-sm leading-6 text-text-muted">{desc}</p>
      </div>
      <span
        role="status"
        aria-label={`${title}状态：${status}`}
        className={`shrink-0 rounded-full border px-3 py-1 text-xs font-bold ${statusClass(status)}`}
      >
        {status}
      </span>
    </div>
    <div className="mt-5 border-t border-border/60 pt-4 text-xs font-bold leading-5 text-text-muted">
      {nextStep}
    </div>
  </li>
);

export const CapabilityCenterPage: React.FC = () => {
  return (
    <div className="flex h-full flex-col overflow-hidden bg-surface">
      <header className="shrink-0 border-b border-border/70 bg-surface px-8 py-7">
        <div>
          <div className="text-[11px] font-bold tracking-[0.42em] text-accent">其他</div>
          <h1 className="mt-2 text-[30px] font-black leading-tight text-text">暂未开放</h1>
        </div>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto px-8 py-7">
        <section className="mx-auto grid w-full max-w-[1120px] gap-8 xl:grid-cols-[minmax(0,1fr)_360px]">
          <ul className="grid gap-x-7 gap-y-6 md:grid-cols-2">
            {CAPABILITIES.map((item) => (
              <CapabilityCard
                key={item.title}
                title={item.title}
                desc={item.desc}
                status={item.status}
                nextStep={item.nextStep}
              />
            ))}
          </ul>

          <aside className="border-t border-border/70 pt-5 xl:border-l xl:border-t-0 xl:pl-7 xl:pt-0">
            <div className="text-[10px] font-bold tracking-[0.24em] text-text-subtle">状态说明</div>
            <h2 className="mt-1 text-2xl font-black text-text">这些能力尚未开放</h2>
            <span className={`mt-4 inline-flex rounded-full border px-3 py-1 text-xs font-bold ${statusClass('暂未开放')}`}>
              暂未开放
            </span>
            <p className="mt-5 text-sm leading-7 text-text-muted">
              当前页面仅展示规划状态，不会触发安装、发布、调度或外观变更。
            </p>
            <div className="mt-5 border-t border-border/60 pt-4 text-sm font-bold text-text">
              能力具备真实入口和完整安全确认后，才会在对应工作台开放。
            </div>
          </aside>
        </section>
      </div>
    </div>
  );
};
