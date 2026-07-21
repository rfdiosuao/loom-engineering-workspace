import React from 'react';
import { Download, RefreshCcw, Server, StopCircle, Trash2 } from 'lucide-react';
import { Button, CodeBlock, cx, EmptyState, InlineState, Panel, SectionHeader, StatTile } from '../components/ui';
import { useAsync } from '../lib/useAsync';
import { loadServiceSnapshot, clearLogs, loadUpdateSnapshot, runUpdate, startProcess, stopProcess } from '../api/adapters';
import { usePreviewStore } from '../store/appStore';
import { translateError } from '../lib/errors';
import { shortenPaths } from '../lib/format';
import type { ServiceSnapshot } from '../types';

// While a start/stop is in flight (or the bridge is still mid-transition),
// poll the snapshot so the progress strip moves without the user hitting 刷新.
const PROGRESS_POLL_MS = 1500;

export function ServicePage() {
  const settings = usePreviewStore((state) => state.settings);
  const pushToast = usePreviewStore((state) => state.pushToast);
  const { data, loading, error, refresh } = useAsync(() => loadServiceSnapshot(settings), [settings], { cacheKey: "service" });
  const [updating, setUpdating] = React.useState(false);
  // 'start' | 'stop' while that request is in flight; disables both buttons.
  const [actionPending, setActionPending] = React.useState<'start' | 'stop' | null>(null);
  const [actionFailed, setActionFailed] = React.useState<{ kind: 'start' | 'stop'; hint: string; diagnostic: string } | null>(null);

  // A request is "in flight" the moment the button is clicked; a transition is
  // still "in progress" afterwards as long as the bridge reports startupState
  // running/starting and hasn't settled into idle/stopped/ready yet.
  const transitioning = Boolean(
    actionPending || (data && data.startupState && !['idle', 'stopped', 'ready'].includes(String(data.startupState).toLowerCase()) && !data.startupError)
  );

  React.useEffect(() => {
    if (!transitioning) return;
    const timer = window.setInterval(() => refresh(), PROGRESS_POLL_MS);
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [transitioning]);

  const handleStart = async () => {
    setActionFailed(null);
    setActionPending('start');
    try {
      await startProcess(settings);
      pushToast({ tone: 'ok', title: '核心服务已启动', detail: '进程接口已接收启动指令。' });
      refresh();
    } catch (err) {
      const friendly = translateError(err);
      pushToast({ tone: 'danger', title: '启动失败', detail: friendly.hint, diagnostic: friendly.diagnostic, logRoute: friendly.logRoute || 'service' });
      setActionFailed({ kind: 'start', hint: friendly.hint, diagnostic: friendly.diagnostic });
    } finally {
      setActionPending(null);
    }
  };

  const handleStop = async () => {
    setActionFailed(null);
    setActionPending('stop');
    try {
      await stopProcess(settings);
      pushToast({ tone: 'warn', title: '核心服务已停止', detail: '进程已回到空闲状态。' });
      refresh();
    } catch (err) {
      const friendly = translateError(err);
      pushToast({ tone: 'danger', title: '停止失败', detail: friendly.hint, diagnostic: friendly.diagnostic, logRoute: friendly.logRoute || 'service' });
      setActionFailed({ kind: 'stop', hint: friendly.hint, diagnostic: friendly.diagnostic });
    } finally {
      setActionPending(null);
    }
  };

  const handleRetry = () => {
    setActionFailed(null);
    if (actionFailed?.kind === 'stop') {
      handleStop();
    } else {
      handleStart();
    }
  };

  const handleClearLogs = async () => {
    try {
      await clearLogs(settings);
      pushToast({ tone: 'warn', title: '日志已清空', detail: '当前日志缓冲区已经清空。' });
      refresh();
    } catch (err) {
      const f = translateError(err);
      pushToast({ tone: 'danger', title: '清空失败', detail: f.hint, diagnostic: f.diagnostic, logRoute: f.logRoute });
    }
  };

  const handleUpdate = async () => {
    setUpdating(true);
    try {
      const check = await loadUpdateSnapshot(settings);
      if (!check.data?.hasUpdate) {
        pushToast({ tone: 'ok', title: '暂无更新', detail: `${check.data?.current || '当前版本'} 已是最新。` });
        return;
      }
      const result = await runUpdate(settings);
      pushToast({ tone: result.data?.success ? 'ok' : 'danger', title: '更新完成', detail: result.data?.current_version || '未知版本' });
      refresh();
    } catch (err) {
      const f = translateError(err);
      pushToast({ tone: 'danger', title: '更新失败', detail: f.hint, diagnostic: f.diagnostic, logRoute: f.logRoute });
    } finally {
      setUpdating(false);
    }
  };

  return (
    <div className="page-grid">
      <section className="hero-band">
        <div className="hero-copy">
          <div className="eyebrow">运行时 / CLI</div>
          <h1>启动 OpenClaw 核心服务，并保留 CLI 与日志。</h1>
          <p>这里是原启动器运行时能力的预览重排：启动、停止、日志、更新和系统信息都对齐同一套桥接接口。</p>
        </div>
        <div className="hero-actions">
          {data?.running ? (
            <Button variant="danger" icon={StopCircle} onClick={handleStop} disabled={actionPending !== null}>
              {actionPending === 'stop' ? '停止中...' : '停止'}
            </Button>
          ) : (
            <Button variant="primary" icon={Server} onClick={handleStart} disabled={actionPending !== null}>
              {actionPending === 'start' ? '启动中...' : '启动'}
            </Button>
          )}
          <Button variant="quiet" icon={RefreshCcw} onClick={refresh}>
            刷新
          </Button>
          <Button variant="secondary" icon={Download} onClick={handleUpdate} disabled={updating}>
            {updating ? '检查中...' : '检查核心更新'}
          </Button>
        </div>
      </section>

      {transitioning ? (
        <ProgressStrip data={data} actionPending={actionPending} actionFailed={actionFailed} onRetry={handleRetry} />
      ) : null}

      <section className="stats-grid">
        <StatTile label="进程" value={data?.running ? '运行中' : '已停止'} hint={data?.pid ? `PID ${data.pid}` : '没有活动 PID'} tone={data?.running ? 'ok' : 'warn'} />
        <StatTile label="启动状态" value={toCnState(data?.startupState || 'idle')} hint={`${data?.startupElapsedSec ?? 0}s / ${data?.startupTimeoutSec ?? 420}s`} tone={data?.startupState === 'running' ? 'warn' : 'neutral'} />
        <StatTile label="桥接" value={data?.portReady ? '就绪' : '等待中'} hint={toCnState(data?.startupStage || '暂无阶段')} tone={data?.portReady ? 'ok' : 'warn'} />
        <StatTile label="日志" value={data?.logTail.length || 0} hint="最近输出行数" tone="neutral" />
      </section>

      {loading ? (
        <Panel className="panel-loading">正在读取服务详情...</Panel>
      ) : error ? (
        <Panel className="panel-error">
          <InlineState tone="danger" title="服务状态读取失败" description={error} />
        </Panel>
      ) : data ? (
        <section className="content-grid content-grid-service">
          <Panel className="surface-panel">
            <SectionHeader eyebrow="进程" title="核心服务状态" subtitle="服务是否正常；异常时直接看处理按钮。" />
            <div className="detail-stack">
              {data.startupError ? (
                <InlineState tone="danger" title="异常原因" description={data.startupError} />
              ) : (
                <InlineState tone={data.running ? 'ok' : 'neutral'} title={data.running ? '服务正常' : '服务未运行'} description={data.running ? `已就绪，PID ${data.pid ?? '未知'}` : '点击上方“启动”即可开始。'} />
              )}
              {data.startupError ? (
                <div className="button-row">
                  <Button variant="primary" icon={Server} onClick={handleRetry} disabled={actionPending !== null}>
                    {actionPending ? '处理中...' : '重试启动'}
                  </Button>
                </div>
              ) : null}
            </div>

            <details className="settings-details">
              <summary>高级排障</summary>
              <div className="detail-stack">
                <div className="detail-row"><span className="detail-label">状态</span><span className="detail-value">{toCnState(data.statusLabel)}</span></div>
                <div className="detail-row"><span className="detail-label">PID</span><span className="detail-value">{data.pid ?? '未知'}</span></div>
                <div className="detail-row"><span className="detail-label">阶段</span><span className="detail-value">{toCnState(data.startupStage)}</span></div>
                <div className="detail-row"><span className="detail-label">网关模式</span><span className="detail-value">{toCnState(data.licenseGate)}</span></div>
                <div className="detail-row"><span className="detail-label">超时秒数</span><span className="detail-value">{data.startupTimeoutSec ?? 420}s</span></div>
                <div className="detail-row"><span className="detail-label">Node 路径</span><span className="detail-value">{shortenPaths(data.system.nodePath)}</span></div>
                <div className="detail-row"><span className="detail-label">根路径</span><span className="detail-value">{shortenPaths(data.system.basePath)}</span></div>
                <div className="detail-row"><span className="detail-label">版本</span><span className="detail-value">{data.system.version}</span></div>
                <div className="detail-row"><span className="detail-label">日志来源</span><span className="detail-value">{toCnState(data.source)}</span></div>
                <div className="detail-row"><span className="detail-label">桥接</span><span className="detail-value">{data.portReady ? '就绪' : '等待中'}</span></div>
              </div>
            </details>
          </Panel>

          <Panel className="surface-panel">
            <SectionHeader eyebrow="CLI / 日志" title="实时日志尾部" subtitle="CLI 与日志能力保留在服务页，方便排错。" action={<Button variant="quiet" icon={Trash2} onClick={handleClearLogs}>清空</Button>} />
            {data.logTail.length ? <CodeBlock text={data.logTail.join('\n')} maxHeight={280} /> : <EmptyState title="暂无日志" description="接口没有返回最近日志。" />}
          </Panel>

          <Panel className="surface-panel">
            <SectionHeader eyebrow="更新" title="版本检查" subtitle="检查核心更新会比对当前版本与最新版本。" />
            <div className="detail-stack">
              <div className="detail-row"><span className="detail-label">当前版本</span><span className="detail-value">{data.update.current || '暂无'}</span></div>
              <div className="detail-row"><span className="detail-label">最新版本</span><span className="detail-value">{data.update.latest || '暂无'}</span></div>
              <div className="detail-row"><span className="detail-label">是否可更新</span><span className="detail-value">{data.update.hasUpdate ? '是' : '否'}</span></div>
            </div>
          </Panel>
        </section>
      ) : null}
    </div>
  );
}

// Continuous progress strip shown while start/stop is in flight, or while the
// bridge is still mid-transition (startupState not yet settled). Surfaces the
// stage, elapsed/cap time, latest log line, and on failure a retry path.
function ProgressStrip({
  data,
  actionPending,
  actionFailed,
  onRetry,
}: {
  data: ServiceSnapshot | null;
  actionPending: 'start' | 'stop' | null;
  actionFailed: { kind: 'start' | 'stop'; hint: string; diagnostic: string } | null;
  onRetry: () => void;
}) {
  const stageLabel = toCnState(data?.startupStage || (actionPending === 'stop' ? '正在停止' : '正在启动'));
  const elapsed = data?.startupElapsedSec ?? 0;
  const cap = data?.startupTimeoutSec ?? 420;
  const lastLog = data?.logTail.length ? data.logTail[data.logTail.length - 1] : '';
  const failed = Boolean(actionFailed || data?.startupError);
  const failHint = actionFailed?.hint || (data?.startupError ? translateError(data.startupError).hint : '');

  const logLineStyle: React.CSSProperties = {
    marginTop: 10,
    padding: '8px 12px',
    borderRadius: 8,
    border: '1px solid var(--line)',
    background: 'rgba(7, 11, 16, 0.9)',
    color: '#9fb0c2',
    fontFamily: 'monospace',
    fontSize: 12,
    whiteSpace: 'nowrap',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
  };

  return (
    <Panel className={cx('surface-panel', failed && 'panel-error')}>
      {failed ? (
        <InlineState tone="danger" title={actionPending === 'stop' || actionFailed?.kind === 'stop' ? '停止未完成' : '启动未完成'} description={failHint || '请重试，或查看日志排查。'} />
      ) : (
        <InlineState tone="warn" title={`${stageLabel}…`} description={`已等待 ${elapsed}s · 最多约 ${cap}s`} />
      )}
      {lastLog ? <div style={logLineStyle}>{shortenPaths(lastLog)}</div> : null}
      {failed ? (
        <div className="button-row">
          <Button variant="secondary" icon={RefreshCcw} onClick={onRetry}>重试</Button>
        </div>
      ) : null}
    </Panel>
  );
}

function toCnState(value: string) {
  const lower = String(value || '').toLowerCase();
  const map: Record<string, string> = {
    idle: '待命',
    running: '运行中',
    starting: '正在启动',
    stopping: '正在停止',
    stopped: '已停止',
    ready: '就绪',
    waiting: '等待中',
    'bridge ready': '桥接已就绪',
    'bridge starting': '桥接启动中',
    none: '无',
    manual: '手动',
    member: '成员',
    mock: '预览',
    live: '真实接口',
    mixed: '混合',
  };
  return map[lower] || value;
}
