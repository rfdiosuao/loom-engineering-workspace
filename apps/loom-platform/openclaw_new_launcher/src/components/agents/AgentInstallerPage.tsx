import React from 'react';
import { AlertTriangle, ShieldCheck } from 'lucide-react';
import { loomClient } from '../../services/loomClient';
import { loomErrorText, normalizeLoomError } from '../../services/loomErrors';
import type {
  AgentModelConfigStatus,
  BridgeJob,
  ComponentSnapshot,
  ComponentSummary,
  DiagnosticCheck,
  DiagnosticReport,
  DiagnosticStatus,
} from '../../services/loomContracts';
import { loadCachedPreflight, preflightCacheUsable, saveCachedPreflight } from '../../services/startupCache';
import { BusyOverlay, Button, Input, Modal, Select, showConfirm, showToast } from '../common';
import { AgentLogo } from './AgentLogo';
import { APP_DISPLAY_NAME } from '../../version';
import { useAppStore } from '../../stores/appStore';

const PINNED_COMPONENT_IDS = [
  'codex-desktop',
  'claude-code',
  'opencode',
  'openclaw-companion',
  'hermes',
];

const FALLBACK_COMPONENTS: Record<string, { name: string; description: string; category: string }> = {
  'codex-desktop': { name: 'ChatGPT Codex 原版', description: 'OpenAI 官方 ChatGPT 桌面应用，内含 Codex，由 Microsoft Store 安装和更新', category: 'agent' },
  'claude-code': { name: 'Claude Code', description: 'Anthropic 命令行编程智能体', category: 'agent' },
  opencode: { name: 'opencode', description: '终端优先的 AI 编程工具', category: 'agent' },
  'openclaw-companion': { name: 'OpenClaw', description: '多智能体编程工作台', category: 'agent' },
  hermes: { name: 'Hermes', description: 'Hermes 智能体运行时', category: 'agent' },
};

const PREREQ_IDS = ['python_runtime', 'node', 'npm', 'git', 'git_bash', 'uv', 'webview2', 'data_dir'];
const COMPONENT_REQUIRED_PREREQ_IDS: Record<string, Set<string>> = {
  'codex-desktop': new Set(),
  'claude-code': new Set(['python_runtime', 'node', 'npm', 'data_dir']),
  opencode: new Set(['python_runtime', 'node', 'npm', 'data_dir']),
  'openclaw-companion': new Set(['python_runtime', 'node', 'npm', 'data_dir']),
  hermes: new Set(['python_runtime', 'data_dir']),
};
const MODEL_CONFIG_COMPONENT_IDS = new Set(['codex-desktop', 'claude-code', 'opencode', 'openclaw-companion']);
const OPENCLAW_WEB_URL = 'http://127.0.0.1:18790';

type CustomProviderOption = {
  id: string;
  label: string;
  baseUrl: string;
};

const CUSTOM_PROVIDER_OPTIONS: CustomProviderOption[] = [
  { id: 'custom', label: '自定义...', baseUrl: '' },
  { id: 'openai', label: 'OpenAI', baseUrl: 'https://api.openai.com/v1' },
  { id: 'anthropic', label: 'Anthropic', baseUrl: 'https://api.anthropic.com/v1' },
  { id: 'gemini', label: 'Google Gemini', baseUrl: 'https://generativelanguage.googleapis.com/v1beta/openai' },
  { id: 'openrouter', label: 'OpenRouter', baseUrl: 'https://openrouter.ai/api/v1' },
  { id: 'deepseek', label: 'DeepSeek', baseUrl: 'https://api.deepseek.com/v1' },
  { id: 'moonshot', label: 'Moonshot - Kimi', baseUrl: 'https://api.moonshot.cn/v1' },
];

type AgentCustomProviderDraft = {
  provider: string;
  baseUrl: string;
  apiKey: string;
  model: string;
};

type ModelConfigRestartPrompt = {
  componentId: string;
  componentName: string;
  channelLabel: string;
};

type ModelConfigFailurePrompt = {
  componentId: string;
  componentName: string;
  message: string;
  requiresLogin: boolean;
};

function providerOptionById(id: string): CustomProviderOption {
  return CUSTOM_PROVIDER_OPTIONS.find((option) => option.id === id) || CUSTOM_PROVIDER_OPTIONS[0];
}

function providerIdForLabel(label?: string): string {
  const normalized = (label || '').trim().toLowerCase();
  if (!normalized) return 'custom';
  return CUSTOM_PROVIDER_OPTIONS.find((option) => option.label.toLowerCase() === normalized)?.id || 'custom';
}

type InstallLogEntry = {
  id: string;
  componentId?: string;
  operationId: string;
  operationLabel: string;
  message: string;
  tone: string;
  time: string;
  timestamp: number;
};

type InstallLogOperation = {
  id: string;
  label: string;
  entries: InstallLogEntry[];
};

const PREREQ_PLACEHOLDER_LABELS: Record<string, string> = {
  python_runtime: 'Python',
  node: 'Node.js',
  npm: 'npm',
  git: 'Git',
  git_bash: 'Git Bash',
  uv: 'uv',
  webview2: 'WebView2',
  data_dir: '数据目录',
  portable_integrity: '便携包完整性',
};

export function statusLabel(status: string): string {
  const labels: Record<string, string> = {
    ready: '已就绪',
    not_installed: '未安装',
    resolving_manifest: '准备中',
    downloading: '下载中',
    verifying: '校验中',
    extracting: '安装中',
    configuring: '配置中',
    health_checking: '检测中',
    starting: '启动中',
    uninstalling: '卸载中',
    upgrade_available: '需升级',
    manual_install_required: '待手动安装',
    simulation_ready: '待检测',
    started: '已启动',
    download_failed: '下载失败',
    verify_failed: '校验失败',
    extract_failed: '安装失败',
    config_failed: '配置失败',
    health_failed: '检测失败',
    start_failed: '启动失败',
    uninstall_failed: '卸载失败',
    rollback_available: '可回滚',
    rolling_back: '回滚中',
    rollback_failed: '回滚失败',
  };
  return labels[status] || status || '-';
}

function displayStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    ready: '已就绪',
    not_installed: '未安装',
    resolving_manifest: '准备中',
    downloading: '下载中',
    verifying: '校验中',
    extracting: '安装中',
    configuring: '配置中',
    health_checking: '检测中',
    starting: '启动中',
    uninstalling: '卸载中',
    upgrade_available: '可升级',
    manual_install_required: '待手动安装',
    simulation_ready: '待检测',
    started: '已启动',
    download_failed: '下载失败',
    verify_failed: '校验失败',
    extract_failed: '安装失败',
    config_failed: '配置失败',
    health_failed: '检测失败',
    start_failed: '启动失败',
    uninstall_failed: '卸载失败',
    rollback_available: '可回滚',
    rolling_back: '回滚中',
    rollback_failed: '回滚失败',
  };
  return labels[status] || status || '-';
}

function statusClass(status: string): string {
  if (status === 'ready' || status === 'started') return 'border-status-success/30 bg-status-success/10 text-status-success';
  if (status === 'upgrade_available') return 'border-status-success/40 bg-status-success/10 text-status-success';
  if (status === 'simulation_ready') return 'border-border/80 bg-surface-alt/60 text-text-muted';
  if (status.endsWith('_failed')) return 'border-status-danger/30 bg-status-danger/10 text-status-danger';
  if (status === 'not_installed' || status === 'manual_install_required') {
    return 'border-[#0B4A3E]/30 bg-[#0B4A3E]/10 text-[#0B4A3E]';
  }
  return 'border-[#0B4A3E]/30 bg-[#0B4A3E]/10 text-[#0B4A3E]';
}

function diagnosticLabel(status: DiagnosticStatus): string {
  if (status === 'ok') return '已就绪';
  if (status === 'warn') return '需处理';
  return '缺失';
}

function diagnosticClass(status: DiagnosticStatus): string {
  if (status === 'ok') return 'border-status-success/30 bg-status-success/10 text-status-success';
  if (status === 'warn') return 'border-[#0B4A3E]/25 bg-[#0B4A3E]/10 text-[#0B4A3E]';
  return 'border-status-danger/30 bg-status-danger/10 text-status-danger';
}

function displayDiagnosticLabel(status: DiagnosticStatus): string {
  if (status === 'ok') return '已就绪';
  if (status === 'warn') return '需处理';
  return '缺失';
}

function prerequisiteChecks(report: DiagnosticReport | null): DiagnosticCheck[] {
  const checks = report?.checks || [];
  const byId = new Map(checks.map((check) => [check.id, check]));
  return PREREQ_IDS.map((id) => byId.get(id)).filter(Boolean) as DiagnosticCheck[];
}

function prerequisiteSummary(checks: DiagnosticCheck[]): { ready: number; total: number; failed: number; repairable: number } {
  return {
    ready: checks.filter((check) => check.status === 'ok').length,
    total: checks.length,
    failed: checks.filter((check) => check.status === 'fail').length,
    repairable: checks.filter((check) => check.repairable).length,
  };
}

function requiredPrerequisiteIdsForComponent(componentId?: string): Set<string> {
  return COMPONENT_REQUIRED_PREREQ_IDS[componentId || ''] || new Set(PREREQ_IDS);
}

function componentPrerequisiteChecks(report: DiagnosticReport | null, componentId?: string): DiagnosticCheck[] {
  const requiredIds = requiredPrerequisiteIdsForComponent(componentId);
  return prerequisiteChecks(report).filter((check) => requiredIds.has(check.id));
}

function prerequisiteNeedsRepair(report: DiagnosticReport | null, componentId?: string): boolean {
  return componentPrerequisiteChecks(report, componentId)
    .some((check) => check.status === 'fail' || (check.status === 'warn' && Boolean(check.repairable)));
}

function blockingPrerequisiteIssues(report: DiagnosticReport | null, componentId?: string): DiagnosticCheck[] {
  return componentPrerequisiteChecks(report, componentId).filter((check) => check.status === 'fail');
}

function isWorking(status: string): boolean {
  return ['resolving_manifest', 'downloading', 'verifying', 'extracting', 'configuring', 'health_checking', 'starting', 'uninstalling'].includes(status);
}

function isFailedStatus(status: string): boolean {
  return status.endsWith('_failed');
}

function needsInstallAfterDetect(component?: ComponentSummary): boolean {
  if (!component) return true;
  return !['ready', 'started'].includes(component.status);
}

function isComponentInstalled(component?: ComponentSummary): boolean {
  return Boolean(component && ['ready', 'started', 'upgrade_available'].includes(component.status));
}

function isOpenClawComponent(component?: ComponentSummary): boolean {
  return component?.id === 'openclaw-companion';
}

function isOfficialCodexComponent(component?: ComponentSummary): boolean {
  return component?.id === 'codex-desktop';
}

function componentWebUrl(component?: ComponentSummary): string {
  if (!component) return '';
  return component.officialUrl || (isOpenClawComponent(component) ? 'https://openclaw.ai' : '');
}

type AgentPrimaryAction = 'install' | 'upgrade' | 'start';

function primaryAgentAction(component?: ComponentSummary): AgentPrimaryAction {
  if (!component) return 'install';
  if (component.status === 'upgrade_available') return 'upgrade';
  if (component.status === 'ready' || component.status === 'started') return 'start';
  return 'install';
}

