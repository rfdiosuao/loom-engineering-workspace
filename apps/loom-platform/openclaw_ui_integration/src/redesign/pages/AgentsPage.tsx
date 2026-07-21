import React from 'react';
import { Bot, CheckCircle2, Download, ExternalLink, RefreshCcw, RotateCcw } from 'lucide-react';
import { Button, Chip, EmptyState, InlineState, Panel, SectionHeader, cx } from '../components/ui';
import { installComponent, loadComponentsSnapshot, rollbackComponent } from '../api/adapters';
import { useAsync } from '../lib/useAsync';
import { formatDateTime } from '../lib/format';
import { usePreviewStore } from '../store/appStore';
import type { ComponentSummary, StatusTone } from '../types';

const AGENT_ORDER = ['codex-desktop', 'claude-code', 'opencode', 'openclaw-companion', 'hermes'];

function statusTone(status: string): Exclude<StatusTone, 'busy'> | 'neutral' {
  if (status === 'ready') return 'ok';
  if (status.endsWith('_failed')) return 'danger';
  if (status === 'not_installed') return 'warn';
  return 'neutral';
}

function statusLabel(status: string): string {
  const labels: Record<string, string> = {
    ready: '已就绪',
    not_installed: '未安装',
    resolving_manifest: '准备中',
    downloading: '下载中',
    verifying: '校验中',
    extracting: '安装中',
    configuring: '配置中',
    health_checking: '检测中',
    rollback_available: '可回滚',
    download_failed: '下载失败',
    verify_failed: '校验失败',
    extract_failed: '安装失败',
    config_failed: '配置失败',
    health_failed: '检测失败',
  };
  return labels[status] || status;
}

function formatSize(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return '-';
  if (value >= 1024 * 1024 * 1024) return `${(value / 1024 / 1024 / 1024).toFixed(1)} GB`;
  if (value >= 1024 * 1024) return `${(value / 1024 / 1024).toFixed(0)} MB`;
  return `${Math.ceil(value / 1024)} KB`;
}

function sortAgents(components: ComponentSummary[]): ComponentSummary[] {
  return [...components].sort((a, b) => {
    const ai = AGENT_ORDER.indexOf(a.id);
    const bi = AGENT_ORDER.indexOf(b.id);
    const ax = ai === -1 ? 999 : ai;
    const bx = bi === -1 ? 999 : bi;
    if (ax !== bx) return ax - bx;
    return a.name.localeCompare(b.name);
  });
}

function isWorking(status: string): boolean {
  return ['resolving_manifest', 'downloading', 'verifying', 'extracting', 'configuring', 'health_checking'].includes(status);
}

