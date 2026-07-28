import React, { useCallback, useMemo, useState } from 'react';
import {
  ArrowRight,
  Bot,
  Check,
  CircleAlert,
  Cpu,
  Image,
  LoaderCircle,
  LockKeyhole,
  RefreshCw,
  ShieldCheck,
} from 'lucide-react';
import overviewHero from '../../assets/overview-hero-openclaw-4k.webp';
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
import { APP_HOME_TITLE, APP_VERSION } from '../../version';
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

const FALLBACK_AGENTS: Record<string, { name: string; description: string }> = {
  'codex-desktop': { name: 'ChatGPT Codex 原版', description: 'OpenAI 官方 ChatGPT 桌面应用，内含 Codex' },
  'claude-code': { name: 'Claude Code', description: 'Anthropic 命令行编程智能体' },
  opencode: { name: 'opencode', description: '终端优先的 AI 编程工具' },
  'openclaw-companion': { name: 'OpenClaw 兼容运行时', description: 'OpenClaw 协议兼容组件' },
  hermes: { name: 'Hermes', description: 'Hermes 智能体运行时' },
};

type WireVerification = Awaited<ReturnType<typeof wireApi.verify>>;
type JourneyTone = 'complete' | 'current' | 'blocked' | 'error';
type VerificationState = 'idle' | 'checking' | 'passed' | 'failed';

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

function hasConfiguredTextModel(wire: WireSnapshot | null): boolean {
  return wire?.ok === true && Boolean(wire.models?.text?.trim());
}

function actionableJourneyError(error: unknown, action: string): string {
  const raw = parseErrorText(error).trim();
  if (/[\u3400-\u9fff]/.test(raw)) return raw.slice(0, 240);
  const normalized = raw.toLowerCase();
  if (/timeout|timed out|connection|network|fetch|unreachable/.test(normalized)) {
    return `${action}超时。请检查网络和本机 Bridge 状态后重试。`;
  }
  if (/login|auth|credential|unauthorized|forbidden/.test(normalized)) {
    return `${action}失败。请先在“模型账户”确认登录状态和 API Key，再重试。`;
  }
  if (/model|channel|provider|not found|not listed/.test(normalized)) {
    return `${action}失败。当前模型或上游通道不可用，请重新选择模型后验证。`;
  }
  return `${action}暂未完成。请重试；若持续出现，请前往环境诊断导出日志。`;
}

