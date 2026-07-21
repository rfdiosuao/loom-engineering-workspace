import { useCallback, useEffect, useMemo, useRef, useState, type MutableRefObject } from 'react';
import { agentApi } from '../../services/api';
import type { AgentRun, AgentTraceNode } from '../../types/agent';
import { useAgentStore } from '../../stores/agentStore';
import { formatDuration, sanitizeDisplayValue } from './agentViewModel';

interface AgentDebuggerProps {
  open: boolean;
  run: AgentRun | null;
  refreshToken: number;
  returnFocusRef: MutableRefObject<HTMLElement | null>;
  onClose: () => void;
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function safeJson(value: unknown): string {
  return JSON.stringify(sanitizeDisplayValue(value), null, 2);
}

function promptMetadata(node: AgentTraceNode | undefined): Record<string, unknown> {
  if (!node) return {};
  const input = record(node.inputSummary);
  const snapshot = Object.keys(record(input.promptSnapshot)).length ? record(input.promptSnapshot) : input;
  const allowed = ['snapshotId', 'hash', 'createdAt', 'runtimeProfileId', 'model', 'messageCount', 'toolCount', 'tokenEstimate'];
  return Object.fromEntries(allowed.filter((key) => snapshot[key] !== undefined).map((key) => [key, snapshot[key]]));
}

export function AgentDebugger({ open, run, refreshToken, returnFocusRef, onClose }: AgentDebuggerProps) {
  const selectedTraceNodeId = useAgentStore((state) => state.selectedTraceNodeId);
  const setSelectedTraceNode = useAgentStore((state) => state.setSelectedTraceNode);
  const [trace, setTrace] = useState<AgentTraceNode[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const panelRef = useRef<HTMLElement>(null);
  const wasOpenRef = useRef(false);

  const closeDebugger = useCallback(() => {
    onClose();
    window.requestAnimationFrame(() => returnFocusRef.current?.focus());
  }, [onClose, returnFocusRef]);

  useEffect(() => {
    if (open && !wasOpenRef.current) panelRef.current?.focus();
    wasOpenRef.current = open;
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') closeDebugger();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [closeDebugger, open]);

  useEffect(() => {
    if (!open) return;
    setTrace([]);
    setError('');
    setLoading(false);
  }, [open, run?.runId]);

  useEffect(() => {
    if (!open || !run?.runId) return;
    let active = true;
    const timeout = window.setTimeout(() => {
      setLoading(true);
      void agentApi.trace(run.runId).then((response) => {
        if (!active) return;
        setTrace(response.trace);
        setError('');
        if (!selectedTraceNodeId && response.trace[0]) setSelectedTraceNode(response.trace[0].traceId);
      }).catch((reason: unknown) => {
        if (active) setError(reason instanceof Error ? reason.message : '轨迹读取失败');
      }).finally(() => {
        if (active) setLoading(false);
      });
    }, refreshToken ? 350 : 0);
    return () => {
      active = false;
      window.clearTimeout(timeout);
    };
  }, [open, refreshToken, run?.runId, selectedTraceNodeId, setSelectedTraceNode]);

  const selected = useMemo(
    () => trace.find((node) => node.traceId === selectedTraceNodeId) || trace[0],
    [selectedTraceNodeId, trace],
  );
  const metadata = promptMetadata(selected);

  if (!open) return null;
  return (
    <aside
      ref={panelRef}
      tabIndex={-1}
      aria-label="运行详情"
      className="flex w-[360px] shrink-0 flex-col border-l border-border bg-surface outline-none max-[1320px]:absolute max-[1320px]:bottom-0 max-[1320px]:right-0 max-[1320px]:top-0 max-[1320px]:z-30 max-[1320px]:shadow-[-18px_0_48px_rgba(5,25,22,0.18)]"
      data-agent-debugger
    >
      <div className="flex h-[66px] shrink-0 items-center justify-between border-b border-border px-4">
        <div>
          <h2 className="text-sm font-black text-text">运行详情</h2>
          <div className="mt-0.5 font-mono text-[10px] text-text-subtle">{run?.runId || '没有活动运行'}</div>
        </div>
        <button type="button" title="关闭运行详情" aria-label="关闭运行详情" onClick={closeDebugger} className="flex h-8 w-8 items-center justify-center rounded-[7px] border border-border bg-surface text-lg text-text-muted hover:bg-hover">×</button>
      </div>

      {!run ? <div className="p-5 text-sm text-text-muted">当前对话没有可调试的运行。</div> : (
        <div className="grid min-h-0 flex-1 grid-rows-[minmax(160px,0.9fr)_minmax(220px,1.1fr)]">
          <div className="overflow-y-auto border-b border-border p-3">
            <div className="mb-2 flex items-center justify-between px-1 text-[10px] font-black uppercase text-text-subtle">
              <span>调用链</span><span>{loading ? '更新中' : `${trace.length} 节点`}</span>
            </div>
            {error ? <div className="rounded-[7px] border border-status-danger/25 bg-status-danger/10 p-2 text-xs text-status-danger">{error}</div> : null}
            <div className="grid gap-1">
              {trace.map((node) => (
                <button
                  key={node.traceId}
                  type="button"
                  onClick={() => setSelectedTraceNode(node.traceId)}
                  className={`grid w-full grid-cols-[18px_minmax(0,1fr)_auto] items-center gap-2 rounded-[7px] border px-2 py-2 text-left ${
                    node.traceId === selected?.traceId ? 'border-accent/35 bg-accent/10' : 'border-transparent hover:border-border hover:bg-surface'
                  }`}
                  style={{ paddingLeft: `${8 + (node.parentTraceId ? 12 : 0)}px` }}
                >
                  <span className={`h-2 w-2 rounded-full ${node.status === 'failed' ? 'bg-status-danger' : node.status === 'completed' ? 'bg-status-success' : 'bg-status-warning'}`} />
                  <span className="min-w-0"><span className="block truncate text-xs font-bold text-text">{node.name}</span><span className="text-[9px] font-semibold uppercase text-text-subtle">{node.kind}</span></span>
                  <span className="font-mono text-[9px] text-text-subtle">{formatDuration(node.durationMs)}</span>
                </button>
              ))}
            </div>
          </div>

          <div className="overflow-y-auto p-4">
            {selected ? (
              <div className="grid gap-4">
                <section>
                  <div className="text-[10px] font-black uppercase text-text-subtle">节点状态</div>
                  <dl className="mt-2 grid grid-cols-2 gap-2 text-[11px]">
                    <div><dt className="text-text-subtle">状态</dt><dd className="mt-0.5 font-bold text-text">{selected.status}</dd></div>
                    <div><dt className="text-text-subtle">耗时</dt><dd className="mt-0.5 font-bold text-text">{formatDuration(selected.durationMs)}</dd></div>
                    <div className="col-span-2"><dt className="text-text-subtle">开始</dt><dd className="mt-0.5 break-all font-mono text-text">{selected.startedAt}</dd></div>
                  </dl>
                </section>
                <section>
                  <div className="text-[10px] font-black uppercase text-text-subtle">Prompt 快照元数据</div>
                  <pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap break-words rounded-[7px] border border-border bg-surface p-2 font-mono text-[10px] leading-5 text-text-muted">{Object.keys(metadata).length ? safeJson(metadata) : '无快照元数据'}</pre>
                </section>
                <section>
                  <div className="text-[10px] font-black uppercase text-text-subtle">输入与范围证据</div>
                  <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap break-words rounded-[7px] border border-border bg-surface-alt p-2 font-mono text-[10px] leading-5 text-text-muted">{selected.inputSummary !== undefined ? safeJson(selected.inputSummary) : '无输入证据'}</pre>
                </section>
                {selected.outputSummary !== undefined ? (
                  <section>
                    <div className="text-[10px] font-black uppercase text-text-subtle">输出摘要</div>
                    <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap break-words rounded-[7px] border border-border bg-surface p-2 font-mono text-[10px] leading-5 text-text-muted">{safeJson(selected.outputSummary)}</pre>
                  </section>
                ) : null}
                {selected.error ? <section className="rounded-[7px] border border-status-danger/25 bg-status-danger/10 p-3 text-xs text-status-danger"><div className="font-black">{selected.error.code}</div><div className="mt-1 text-text">{selected.error.message}</div></section> : null}
              </div>
            ) : <div className="text-sm text-text-muted">选择轨迹节点查看详情。</div>}
          </div>
        </div>
      )}
    </aside>
  );
}