function primaryAgentButtonLabel(component: ComponentSummary, busyId: string, busyAction: string): string {
  const busy = busyId === component.id;
  if (busy) {
    if (busyAction === 'start') return '启动中...';
    if (busyAction === 'prepare-start') return component.status === 'upgrade_available' ? '升级启动中...' : '安装启动中...';
    return component.status === 'upgrade_available' ? '升级中...' : '安装中...';
  }
  const action = primaryAgentAction(component);
  if (action === 'start') return isOfficialCodexComponent(component) ? '启动原版' : '启动';
  if (action === 'upgrade') return '升级并启动';
  if (isOfficialCodexComponent(component)) return '安装原版';
  return isFailedStatus(component.status) ? '重新安装并启动' : '安装并启动';
}

function toneClass(tone: string): string {
  if (tone === 'ok' || tone === 'success') return 'text-status-success';
  if (tone === 'danger' || tone === 'error') return 'text-status-danger';
  if (tone === 'warning' || tone === 'warn') return 'text-status-warning';
  return 'text-text-muted';
}

function extractJobComponentId(job?: BridgeJob): string {
  if (!job) return '';
  const progress = job.progress as Record<string, unknown> | undefined;
  if (typeof progress?.componentId === 'string') return progress.componentId;
  if (typeof progress?.targetComponentId === 'string') return progress.targetComponentId;
  if (typeof progress?.component === 'string') return progress.component;
  return '';
}

function isActiveJobStatus(status: string): boolean {
  return status === 'queued' || status === 'running';
}

function normalizeLogMessage(message?: string): string {
  return (message || '').replace(/\s+/g, ' ').trim();
}

function normalizeOperationHistory(job: BridgeJob, selectedId: string): InstallLogEntry[] {
  const componentId = extractJobComponentId(job) || undefined;
  if (selectedId && componentId && componentId !== selectedId) return [];

  const history = job.progress?.history || [];
  const fallbackMessage = job.progress?.message || job.message || '';
  const candidates = history.length
    ? history
    : [{ message: fallbackMessage, tone: job.progress?.tone, updatedAt: Number((job as any).updatedAt || 0) }];
  const entries: InstallLogEntry[] = [];
  let previousKey = '';

  candidates.forEach((entry, index) => {
    const message = normalizeLogMessage(entry.message || fallbackMessage);
    if (!message || message === 'queued' || message === 'running') return;
    const tone = entry.tone || job.progress?.tone || 'neutral';
    const key = `${message}\u0000${tone}`;
    if (key === previousKey) return;
    previousKey = key;
    const timestamp = Number(entry.updatedAt || 0) * 1000;
    entries.push({
      id: `${job.id}-${index}`,
      componentId,
      operationId: job.id,
      operationLabel: job.label || '后台任务',
      message,
      tone,
      time: timestamp ? new Date(timestamp).toLocaleTimeString() : '-',
      timestamp,
    });
  });

  return entries;
}

function jobHistoryEntries(jobs: BridgeJob[], selectedId: string): InstallLogEntry[] {
  return jobs.flatMap((job) => normalizeOperationHistory(job, selectedId));
}

function normalizeInstallLogEntries(entries: InstallLogEntry[]): InstallLogEntry[] {
  const previousKeyByOperation = new Map<string, string>();
  return [...entries]
    .sort((left, right) => right.timestamp - left.timestamp)
    .filter((entry) => {
      const key = `${normalizeLogMessage(entry.message)}\u0000${entry.tone}\u0000${entry.componentId || ''}`;
      if (previousKeyByOperation.get(entry.operationId) === key) return false;
      previousKeyByOperation.set(entry.operationId, key);
      return true;
    });
}

function groupInstallLogEntriesByOperation(entries: InstallLogEntry[]): InstallLogOperation[] {
  const operations = new Map<string, InstallLogOperation>();
  entries.forEach((entry) => {
    const operation = operations.get(entry.operationId) || {
      id: entry.operationId,
      label: entry.operationLabel,
      entries: [],
    };
    operation.entries.push(entry);
    operations.set(entry.operationId, operation);
  });
  return [...operations.values()];
}

function formatInstallLogEntries(entries: InstallLogEntry[]): string {
  return groupInstallLogEntriesByOperation(entries)
    .map((operation) => [
      `== ${operation.label} ==`,
      ...operation.entries.map((entry) => `[${entry.time || '-'}] ${entry.message}`),
    ].join('\n'))
    .join('\n\n');
}

function formatSize(size: number): string {
  if (!Number.isFinite(size) || size <= 0) return '-';
  if (size >= 1024 * 1024 * 1024) return `${(size / 1024 / 1024 / 1024).toFixed(1)} GB`;
  if (size >= 1024 * 1024) return `${(size / 1024 / 1024).toFixed(0)} MB`;
  return `${Math.ceil(size / 1024)} KB`;
}

function sortComponents(components: ComponentSummary[]): ComponentSummary[] {
  return [...components].sort((a, b) => {
    const ai = PINNED_COMPONENT_IDS.indexOf(a.id);
    const bi = PINNED_COMPONENT_IDS.indexOf(b.id);
    const ax = ai === -1 ? 999 : ai;
    const bx = bi === -1 ? 999 : bi;
    if (ax !== bx) return ax - bx;
    return a.name.localeCompare(b.name);
  });
}

function componentRows(snapshot: ComponentSnapshot | null): ComponentSummary[] {
  const byId = new Map((snapshot?.components || []).map((item) => [item.id, item]));
  const rows = PINNED_COMPONENT_IDS.map((id) => {
    const existing = byId.get(id);
    if (existing) return existing;
    const fallback = FALLBACK_COMPONENTS[id];
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
      category: fallback?.category || 'component',
      officialUrl: '',
      description: fallback?.description || '',
      urls: [],
      updatedAt: null,
      errorCode: null,
      errorMessage: null,
    };
  });
  const extra = (snapshot?.components || []).filter((item) => !PINNED_COMPONENT_IDS.includes(item.id));
  return sortComponents([...rows, ...extra]);
}

function manifestInstallLocked(snapshot: ComponentSnapshot | null): boolean {
  if (!snapshot) return true;
  return Boolean(snapshot.installLocked || snapshot.manifestErrorCode === 'manifest_unavailable' || !snapshot.manifest);
}

const InfoTile: React.FC<{ label: string; value: string }> = ({ label, value }) => (
  <div className="border-t border-border/70 pt-3">
    <div className="text-[11px] font-bold text-text-subtle">{label}</div>
    <div className="mt-1 truncate text-sm font-black text-text" title={value}>{value}</div>
  </div>
);

const ActivityRing: React.FC<{ active?: boolean; className?: string }> = ({ active = true, className = '' }) => (
  <span className={`loom-activity-ring ${active ? '' : 'opacity-45'} ${className}`} aria-hidden="true" />
);

export const PrerequisitePanel: React.FC<{
  report: DiagnosticReport | null;
  loading: boolean;
  repairing: boolean;
  error: string;
  onRefresh: () => void;
  onRepair: () => void;
}> = ({ report, loading, repairing, error, onRefresh, onRepair }) => {
  const checks = prerequisiteChecks(report);
  const summary = prerequisiteSummary(checks);
  const allReady = checks.length > 0 && summary.ready === summary.total;
  const overall =
    !checks.length
      ? '待检测'
      : summary.failed
        ? `${summary.failed} 项缺失`
        : summary.ready === summary.total
          ? '前置已就绪'
          : `${summary.total - summary.ready} 项需处理`;

  return (
    <section className="px-6 py-6">
      <div className="flex flex-wrap items-start justify-between gap-5">
        <div className="max-w-3xl">
          <div className="text-[10px] font-bold tracking-[0.24em] text-text-subtle">前置环境</div>
          <h2 className="mt-1 text-2xl font-black text-text">先检测 Python / Node / npm / Git / Git Bash</h2>
          <p className="mt-2 text-sm leading-6 text-text-muted">
            普通用户电脑可能没有开发环境；LOOM 会先检查随包运行时和必要工具，缺失时优先处理前置，再继续安装智能体。
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap justify-end gap-3">
          <span className={`rounded-full border px-3 py-2 text-xs font-black ${
            summary.failed ? 'border-status-danger/30 bg-status-danger/10 text-status-danger' : 'border-status-success/30 bg-status-success/10 text-status-success'
          }`}>
            {overall}
          </span>
          <Button variant="quiet" onClick={onRefresh} disabled={loading || repairing}>
            {loading ? '检测中...' : '检测前置'}
          </Button>
          <Button variant="primary" onClick={onRepair} disabled={loading || repairing || allReady}>
            {repairing ? '处理中...' : '安装/修复前置'}
          </Button>
        </div>
      </div>

      {error ? (
        <div className="mt-5 rounded-[14px] border border-status-danger/30 bg-status-danger/10 p-3 text-sm text-status-danger">
          {error}
        </div>
      ) : null}

      <div className="mt-5 grid gap-x-6 gap-y-4 md:grid-cols-3 xl:grid-cols-4">
        {(checks.length ? checks : PREREQ_IDS.map((id) => ({
          id,
          label: PREREQ_PLACEHOLDER_LABELS[id] || id,
          status: 'warn' as DiagnosticStatus,
          message: '等待检测',
          detail: '',
          repairable: false,
        } satisfies DiagnosticCheck))).map((check) => (
          <div key={check.id} className="border-t border-border/70 pt-3">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="truncate text-sm font-black text-text">{check.label}</div>
                <div className="mt-1 line-clamp-2 text-xs leading-5 text-text-muted">{check.message}</div>
              </div>
              <span className={`shrink-0 rounded-full border px-2.5 py-1 text-[11px] font-bold ${diagnosticClass(check.status)}`}>
                {diagnosticLabel(check.status)}
              </span>
            </div>
            {check.detail ? (
              <details className="mt-3 text-xs text-text-subtle">
                <summary className="cursor-pointer font-bold">详情</summary>
                <div className="mt-2 break-all font-mono leading-5">{check.detail}</div>
              </details>
            ) : null}
          </div>
        ))}
      </div>
    </section>
  );
};

