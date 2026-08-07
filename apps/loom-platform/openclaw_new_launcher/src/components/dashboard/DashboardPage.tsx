import React, { useCallback, useEffect, useMemo, useState } from 'react';
import overviewHero from '../../assets/overview-hero-openclaw-4k.webp';
import {
  Activity,
  ArrowRight,
  Bot,
  Check,
  CheckCircle2,
  ChevronRight,
  CircleAlert,
  Cpu,
  LoaderCircle,
  LockKeyhole,
  Network,
  Palette,
  Phone,
  Radio,
  RefreshCw,
  Rocket,
  ShieldCheck,
  Sparkles,
  Workflow,
  Zap,
} from 'lucide-react';
import {
  componentApi,
  parseErrorText,
  wireApi,
  type ComponentSnapshot,
  type ComponentSummary,
  type WireSnapshot,
} from '../../services/api';
import { loadCachedComponentSnapshot } from '../../services/componentStatusCache';
import { useAppStore } from '../../stores/appStore';
import { APP_VERSION } from '../../version';
import { showToast } from '../common';
import {
  loadLastVerifiedJourney,
  saveLastVerifiedJourney,
  type LastVerifiedJourney,
} from './dashboardJourneyCache';
import {
  configurationCheckSucceeded,
  resolveDashboardJourneyState,
  type ComponentSnapshotProvenance,
} from './dashboardJourneyState';

const REQUIRED_AGENT_IDS = ['codex-desktop', 'claude-code', 'opencode', 'openclaw-companion', 'hermes'];

const FALLBACK_AGENTS: Record<string, { name: string; shortName: string }> = {
  'codex-desktop': { name: 'ChatGPT Codex', shortName: 'CX' },
  'claude-code': { name: 'Claude Code', shortName: 'CL' },
  opencode: { name: 'OpenCode', shortName: 'OC' },
  'openclaw-companion': { name: 'OpenClaw Runtime', shortName: 'OW' },
  hermes: { name: 'Hermes', shortName: 'HM' },
};

type WireVerification = Awaited<ReturnType<typeof wireApi.verify>>;
type VerificationState = 'idle' | 'checking' | 'passed' | 'failed';
type StepTone = 'done' | 'active' | 'locked';

function requiredRows(snapshot: ComponentSnapshot | null): ComponentSummary[] {
  const byId = new Map((snapshot?.components || []).map((item) => [item.id, item]));
  return REQUIRED_AGENT_IDS.map((id) => byId.get(id) || {
    id,
    name: FALLBACK_AGENTS[id]?.name || id,
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
    description: '',
    urls: [],
    updatedAt: null,
    errorCode: null,
    errorMessage: null,
  });
}

function isAgentReady(agent: ComponentSummary): boolean {
  return agent.status === 'ready' || agent.status === 'started';
}

function hasConfiguredTextModel(wire: WireSnapshot | null): boolean {
  return wire?.ok === true && Boolean(wire.models?.text?.trim());
}

function actionableJourneyError(error: unknown, action: string): string {
  const raw = parseErrorText(error).trim();
  if (/[㐀-鿿]/.test(raw)) return raw.slice(0, 180);
  const normalized = raw.toLowerCase();
  if (/timeout|timed out|connection|network|fetch|unreachable/.test(normalized)) {
    return `${action}超时，请检查本机 Bridge 后重试。`;
  }
  if (/login|auth|credential|unauthorized|forbidden/.test(normalized)) {
    return `${action}失败，请检查模型账户与 API Key。`;
  }
  return `${action}暂未完成，请稍后重试。`;
}

function compactTime(value?: string | null): string {
  if (!value) return '尚未验证';
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) return '时间未知';
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(timestamp));
}

