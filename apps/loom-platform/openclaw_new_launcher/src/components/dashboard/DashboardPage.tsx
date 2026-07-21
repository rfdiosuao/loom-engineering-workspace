import React, { useCallback, useEffect, useMemo, useState } from 'react';
import overviewHero from '../../assets/overview-hero-openclaw-4k.webp';
import { componentApi, parseErrorText, type ComponentSnapshot, type ComponentSummary } from '../../services/api';
import { loadCachedComponentSnapshot } from '../../services/componentStatusCache';
import { useAppStore } from '../../stores/appStore';
import { APP_DISPLAY_NAME, APP_VERSION } from '../../version';
import { BusyOverlay } from '../common';

const REQUIRED_AGENT_IDS = ['codex-desktop', 'claude-code', 'opencode', 'openclaw-companion', 'hermes'];

const FALLBACK_AGENTS: Record<string, { name: string; description: string }> = {
  'codex-desktop': { name: 'ChatGPT Codex 原版', description: 'OpenAI 官方 ChatGPT 桌面应用，内含 Codex' },
  'claude-code': { name: 'Claude Code', description: 'Anthropic 命令行编程智能体' },
  opencode: { name: 'opencode', description: '终端优先的 AI 编程工具' },
  'openclaw-companion': { name: 'OpenClaw 兼容运行时', description: 'OpenClaw 协议兼容组件' },
  hermes: { name: 'Hermes', description: 'Hermes 智能体运行时' },
};

function requiredRows(snapshot: ComponentSnapshot | null): ComponentSummary[] {
  const byId = new Map((snapshot?.components || []).map((item) => [item.id, item]));
  return REQUIRED_AGENT_IDS.map((id) => {
    const existing = byId.get(id);
    if (existing) return existing;
    const fallback = FALLBACK_AGENTS[id];
    return {
      id,
      name: fallback?.name || id,
      version: '-',
      installedVersion: null,
      previousVersion: null,
      status: 'not_installed',
      platform: 'windows',
      arch: 'x64',
      type: 'installer',
      size: 0,
      entry: null,
      installPath: '',
      category: 'agent',
      officialUrl: '',
      description: fallback?.description || '',
      urls: [],
      updatedAt: null,
      errorCode: null,
      errorMessage: null,
    };
  });
}

function isAgentReady(agent: ComponentSummary): boolean {
  return agent.status === 'ready' || agent.status === 'started';
}