function verificationTimeLabel(value: string): string {
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
  const [view, setView] = useState<'hero' | 'journey'>('hero');
  const initialComponents = useMemo(() => loadCachedComponentSnapshot(), []);
  const [lastVerified, setLastVerified] = useState<LastVerifiedJourney | null>(() => loadLastVerifiedJourney());
  const [components, setComponents] = useState<ComponentSnapshot | null>(initialComponents);
  const [componentsProvenance, setComponentsProvenance] = useState<ComponentSnapshotProvenance>(
    initialComponents ? 'cache' : 'empty',
  );
  const [wire, setWire] = useState<WireSnapshot | null>(null);
  const [verification, setVerification] = useState<WireVerification | null>(null);
  const [loading, setLoading] = useState(false);
  const [verificationState, setVerificationState] = useState<VerificationState>('idle');
  const [liveCheckedAt, setLiveCheckedAt] = useState('');
  const [statusError, setStatusError] = useState('');
  const [verificationError, setVerificationError] = useState('');

  const liveComponents = componentsProvenance === 'live' ? components : null;
  const agents = useMemo(() => requiredRows(components), [components]);
  const readyAgents = components ? agents.filter(isAgentReady).length : 0;
  const readyAgentIds = agents.filter(isAgentReady).map((agent) => agent.id);
  const failedAgents = liveComponents ? agents.filter((agent) => agent.status.endsWith('_failed')).length : 0;
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

  const refreshJourney = useCallback(async () => {
    setLoading(true);
    setStatusError('');
    setVerificationError('');
    setVerificationState('idle');
    setVerification(null);
    setComponentsProvenance((provenance) => provenance === 'empty' ? 'empty' : 'cache');
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
    setLiveCheckedAt(new Date().toISOString());
    setLoading(false);
  }, []);

  const openJourney = useCallback(() => {
    setView('journey');
    void refreshJourney();
  }, [refreshJourney]);

  const verifyConnection = useCallback(async () => {
    if (!canCheckNow || verificationState === 'checking') return;
    setVerificationState('checking');
    setVerification(null);
    setVerificationError('');
    try {
      const result = await wireApi.verify();
      setVerification(result);
      if (result.wire) setWire(result.wire);
      if (configurationCheckSucceeded(result, readyAgentIds)) {
        const verifiedWire = result.wire || wire;
        const record = saveLastVerifiedJourney({
          verifiedAt: new Date().toISOString(),
          textModel: verifiedWire?.models?.text?.trim() || lastVerified?.textModel || '',
          readyAgentIds: readyAgentIds.length > 0 ? readyAgentIds : lastVerified?.readyAgentIds || [],
        });
        setLastVerified(record);
        setVerificationState('passed');
        showToast('当前配置检查通过，可以进入智能体或创作。', 'success');
      } else {
        const targetErrors = Object.values(result.targets || {})
          .filter((target) => target.ok === false && target.error)
          .map((target) => actionableJourneyError(target.error, '检查本机配置'));
        setVerificationError(targetErrors[0] || '配置检查未通过。请确认模型凭据和至少一个已安装 Agent 的配置。');
        setVerificationState('failed');
        showToast('当前配置检查未通过。', 'error');
      }
    } catch (error) {
      const message = actionableJourneyError(error, '检查本机配置');
      setVerificationError(message);
      setVerificationState('failed');
      showToast(message, 'error');
    }
  }, [canCheckNow, lastVerified, readyAgentIds, verificationState, wire]);

  return (
    <div className="flex h-full flex-col overflow-hidden bg-surface">
      {view === 'hero' ? (
        <section data-dashboard-matrix-hero className="flex h-full w-full items-center justify-center overflow-hidden bg-app-bg">
          <div className="relative inline-block h-full max-w-full overflow-hidden bg-app-bg">
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
              onClick={openJourney}
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
        <div className="flex-1 overflow-y-auto" data-dashboard-journey>
          <section className="mx-auto w-full max-w-[1320px] px-4 py-5 sm:px-6 xl:px-8">
            <header className="flex flex-wrap items-end justify-between gap-4 border-b border-border/70 pb-5">
              <div className="min-w-0">
                <div className="text-[11px] font-bold tracking-[0.18em] text-accent">首次使用主旅程</div>
                <h1 className="mt-2 text-[28px] font-black leading-tight text-text">{APP_HOME_TITLE}</h1>
                <p className="mt-2 max-w-2xl text-sm leading-6 text-text-muted">
                  安装 Agent、选择模型并完成一次当前配置检查，随后进入智能体或创作。
                </p>
              </div>
              <div className="flex items-center gap-2">
                <span className="hidden text-xs font-bold text-text-subtle sm:inline">v{APP_VERSION}</span>
                <button
                  type="button"
                  onClick={() => setCurrentPage('phone')}
                  className="h-10 rounded-[8px] border border-border bg-surface px-3 text-sm font-bold text-text transition-colors hover:border-accent/45 hover:text-accent"
                >
                  手机控制
                </button>
                <button
                  type="button"
                  onClick={() => void refreshJourney()}
                  disabled={loading || verificationState === 'checking'}
                  className="inline-flex h-10 items-center gap-2 rounded-[8px] border border-border bg-surface px-3 text-sm font-bold text-text transition-colors hover:border-accent/45 hover:text-accent disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} aria-hidden="true" />
                  重新检测
                </button>
                <button
                  type="button"
                  onClick={() => setView('hero')}
                  className="h-10 rounded-[8px] border border-border bg-surface px-3 text-sm font-bold text-text transition-colors hover:border-accent/45 hover:text-accent"
                >
                  返回总览图
                </button>
              </div>
            </header>

            <div className="mt-5 flex items-center gap-3 rounded-[8px] border border-border bg-surface-alt/40 px-4 py-3" role="status" aria-live="polite">
              {loading ? (
                <LoaderCircle className="h-5 w-5 shrink-0 animate-spin text-accent" aria-hidden="true" />
              ) : statusError ? (
                <CircleAlert className="h-5 w-5 shrink-0 text-status-danger" aria-hidden="true" />
              ) : (
                <ShieldCheck className="h-5 w-5 shrink-0 text-status-success" aria-hidden="true" />
              )}
              <div className="min-w-0">
                <div className="text-sm font-black text-text">
                  {loading
                    ? '正在后台刷新当前基础状态'
                    : statusError ? '当前基础状态读取不完整'
                      : liveCheckedAt ? '当前基础状态已刷新'
                        : lastVerified ? '已读取上次配置检查记录'
                          : '尚无验证记录'}
                </div>
                <div className="mt-0.5 break-words text-xs leading-5 text-text-muted [overflow-wrap:anywhere]">
                  {loading
                    ? lastVerified
                      ? `保留 ${verificationTimeLabel(lastVerified.verifiedAt)} 的历史检查记录；它不会代替本次 Bridge 状态。`
                      : '页面可以继续使用；检测完成后会更新当前状态。'
                    : statusError
                      || (liveCheckedAt
                        ? `基础状态刷新于 ${verificationTimeLabel(liveCheckedAt)}；入口仍需完成本次配置检查。`
                        : lastVerified
                          ? `上次配置检查：${verificationTimeLabel(lastVerified.verifiedAt)}。这不是当前可用性声明。`
                          : '请完成一次当前配置检查；历史记录只用于参考。')}
                </div>
              </div>
            </div>

            <div className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              <JourneyStep
                number={1}
                title="安装 Agent"
                detail="安装并启动至少一个受管 Agent。"
                state={componentsProvenance !== 'live'
                  ? readyAgents > 0
                    ? `上次识别 ${readyAgents} 个`
                    : lastVerified?.readyAgentIds.length
                      ? `上次检查 ${lastVerified.readyAgentIds.length} 个`
                      : loading ? '后台检测中' : '尚未确认'
                  : failedAgents > 0 ? '需要处理'
                    : liveInstallReady ? `${readyAgents} 个可用`
                      : '尚未安装'}
                tone={failedAgents > 0 ? 'error' : liveInstallReady ? 'complete' : activeStep === 1 ? 'current' : 'blocked'}
                icon={<Bot className="h-5 w-5" aria-hidden="true" />}
                actionLabel={liveInstallReady ? '查看 Agent' : '安装 Agent'}
                onAction={() => setCurrentPage('agents')}
              />
              <JourneyStep
                number={2}
                title="选择模型"
                detail="选择文本模型，状态以当前配置为准。"
                state={wire === null
                  ? lastVerified?.textModel ? `上次：${lastVerified.textModel}` : loading ? '后台检测中' : '尚未确认'
                  : liveModelReady ? wire.models?.text || '已选择'
                    : '尚未选择'}
                tone={liveModelReady ? 'complete' : activeStep === 2 ? 'current' : 'blocked'}
                icon={<Cpu className="h-5 w-5" aria-hidden="true" />}
                actionLabel={liveModelReady ? '查看模型' : '选择模型'}
                onAction={() => setCurrentPage('models')}
              />
              <JourneyStep
                number={3}
                title="配置检查"
                detail="由 Bridge 检查模型凭据与已安装 Agent 的本机配置，不发起上游推理。"
                state={verificationState === 'checking'
                  ? '检查中'
                  : verificationReady ? '本次检查通过'
                    : lastVerified ? `上次检查 · ${verificationTimeLabel(lastVerified.verifiedAt)}`
                      : verificationError ? '检查未通过'
                        : '等待检查'}
                tone={verificationError ? 'error' : journeyReady ? 'complete' : activeStep === 3 ? 'current' : 'blocked'}
                icon={verificationState === 'checking'
                  ? <LoaderCircle className="h-5 w-5 animate-spin" aria-hidden="true" />
                  : <ShieldCheck className="h-5 w-5" aria-hidden="true" />}
                actionLabel={verificationState === 'checking' ? '正在检查' : journeyReady ? '重新检查' : '开始检查'}
                disabled={!canCheckNow || verificationState === 'checking'}
                disabledReason={!liveInstallReady
                  ? '请等待 Bridge 确认当前 Agent 状态。'
                  : !liveModelReady ? '请等待 Bridge 确认当前模型配置。'
                    : ''}
                error={verificationError}
                onAction={() => void verifyConnection()}
              />
              <JourneyStep
                number={4}
                title="进入 Agent / 创作"
                detail="本次配置检查通过后进入真实工作区。"
                state={verificationReady
                  ? '本次检查通过'
                  : lastVerified ? `有 ${verificationTimeLabel(lastVerified.verifiedAt)} 的历史记录，仍需本次检查`
                    : '等待检查'}
                tone={journeyReady ? 'complete' : 'blocked'}
                icon={journeyReady
                  ? <Check className="h-5 w-5" aria-hidden="true" />
                  : <LockKeyhole className="h-5 w-5" aria-hidden="true" />}
                disabled={!journeyReady}
                disabledReason="当前 Bridge 尚未返回本次配置检查通过，入口暂不可用。"
                actions={[
                  { label: '进入智能体', icon: <Bot className="h-4 w-4" aria-hidden="true" />, onClick: () => setCurrentPage('agent') },
                  { label: '进入创作', icon: <Image className="h-4 w-4" aria-hidden="true" />, onClick: () => setCurrentPage('creative') },
                ]}
              />
            </div>

            <div className="mt-5 border-t border-border/70 pt-4 text-xs leading-5 text-text-subtle">
              本页检查本机凭据和 Agent 配置，不会发起上游模型推理。模型与 API 服务是否可用，请以“模型账户”中的实时连接测试为准；历史记录不会解锁当前入口。
            </div>
          </section>
        </div>
      )}
    </div>
  );
};