export const DashboardPage: React.FC = () => {
  const setCurrentPage = useAppStore((state) => state.setCurrentPage);
  const serviceRunning = useAppStore((state) => state.serviceRunning);
  const serviceStatus = useAppStore((state) => state.serviceStatus);
  const phoneAgentStatus = useAppStore((state) => state.phoneAgentStatus);
  const phoneAgentSummary = useAppStore((state) => state.phoneAgentSummary);

  const initialComponents = useMemo(() => loadCachedComponentSnapshot(), []);
  const [components, setComponents] = useState<ComponentSnapshot | null>(initialComponents);
  const [componentsProvenance, setComponentsProvenance] = useState<ComponentSnapshotProvenance>(
    initialComponents ? 'cache' : 'empty',
  );
  const [wire, setWire] = useState<WireSnapshot | null>(null);
  const [verification, setVerification] = useState<WireVerification | null>(null);
  const [verificationState, setVerificationState] = useState<VerificationState>('idle');
  const [lastVerified, setLastVerified] = useState<LastVerifiedJourney | null>(() => loadLastVerifiedJourney());
  const [loading, setLoading] = useState(false);
  const [statusError, setStatusError] = useState('');
  const [checkedAt, setCheckedAt] = useState('');

  const liveComponents = componentsProvenance === 'live' ? components : null;
  const agents = useMemo(() => requiredRows(components), [components]);
  const readyAgents = agents.filter(isAgentReady);
  const readyAgentIds = readyAgents.map((agent) => agent.id);
  const failedAgents = liveComponents
    ? agents.filter((agent) => agent.status.endsWith('_failed')).length
    : 0;
  const verificationReady = configurationCheckSucceeded(verification, readyAgentIds);

  const {
    liveInstallReady,
    liveModelReady,
    canCheckNow,
    journeyReady,
    activeStep,
  } = resolveDashboardJourneyState({
    loading,
    componentsProvenance,
    readyAgentIds,
    hasConfiguredTextModel: hasConfiguredTextModel(wire),
    configurationCheckPassed: verificationReady,
  });

  const readinessSignals = [liveInstallReady, liveModelReady, journeyReady, serviceRunning];
  const readiness = Math.round((readinessSignals.filter(Boolean).length / readinessSignals.length) * 100);
  const currentModel = wire?.models?.text?.trim() || '待选择';
  const provider = wire?.provider?.trim() || '未连接';
  const statusLabel = loading
    ? '正在同步'
    : statusError
      ? '需要处理'
      : journeyReady
        ? '可以开始'
        : '配置中';

  const refreshJourney = useCallback(async () => {
    setLoading(true);
    setStatusError('');
    setVerification(null);
    setVerificationState('idle');
    setComponentsProvenance((value) => value === 'empty' ? 'empty' : 'cache');
    setWire(null);

    const [componentResult, wireResult] = await Promise.allSettled([
      componentApi.status(),
      wireApi.current(),
    ]);

    const errors: string[] = [];
    if (componentResult.status === 'fulfilled') {
      setComponents(componentResult.value);
      setComponentsProvenance('live');
    } else {
      errors.push(actionableJourneyError(componentResult.reason, '读取 Agent 状态'));
    }
    if (wireResult.status === 'fulfilled') {
      setWire(wireResult.value.wire);
    } else {
      errors.push(actionableJourneyError(wireResult.reason, '读取模型配置'));
    }
    setStatusError(errors.join(' '));
    setCheckedAt(new Date().toISOString());
    setLoading(false);
  }, []);

  useEffect(() => {
    void refreshJourney();
  }, [refreshJourney]);

  const verifyConnection = useCallback(async () => {
    if (!canCheckNow || verificationState === 'checking') return;
    setVerificationState('checking');
    setStatusError('');
    try {
      const result = await wireApi.verify();
      setVerification(result);
      if (result.wire) setWire(result.wire);
      if (configurationCheckSucceeded(result, readyAgentIds)) {
        const verifiedWire = result.wire || wire;
        const record = saveLastVerifiedJourney({
          verifiedAt: new Date().toISOString(),
          textModel: verifiedWire?.models?.text?.trim() || lastVerified?.textModel || '',
          readyAgentIds,
        });
        setLastVerified(record);
        setVerificationState('passed');
        showToast('配置检查通过，工作台已就绪。', 'success');
      } else {
        setVerificationState('failed');
        setStatusError('配置检查未通过，请确认模型凭据和 Agent 连接。');
        showToast('配置检查未通过。', 'error');
      }
    } catch (error) {
      const message = actionableJourneyError(error, '配置检查');
      setVerificationState('failed');
      setStatusError(message);
      showToast(message, 'error');
    }
  }, [canCheckNow, lastVerified, readyAgentIds, verificationState, wire]);

  const steps = [
    {
      number: 1,
      title: '安装 Agent',
      detail: readyAgents.length > 0 ? `${readyAgents.length} 个 Agent 已就绪` : '选择并安装你的首个智能体',
      done: liveInstallReady,
      action: '打开安装中心',
      onClick: () => setCurrentPage('agents'),
    },
    {
      number: 2,
      title: '选择模型',
      detail: liveModelReady ? currentModel : '连接模型账户并选择默认模型',
      done: liveModelReady,
      action: '配置模型',
      onClick: () => setCurrentPage('license'),
    },
    {
      number: 3,
      title: '配置检查',
      detail: journeyReady ? '本次检查已通过' : '验证凭据、模型与运行时连接',
      done: journeyReady,
      action: verificationState === 'checking' ? '检查中' : '立即检查',
      onClick: () => void verifyConnection(),
      disabled: !canCheckNow || verificationState === 'checking',
    },
    {
      number: 4,
      title: '进入 Agent',
      detail: journeyReady ? '一切就绪，开始你的第一个任务' : '完成检查后即可开始',
      done: journeyReady,
      action: '开始对话',
      onClick: () => setCurrentPage('agent'),
      disabled: !journeyReady,
    },
  ];

  return (
    <div
      data-dashboard-journey
      className="h-full overflow-y-auto bg-app-bg text-text"
    >
      <div className="mx-auto w-full max-w-[1500px] px-5 py-5 2xl:px-8 2xl:py-7">
        <header className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 text-[11px] font-black uppercase tracking-[0.2em] text-accent">
              <span className="h-1.5 w-1.5 rounded-full bg-accent ring-4 ring-accent-soft" />
              Loom command center
            </div>
            <h1 className="mt-2 text-2xl font-black tracking-[-0.03em] text-text sm:text-[30px]">
              让你的 Agent 开始工作
            </h1>
            <p className="mt-1 text-sm text-text-muted">在一个界面里完成配置、验证与任务分发。</p>
          </div>
          <div className="flex items-center gap-2">
            <span className="hidden rounded-full border border-border bg-surface px-3 py-2 text-xs font-bold text-text-muted lg:inline-flex">
              v{APP_VERSION}
            </span>
            <button
              type="button"
              onClick={() => void refreshJourney()}
              disabled={loading || verificationState === 'checking'}
              className="inline-flex h-10 items-center gap-2 rounded-xl border border-border bg-surface px-3.5 text-sm font-bold text-text shadow-elevation-low transition hover:border-border-strong hover:bg-hover disabled:cursor-not-allowed disabled:opacity-50"
            >
              <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} aria-hidden="true" />
              刷新状态
            </button>
            <button
              type="button"
              onClick={() => setCurrentPage('agent')}
              disabled={!journeyReady}
              className="inline-flex h-10 items-center gap-2 rounded-xl border border-accent bg-accent px-4 text-sm font-black text-accent-ink shadow-elevation-medium transition hover:-translate-y-0.5 hover:bg-accent-hover disabled:translate-y-0 disabled:cursor-not-allowed disabled:border-border disabled:bg-disabled disabled:text-disabled disabled:shadow-none"
            >
              <Sparkles className="h-4 w-4" aria-hidden="true" />
              新建任务
            </button>
          </div>
        </header>

        {statusError ? (
          <div className="mt-4 flex items-start gap-3 rounded-xl border border-status-warning/30 bg-status-warning-soft px-4 py-3 text-sm text-status-warning-ink">
            <CircleAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
            <span>{statusError}</span>
          </div>
        ) : null}

        <section className="mt-5 grid gap-4 xl:grid-cols-[minmax(0,1.45fr)_minmax(320px,0.55fr)]">
          <div data-dashboard-matrix-hero className="relative min-h-[300px] overflow-hidden rounded-[22px] border border-white/10 bg-surface-deeper px-6 py-7 text-white shadow-elevation-medium sm:px-8 sm:py-8">
            <div className="pointer-events-none absolute inset-0 overflow-hidden" aria-hidden="true">
              <img
                src={overviewHero}
                alt=""
                className="absolute inset-0 h-full w-full object-cover opacity-35"
              />
              <div className="absolute inset-0 bg-gradient-to-r from-surface-deeper via-surface-deeper/90 to-surface-deeper/35" />
              <div className="absolute -right-20 -top-36 h-[420px] w-[420px] rounded-full border border-accent/15" />
              <div className="absolute -right-2 -top-16 h-[280px] w-[280px] rounded-full border border-accent/25" />
              <div className="absolute right-20 top-14 h-28 w-28 rounded-full bg-accent/20 blur-2xl" />
              <div className="absolute bottom-0 left-0 h-36 w-3/4 bg-accent/10 blur-3xl" />
            </div>
            <div className="relative flex h-full flex-col justify-between">
              <div>
                <div className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/[0.06] px-3 py-1.5 text-xs font-bold text-terminal-text backdrop-blur">
                  <Radio className="h-3.5 w-3.5" aria-hidden="true" />
                  {statusLabel}
                </div>
                <h2 className="mt-5 max-w-[650px] text-[32px] font-black leading-[1.1] tracking-[-0.04em] sm:text-[40px]">
                  一个控制台，调度你的全部 AI 能力。
                </h2>
                <p className="mt-4 max-w-xl text-sm leading-6 text-terminal-label-muted sm:text-[15px]">
                  连接 Agent、模型与手机矩阵，从想法到执行保持在同一条可验证的工作流里。
                </p>
              </div>
              <div className="mt-7 flex flex-wrap gap-3">
                <button
                  type="button"
                  aria-label="开始配置"
                  onClick={() => journeyReady ? setCurrentPage('agent') : void verifyConnection()}
                  disabled={!journeyReady && !canCheckNow}
                  className="inline-flex h-11 items-center gap-2 rounded-xl bg-terminal-text px-5 text-sm font-black text-terminal-bg transition hover:-translate-y-0.5 hover:bg-accent-hover disabled:translate-y-0 disabled:cursor-not-allowed disabled:bg-disabled disabled:text-disabled"
                >
                  {verificationState === 'checking' ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Rocket className="h-4 w-4" />}
                  {journeyReady ? '进入智能体' : '验证并启动'}
                </button>
                <button
                  type="button"
                  aria-label="连接手机"
                  onClick={() => setCurrentPage('phone')}
                  className="inline-flex h-11 items-center gap-2 rounded-xl border border-white/15 bg-white/[0.06] px-5 text-sm font-bold text-white transition hover:border-white/30 hover:bg-white/10"
                >
                  <Phone className="h-4 w-4" aria-hidden="true" />
                  连接手机
                </button>
                <button
                  type="button"
                  aria-label="打开矩阵工作台"
                  onClick={() => setCurrentPage('workbench')}
                  className="inline-flex h-11 items-center gap-2 rounded-xl border border-white/15 bg-white/[0.06] px-5 text-sm font-bold text-white transition hover:border-white/30 hover:bg-white/10"
                >
                  <Workflow className="h-4 w-4" aria-hidden="true" />
                  让 AI 带着手机干活
                </button>
              </div>
            </div>
          </div>

          <div className="rounded-[22px] border border-border bg-surface p-5 shadow-elevation-low sm:p-6">
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className="text-xs font-black uppercase tracking-[0.16em] text-text-subtle">System readiness</div>
                <h2 className="mt-2 text-xl font-black text-text">系统就绪度</h2>
              </div>
              <ShieldCheck className="h-5 w-5 text-accent" aria-hidden="true" />
            </div>
            <div className="mt-6 flex items-center gap-6">
              <div
                className="relative grid h-28 w-28 shrink-0 place-items-center rounded-full"
                style={{ background: `conic-gradient(var(--color-accent) ${readiness * 3.6}deg, var(--color-surface-alt) 0deg)` }}
                aria-label={`系统就绪度 ${readiness}%`}
              >
                <div className="grid h-[88px] w-[88px] place-items-center rounded-full bg-surface">
                  <div className="text-center">
                    <div className="text-2xl font-black tabular-nums text-text">{readiness}%</div>
                    <div className="mt-0.5 text-[10px] font-bold text-text-subtle">READY</div>
                  </div>
                </div>
              </div>
              <div className="min-w-0 flex-1 space-y-3">
                <HealthRow label="Bridge 服务" ready={serviceRunning} pending={serviceStatus === 'starting'} />
                <HealthRow label="Agent 运行时" ready={liveInstallReady} pending={loading} />
                <HealthRow label="模型连接" ready={liveModelReady} pending={loading} />
                <HealthRow label="配置验证" ready={journeyReady} pending={verificationState === 'checking'} />
              </div>
            </div>
            <div className="mt-6 rounded-xl bg-surface-alt px-4 py-3">
              <div className="flex items-center justify-between gap-3 text-xs">
                <span className="font-bold text-text-muted">最近同步</span>
                <span className="font-black text-text">{compactTime(checkedAt)}</span>
              </div>
            </div>
          </div>
        </section>

        <section className="mt-4 grid grid-cols-2 gap-3 xl:grid-cols-4">
          <MetricCard
            icon={<Bot className="h-5 w-5" />}
            label="已就绪 Agent"
            value={`${readyAgents.length}/${agents.length}`}
            note={failedAgents > 0 ? `${failedAgents} 个需要处理` : componentsProvenance === 'live' ? '状态已同步' : '等待实时状态'}
            tone={failedAgents > 0 ? 'warning' : 'accent'}
          />
          <MetricCard
            icon={<Cpu className="h-5 w-5" />}
            label="当前模型"
            value={currentModel}
            note={provider}
            tone="info"
            compact
          />
          <MetricCard
            icon={<Activity className="h-5 w-5" />}
            label="Bridge 状态"
            value={serviceRunning ? '运行中' : '未启动'}
            note={serviceStatus === 'starting' ? '正在启动服务' : serviceRunning ? '可以接收任务' : '启动后可执行任务'}
            tone={serviceRunning ? 'success' : 'neutral'}
          />
          <MetricCard
            icon={<Zap className="h-5 w-5" />}
            label="最近任务"
            value={phoneAgentStatus === 'running' ? '执行中' : phoneAgentStatus === 'success' ? '已完成' : '暂无任务'}
            note={phoneAgentSummary || compactTime(lastVerified?.verifiedAt)}
            tone={phoneAgentStatus === 'running' ? 'info' : phoneAgentStatus === 'success' ? 'success' : 'neutral'}
            compact
          />
        </section>

        <section className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1.25fr)_minmax(360px,0.75fr)]">
          <div className="rounded-[22px] border border-border bg-surface p-5 shadow-elevation-low sm:p-6">
            <div className="flex flex-wrap items-end justify-between gap-3">
              <div>
                <div className="text-xs font-black uppercase tracking-[0.16em] text-text-subtle">Quick start</div>
                <h2 className="mt-2 text-xl font-black text-text">从配置到执行</h2>
                <p className="mt-1 text-sm text-text-muted">四步完成第一条可验证工作流。</p>
              </div>
              <span className="rounded-full bg-accent-soft px-3 py-1.5 text-xs font-black text-accent">
                当前步骤 {activeStep}/4
              </span>
            </div>
            <div className="mt-5 grid gap-3 md:grid-cols-2">
              {steps.map((step) => {
                const tone: StepTone = step.done ? 'done' : activeStep === step.number ? 'active' : 'locked';
                return (
                  <JourneyCard
                    key={step.number}
                    {...step}
                    tone={tone}
                  />
                );
              })}
            </div>
            <p className="mt-4 text-xs leading-5 text-text-subtle">
              安全说明：历史记录不会解锁当前入口；每次启动都以本机 Bridge 的实时结果为准。
            </p>
          </div>

          <div className="rounded-[22px] border border-border bg-surface p-5 shadow-elevation-low sm:p-6">
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className="text-xs font-black uppercase tracking-[0.16em] text-text-subtle">Live workspace</div>
                <h2 className="mt-2 text-xl font-black text-text">运行态势</h2>
              </div>
              <Network className="h-5 w-5 text-accent" aria-hidden="true" />
            </div>

            <div className="mt-5 space-y-2.5">
              {agents.map((agent) => {
                const ready = isAgentReady(agent);
                return (
                  <button
                    key={agent.id}
                    type="button"
                    onClick={() => setCurrentPage('agents')}
                    className="group flex w-full items-center gap-3 rounded-xl border border-transparent px-2.5 py-2 text-left transition hover:border-border hover:bg-hover"
                  >
                    <span className={`grid h-9 w-9 shrink-0 place-items-center rounded-xl text-[11px] font-black ${ready ? 'bg-accent-soft text-accent' : 'bg-surface-alt text-text-subtle'}`}>
                      {FALLBACK_AGENTS[agent.id]?.shortName || 'AI'}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-black text-text">{FALLBACK_AGENTS[agent.id]?.name || agent.name}</span>
                      <span className="mt-0.5 block truncate text-xs text-text-subtle">
                        {ready ? agent.installedVersion || agent.version || '已就绪' : '等待安装'}
                      </span>
                    </span>
                    <span className={`h-2 w-2 shrink-0 rounded-full ${ready ? 'bg-status-success ring-4 ring-status-success-soft' : 'bg-border-strong'}`} />
                    <ChevronRight className="h-4 w-4 shrink-0 text-text-subtle transition group-hover:translate-x-0.5 group-hover:text-accent" />
                  </button>
                );
              })}
            </div>

            <div className="mt-5 border-t border-border pt-5">
              <div className="grid grid-cols-3 gap-2">
                <QuickLink icon={<Workflow className="h-4 w-4" />} label="工作台" onClick={() => setCurrentPage('workbench')} />
                <QuickLink icon={<Palette className="h-4 w-4" />} label="创作" onClick={() => setCurrentPage('creative')} />
                <QuickLink icon={<Cpu className="h-4 w-4" />} label="模型" onClick={() => setCurrentPage('license')} />
              </div>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
};