export const DashboardPage: React.FC = () => {
  const setCurrentPage = useAppStore((state) => state.setCurrentPage);
  const [view, setView] = useState<'hero' | 'paths'>('hero');
  const initialComponents = useMemo(() => loadCachedComponentSnapshot(), []);
  const [components, setComponents] = useState<ComponentSnapshot | null>(initialComponents);
  const [loading, setLoading] = useState(initialComponents === null);
  const [refreshError, setRefreshError] = useState('');

  const refresh = useCallback(async () => {
    setLoading(true);
    setRefreshError('');
    try {
      setComponents(await componentApi.status());
    } catch (error) {
      setRefreshError(parseErrorText(error) || '组件状态读取失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (components === null) void refresh();
  }, [components, refresh]);

  const agents = useMemo(() => requiredRows(components), [components]);
  const readyAgents = agents.filter(isAgentReady).length;
  const failedAgents = agents.filter((agent) => agent.status.endsWith('_failed')).length;
  const agentsReady = agents.length > 0 && readyAgents === agents.length;

  return (
    <div className="flex h-full flex-col overflow-hidden bg-surface">
      <BusyOverlay
        active={loading}
        title="正在刷新总览"
        detail={`${APP_DISPLAY_NAME} 正在读取智能体安装状态。`}
      />

      {view === 'hero' ? (
        <section data-dashboard-matrix-hero className="flex h-full w-full items-center justify-center overflow-hidden bg-[#fbfaf2]">
          <div className="relative inline-block h-full max-w-full overflow-hidden bg-[#fbfaf2]">
            <img
              src={overviewHero}
              alt="让 AI 带着手机干活"
              className="block h-full max-w-full select-none object-contain"
              draggable={false}
            />
            <button
              type="button"
              aria-label="开始配置"
              title="开始配置"
              onClick={() => setView('paths')}
              className="absolute left-[4.1%] top-[38.8%] h-[9.5%] w-[16.7%] rounded-[8px] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
            />
            <button
              type="button"
              aria-label="查看可做的事"
              title="查看可做的事"
              onClick={() => setCurrentPage('workbench')}
              className="absolute left-[22.2%] top-[38.8%] h-[9.5%] w-[15.8%] rounded-[8px] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
            />
          </div>
        </section>
      ) : (
        <div className="flex-1 overflow-y-auto">
          <section id="legacy-overview" className="mx-auto w-full max-w-[1320px] px-5 py-5 xl:px-8">
            {refreshError ? (
              <div className="mb-4 rounded-[8px] border border-status-danger/30 bg-status-danger/10 p-4 text-sm text-status-danger">
                {refreshError}
              </div>
            ) : null}
            {!refreshError && components?.warning ? (
              <div className="mb-4 rounded-[8px] border border-status-warning/30 bg-status-warning/10 p-4 text-sm text-status-warning">
                {components.warning}
              </div>
            ) : null}

            <header className="mb-5 flex flex-wrap items-end justify-between gap-4 border-b border-border/70 pb-5">
              <div>
                <div className="text-[11px] font-bold tracking-[0.18em] text-accent">配置入口</div>
                <h1 className="mt-2 text-[30px] font-black leading-tight text-text">开始使用麓鸣</h1>
                <p className="mt-2 max-w-2xl text-sm leading-6 text-text-muted">
                  完成智能体安装与手机连接后，即可进入任务编排和矩阵执行。
                </p>
              </div>
              <div className="flex items-center gap-3">
                <span className="text-xs font-bold text-text-subtle">v{APP_VERSION}</span>
                <button
                  type="button"
                  onClick={() => setView('hero')}
                  className="rounded-[8px] border border-border/80 bg-surface px-4 py-2.5 text-sm font-bold text-text transition-colors duration-150 hover:border-accent/60 hover:text-accent"
                >
                  返回总览图
                </button>
              </div>
            </header>

            <section className="grid gap-4 xl:grid-cols-2">
              <PathCard
                eyebrow="第一步"
                title="安装智能体"
                detail="安装、更新和启动 Codex、Claude Code、opencode、OpenClaw 与 Hermes。"
                state={failedAgents ? '需要处理' : agentsReady ? '全部就绪' : `${readyAgents}/${agents.length} 已就绪`}
                primaryLabel={agentsReady ? '查看安装状态' : '选择智能体'}
                tone={failedAgents ? 'danger' : agentsReady ? 'ok' : 'warn'}
                onClick={() => setCurrentPage('agents')}
              />
              <PathCard
                eyebrow="第二步"
                title="连接手机"
                detail="配置手机地址与令牌，确认连接状态后执行任务、同步模型和查看结果。"
                state={agentsReady ? '可以连接' : '安装后连接'}
                primaryLabel="打开手机控制"
                tone={agentsReady ? 'ok' : 'warn'}
                onClick={() => setCurrentPage('phone')}
              />
            </section>
          </section>
        </div>
      )}
    </div>
  );
};

const PathCard: React.FC<{
  eyebrow: string;
  title: string;
  detail: string;
  state: string;
  primaryLabel: string;
  tone: 'ok' | 'warn' | 'danger';
  onClick: () => void;
}> = ({ eyebrow, title, detail, state, primaryLabel, tone, onClick }) => (
  <button
    type="button"
    onClick={onClick}
    className={`min-h-[184px] rounded-[8px] border p-5 text-left transition-colors duration-150 ${
      tone === 'danger'
        ? 'border-status-danger/35 bg-status-danger/10'
        : tone === 'ok'
          ? 'border-[#0B4A3E]/25 bg-[#0B4A3E]/10'
          : 'border-border/80 bg-surface-alt/35 hover:border-[#0B4A3E]/35'
    }`}
  >
    <div className="flex items-center justify-between gap-3">
      <span className="text-[11px] font-black tracking-[0.18em] text-text-subtle">{eyebrow}</span>
      <span className={`rounded-full border px-2.5 py-1 text-xs font-bold ${
        tone === 'danger'
          ? 'border-status-danger/35 bg-status-danger/10 text-status-danger'
          : tone === 'ok'
            ? 'border-status-success/30 bg-status-success/10 text-status-success'
            : 'border-status-warning/30 bg-status-warning/10 text-status-warning'
      }`}>{state}</span>
    </div>
    <div className="mt-5 text-[24px] font-black leading-tight text-text">{title}</div>
    <div className="mt-2 max-w-[460px] text-sm leading-6 text-text-muted">{detail}</div>
    <div className="mt-5 inline-flex rounded-[8px] border border-[#0B4A3E]/35 bg-[#0B4A3E] px-4 py-2 text-sm font-black text-[#F5FFF9]">
      {primaryLabel}
    </div>
  </button>
);