interface JourneyAction {
  label: string;
  icon: React.ReactNode;
  onClick: () => void;
}

const JourneyStep: React.FC<{
  number: number;
  title: string;
  detail: string;
  state: string;
  tone: JourneyTone;
  icon: React.ReactNode;
  actionLabel?: string;
  onAction?: () => void;
  actions?: JourneyAction[];
  disabled?: boolean;
  disabledReason?: string;
  error?: string;
}> = ({
  number,
  title,
  detail,
  state,
  tone,
  icon,
  actionLabel,
  onAction,
  actions,
  disabled,
  disabledReason,
  error,
}) => {
  const toneClasses: Record<JourneyTone, string> = {
    complete: 'border-status-success/35 bg-status-success/8',
    current: 'border-accent/40 bg-accent/8 shadow-[0_10px_28px_rgba(8,60,49,0.08)]',
    blocked: 'border-border bg-surface-alt/25',
    error: 'border-status-danger/35 bg-status-danger/8',
  };

  return (
    <section
      className={`flex min-h-[250px] min-w-0 flex-col rounded-[8px] border p-4 ${toneClasses[tone]}`}
      data-journey-step={number}
    >
      <div className="flex items-center justify-between gap-3">
        <span className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-[8px] border ${
          tone === 'complete' ? 'border-status-success/35 text-status-success'
            : tone === 'error' ? 'border-status-danger/35 text-status-danger'
              : 'border-border text-accent'
        }`}>
          {icon}
        </span>
        <span className="text-[11px] font-black tracking-[0.12em] text-text-subtle">步骤 {number}</span>
      </div>
      <h2 className="mt-4 text-lg font-black text-text">{title}</h2>
      <p className="mt-1 text-sm leading-5 text-text-muted">{detail}</p>
      <div className={`mt-3 break-words text-xs font-bold [overflow-wrap:anywhere] ${
        tone === 'error' ? 'text-status-danger'
          : tone === 'complete' ? 'text-status-success'
            : 'text-text-subtle'
      }`}>
        {state}
      </div>
      {error ? (
        <div className="mt-2 break-words rounded-[8px] border border-status-danger/25 bg-surface px-3 py-2 text-xs leading-5 text-status-danger [overflow-wrap:anywhere]">
          {error}
        </div>
      ) : null}
      <div className="mt-auto pt-4">
        {actions ? (
          <div className="grid grid-cols-2 gap-2">
            {actions.map((action) => (
              <button
                key={action.label}
                type="button"
                onClick={action.onClick}
                disabled={disabled}
                title={disabled ? disabledReason : action.label}
                className="inline-flex min-w-0 items-center justify-center gap-1.5 rounded-[8px] border border-accent/35 bg-accent px-2.5 py-2 text-xs font-black text-white transition-colors hover:bg-accent-hover disabled:cursor-not-allowed disabled:border-border disabled:bg-disabled disabled:text-disabled-text"
              >
                {action.icon}
                <span className="truncate">{action.label}</span>
              </button>
            ))}
          </div>
        ) : (
          <>
            <button
              type="button"
              onClick={onAction}
              disabled={disabled}
              title={disabled ? disabledReason : actionLabel}
              className="inline-flex w-full items-center justify-between gap-2 rounded-[8px] border border-accent/35 bg-accent px-3 py-2.5 text-sm font-black text-white transition-colors hover:bg-accent-hover disabled:cursor-not-allowed disabled:border-border disabled:bg-disabled disabled:text-disabled-text"
              data-journey-action={number}
            >
              <span className="truncate">{actionLabel}</span>
              <ArrowRight className="h-4 w-4 shrink-0" aria-hidden="true" />
            </button>
            {disabled && disabledReason ? (
              <p className="mt-2 text-xs leading-5 text-text-subtle">{disabledReason}</p>
            ) : null}
          </>
        )}
      </div>
    </section>
  );
};