const HealthRow: React.FC<{ label: string; ready: boolean; pending?: boolean }> = ({ label, ready, pending }) => (
  <div className="flex items-center justify-between gap-3 text-xs">
    <span className="font-bold text-text-muted">{label}</span>
    <span className={`inline-flex items-center gap-1.5 font-black ${ready ? 'text-status-success' : pending ? 'text-info' : 'text-text-subtle'}`}>
      {pending ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : ready ? <CheckCircle2 className="h-3.5 w-3.5" /> : <span className="h-1.5 w-1.5 rounded-full bg-current" />}
      {pending ? '同步中' : ready ? '就绪' : '待配置'}
    </span>
  </div>
);

const MetricCard: React.FC<{
  icon: React.ReactNode;
  label: string;
  value: string;
  note: string;
  tone: 'accent' | 'info' | 'success' | 'warning' | 'neutral';
  compact?: boolean;
}> = ({ icon, label, value, note, tone, compact }) => {
  const tones = {
    accent: 'bg-accent-soft text-accent',
    info: 'bg-info-soft text-info',
    success: 'bg-status-success-soft text-status-success',
    warning: 'bg-status-warning-soft text-status-warning',
    neutral: 'bg-surface-alt text-text-muted',
  };
  return (
    <div className="min-w-0 rounded-2xl border border-border bg-surface p-4 shadow-elevation-low sm:p-5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-xs font-bold text-text-subtle">{label}</div>
          <div className={`mt-2 truncate font-black tracking-[-0.03em] text-text ${compact ? 'text-lg' : 'text-2xl'}`} title={value}>{value}</div>
        </div>
        <span className={`grid h-10 w-10 shrink-0 place-items-center rounded-xl ${tones[tone]}`}>{icon}</span>
      </div>
      <div className="mt-3 truncate text-xs font-medium text-text-muted" title={note}>{note}</div>
    </div>
  );
};