export const CompactPrerequisitePanel: React.FC<{
  report: DiagnosticReport | null;
  loading: boolean;
  repairing: boolean;
  error: string;
  installLocked?: boolean;
  onRefresh: () => void;
  onRepair: () => void;
}> = ({ report, loading, repairing, error, installLocked = false, onRefresh, onRepair }) => {
  const checks = prerequisiteChecks(report);
  const summary = prerequisiteSummary(checks);
  const visibleChecks = (checks.length ? checks : PREREQ_IDS.map((id) => ({
    id,
    label: PREREQ_PLACEHOLDER_LABELS[id] || id,
    status: 'warn' as DiagnosticStatus,
    message: '等待检测',
    detail: '',
    repairable: false,
  } satisfies DiagnosticCheck))).slice(0, 5);
  const total = Math.max(summary.total || visibleChecks.length, 1);
  const ready = summary.ready || 0;
  const pct = checks.length ? Math.round((ready / total) * 100) : 0;
  const allReady = checks.length > 0 && summary.ready === summary.total;
  const busy = loading || repairing;
  const timing = report?.timing;
  const title = !checks.length
    ? '准备检测前置环境'
    : summary.failed
      ? `${summary.failed} 项需要处理`
      : allReady
        ? '前置环境已就绪'
        : `${summary.total - summary.ready} 项待处理`;
  const subtitle = busy
    ? repairing ? '正在安装或修复必要环境...' : '正在检测 Python、Node、npm、Git...'
    : installLocked
      ? '安装清单未就绪，安装和启动暂不可用。'
      : allReady ? '可以继续安装和启动智能体。' : '缺失项会优先处理，详情可展开查看。';

  return (
    <section className="h-full">
      <div className="flex h-full flex-col rounded-[8px] border border-border/80 bg-surface/70 p-4 shadow-[0_12px_30px_rgba(8,35,48,0.05)]">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex min-w-0 items-center gap-3">
            <div className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-[8px] ${
              allReady ? 'bg-status-success/12 text-status-success' : busy ? 'bg-[#0B4A3E]/10 text-[#0B4A3E]' : 'bg-surface-alt text-text-muted'
            }`}>
              {busy ? <ActivityRing /> : <span className="text-lg font-black">{allReady ? '✓' : '•'}</span>}
            </div>
            <div className="min-w-0">
              <div className="text-[10px] font-black tracking-[0.22em] text-text-subtle">前置环境</div>
              <h2 className="mt-0.5 text-base font-black text-text">{title}</h2>
              <p className="mt-1 text-xs text-text-muted">{subtitle}</p>
            </div>
          </div>
          <div className="flex shrink-0 flex-wrap justify-end gap-2">
            <Button variant="quiet" onClick={onRefresh} disabled={loading || repairing} className="!rounded-[8px] !px-3 !py-1.5 !text-xs">
              {loading ? '检测中...' : '重新检测'}
            </Button>
            <Button variant="primary" onClick={onRepair} disabled={loading || repairing || allReady} className="!rounded-[8px] !px-3 !py-1.5 !text-xs">
              {repairing ? '处理中...' : '一键补齐'}
            </Button>
          </div>
        </div>

        <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-[#0B4A3E]/10">
          <div
            className={`h-full rounded-full bg-[#0B4A3E] transition-all duration-300 ${busy ? 'loom-scan-line' : ''}`}
            style={{ width: `${Math.max(8, pct)}%` }}
          />
        </div>

        {error ? (
          <div className="mt-4 rounded-[12px] border border-status-danger/30 bg-status-danger/10 px-3 py-2 text-sm text-status-danger">
            {error}
          </div>
        ) : null}

        {timing ? (
          <details className="mt-3 rounded-[10px] border border-border/70 bg-surface-alt/35 px-3 py-2 text-xs text-text-subtle">
            <summary className="cursor-pointer font-bold">检测耗时</summary>
            <div className="mt-2 space-y-1 font-mono">
              <div>totalMs: {timing.totalMs}</div>
              <div>measuredAt: {timing.measuredAt}</div>
            </div>
          </details>
        ) : null}

        <div className="mt-3 grid grid-cols-[repeat(auto-fit,minmax(120px,1fr))] gap-2">
          {visibleChecks.map((check) => (
            <div key={check.id} className="rounded-[8px] border border-border/70 bg-surface/60 px-2.5 py-2">
              <div className="flex items-center justify-between gap-2">
                <div className="truncate text-xs font-black text-text">{check.label}</div>
                <span className={`h-2.5 w-2.5 shrink-0 rounded-full ${
                  check.status === 'ok' ? 'bg-status-success' : check.status === 'fail' ? 'bg-status-danger' : 'bg-[#0B4A3E]/50'
                }`} />
              </div>
              <div className="mt-1 truncate text-xs text-text-muted" title={check.message}>{check.message || displayDiagnosticLabel(check.status)}</div>
            </div>
          ))}
        </div>

        {checks.some((check) => check.detail) ? (
          <details className="mt-4 text-xs text-text-muted">
            <summary className="cursor-pointer font-bold text-text-subtle">查看检测详情</summary>
            <div className="mt-3 grid gap-2 xl:grid-cols-2">
              {checks.filter((check) => check.detail).map((check) => (
                <div key={check.id} className="rounded-[10px] border border-border/70 bg-surface/50 p-3">
                  <div className="font-bold text-text">{check.label}</div>
                  <div className="mt-1 break-all font-mono leading-5">{check.detail}</div>
                </div>
              ))}
            </div>
          </details>
        ) : null}
      </div>
    </section>
  );
};

function supportsModelConfig(component?: ComponentSummary): boolean {
  return Boolean(component && MODEL_CONFIG_COMPONENT_IDS.has(component.id));
}

function canWriteAgentModelConfig(component: ComponentSummary, status?: AgentModelConfigStatus): boolean {
  return Boolean(status?.installed || ['ready', 'started', 'upgrade_available'].includes(component.status));
}

function modelConfigLabel(status?: AgentModelConfigStatus): string {
  if (!status) return '读取中';
  if (status.status === 'official') return 'OpenAI 官方';
  if (status.status === 'not_installed') return '未安装';
  if (status.status === 'no_wire') return '待同步模型';
  if (status.status === 'unverified') return '待验证';
  if (status.status === 'configured') return '已配置';
  if (status.status === 'failed') return '配置失败';
  if (status.status === 'unconfigured') return '未配置';
  return status.message || status.status || '未配置';
}

function modelConfigTone(status?: AgentModelConfigStatus): string {
  if (!status) return 'border-border/70 bg-surface-alt/50 text-text-muted';
  if (status.status === 'official') return 'border-status-success/30 bg-status-success/10 text-status-success';
  if (status.status === 'configured') return 'border-status-success/30 bg-status-success/10 text-status-success';
  if (status.status === 'unverified') return 'border-status-warning/30 bg-status-warning/10 text-status-warning';
  if (status.status === 'failed') return 'border-status-danger/30 bg-status-danger/10 text-status-danger';
  if (status.status === 'not_installed' || status.status === 'no_wire') return 'border-border/70 bg-surface-alt/50 text-text-muted';
  return 'border-[#0B4A3E]/30 bg-[#0B4A3E]/10 text-[#0B4A3E]';
}

const AgentModelConfigPanel: React.FC<{
  component: ComponentSummary;
  status?: AgentModelConfigStatus;
  draftModel: string;
  busy: boolean;
  locked: boolean;
  onDraftModelChange: (value: string) => void;
  onDisable: () => void;
  onApply: () => void;
  onApplyCustom: (draft: AgentCustomProviderDraft) => void;
}> = ({ component, status, draftModel, busy, locked, onDraftModelChange, onDisable, onApply, onApplyCustom }) => {
  const [sourceMode, setSourceMode] = React.useState<'off' | 'oneClick' | 'custom'>('oneClick');
  const [customProviderId, setCustomProviderId] = React.useState('custom');
  const [customProvider, setCustomProvider] = React.useState('OpenAI 兼容');
  const [customBaseUrl, setCustomBaseUrl] = React.useState('');
  const [customApiKey, setCustomApiKey] = React.useState('');
  const availableModels = status?.availableModels || [];
  const canUseWire = Boolean(status?.installed && status.status !== 'no_wire');
  const managedBy = status?.managedBy || '';
  const availableManagedBy = status?.wireManagedBy || managedBy;
  const isManagedAccount = availableManagedBy === 'heang_account' || availableManagedBy === 'newapi_account';
  const hasDraftModel = Boolean(draftModel.trim());
  const canApply = sourceMode === 'custom'
    ? canUseWire && hasDraftModel
    : canUseWire && availableModels.length > 0;
  const detail = status?.message || '读取模型配置状态';
  const oneClickLocked = locked || !canUseWire || !isManagedAccount || availableModels.length === 0;
  const customModelPlaceholder = '输入当前账号可用文本模型';
  const modelConfigTitle = isOpenClawComponent(component) ? 'OpenClaw 模型' : 'Codex / Claude Code 模型';
  const customProviderOption = providerOptionById(customProviderId);
  const customProviderName = customProviderId === 'custom' ? customProvider.trim() : customProviderOption.label;
  const canApplyCustom = Boolean(customProviderName && customBaseUrl.trim() && customApiKey.trim() && draftModel.trim());
  const sessionPreservation = status?.sessionPreservation;
  const sessionsProtected = sessionPreservation?.protected !== false;

  React.useEffect(() => {
    if (status?.channelMode === 'official') {
      setSourceMode('off');
      return;
    }
    if (status?.managedBy === 'custom_provider') {
      const provider = status.provider || 'OpenAI 兼容';
      setSourceMode('custom');
      setCustomProvider(provider);
      setCustomProviderId(providerIdForLabel(provider));
      setCustomBaseUrl(status.baseUrl || '');
      return;
    }
    if (status?.channelMode === 'managed' || status?.configured) setSourceMode('oneClick');
  }, [status?.channelMode, status?.configured, status?.managedBy, status?.provider, status?.baseUrl]);

  const selectCustomProvider = (providerId: string) => {
    const option = providerOptionById(providerId);
    setCustomProviderId(providerId);
    setCustomProvider(option.label);
    if (option.baseUrl) setCustomBaseUrl(option.baseUrl);
  };

  return (
    <section data-agent-model-config className="border-t border-border/70 pt-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="text-sm font-black text-text">{modelConfigTitle}</div>
          <div className="mt-1 text-xs text-text-subtle">{component.name} 使用 LOOM 托管模型配置</div>
        </div>
        <span className={`rounded-full border px-2.5 py-1 text-[11px] font-bold ${modelConfigTone(status)}`}>
          {busy ? '配置中' : modelConfigLabel(status)}
        </span>
      </div>

      {sessionPreservation?.supported ? (
        <div
          data-agent-session-protection
          className={`mt-4 flex items-start gap-3 border-y px-1 py-3 ${
            sessionsProtected
              ? 'border-status-success/25 text-status-success'
              : 'border-status-danger/30 text-status-danger'
          }`}
        >
          {sessionsProtected ? (
            <ShieldCheck className="mt-0.5 h-5 w-5 shrink-0" aria-hidden="true" />
          ) : (
            <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0" aria-hidden="true" />
          )}
          <div className="min-w-0">
            <div className="text-sm font-black">
              {sessionsProtected ? '原有会话已保护' : '原有会话需要检查'}
            </div>
            <div className="mt-1 text-xs leading-5 text-text-muted">
              {sessionPreservation.message}
              {sessionPreservation.lastVerifiedAt ? '，本次配置已完成前后校验' : ''}
            </div>
          </div>
        </div>
      ) : null}

      <div data-agent-model-source-card className="mt-4 rounded-[16px] border border-border/70 bg-surface-alt/35 p-4">
        <div className="text-sm font-black text-text">模型来源</div>
        <div className="mt-1 text-xs leading-5 text-text-muted">
          不接入额外配置时，启动时沿用该工具自带的默认设置。
        </div>
        <div className={`mt-4 grid grid-cols-1 gap-1 rounded-[8px] border border-border/70 bg-app-bg/70 p-1 ${component.id === 'codex-desktop' ? 'sm:grid-cols-3' : 'sm:grid-cols-2'}`}>
          {component.id === 'codex-desktop' ? (
            <button
              type="button"
              onClick={() => setSourceMode('off')}
              disabled={locked || busy}
              className={`h-10 min-w-0 rounded-[6px] px-2 text-xs font-black transition ${sourceMode === 'off' ? 'bg-surface text-text shadow-sm' : 'text-text-muted hover:text-text'}`}
            >
              OpenAI 官方
            </button>
          ) : null}
          <button
            data-agent-one-click-config-lock
            type="button"
            onClick={() => setSourceMode('oneClick')}
            disabled={oneClickLocked || busy}
            title={oneClickLocked ? '登录后解锁：请先同步托管模型' : `选择 ${APP_DISPLAY_NAME} 托管模型，确认后再写入`}
            className={`h-10 min-w-0 rounded-[6px] px-2 text-xs font-black transition ${sourceMode === 'oneClick' ? 'bg-surface text-text shadow-sm' : 'text-text-muted hover:text-text'} disabled:cursor-not-allowed disabled:opacity-65`}
          >
            <span className="inline-flex items-center justify-center gap-2">
              <span className="flex h-4 w-4 items-center justify-center rounded-[4px] border border-current text-[10px] leading-none">
                {oneClickLocked ? '锁' : '开'}
              </span>
              一键配置
            </span>
          </button>
          <button
            type="button"
            onClick={() => setSourceMode('custom')}
            disabled={locked || busy}
            className={`h-10 min-w-0 rounded-[6px] px-2 text-xs font-black transition ${sourceMode === 'custom' ? 'bg-[#0B6B57] text-white shadow-[0_12px_24px_rgba(11,107,87,0.22)]' : 'text-text-muted hover:text-text'}`}
          >
            自定义
          </button>
        </div>
        <div className="mt-3 text-xs text-text-muted">
          {sourceMode === 'off'
            ? '选择模式不会修改本机；点击下方按钮后才会撤销麓鸣托管并恢复原有 Codex 配置。'
            : sourceMode === 'custom'
            ? '自定义会先保存本机第三方 Provider；已安装智能体会继续写入配置。'
            : oneClickLocked
              ? '一键配置需登录后解锁，并同步托管模型。'
              : '选择模型不会修改本机；只有点击“写入配置”后才会更新 Codex / Claude Code。'}
        </div>
      </div>

      {sourceMode === 'off' ? (
        <div className="mt-4 flex flex-wrap items-center justify-between gap-4 border-y border-border/70 py-4">
          <div className="min-w-0">
            <div className="text-sm font-black text-text">
              {status?.channelMode === 'official' ? '当前使用 OpenAI 官方渠道' : '恢复 Codex 原有配置'}
            </div>
            <div className="mt-1 text-xs leading-5 text-text-muted">
              保留 ChatGPT / OpenAI 登录状态，只撤销麓鸣写入的模型渠道与专用环境变量。
            </div>
          </div>
          <Button
            data-agent-model-disable
            variant={status?.channelMode === 'official' ? 'quiet' : 'primary'}
            onClick={onDisable}
            disabled={locked || busy || component.id !== 'codex-desktop' || status?.channelMode === 'official'}
          >
            {busy ? '恢复中...' : status?.channelMode === 'official' ? '已使用官方渠道' : '恢复 OpenAI 官方渠道'}
          </Button>
        </div>
      ) : sourceMode === 'custom' ? (
        <div data-agent-custom-provider-card className="mt-4 rounded-[14px] border border-border/70 bg-surface-alt/25 p-4">
          <div className="grid gap-3 md:grid-cols-[220px_minmax(0,1fr)]">
            <label className="block">
              <div className="mb-2 text-xs font-bold text-text-muted">Provider</div>
              <Select
                data-agent-custom-provider-select
                value={customProviderId}
                onChange={(event) => selectCustomProvider(event.target.value)}
                disabled={locked || busy}
                className="w-full"
              >
                {CUSTOM_PROVIDER_OPTIONS.map((option) => (
                  <option key={option.id} value={option.id}>{option.label}</option>
                ))}
              </Select>
            </label>
            <label className="block">
              <div className="mb-2 text-xs font-bold text-text-muted">默认文本模型</div>
              <Input
                data-agent-custom-model-input
                value={draftModel}
                onChange={(event) => onDraftModelChange(event.target.value)}
                disabled={locked || busy}
                placeholder={customModelPlaceholder}
                className="w-full"
              />
            </label>
            {customProviderId === 'custom' ? (
              <label className="block md:col-span-2">
                <div className="mb-2 text-xs font-bold text-text-muted">Provider 名称</div>
                <Input
                  data-agent-custom-provider-name-input
                  value={customProvider}
                  onChange={(event) => setCustomProvider(event.target.value)}
                  disabled={locked || busy}
                  placeholder="自定义..."
                />
              </label>
            ) : null}
            <label className="block md:col-span-2">
              <div className="mb-2 text-xs font-bold text-text-muted">Base URL</div>
              <Input
                data-agent-custom-base-url-input
                value={customBaseUrl}
                onChange={(event) => setCustomBaseUrl(event.target.value)}
                disabled={locked || busy}
                placeholder="https://example.com/v1"
              />
            </label>
            <label className="block md:col-span-2">
              <div className="mb-2 flex items-center justify-between gap-3 text-xs font-bold text-text-muted">
                <span>API Key</span>
                <span className="text-[#0B6B57]">保存在本机，并写入 Codex 所需的用户环境</span>
              </div>
              <Input
                data-agent-custom-api-key-input
                type="password"
                value={customApiKey}
                onChange={(event) => setCustomApiKey(event.target.value)}
                disabled={locked || busy}
                placeholder="粘贴自己的 API Key"
                autoComplete="off"
              />
            </label>
          </div>
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <Button
              variant="primary"
              onClick={() => onApplyCustom({
                provider: customProviderName,
                baseUrl: customBaseUrl,
                apiKey: customApiKey,
                model: draftModel,
              })}
              disabled={locked || busy || !canApplyCustom}
            >
              {busy ? '写入中...' : canUseWire ? '保存并写入' : '保存配置'}
            </Button>
            <span className="text-xs font-bold text-text-muted">密钥不会回显；换 Key 时重新粘贴即可覆盖。</span>
          </div>
        </div>
      ) : (
        <div className="mt-4 grid gap-3 md:grid-cols-[minmax(0,1fr)_auto]">
          <Select
            aria-label={`${component.name} 托管模型`}
            value={draftModel}
            onChange={(event) => onDraftModelChange(event.target.value)}
            disabled={locked || busy || !canUseWire || availableModels.length === 0}
            className="w-full"
          >
            {(availableModels.length ? availableModels : [draftModel || status?.model]).filter(Boolean).map((model) => (
              <option key={model} value={model}>{model}</option>
            ))}
          </Select>
          <Button data-agent-model-apply variant="primary" onClick={onApply} disabled={locked || busy || !canApply}>
            {busy ? '写入中...' : '写入配置'}
          </Button>
        </div>
        )}

      <div className="mt-3 grid gap-2 text-xs text-text-muted md:grid-cols-3">
        <div className="truncate">模型：{status?.model || draftModel || '-'}</div>
        <div className="truncate">来源：{status?.channelMode === 'official' ? 'OpenAI 官方' : status?.provider || 'LOOM'}</div>
        <div className="truncate">{detail}</div>
      </div>
      {component.id === 'codex-desktop' ? (
        <div
          data-codex-model-verification
          className={`mt-3 rounded-[8px] border px-3 py-2 text-xs font-bold ${
            status?.channelMode === 'official' || status?.remoteVerified
              ? 'border-status-success/30 bg-status-success/10 text-status-success'
              : 'border-status-warning/30 bg-status-warning/10 text-status-warning'
          }`}
        >
          {status?.channelMode === 'official'
            ? '当前使用 OpenAI 官方渠道；ChatGPT 登录状态由官方应用管理'
            : status?.remoteVerified
            ? `模型连通性已验证${status.remoteValidation?.model ? `：${status.remoteValidation.model}` : ''}`
            : '尚未完成真实模型验证；点击“写入配置”后才会设为可用'}
        </div>
      ) : null}
    </section>
  );
};

export const AgentInstallerPage: React.FC = () => {
  const setCurrentPage = useAppStore((state) => state.setCurrentPage);
  const cachedPreflight = React.useRef<DiagnosticReport | null>(loadCachedPreflight());
  const [snapshot, setSnapshot] = React.useState<ComponentSnapshot | null>(null);
  const [selectedId, setSelectedId] = React.useState('');
  const [loading, setLoading] = React.useState(true);
  const [busyId, setBusyId] = React.useState('');
  const [busyAction, setBusyAction] = React.useState('');
  const [error, setError] = React.useState('');
  const [preflight, setPreflight] = React.useState<DiagnosticReport | null>(() => cachedPreflight.current);
  const [preflightLoading, setPreflightLoading] = React.useState(false);
  const [preflightRepairing, setPreflightRepairing] = React.useState(false);
  const [preflightError, setPreflightError] = React.useState('');
  const [jobs, setJobs] = React.useState<BridgeJob[]>([]);
  const [installLog, setInstallLog] = React.useState<InstallLogEntry[]>([]);
  const [logError, setLogError] = React.useState('');
  const [modelConfigs, setModelConfigs] = React.useState<Record<string, AgentModelConfigStatus>>({});
  const [modelDrafts, setModelDrafts] = React.useState<Record<string, string>>({});
  const [modelConfigBusy, setModelConfigBusy] = React.useState('');
  const [modelRestartPrompt, setModelRestartPrompt] = React.useState<ModelConfigRestartPrompt | null>(null);
  const [pendingModelRestart, setPendingModelRestart] = React.useState<ModelConfigRestartPrompt | null>(null);
  const [modelConfigFailurePrompt, setModelConfigFailurePrompt] = React.useState<ModelConfigFailurePrompt | null>(null);
  const modelConfigBusyRef = React.useRef('');
  const modelConfigRequestGeneration = React.useRef<Record<string, number>>({});

  const pushLog = React.useCallback((message: string, tone = 'neutral', componentId?: string) => {
    const timestamp = Date.now();
    const entry: InstallLogEntry = {
      id: `${timestamp}-${Math.random().toString(16).slice(2)}`,
      componentId,
      operationId: `local:${componentId || 'global'}`,
      operationLabel: '操作步骤',
      message: normalizeLogMessage(message),
      tone,
      time: new Date(timestamp).toLocaleTimeString(),
      timestamp,
    };
    setInstallLog((current) => [...current, entry].slice(-40));
  }, []);

  const refreshJobs = React.useCallback(async () => {
    setLogError('');
    try {
      const result = await loomClient.jobs.list(20);
      setJobs(result.jobs || []);
    } catch (err: any) {
      setLogError(loomErrorText(err, '安装日志暂不可用'));
    }
  }, []);

  const recordJobProgress = React.useCallback((job: BridgeJob, _componentId: string) => {
    setJobs((current) => [job, ...current.filter((item) => item.id !== job.id)].slice(0, 20));
  }, []);

  const refresh = React.useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      setSnapshot(await loomClient.components.status());
    } catch (err: any) {
      setError(loomErrorText(err, '安装清单读取失败'));
    } finally {
      setLoading(false);
    }
  }, []);

  const refreshPreflight = React.useCallback(async (options: { preferCache?: boolean; force?: boolean } = {}) => {
    const cached = options.force ? null : loadCachedPreflight();
    if (options.preferCache && cached) {
      cachedPreflight.current = cached;
      setPreflight(cached);
      setPreflightError('');
      setPreflightLoading(false);
      return;
    }
    setPreflightLoading(true);
    setPreflightError('');
    try {
      const report = await loomClient.diagnostics.prerequisites();
      cachedPreflight.current = report;
      setPreflight(report);
      saveCachedPreflight(report);
    } catch (err: any) {
      setPreflightError(loomErrorText(err, '前置环境检测失败'));
    } finally {
      setPreflightLoading(false);
    }
  }, []);

  const refreshModelConfig = React.useCallback(async (componentId: string) => {
    if (!MODEL_CONFIG_COMPONENT_IDS.has(componentId)) return;
    const generation = (modelConfigRequestGeneration.current[componentId] || 0) + 1;
    modelConfigRequestGeneration.current[componentId] = generation;
    try {
      const result = await loomClient.components.modelConfigStatus(componentId);
      if (modelConfigRequestGeneration.current[componentId] !== generation) return;
      const status = result.status;
      setModelConfigs((current) => ({ ...current, [componentId]: status }));
      setModelDrafts((current) => {
        if (current[componentId]) return current;
        const firstModel = status.model || status.availableModels?.[0] || '';
        return { ...current, [componentId]: firstModel };
      });
    } catch (err: any) {
      if (modelConfigRequestGeneration.current[componentId] !== generation) return;
      setModelConfigs((current) => ({
        ...current,
        [componentId]: {
          componentId,
          supported: true,
          configured: false,
          status: 'failed',
          message: loomErrorText(err, '模型配置状态读取失败'),
          availableModels: [],
        },
      }));
    }
  }, []);

  const repairPreflight = React.useCallback(async () => {
    const confirmPreflightRepair = await showConfirm({
      title: '安装/修复前置环境',
      message: 'LOOM 会检查并可能安装 Git、Node.js、Python、uv 或 WebView2，也可能处理本地运行环境。继续吗？',
      confirmText: '继续处理',
    });
    if (!confirmPreflightRepair) return;
    setPreflightRepairing(true);
    setPreflightError('');
    try {
      const next = await loomClient.diagnostics.repairPrerequisites();
      setPreflight(next.diagnostics);
      saveCachedPreflight(next.diagnostics);
      const hasFailedAction = next.actions.some((action) => action.status === 'fail');
      const hasWarnAction = next.actions.some((action) => action.status === 'warn');
      const hasFailedCheck = next.diagnostics.checks.some((check) => check.status === 'fail');
      if (hasFailedAction || hasFailedCheck || next.ok === false) {
        showToast('前置环境处理未完成，请查看检测结果中的失败项', 'error');
      } else if (next.restartRequired) {
        showToast('前置环境已补齐，请重启麓鸣后继续安装', 'info');
      } else if (hasWarnAction) {
        showToast('前置环境仍有需要手动处理的项目，请查看检测结果', 'info');
      } else {
        showToast('已执行前置环境处理，请查看检测结果', 'success');
      }
    } catch (err: any) {
      setPreflightError(loomErrorText(err, '前置环境修复失败'));
      showToast(loomErrorText(err, '前置环境修复失败'), 'error');
    } finally {
      setPreflightRepairing(false);
    }
  }, []);

  const repairMissingPrerequisites = React.useCallback(async (currentReport: DiagnosticReport | null, componentId?: string): Promise<DiagnosticReport> => {
    if (!prerequisiteNeedsRepair(currentReport, componentId)) {
      return currentReport as DiagnosticReport;
    }
    if (currentReport?.repairAvailable === false) {
      const blocking = blockingPrerequisiteIssues(currentReport, componentId);
      const names = blocking.map((check) => check.label || check.id).join('、') || '必要环境';
      throw new Error(`前置环境未就绪：${names}。请使用完整安装包或手动安装后重新检测。`);
    }
    setPreflightRepairing(true);
    setPreflightError('');
    try {
      const repaired = await loomClient.diagnostics.repairPrerequisites();
      const report = repaired.diagnostics;
      setPreflight(report);
      saveCachedPreflight(report);
      const blocking = blockingPrerequisiteIssues(report, componentId);
      if (blocking.length) {
        const names = blocking.map((check) => check.label || check.id).join('、');
        throw new Error(`前置环境仍未就绪：${names}。请查看检测详情后重试。`);
      }
      return report;
    } finally {
      setPreflightRepairing(false);
    }
  }, []);

  React.useEffect(() => {
    void refresh();
    void refreshJobs();
    void refreshPreflight({ preferCache: true });
  }, [refresh, refreshJobs, refreshPreflight]);

  const components = componentRows(snapshot);
  React.useEffect(() => {
    if (!selectedId && components.length) setSelectedId(components[0].id);
  }, [components, selectedId]);

  const selected = components.find((item) => item.id === selectedId) || components[0];
  const selectedActiveJob = React.useMemo(
    () => jobs.find((job) => (
      isActiveJobStatus(String(job.status || ''))
      && extractJobComponentId(job) === selected?.id
    )),
    [jobs, selected?.id],
  );
  const activeJobComponentIds = React.useMemo(() => {
    const ids = new Set<string>();
    jobs.forEach((job) => {
      const componentId = extractJobComponentId(job);
      if (componentId && isActiveJobStatus(String(job.status || ''))) {
        ids.add(componentId);
      }
    });
    if (busyId) ids.add(busyId);
    if (modelConfigBusy) ids.add(modelConfigBusy);
    return ids;
  }, [busyId, jobs, modelConfigBusy]);
  const selectedBusy = Boolean(selected && activeJobComponentIds.has(selected.id));
  const selectedModelConfig = selected ? modelConfigs[selected.id] : undefined;
  const selectedModelDraft = selected ? (modelDrafts[selected.id] || selectedModelConfig?.model || selectedModelConfig?.availableModels?.[0] || '') : '';
  const readyCount = components.filter((item) => item.status === 'ready' || item.status === 'started').length;
  const installActionsLocked = manifestInstallLocked(snapshot);
  const selectedLogEntries = React.useMemo(() => {
    const selectedComponentId = selected?.id || '';
    const localEntries = installLog.filter((entry) => !selectedComponentId || !entry.componentId || entry.componentId === selectedComponentId);
    return normalizeInstallLogEntries([...jobHistoryEntries(jobs, selectedComponentId), ...localEntries]);
  }, [installLog, jobs, selected?.id]);
  const selectedLogOperations = React.useMemo(
    () => groupInstallLogEntriesByOperation(selectedLogEntries),
    [selectedLogEntries],
  );

  React.useEffect(() => {
    if (!jobs.some((job) => job.status === 'running' || job.status === 'queued')) return undefined;
    const timer = window.setInterval(() => {
      void refreshJobs();
    }, 2500);
    return () => window.clearInterval(timer);
  }, [jobs, refreshJobs]);

  React.useEffect(() => {
    if (!selected || !supportsModelConfig(selected)) return;
    void refreshModelConfig(selected.id);
  }, [refreshModelConfig, selected?.id, selected?.status]);

  const ensurePreflightReady = async (componentId?: string): Promise<DiagnosticReport | null> => {
    const cached = loadCachedPreflight();
    const reusablePreflight = preflightCacheUsable(preflight) ? preflight : cached;
    let report: DiagnosticReport | null = reusablePreflight;
    if (reusablePreflight) {
      cachedPreflight.current = reusablePreflight;
      setPreflight(reusablePreflight);
      setPreflightError('');
      setPreflightLoading(false);
    } else {
      setPreflightLoading(true);
      setPreflightError('');
      try {
        report = await loomClient.diagnostics.prerequisites();
        setPreflight(report);
        saveCachedPreflight(report);
      } catch (err: any) {
        const message = loomErrorText(err, '前置环境检测失败');
        setPreflightError(message);
        throw new Error(message);
      } finally {
        setPreflightLoading(false);
      }
    }

    report = await repairMissingPrerequisites(report, componentId);
    const blocking = blockingPrerequisiteIssues(report, componentId);
    if (blocking.length) {
      const names = blocking.map((check) => check.label || check.id).join('、');
      throw new Error(`前置环境未就绪：${names}。请先点“一键补齐”或查看检测详情。`);
    }
    return report;
  };

  const readAgentModelConfigStatus = async (component: ComponentSummary): Promise<AgentModelConfigStatus | null> => {
    if (!supportsModelConfig(component)) return null;
    const status = (await loomClient.components.modelConfigStatus(component.id)).status;
    setModelConfigs((current) => ({ ...current, [component.id]: status }));
    return status;
  };

  const prepareComponent = async (
    component: ComponentSummary,
    options: { autoStart?: boolean; confirmAction?: boolean } = {},
  ) => {
    if (installActionsLocked) {
      const message = '安装清单未就绪，安装和启动暂不可用。请刷新后重试。';
      pushLog(message, 'warning', component.id);
      showToast(message, 'error');
      return;
    }
    const autoStart = options.autoStart ?? false;
    const shouldConfirm = options.confirmAction ?? true;
    if (shouldConfirm) {
      const isOfficialCodex = isOfficialCodexComponent(component);
      const ok = await showConfirm({
        title: `${component.status === 'upgrade_available' ? '升级' : '安装'} ${component.name}`,
        message: isOfficialCodex
          ? '将通过 Microsoft Store 安装 OpenAI 官方 ChatGPT 桌面应用（内含 Codex）。安装完成后由你手动登录 ChatGPT。继续吗？'
          : `${component.status === 'upgrade_available' ? '升级' : '安装'}前会先检测必要环境；缺失时会尝试补齐 Git / Node.js / Python 等工具，然后下载、安装并启动智能体。继续吗？`,
        confirmText: isOfficialCodex ? '安装原版' : component.status === 'upgrade_available' ? '升级并启动' : '安装并启动',
      });
      if (!ok) return;
    }

    setBusyId(component.id);
    setBusyAction(autoStart ? 'prepare-start' : 'prepare');
    try {
      showToast(`开始处理 ${component.name}：检测前置环境`, 'info');
      pushLog(`开始处理 ${component.name}：检测前置环境`, 'neutral', component.id);
      await ensurePreflightReady(component.id);

      let next: ComponentSnapshot | null = null;
      try {
        next = await loomClient.components.detect(component.id, { onProgress: (job) => recordJobProgress(job, component.id) });
        setSnapshot(next);
        const detected = next.components.find((item) => item.id === component.id);
        if (needsInstallAfterDetect(detected)) {
          showToast(`${component.name} 检测到需安装或升级，开始下载并安装`, 'info');
          pushLog(`${component.name} 检测到需安装或升级，开始下载安装`, 'neutral', component.id);
          next = await loomClient.components.install(component.id, { confirmed: true, onProgress: (job) => recordJobProgress(job, component.id) });
          setSnapshot(next);
          const installed = next.components.find((item) => item.id === component.id);
          if (isOfficialCodexComponent(component) && installed?.status === 'manual_install_required') {
            const message = '等待 Microsoft Store 完成安装；完成后点击“重新检测”，再启动原版 ChatGPT Codex。';
            pushLog(message, 'warning', component.id);
            showToast(message, 'info');
            return;
          }
          next = await loomClient.components.detect(component.id, { onProgress: (job) => recordJobProgress(job, component.id) });
          setSnapshot(next);
        }
      } catch (error: any) {
        throw new Error(loomErrorText(error, `${component.name} 检测失败，已停止安装`));
      }

      const current = next.components.find((item) => item.id === component.id);
      if (!current || !['ready', 'started'].includes(current.status)) {
        throw new Error(current?.errorMessage || `${component.name} 安装后仍未就绪，请打开诊断查看原因`);
      }

      const modelStatus = await readAgentModelConfigStatus(component);
      const codexModelPending = component.id === 'codex-desktop' && !modelStatus?.configured;

      if (autoStart) {
        if (codexModelPending) {
          const pendingMessage = 'Codex 未写入 LOOM 模型配置，将沿用 Codex 当前配置或默认登录方式继续启动。';
          pushLog(pendingMessage, 'warning', component.id);
          showToast(pendingMessage, 'info');
        }
        const started = await loomClient.components.start(component.id, { onProgress: (job) => recordJobProgress(job, component.id) });
        setSnapshot(started);
        pushLog(`${component.name} 已检测、安装并启动`, 'ok', component.id);
        showToast(`${component.name} 已检测、安装并启动`, 'success');
      } else {
        pushLog(`${component.name} 已检测并安装就绪`, 'ok', component.id);
        showToast(`${component.name} 已检测并安装就绪`, 'success');
      }
      if (supportsModelConfig(component)) {
        void refreshModelConfig(component.id);
      }
    } catch (err: any) {
      const message = loomErrorText(err, err?.message || `${component.name} 准备失败`);
      pushLog(message, 'danger', component.id);
      showToast(message, 'error');
      await refresh();
      try {
        const report = await loomClient.diagnostics.prerequisites();
        setPreflight(report);
        saveCachedPreflight(report);
      } catch {
        // Keep the component error visible if diagnostics cannot be refreshed.
      }
    } finally {
      void refreshJobs();
      setBusyId('');
      setBusyAction('');
    }
  };

  const install = async (component: ComponentSummary) => {
    await prepareComponent(component, { autoStart: true });
  };

  const uninstall = async (component: ComponentSummary) => {
    const ok = await showConfirm({
      title: `卸载 ${component.name}`,
      message: '这会删除 LOOM 管理的安装目录；如果智能体提供官方卸载命令，也会一并执行。确定继续吗？',
      confirmText: '一键卸载',
      tone: 'danger',
    });
    if (!ok) return;
    setBusyId(component.id);
    setBusyAction('uninstall');
    try {
      pushLog(`开始卸载 ${component.name}`, 'warning', component.id);
      const next = await loomClient.components.uninstall(component.id, { onProgress: (job) => recordJobProgress(job, component.id) });
      setSnapshot(next);
      if (supportsModelConfig(component)) void refreshModelConfig(component.id);
      pushLog(`${component.name} 已卸载`, 'ok', component.id);
      showToast(`${component.name} 已卸载`, 'info');
    } catch (err: any) {
      const message = loomErrorText(err, '卸载失败');
      pushLog(message, 'danger', component.id);
      showToast(message, 'error');
      await refresh();
    } finally {
      void refreshJobs();
      setBusyId('');
      setBusyAction('');
    }
  };

  const detect = async (component: ComponentSummary) => {
    if (installActionsLocked) {
      const message = '安装清单未就绪，暂不能检测。请先刷新清单。';
      pushLog(message, 'warning', component.id);
      showToast(message, 'error');
      return;
    }
    setBusyId(component.id);
    setBusyAction('detect');
    try {
      pushLog(`开始检测 ${component.name}`, 'neutral', component.id);
      const next = await loomClient.components.detect(component.id, { onProgress: (job) => recordJobProgress(job, component.id) });
      setSnapshot(next);
      if (supportsModelConfig(component)) void refreshModelConfig(component.id);
      pushLog(`${component.name} 检测完成`, 'ok', component.id);
      showToast(`${component.name} 检测完成`, 'success');
    } catch (err: any) {
      const message = loomErrorText(err, '检测失败，请先安装或重新安装');
      pushLog(message, 'danger', component.id);
      showToast(message, 'error');
      await refresh();
    } finally {
      void refreshJobs();
      setBusyId('');
      setBusyAction('');
    }
  };

  const start = async (component: ComponentSummary) => {
    if (installActionsLocked) {
      const message = '安装清单未就绪，启动暂不可用。请先刷新清单。';
      pushLog(message, 'warning', component.id);
      showToast(message, 'error');
      return;
    }
    setBusyId(component.id);
    setBusyAction('start');
    try {
      pushLog(`开始启动 ${component.name}`, 'neutral', component.id);
      const modelStatus = await readAgentModelConfigStatus(component);
      if (component.id === 'codex-desktop' && !modelStatus?.configured) {
        const message = 'Codex 未写入 LOOM 模型配置，将沿用 Codex 当前配置或默认登录方式继续启动。';
        pushLog(message, 'warning', component.id);
        showToast(message, 'info');
      }
      const next = await loomClient.components.start(component.id, { onProgress: (job) => recordJobProgress(job, component.id) });
      setSnapshot(next);
      pushLog(`${component.name} 已提交启动`, 'ok', component.id);
      showToast(`${component.name} 已提交启动`, 'success');
    } catch (err: any) {
      const message = loomErrorText(err, '启动失败，请先检测安装状态');
      pushLog(message, 'danger', component.id);
      showToast(message, 'error');
      await refresh();
    } finally {
      void refreshJobs();
      setBusyId('');
      setBusyAction('');
    }
  };

  const updateModelDraft = (componentId: string, model: string) => {
    setModelDrafts((current) => ({ ...current, [componentId]: model }));
  };

  const beginModelConfigOperation = (componentId: string): boolean => {
    if (modelConfigBusyRef.current) return false;
    modelConfigBusyRef.current = componentId;
    modelConfigRequestGeneration.current[componentId] = (modelConfigRequestGeneration.current[componentId] || 0) + 1;
    setModelConfigBusy(componentId);
    return true;
  };

  const endModelConfigOperation = (componentId: string) => {
    if (modelConfigBusyRef.current === componentId) modelConfigBusyRef.current = '';
    setModelConfigBusy('');
  };

  const finishModelConfigChange = (
    component: ComponentSummary,
    status: AgentModelConfigStatus,
    channelLabel: string,
  ) => {
    setModelConfigFailurePrompt(null);
    setModelConfigs((current) => ({ ...current, [component.id]: status }));
    if (component.id === 'codex-desktop') {
      const prompt = {
        componentId: component.id,
        componentName: component.name,
        channelLabel,
      };
      setPendingModelRestart(prompt);
      setModelRestartPrompt(prompt);
      return true;
    }
    showToast(`${component.name} 已切换为 ${channelLabel}，下次启动生效`, 'success');
    return false;
  };

  const openModelConfigFailure = (
    component: ComponentSummary,
    error: unknown,
    fallback: string,
  ) => {
    const normalized = normalizeLoomError(error, fallback);
    const requiresLogin = normalized.code === 'account_relogin_required'
      || normalized.action === 'open_model_account'
      || normalized.message.includes('重新登录模型账号');
    setModelRestartPrompt(null);
    setModelConfigFailurePrompt({
      componentId: component.id,
      componentName: component.name,
      message: normalized.message,
      requiresLogin,
    });
    return normalized.message;
  };

  const disableModelConfig = async (component: ComponentSummary) => {
    if (component.id !== 'codex-desktop') {
      showToast('当前仅支持恢复 Codex 的 OpenAI 官方渠道', 'info');
      return;
    }
    if (!beginModelConfigOperation(component.id)) return;
    try {
      const result = await loomClient.components.disableModelConfig(component.id);
      finishModelConfigChange(component, result.status, 'OpenAI 官方渠道');
      setModelDrafts((current) => ({
        ...current,
        [component.id]: result.status.availableModels?.[0] || '',
      }));
      pushLog(`${component.name} 已恢复 OpenAI 官方渠道`, 'ok', component.id);
    } catch (err: any) {
      const message = loomErrorText(err, '恢复 OpenAI 官方渠道失败');
      pushLog(message, 'danger', component.id);
      showToast(message, 'error');
      await refreshModelConfig(component.id);
    } finally {
      endModelConfigOperation(component.id);
    }
  };

  const restartCodexAfterModelChange = async () => {
    const prompt = modelRestartPrompt;
    if (!prompt) return;
    const component = components.find((item) => item.id === prompt.componentId);
    if (!component) {
      setModelRestartPrompt(null);
      showToast('未找到 Codex 组件，请刷新后重试', 'error');
      return;
    }
    if (!beginModelConfigOperation(component.id)) return;
    setBusyId(component.id);
    setBusyAction('restart');
    try {
      pushLog(`正在重启 ${component.name} 以应用新配置`, 'neutral', component.id);
      const next = await loomClient.components.restart(component.id, {
        onProgress: (job) => recordJobProgress(job, component.id),
      });
      setSnapshot(next);
      await refreshModelConfig(component.id);
      setModelRestartPrompt(null);
      setPendingModelRestart(null);
      pushLog(`${component.name} 已重启，新配置已生效`, 'ok', component.id);
      showToast(`${component.name} 已重启`, 'success');
    } catch (err: any) {
      const message = loomErrorText(err, 'Codex 重启失败，请关闭官方应用后重试');
      pushLog(message, 'danger', component.id);
      showToast(message, 'error');
      await refresh();
    } finally {
      setBusyId('');
      setBusyAction('');
      endModelConfigOperation(component.id);
      void refreshJobs();
    }
  };

  const applyModelConfig = async (component: ComponentSummary) => {
    const model = (modelDrafts[component.id] || modelConfigs[component.id]?.model || '').trim();
    if (!model) {
      showToast('请先输入或选择模型', 'info');
      return;
    }
    if (!beginModelConfigOperation(component.id)) return;
    setModelConfigFailurePrompt(null);
    try {
      const result = await loomClient.components.applyModelConfig({ componentId: component.id, model });
      if (
        component.id === 'codex-desktop'
        && (!result.status.configured || !result.status.remoteVerified || result.status.transactionState !== 'committed')
      ) {
        throw new Error('模型配置未完成真实连通性验证，麓鸣没有将其设为可用');
      }
      finishModelConfigChange(component, result.status, `${APP_DISPLAY_NAME} 托管渠道`);
      setModelDrafts((current) => ({ ...current, [component.id]: result.status.model || model }));
      pushLog(`${component.name} 模型配置已写入`, 'ok', component.id);
    } catch (err: any) {
      const message = openModelConfigFailure(component, err, '模型配置写入失败');
      pushLog(message, 'danger', component.id);
      showToast(message, 'error');
      await refreshModelConfig(component.id);
    } finally {
      endModelConfigOperation(component.id);
    }
  };

  const applyCustomModelConfig = async (component: ComponentSummary, draft: AgentCustomProviderDraft) => {
    const provider = draft.provider.trim() || '自定义 Provider';
    const baseUrl = draft.baseUrl.trim();
    const apiKey = draft.apiKey.trim();
    const model = draft.model.trim();
    if (!baseUrl || !apiKey || !model) {
      showToast('请填写 Base URL、API Key 和默认文本模型', 'error');
      return;
    }
    if (!beginModelConfigOperation(component.id)) return;
    setModelConfigFailurePrompt(null);
    try {
      let message = '第三方模型配置已保存';
      if (canWriteAgentModelConfig(component, modelConfigs[component.id])) {
        const result = await loomClient.components.applyCustomModelConfig({
          componentId: component.id,
          provider,
          baseUrl,
          apiKey,
          model,
        });
        if (
          component.id === 'codex-desktop'
          && (!result.status.configured || !result.status.remoteVerified || result.status.transactionState !== 'committed')
        ) {
          throw new Error('第三方模型未完成真实连通性验证，麓鸣没有将其设为可用');
        }
        finishModelConfigChange(component, result.status, '自定义渠道');
        message = `${component.name} 第三方模型已保存并写入`;
      } else {
        await loomClient.wire.custom({ provider, baseUrl, apiKey, textModel: model, targets: [] });
        message = '第三方模型已保存；安装智能体后可写入配置';
        showToast(message, 'success');
      }
      setModelDrafts((current) => ({ ...current, [component.id]: model }));
      pushLog(message, 'ok', component.id);
    } catch (err: any) {
      const message = openModelConfigFailure(component, err, '第三方模型配置失败');
      pushLog(message, 'danger', component.id);
      showToast(message, 'error');
      await refreshModelConfig(component.id);
    } finally {
      endModelConfigOperation(component.id);
    }
  };

  const copyInstallLog = async () => {
    const text = formatInstallLogEntries(selectedLogEntries);
    if (!text) {
      showToast('暂无可复制的日志', 'info');
      return;
    }
    try {
      await navigator.clipboard.writeText(text);
      showToast('日志已复制', 'success');
    } catch {
      showToast('复制日志失败，请展开后手动选择复制', 'error');
    }
  };

  const exportInstallLog = () => {
    const text = formatInstallLogEntries(selectedLogEntries);
    if (!text) {
      showToast('暂无可导出的日志', 'info');
      return;
    }
    const blob = new Blob([text], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `loom-install-log-${new Date().toISOString().replace(/[:.]/g, '-')}.txt`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    showToast('日志已导出', 'success');
  };

  const openWeb = async (component: ComponentSummary) => {
    if (isOpenClawComponent(component)) {
      if (!['ready', 'started', 'upgrade_available'].includes(component.status)) {
        const message = '请先安装 OpenClaw，再打开网页版';
        pushLog(message, 'warning', component.id);
        showToast(message, 'error');
        return;
      }
      setBusyId(component.id);
      setBusyAction('open-web');
      try {
        const status = await loomClient.process.status();
        if (!status.running) {
          if (!status.starting) {
            await loomClient.process.start();
          }
          await loomClient.process.waitForReady({ timeoutMs: 180000, intervalMs: 800 });
        }
        window.open(OPENCLAW_WEB_URL, '_blank', 'noopener,noreferrer');
        pushLog('OpenClaw 网页版已打开', 'ok', component.id);
        showToast('OpenClaw 网页版已打开', 'success');
      } catch (err: any) {
        const detail = loomErrorText(err, '');
        const message = detail ? `OpenClaw 网页版启动失败：${detail}` : 'OpenClaw 网页版启动失败';
        pushLog(message, 'danger', component.id);
        showToast(message, 'error');
      } finally {
        setBusyId('');
        setBusyAction('');
      }
      return;
    }
    const url = componentWebUrl(component);
    if (!url) {
      showToast('暂无可打开的网页', 'info');
      return;
    }
    window.open(url, '_blank', 'noopener,noreferrer');
  };

  const activeBusyName = busyId
    ? components.find((item) => item.id === busyId)?.name || ''
    : modelConfigBusy
      ? components.find((item) => item.id === modelConfigBusy)?.name || ''
      : '';
  const preflightBusy = preflightLoading || preflightRepairing;
  const componentJobBusy = activeJobComponentIds.size > 0;
  const blockingBusy = loading;
  const busyOverlayActive = blockingBusy || preflightBusy || componentJobBusy || Boolean(modelConfigBusy);
  const pageLocked = loading;
  const controlsLocked = loading || Boolean(modelConfigBusy);
  const busyOverlayMode = (preflightBusy || componentJobBusy || Boolean(modelConfigBusy)) && !blockingBusy ? 'corner' : 'blocking';
  const busyOverlayTitle = busyAction === 'restart'
    ? '正在重启 Codex'
    : modelConfigBusy
    ? '正在写入模型配置'
    : preflightRepairing
    ? '正在修复前置环境'
    : preflightLoading
      ? '正在检测前置环境'
      : loading
        ? '正在读取安装清单'
        : busyAction === 'detect'
          ? '正在检测安装状态'
          : busyAction === 'open-web'
            ? '正在打开 OpenClaw 网页版'
            : busyAction === 'start'
              ? '正在启动智能体'
            : busyAction === 'uninstall'
              ? '正在卸载智能体'
              : '正在安装或升级智能体';
  const busyOverlayDetail = activeBusyName
    ? `${activeBusyName} 正在处理，请稍候。`
    : `${APP_DISPLAY_NAME} 正在检查本机环境和安装状态。`;

  return (
    <div
      data-agent-page-scroll
      data-installer-nonblocking
      data-installer-active-job={selectedBusy ? selected?.id : undefined}
      data-white-label-layout="installer"
      data-agent-page-locked={pageLocked ? 'true' : undefined}
      aria-busy={busyOverlayActive}
      className="loom-white-page loom-installer-shell h-full overflow-y-auto bg-app-bg"
    >
      <BusyOverlay active={busyOverlayActive} mode={busyOverlayMode} title={busyOverlayTitle} detail={busyOverlayDetail} />
      <div className="mx-auto flex w-full max-w-[1220px] flex-col gap-5 px-6 pb-7 pt-7 xl:px-8">
        <header className="flex flex-wrap items-end justify-between gap-6">
          <div>
            <div className="text-[11px] font-bold tracking-[0.18em] text-accent">安装</div>
            <h1 className="mt-2 text-[30px] font-black leading-tight text-text">安装智能体</h1>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-text-muted">
              选择一个智能体安装、更新或启动。必要环境会在操作时自动检测。
            </p>
          </div>
          <div className="flex items-center gap-3">
            <span className="rounded-full border border-border/70 bg-surface-alt/50 px-3 py-2 text-xs font-bold text-text">
              {readyCount}/{components.length} 已就绪
            </span>
            <Button
              variant="quiet"
              onClick={() => {
                void refresh();
                if (selected) void refreshModelConfig(selected.id);
              }}
              disabled={controlsLocked}
            >
              刷新
            </Button>
          </div>
        </header>

        <section data-agent-page-shell className="loom-panel loom-installer-stage border-y border-border/80 bg-surface/55">
          {snapshot?.warning ? (
            <div className="border-b border-border/70 px-6 py-4 text-sm text-status-warning">
              {snapshot.warning}
            </div>
          ) : null}

          {preflightError ? (
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-status-danger/25 bg-status-danger/10 px-6 py-3 text-sm text-status-danger">
              <span>{preflightError}</span>
              <div className="flex gap-2">
                <Button variant="quiet" onClick={() => void refreshPreflight({ force: true })} disabled={preflightLoading || preflightRepairing}>
                  重新检测
                </Button>
                <Button variant="primary" onClick={() => void repairPreflight()} disabled={preflightLoading || preflightRepairing}>
                  修复环境
                </Button>
              </div>
            </div>
          ) : null}

          <section className="px-6 py-6">
            <div className="flex flex-wrap items-end justify-between gap-4">
              <div>
                <div className="text-[10px] font-bold tracking-[0.24em] text-text-subtle">可安装智能体</div>
                <h2 className="mt-1 text-2xl font-black text-text">Codex / Claude Code / opencode / OpenClaw / Hermes</h2>
              </div>
              {error ? <span className="text-sm font-bold text-status-danger">{error}</span> : null}
            </div>

            <div className="mt-5 grid w-full min-w-0 grid-cols-[minmax(0,1fr)] gap-6 lg:grid-cols-[minmax(0,0.92fr)_minmax(420px,1.08fr)]">
              <div>
                {loading ? (
                  <div className="border-t border-border/70 py-5 text-sm text-text-muted">正在读取安装清单...</div>
                ) : (
                  <div className="border-y border-border/70 bg-surface/30">
                    {components.map((component, index) => (
                      <button
                        type="button"
                        key={component.id}
                        onClick={() => setSelectedId(component.id)}
                        disabled={controlsLocked}
                        className={`flex w-full items-center gap-4 border-b border-border/60 px-4 py-4 text-left transition last:border-b-0 ${
                          selected?.id === component.id
                            ? 'bg-accent/[0.07]'
                            : controlsLocked ? '' : 'hover:bg-surface-alt/45'
                        }`}
                      >
                        <span className="w-5 text-center text-xs font-black text-text-subtle">{index + 1}</span>
                        <AgentLogo id={component.id} />
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-base font-black text-text">{component.name}</span>
                          <span className="mt-1 block truncate text-xs text-text-muted">{component.description || component.id}</span>
                        </span>
                        <span className={`inline-flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-bold ${statusClass(component.status)}`}>
                          {isWorking(component.status) ? <ActivityRing /> : null}
                          {displayStatusLabel(component.status)}
                        </span>
                      </button>
                    ))}
                  </div>
                )}
              </div>

              <div className="min-w-0 border-t border-border/70 pt-5 lg:border-l lg:border-t-0 lg:pl-6 lg:pt-0">
                {selected ? (
                  <div className="space-y-6">
                    <div className="flex items-start justify-between gap-5">
                      <div className="flex min-w-0 items-start gap-4">
                        <AgentLogo id={selected.id} size="large" />
                        <div className="min-w-0">
                          <div className="text-[11px] font-bold uppercase tracking-[0.3em] text-text-subtle">
                            {selected.category || 'component'} / {selected.platform} / {selected.arch}
                          </div>
                          <h2 className="mt-2 truncate text-[34px] font-black leading-tight text-text">{selected.name}</h2>
                          <p className="mt-2 max-w-2xl text-sm leading-6 text-text-muted">{selected.description || selected.id}</p>
                        </div>
                      </div>
                      <span className={`rounded-full border px-3 py-1.5 text-xs font-black ${statusClass(selected.status)}`}>
                        {displayStatusLabel(selected.status)}
                      </span>
                    </div>

                    <div className="grid grid-cols-2 gap-x-5 gap-y-4 xl:grid-cols-4">
                      <InfoTile label="版本" value={selected.version} />
                      <InfoTile label="已安装" value={selected.installedVersion || '-'} />
                      <InfoTile label="大小" value={formatSize(selected.size)} />
                      <InfoTile label="类型" value={selected.type} />
                    </div>

                    {installActionsLocked ? (
                      <div className="rounded-[16px] border border-status-warning/30 bg-status-warning/10 p-4 text-sm font-bold text-status-warning">
                        安装清单未就绪，暂时不能安装或启动。请刷新后重试。
                      </div>
                    ) : selected.errorMessage ? (
                      <div className="rounded-[16px] border border-status-danger/30 bg-status-danger/10 p-4 text-sm text-status-danger">
                        {selected.errorMessage}
                      </div>
                    ) : isWorking(selected.status) ? (
                      <div data-installer-job-progress className="rounded-[16px] border border-[#0B4A3E]/30 bg-[#0B4A3E]/10 p-4 text-sm font-bold text-[#0B4A3E]">
                        <span className="inline-flex items-center gap-2">
                          <ActivityRing />
                          {selectedActiveJob?.progress?.message || selectedActiveJob?.message || displayStatusLabel(selected.status)}
                        </span>
                      </div>
                    ) : selected.status === 'upgrade_available' ? (
                      <div className="rounded-[16px] border border-status-success/35 bg-status-success/10 p-4 text-sm font-bold text-status-success">
                        检测到可升级版本。点击下方绿色“升级并启动”即可更新并启动。
                      </div>
                    ) : selected.status === 'ready' || selected.status === 'started' ? (
                      <div className="rounded-[16px] border border-status-success/30 bg-status-success/10 p-4 text-sm text-status-success">
                        {selected.status === 'started' ? '已启动' : '已安装，可启动'}
                      </div>
                    ) : selected.status === 'simulation_ready' ? (
                      <div className="rounded-[16px] border border-border/70 bg-surface-alt/50 p-4 text-sm text-text-muted">
                        还没确认本机安装状态。可以直接点击“安装”，LOOM 会先检测必要环境。
                      </div>
                    ) : selected.status === 'manual_install_required' ? (
                      <div className="rounded-[16px] border border-border/70 bg-surface-alt/50 p-4 text-sm text-text-muted">
                        {isOfficialCodexComponent(selected)
                          ? '等待 Microsoft Store 完成安装。安装结束后点击“重新检测”，再启动原版 ChatGPT Codex。'
                          : '已发现本机安装器。建议点击“安装”接管流程，完成后再启动。'}
                      </div>
                    ) : null}

                    <div className="flex flex-wrap gap-3">
                      <Button
                        variant={installActionsLocked ? 'quiet' : 'primary'}
                        className="min-w-[132px]"
                        onClick={() => void (primaryAgentAction(selected) === 'start' ? start(selected) : install(selected))}
                        disabled={controlsLocked || installActionsLocked || isWorking(selected.status)}
                      >
                        {installActionsLocked ? '清单未就绪' : primaryAgentButtonLabel(selected, busyId, busyAction)}
                      </Button>
                      <Button
                        variant="quiet"
                        onClick={() => detect(selected)}
                        disabled={controlsLocked || installActionsLocked || isWorking(selected.status)}
                      >
                        {installActionsLocked ? '等待清单' : busyId === selected.id && busyAction === 'detect' ? '检测中...' : '重新检测'}
                      </Button>
                      {isOpenClawComponent(selected) ? (
                        <Button
                          data-agent-open-web-button
                          variant="quiet"
                          onClick={() => void openWeb(selected)}
                          disabled={controlsLocked || installActionsLocked || !isComponentInstalled(selected)}
                        >
                          打开网页
                        </Button>
                      ) : null}
                      {['ready', 'started'].includes(selected.status) ? (
                        <Button
                          variant="quiet"
                          onClick={() => install(selected)}
                          disabled={controlsLocked || installActionsLocked || isWorking(selected.status)}
                        >
                          {busyId === selected.id && busyAction === 'prepare' ? '安装中...' : '重新安装'}
                        </Button>
                      ) : null}
                      {isFailedStatus(selected.status) ? (
                        <Button
                          data-agent-retry-button
                          variant="danger"
                          onClick={() => install(selected)}
                          disabled={controlsLocked || installActionsLocked || isWorking(selected.status)}
                        >
                          重试安装
                        </Button>
                      ) : null}
                    </div>

                    {supportsModelConfig(selected) ? (
                      <AgentModelConfigPanel
                        key={selected.id}
                        component={selected}
                        status={selectedModelConfig}
                        draftModel={selectedModelDraft}
                        busy={modelConfigBusy === selected.id}
                        locked={controlsLocked}
                        onDraftModelChange={(value) => updateModelDraft(selected.id, value)}
                        onDisable={() => void disableModelConfig(selected)}
                        onApply={() => void applyModelConfig(selected)}
                        onApplyCustom={(draft) => void applyCustomModelConfig(selected, draft)}
                      />
                    ) : null}

                    {pendingModelRestart?.componentId === selected.id && !modelRestartPrompt ? (
                      <div
                        data-agent-model-restart-pending
                        className="flex max-w-[min(420px,calc(100vw-40px))] flex-wrap items-center justify-between gap-3 rounded-[8px] border border-status-warning/35 bg-[#FFFCF4] px-4 py-3 text-xs font-bold text-status-warning shadow-[0_20px_60px_rgba(5,35,29,0.28)]"
                        style={{
                          position: 'fixed',
                          bottom: '20px',
                          right: '20px',
                          zIndex: 2_147_482_000,
                        }}
                      >
                        <span>配置已写入，当前运行中的 Codex 仍需重启后生效。</span>
                        <Button variant="quiet" onClick={() => setModelRestartPrompt(pendingModelRestart)} disabled={Boolean(modelConfigBusy)}>
                          重启 Codex
                        </Button>
                      </div>
                    ) : null}

                    <section data-agent-danger-zone className="border-t border-border/70 pt-4">
                      <div className="flex flex-wrap items-center justify-between gap-4">
                        <div>
                          <div className="text-sm font-black text-text">更多操作</div>
                          <div className="mt-1 text-xs text-text-subtle">
                            {isOfficialCodexComponent(selected)
                              ? '原版应用请在 Windows 设置中卸载。'
                              : '卸载只移除由 LOOM 管理的智能体文件。'}
                          </div>
                        </div>
                        <div className="flex flex-wrap gap-3">
                          {!isOfficialCodexComponent(selected) ? (
                            <Button
                              variant="quiet"
                              onClick={() => uninstall(selected)}
                              disabled={controlsLocked || installActionsLocked || isWorking(selected.status) || selected.status === 'not_installed'}
                            >
                              {busyId === selected.id && busyAction === 'uninstall' ? '卸载中...' : `卸载 ${selected.name}`}
                            </Button>
                          ) : null}
                        </div>
                      </div>
                    </section>

                    <details data-agent-log-panel className="border-t border-border/70 pt-4">
                      <summary data-agent-log-summary className="cursor-pointer text-sm font-black text-text">
                        <span className="ml-2 inline-flex flex-wrap items-baseline gap-x-3 gap-y-1">
                          <span>安装日志</span>
                          <span className="text-xs font-medium text-text-subtle">
                            {selectedLogEntries.length
                              ? `${selectedLogOperations.length} 个操作，${selectedLogEntries.length} 条记录`
                              : '暂无记录'}
                          </span>
                        </span>
                      </summary>
                      <div className="pt-4">
                        <div className="flex flex-wrap justify-end gap-2">
                          <Button data-agent-copy-log-button variant="quiet" onClick={() => void copyInstallLog()} disabled={!selectedLogEntries.length}>
                            复制日志
                          </Button>
                          <Button data-agent-export-log-button variant="quiet" onClick={exportInstallLog} disabled={!selectedLogEntries.length}>
                            导出日志
                          </Button>
                          <Button variant="quiet" onClick={() => void refreshJobs()} disabled={controlsLocked}>
                            刷新日志
                          </Button>
                        </div>
                        {logError ? (
                          <div className="mt-3 rounded-[12px] border border-status-warning/30 bg-status-warning/10 px-3 py-2 text-xs text-status-warning">
                            {logError}
                          </div>
                        ) : null}
                        <div className="mt-4 space-y-5">
                          {selectedLogOperations.length ? (
                            selectedLogOperations.map((operation) => (
                              <div key={operation.id} data-agent-log-operation>
                                <div className="text-xs font-black text-text">{operation.label}</div>
                                <div className="mt-2 border-l border-border/80 pl-4">
                                  {operation.entries.map((entry) => (
                                    <div key={entry.id} className="mb-3 last:mb-0">
                                      <div className="text-[11px] font-bold text-text-subtle">{entry.time}</div>
                                      <div className={`mt-1 text-xs leading-5 ${toneClass(entry.tone)}`}>{entry.message}</div>
                                    </div>
                                  ))}
                                </div>
                              </div>
                            ))
                          ) : (
                            <div className="py-3 text-xs leading-5 text-text-muted">
                              等待安装任务。点击“安装”“升级”或“启动”后，这里会显示实时进度和失败原因。
                            </div>
                          )}
                        </div>
                      </div>
                    </details>

                    <details data-agent-advanced-settings className="border-t border-border/70 pt-4">
                      <summary className="cursor-pointer text-sm font-bold text-text">高级详情</summary>
                      <div className="mt-4 space-y-2 text-xs text-text-muted">
                        <div className="font-mono">id: {selected.id}</div>
                        <div className="font-mono">entry: {selected.entry || '-'}</div>
                        <div className="font-mono">installPath: {selected.installPath || '-'}</div>
                        {selected.installCommand?.length ? (
                          <div className="break-all font-mono">install: {selected.installCommand.join(' ')}</div>
                        ) : null}
                        {selected.uninstallCommand?.length ? (
                          <div className="break-all font-mono">uninstall: {selected.uninstallCommand.join(' ')}</div>
                        ) : null}
                        {selected.officialUrl ? (
                          <button
                            type="button"
                            onClick={() => window.open(selected.officialUrl || '', '_blank', 'noopener,noreferrer')}
                            className="font-mono text-accent hover:text-accent-hover"
                          >
                            officialUrl: {selected.officialUrl}
                          </button>
                        ) : null}
                        {selected.urls.slice(0, 4).map((url) => (
                          <div key={url} className="truncate font-mono" title={url}>{url}</div>
                        ))}
                      </div>
                    </details>
                  </div>
                ) : (
                  <div className="py-10 text-sm text-text-muted">选择一个智能体</div>
                )}
              </div>
            </div>
          </section>
        </section>
      </div>
      <Modal
        isOpen={Boolean(modelRestartPrompt)}
        onClose={() => {
          if (!modelConfigBusy) setModelRestartPrompt(null);
        }}
        title="重启 Codex 使配置生效"
      >
        <div data-agent-model-restart-dialog data-agent-model-restart-wall>
          <div className="border-y border-status-success/30 bg-status-success/10 px-4 py-4">
            <div className="text-sm font-black text-status-success">配置已写入</div>
            <p className="mt-2 text-sm leading-6 text-text-muted">
            {modelRestartPrompt?.componentName || 'Codex'} 已切换为
              <span className="font-black text-text"> {modelRestartPrompt?.channelLabel || '新渠道'}</span>。配置已经完成真实校验并写入本机，重启 Codex 后生效。
            </p>
          </div>
          <div className="mt-5 flex flex-wrap justify-end gap-3">
            <Button
              variant="quiet"
              onClick={() => setModelRestartPrompt(null)}
              disabled={Boolean(modelConfigBusy)}
            >
              稍后重启
            </Button>
            <Button
              variant="primary"
              onClick={() => void restartCodexAfterModelChange()}
              disabled={Boolean(modelConfigBusy)}
            >
              {busyAction === 'restart' ? '重启中...' : '重启 Codex'}
            </Button>
          </div>
        </div>
      </Modal>
      <Modal
        isOpen={Boolean(modelConfigFailurePrompt)}
        onClose={() => {
          if (!modelConfigBusy) setModelConfigFailurePrompt(null);
        }}
        title="配置未写入"
      >
        <div data-agent-model-write-failure-dialog>
          <div className="border-y border-status-danger/30 bg-status-danger/10 px-4 py-4">
            <div className="text-sm font-black text-status-danger">Codex 当前配置没有被修改</div>
            <p className="mt-2 text-sm leading-6 text-text-muted">
              {modelConfigFailurePrompt?.message || '模型配置写入失败，请检查后重试。'}
            </p>
          </div>
          <div className="mt-5 flex flex-wrap justify-end gap-3">
            <Button
              variant="quiet"
              onClick={() => setModelConfigFailurePrompt(null)}
              disabled={Boolean(modelConfigBusy)}
            >
              关闭
            </Button>
            {modelConfigFailurePrompt?.requiresLogin ? (
              <Button
                variant="primary"
                onClick={() => {
                  setModelConfigFailurePrompt(null);
                  setCurrentPage('license');
                }}
                disabled={Boolean(modelConfigBusy)}
              >
                重新登录模型账号
              </Button>
            ) : null}
          </div>
        </div>
      </Modal>
    </div>
  );
};
