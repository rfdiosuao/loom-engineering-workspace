import React from 'react';
import {
  Bot,
  CheckCircle2,
  Circle,
  ExternalLink,
  PlayCircle,
  RefreshCcw,
  Server,
  ShieldCheck,
  UserRound,
  Wrench,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { Button, Chip, EmptyState, InlineState, Panel, StatTile, cx } from '../components/ui';
import {
  loadAccountSnapshot,
  loadComponentsSnapshot,
  loadDashboardSnapshot,
  startProcess,
  stopProcess,
  type DashboardSnapshot,
} from '../api/adapters';
import { translateError } from '../lib/errors';
import { formatDateTime } from '../lib/format';
import { useAsync } from '../lib/useAsync';
import { usePreviewStore, type PreviewSettings } from '../store/appStore';
import type { AccountSnapshot, ComponentSnapshot, ComponentSummary, StatusTone } from '../types';

const REQUIRED_AGENT_IDS = ['codex-desktop', 'claude-code', 'opencode', 'openclaw-companion', 'hermes'] as const;

const AGENT_FALLBACK: Record<string, { name: string; description: string }> = {
  'codex-desktop': { name: 'Codex', description: 'OpenAI 编程智能体' },
  'claude-code': { name: 'Claude Code', description: 'Anthropic 命令行编程智能体' },
  opencode: { name: 'opencode', description: '终端优先的 AI 编程工具' },
  'openclaw-companion': { name: 'OpenClaw', description: 'OpenClaw 多智能体工作台' },
  hermes: { name: 'Hermes', description: 'Hermes 智能体运行时' },
};

interface InstallerDashboardSnapshot extends DashboardSnapshot {
  account: AccountSnapshot | null;
  components: ComponentSnapshot | null;
  accountError: string;
  componentsError: string;
}

async function loadInstallerDashboard(settings: PreviewSettings): Promise<InstallerDashboardSnapshot> {
  const [dashboard, account, components] = await Promise.all([
    loadDashboardSnapshot(settings),
    loadAccountSnapshot(settings)
      .then((value) => ({ value, error: '' }))
      .catch((error) => ({ value: null, error: String(error) })),
    loadComponentsSnapshot(settings)
      .then((value) => ({ value, error: '' }))
      .catch((error) => ({ value: null, error: String(error) })),
  ]);

  return {
    ...dashboard,
    account: account.value,
    components: components.value,
    accountError: account.error,
    componentsError: components.error,
  };
}

export function DashboardPage() {
  const settings = usePreviewStore((state) => state.settings);
  const navigate = usePreviewStore((state) => state.navigate);
  const pushToast = usePreviewStore((state) => state.pushToast);
  const { data, loading, error, refresh } = useAsync(() => loadInstallerDashboard(settings), [settings]);

  const service = data?.service;
  const account = data?.account;
  const license = data?.license;
  const gateway = data?.gateway;
  const diagnostics = data?.diagnostics;
  const components = data?.components;
  const agents = React.useMemo(() => requiredAgentRows(components), [components]);
  const readyAgents = agents.filter((agent) => agent.status === 'ready').length;
  const accountReady = Boolean(account?.loggedIn || license?.authorized || data?.member.status === 'active');
  const agentsReady = agents.length > 0 && readyAgents === agents.length;
  const coreReady = Boolean(service?.running);
  const gatewayReady = Boolean(gateway?.hasGateway);
  const modelCount = countModels(account);
  const failedAgents = agents.filter((agent) => agent.status.endsWith('_failed'));
  const activeStep = !accountReady ? 0 : !agentsReady ? 1 : !coreReady ? 2 : 3;
  const overall = resolveOverallStatus({ loading, error, accountReady, agentsReady, coreReady, failedAgents: failedAgents.length });
  const mainAction = resolveMainAction({
    accountReady,
    agentsReady,
    coreReady,
    navigate,
    onStart: () => void handleStart(),
    onOpenConsole: () => void handleOpenConsole(),
  });

  const handleStart = async () => {
    try {
      await startProcess(settings);
      pushToast({ tone: 'ok', title: '核心服务已启动', detail: 'OpenClaw 已接收启动指令。' });
      refresh();
    } catch (err) {
      const f = translateError(err);
      pushToast({ tone: 'danger', title: '启动失败', detail: f.hint, diagnostic: f.diagnostic, logRoute: f.logRoute });
    }
  };

  const handleStop = async () => {
    try {
      await stopProcess(settings);
      pushToast({ tone: 'warn', title: '核心服务已停止', detail: '启动器回到待启动状态。' });
      refresh();
    } catch (err) {
      const f = translateError(err);
      pushToast({ tone: 'danger', title: '停止失败', detail: f.hint, diagnostic: f.diagnostic, logRoute: f.logRoute });
    }
  };

  const handleOpenConsole = async () => {
    const url = 'http://127.0.0.1:18790';
    try {
      const { open } = await import('@tauri-apps/plugin-shell');
      await open(url);
    } catch {
      window.open(url, '_blank', 'noopener,noreferrer');
    }
  };

  return (
    <div className="page-grid installer-page">
      <section className="installer-hero">
        <div className="installer-hero-copy">
          <div className="eyebrow">OpenClaw Installer</div>
          <h1>启动三方智能体</h1>
          <p>安装 Codex、Claude Code、opencode、OpenClaw 与 Hermes，并把中转站模型配置同步到本机。</p>
          <div className="hero-mini-signals">
            <Chip tone={overall.tone}>{overall.label}</Chip>
            <Chip tone={accountReady ? 'ok' : 'warn'}>{accountReady ? '账号就绪' : '可访客浏览'}</Chip>
            <Chip tone={coreReady ? 'ok' : 'neutral'}>{coreReady ? '核心运行中' : '核心待启动'}</Chip>
          </div>
        </div>
        <Panel className="installer-hero-card">
          <div className="hero-action-label">当前状态</div>
          <div className="hero-action-value">{overall.label}</div>
          <div className="hero-action-note">{overall.note}</div>
          <div className="hero-action-buttons">
            <Button variant="primary" icon={mainAction.icon} onClick={mainAction.onClick} disabled={loading || Boolean(error)}>
              {mainAction.label}
            </Button>
            {coreReady ? (
              <Button variant="quiet" icon={Server} onClick={handleStop}>
                停止核心
              </Button>
            ) : null}
            <Button variant="quiet" icon={RefreshCcw} onClick={refresh}>
              刷新
            </Button>
          </div>
        </Panel>
      </section>

      {error ? <InlineState tone="danger" title="安装器状态读取失败" description={error} /> : null}
      {data?.componentsError ? <InlineState tone="warn" title="智能体目录不可用" description={data.componentsError} /> : null}
      {data?.accountError ? <InlineState tone="warn" title="账号状态暂不可用" description={data.accountError} /> : null}

      <section className="installer-flow-grid">
        <InstallerStep
          index={1}
          title="登录账号"
          description={accountReady ? accountLabel(account, license?.licensee) : '登录中转站后自动同步模型；也可以继续访客模式安装。'}
          icon={UserRound}
          done={accountReady}
          active={activeStep === 0}
          action={<Button variant="secondary" icon={ShieldCheck} onClick={() => navigate('license')}>账号 / 授权</Button>}
        />
        <InstallerStep
          index={2}
          title="安装智能体"
          description={`${readyAgents}/${agents.length} 个已就绪`}
          icon={Bot}
          done={agentsReady}
          active={activeStep === 1}
          action={<Button variant="secondary" icon={Bot} onClick={() => navigate('agents')}>管理智能体</Button>}
        />
        <InstallerStep
          index={3}
          title="启动核心"
          description={coreReady ? `PID ${service?.pid ?? '未知'}` : startupText(service?.startupStage)}
          icon={Server}
          done={coreReady}
          active={activeStep === 2}
          action={
            coreReady
              ? <Button variant="quiet" icon={Server} onClick={handleStop}>停止</Button>
              : <Button variant="success" icon={PlayCircle} onClick={handleStart}>启动</Button>
          }
        />
        <InstallerStep
          index={4}
          title="进入工作台"
          description={coreReady ? '打开 OpenClaw Web 控制台。' : '核心启动后可进入工作台。'}
          icon={ExternalLink}
          done={accountReady && agentsReady && coreReady}
          active={activeStep === 3}
          action={<Button variant="secondary" icon={ExternalLink} onClick={handleOpenConsole} disabled={!coreReady}>打开</Button>}
        />
      </section>

      {loading ? (
        <Panel className="panel-loading">正在读取安装器状态...</Panel>
      ) : data ? (
        <>
          <section className="stats-grid installer-status-grid">
            <StatTile label="账号" value={accountReady ? '已接入' : '未登录'} hint={accountLabel(account, license?.licensee)} tone={accountReady ? 'ok' : 'warn'} />
            <StatTile label="模型" value={modelCount ? `${modelCount} 个` : '未同步'} hint={gatewayReady ? gateway?.baseUrl : '登录后自动同步'} tone={modelCount || gatewayReady ? 'ok' : 'warn'} />
            <StatTile label="智能体" value={`${readyAgents}/${agents.length}`} hint={failedAgents.length ? `${failedAgents.length} 个失败` : components?.manifest?.version || '等待目录'} tone={failedAgents.length ? 'danger' : agentsReady ? 'ok' : 'warn'} />
            <StatTile label="环境" value={diagnostics?.summary.status === 'ok' ? '正常' : diagnostics?.summary.status === 'fail' ? '失败' : '待检查'} hint={diagnostics?.summary.total ? `${diagnostics.summary.ok}/${diagnostics.summary.total} 项通过` : '按需检测'} tone={diagnostics?.summary.status === 'ok' ? 'ok' : diagnostics?.summary.status === 'fail' ? 'danger' : 'warn'} />
          </section>

          <section className="content-grid installer-main-grid">
            <Panel className="surface-panel">
              <div className="installer-panel-head">
                <div>
                  <div className="eyebrow">Agents</div>
                  <h2>智能体安装状态</h2>
                </div>
                <Button variant="quiet" icon={Bot} onClick={() => navigate('agents')}>查看全部</Button>
              </div>
              <div className="installer-agent-list">
                {agents.map((agent) => (
                  <button key={agent.id} type="button" className="installer-agent-row" onClick={() => navigate('agents')}>
                    <span className="installer-agent-mark">{agent.status === 'ready' ? <CheckCircle2 size={16} /> : <Circle size={16} />}</span>
                    <span className="installer-agent-copy">
                      <strong>{agent.name}</strong>
                      <span>{agent.description || AGENT_FALLBACK[agent.id]?.description || agent.id}</span>
                    </span>
                    <Chip tone={componentTone(agent.status)}>{componentStatusLabel(agent.status)}</Chip>
                  </button>
                ))}
              </div>
            </Panel>

            <Panel className="surface-panel">
              <div className="installer-panel-head">
                <div>
                  <div className="eyebrow">Runtime</div>
                  <h2>运行摘要</h2>
                </div>
                <Button variant="quiet" icon={Wrench} onClick={() => navigate('diagnostics')}>诊断</Button>
              </div>
              <div className="detail-stack">
                <div className="detail-row"><span className="detail-label">核心服务</span><span className="detail-value">{coreReady ? '运行中' : '未启动'}</span></div>
                <div className="detail-row"><span className="detail-label">模型网关</span><span className="detail-value">{gatewayReady ? gateway?.baseUrl : '未配置'}</span></div>
                <div className="detail-row"><span className="detail-label">文本模型</span><span className="detail-value">{account?.models.text[0] || gateway?.defaultModel || '未同步'}</span></div>
                <div className="detail-row"><span className="detail-label">刷新时间</span><span className="detail-value">{formatDateTime(Date.now())}</span></div>
              </div>
              {data.recentLogs.length ? (
                <div className="log-list installer-log-list">
                  {data.recentLogs.slice(-5).map((line, index) => <div key={index} className="log-line">{line}</div>)}
                </div>
              ) : (
                <EmptyState title="暂无日志" description="启动核心或执行安装后会显示最近输出。" />
              )}
            </Panel>
          </section>
        </>
      ) : null}
    </div>
  );
}

function InstallerStep({
  index,
  title,
  description,
  icon: Icon,
  done,
  active,
  action,
}: {
  index: number;
  title: string;
  description: React.ReactNode;
  icon: LucideIcon;
  done: boolean;
  active: boolean;
  action: React.ReactNode;
}) {
  return (
    <Panel className={cx('installer-step-card', active && 'installer-step-active', done && 'installer-step-done')}>
      <div className="installer-step-index">{done ? <CheckCircle2 size={18} /> : index}</div>
      <div className="installer-step-body">
        <div className="installer-step-title"><Icon size={17} /> {title}</div>
        <div className="installer-step-desc">{description}</div>
      </div>
      <div className="installer-step-action">{action}</div>
    </Panel>
  );
}

function requiredAgentRows(components: ComponentSnapshot | null | undefined): ComponentSummary[] {
  const byId = new Map((components?.components || []).map((item) => [item.id, item]));
  return REQUIRED_AGENT_IDS.map((id) => {
    const component = byId.get(id);
    if (component) return component;
    const fallback = AGENT_FALLBACK[id];
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

function countModels(account: AccountSnapshot | null | undefined): number {
  if (!account?.models) return 0;
  return account.models.text.length + account.models.image.length + account.models.video.length;
}

function accountLabel(account: AccountSnapshot | null | undefined, licensee?: string): string {
  if (account?.loggedIn) return account.account || account.memberId || '中转站账号';
  if (licensee) return licensee;
  return '访客模式';
}

function startupText(stage?: string): string {
  if (!stage || stage === 'idle') return '等待启动';
  if (stage === 'running') return '启动中';
  return stage;
}

function componentTone(status: string): Exclude<StatusTone, 'busy'> | 'neutral' {
  if (status === 'ready') return 'ok';
  if (status.endsWith('_failed')) return 'danger';
  if (status === 'not_installed') return 'warn';
  return 'neutral';
}

function componentStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    ready: '已就绪',
    not_installed: '未安装',
    downloading: '下载中',
    verifying: '校验中',
    extracting: '安装中',
    configuring: '配置中',
    health_checking: '检测中',
    rollback_available: '可回滚',
    download_failed: '下载失败',
    verify_failed: '校验失败',
    extract_failed: '安装失败',
  };
  return labels[status] || status;
}

function resolveOverallStatus(input: {
  loading: boolean;
  error: string | null | undefined;
  accountReady: boolean;
  agentsReady: boolean;
  coreReady: boolean;
  failedAgents: number;
}): { label: string; note: string; tone: Exclude<StatusTone, 'busy'> | 'neutral' } {
  if (input.loading) return { label: '读取中', note: '正在读取本机状态。', tone: 'neutral' };
  if (input.error) return { label: '桥接异常', note: '本机桥接不可用，先查看诊断。', tone: 'danger' };
  if (!input.accountReady) return { label: '待登录', note: '登录后会自动同步模型，也可以访客安装。', tone: 'warn' };
  if (input.failedAgents) return { label: '安装失败', note: `${input.failedAgents} 个智能体需要处理。`, tone: 'danger' };
  if (!input.agentsReady) return { label: '待安装', note: '先安装需要的智能体组件。', tone: 'warn' };
  if (!input.coreReady) return { label: '待启动', note: '组件和账号已就绪，启动核心即可使用。', tone: 'warn' };
  return { label: '已就绪', note: '可以进入 OpenClaw 工作台。', tone: 'ok' };
}

function resolveMainAction(input: {
  accountReady: boolean;
  agentsReady: boolean;
  coreReady: boolean;
  navigate: (route: any) => void;
  onStart: () => void;
  onOpenConsole: () => void;
}): { label: string; icon: LucideIcon; onClick: () => void } {
  if (!input.accountReady) return { label: '登录账号', icon: ShieldCheck, onClick: () => input.navigate('license') };
  if (!input.agentsReady) return { label: '安装智能体', icon: Bot, onClick: () => input.navigate('agents') };
  if (!input.coreReady) return { label: '启动核心', icon: PlayCircle, onClick: input.onStart };
  return { label: '打开工作台', icon: ExternalLink, onClick: input.onOpenConsole };
}