export function AgentsPage() {
  const settings = usePreviewStore((state) => state.settings);
  const pushToast = usePreviewStore((state) => state.pushToast);
  const { data, loading, error, refresh } = useAsync(() => loadComponentsSnapshot(settings), [settings], { cacheKey: 'components' });
  const agents = sortAgents((data?.components || []).filter((component) => component.category === 'agent'));
  const [selectedId, setSelectedId] = React.useState('');
  const [busyId, setBusyId] = React.useState('');

  React.useEffect(() => {
    if (!selectedId && agents.length) setSelectedId(agents[0].id);
  }, [agents, selectedId]);

  const selected = agents.find((component) => component.id === selectedId) || agents[0] || null;
  const readyCount = agents.filter((component) => component.status === 'ready').length;

  const handleInstall = async (component: ComponentSummary) => {
    setBusyId(component.id);
    try {
      await installComponent(settings, component.id);
      pushToast({ tone: 'ok', title: '组件已就绪', detail: component.name });
      refresh();
    } catch (err) {
      pushToast({ tone: 'danger', title: '安装失败', detail: component.name, diagnostic: String(err) });
      refresh();
    } finally {
      setBusyId('');
    }
  };

  const handleRollback = async (component: ComponentSummary) => {
    setBusyId(component.id);
    try {
      await rollbackComponent(settings, component.id);
      pushToast({ tone: 'warn', title: '已回滚组件', detail: component.name });
      refresh();
    } catch (err) {
      pushToast({ tone: 'danger', title: '回滚失败', detail: component.name, diagnostic: String(err) });
    } finally {
      setBusyId('');
    }
  };

  return (
    <div className="page-grid agents-page">
      <section className="hero-band agents-hero">
        <div className="hero-copy">
          <div className="eyebrow">Agents</div>
          <h1>智能体安装</h1>
          <p>Codex、Claude Code、opencode、OpenClaw、Hermes。</p>
        </div>
        <div className="hero-actions">
          <Chip tone={readyCount === agents.length && agents.length ? 'ok' : 'warn'}>{readyCount}/{agents.length} 已就绪</Chip>
          <Button variant="quiet" icon={RefreshCcw} onClick={refresh}>刷新</Button>
        </div>
      </section>

      {error ? <InlineState tone="danger" title="组件目录读取失败" description={error} /> : null}
      {data?.error ? <InlineState tone="warn" title="Manifest 不可用" description={data.error} /> : null}

      <section className="agents-layout">
        <Panel className="surface-panel agents-list-panel">
          <SectionHeader eyebrow="列表" title="可安装智能体" subtitle={data?.manifest ? `Manifest ${data.manifest.version}` : '等待 manifest'} />
          {loading ? (
            <div className="panel-loading-inline">正在读取组件目录...</div>
          ) : agents.length ? (
            <div className="agent-list">
              {agents.map((component) => (
                <button
                  key={component.id}
                  type="button"
                  className={cx('agent-row', selected?.id === component.id && 'agent-row-active')}
                  onClick={() => setSelectedId(component.id)}
                >
                  <span className="agent-icon"><Bot size={18} /></span>
                  <span className="agent-row-copy">
                    <strong>{component.name}</strong>
                    <span>{component.description || component.id}</span>
                  </span>
                  <Chip tone={statusTone(component.status)}>{statusLabel(component.status)}</Chip>
                </button>
              ))}
            </div>
          ) : (
            <EmptyState title="暂无智能体" description="manifest 中没有 agent 组件。" />
          )}
        </Panel>

        <Panel className="surface-panel agent-detail-panel">
          {selected ? (
            <>
              <div className="agent-detail-head">
                <div className="agent-detail-title">
                  <span className="agent-detail-icon"><Bot size={24} /></span>
                  <div>
                    <div className="eyebrow">{selected.platform} / {selected.arch}</div>
                    <h2>{selected.name}</h2>
                  </div>
                </div>
                <Chip tone={statusTone(selected.status)}>{statusLabel(selected.status)}</Chip>
              </div>

              <div className="agent-meta-grid">
                <div><span>版本</span><strong>{selected.version}</strong></div>
                <div><span>已安装</span><strong>{selected.installedVersion || '-'}</strong></div>
                <div><span>大小</span><strong>{formatSize(selected.size)}</strong></div>
                <div><span>类型</span><strong>{selected.type}</strong></div>
              </div>

              <div className="agent-source-list">
                {selected.urls.map((url) => (
                  <div key={url} title={url}>{url}</div>
                ))}
              </div>

              {selected.errorMessage ? (
                <InlineState tone="danger" title={selected.errorCode || '组件错误'} description={selected.errorMessage} />
              ) : isWorking(selected.status) ? (
                <InlineState tone="neutral" title={statusLabel(selected.status)} description={selected.jobId ? `任务 ${selected.jobId}` : '后台任务执行中'} />
              ) : selected.status === 'ready' ? (
                <InlineState tone="ok" icon={CheckCircle2} title="组件可用" description={selected.entry || selected.installPath} />
              ) : (
                <InlineState tone="warn" title="尚未安装" description="点击安装后会下载、校验并写入组件目录。" />
              )}

              <div className="button-row">
                <Button variant="primary" icon={Download} disabled={busyId === selected.id || isWorking(selected.status)} onClick={() => handleInstall(selected)}>
                  {busyId === selected.id || isWorking(selected.status) ? '安装中...' : selected.status === 'ready' ? '重新安装' : '安装'}
                </Button>
                {selected.officialUrl ? (
                  <Button variant="quiet" icon={ExternalLink} onClick={() => window.open(selected.officialUrl || '', '_blank', 'noopener,noreferrer')}>
                    官网
                  </Button>
                ) : null}
                <Button variant="quiet" icon={RotateCcw} disabled={busyId === selected.id || !selected.previousVersion} onClick={() => handleRollback(selected)}>
                  回滚
                </Button>
              </div>

              {selected.updatedAt ? <div className="muted-line">最近更新 {formatDateTime(selected.updatedAt)}</div> : null}
            </>
          ) : (
            <EmptyState title="选择智能体" />
          )}
        </Panel>
      </section>
    </div>
  );
}