const JourneyCard: React.FC<{
  number: number;
  title: string;
  detail: string;
  action: string;
  tone: StepTone;
  onClick: () => void;
  disabled?: boolean;
}> = ({ number, title, detail, action, tone, onClick, disabled }) => {
  const done = tone === 'done';
  const active = tone === 'active';
  return (
    <article className={`relative min-w-0 overflow-hidden rounded-2xl border p-4 transition ${done ? 'border-status-success/30 bg-status-success-soft/40' : active ? 'border-accent/35 bg-accent-soft/45 shadow-elevation-low' : 'border-border bg-surface-alt/35'}`}>
      {active ? <span className="absolute inset-y-0 left-0 w-1 bg-accent" /> : null}
      <div className="flex items-start gap-3">
        <span className={`grid h-9 w-9 shrink-0 place-items-center rounded-xl border text-xs font-black ${done ? 'border-status-success/25 bg-status-success text-white' : active ? 'border-accent/25 bg-accent text-accent-ink' : 'border-border bg-surface text-text-subtle'}`}>
          {done ? <Check className="h-4 w-4" /> : number}
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-black text-text">{title}</h3>
          <p className="mt-1 min-h-9 text-xs leading-[18px] text-text-muted">{detail}</p>
        </div>
      </div>
      <button
        type="button"
        onClick={onClick}
        disabled={disabled}
        className={`mt-3 inline-flex w-full items-center justify-between rounded-xl px-3 py-2 text-xs font-black transition ${active || done ? 'bg-surface text-text shadow-elevation-low hover:text-accent' : 'bg-surface-alt text-text-subtle'} disabled:cursor-not-allowed disabled:opacity-55`}
      >
        <span className="inline-flex items-center gap-2">
          {disabled ? <LockKeyhole className="h-3.5 w-3.5" /> : active ? <Zap className="h-3.5 w-3.5 text-accent" /> : <CheckCircle2 className="h-3.5 w-3.5 text-status-success" />}
          {action}
        </span>
        <ArrowRight className="h-3.5 w-3.5" />
      </button>
    </article>
  );
};

const QuickLink: React.FC<{ icon: React.ReactNode; label: string; onClick: () => void }> = ({ icon, label, onClick }) => (
  <button
    type="button"
    onClick={onClick}
    className="inline-flex min-w-0 flex-col items-center justify-center gap-1.5 rounded-xl border border-border bg-surface-alt px-2 py-3 text-xs font-black text-text transition hover:border-accent/35 hover:bg-accent-soft hover:text-accent"
  >
    {icon}
    <span className="truncate">{label}</span>
  </button>
);
