import type { AgentMessageBlock, AgentRun } from '../../types/agent';
import type { FeatureNavigationContext } from '../../stores/appStore';
import { convertFileSrc } from '@tauri-apps/api/core';
import { AlertCircle, Check, ChevronDown, Circle, Image as ImageIcon, LoaderCircle, Paperclip, Video } from 'lucide-react';
import { useEffect, useId, useMemo, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { capabilityActionLabel, userFacingAgentError } from './agentViewModel';
import { AgentApprovalCard } from './AgentApprovalCard';
import { AgentRunAttachment } from './AgentRunAttachment';

interface MessageBlockViewProps {
  block: AgentMessageBlock;
  runs: Record<string, AgentRun>;
  busyKey: string | null;
  onRunAction: (runId: string, action: 'pause' | 'resume' | 'cancel') => Promise<void>;
  onOpenRunDetails: (runId: string, trigger: HTMLButtonElement) => void;
  onResolveApproval: (approvalId: string, decision: 'approve' | 'reject') => Promise<void>;
  onOpenWorkbench: (context: FeatureNavigationContext) => void;
}

function text(value: unknown, fallback = ''): string {
  return typeof value === 'string' ? value : fallback;
}

function localAttachmentUrl(path: string): string {
  if (/^(?:https?:|data:|asset:)/i.test(path)) return path;
  try {
    return convertFileSrc(path);
  } catch {
    return path;
  }
}

function safeMarkdownUrl(url: string): string {
  const value = url.trim();
  return /^(?:https?:|mailto:|#)/i.test(value) ? value : '';
}

export function AgentMarkdown({ value }: { value: string }) {
  return (
    <div className="min-w-0 break-words text-sm leading-6 text-text" data-agent-markdown>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        skipHtml
        urlTransform={safeMarkdownUrl}
        components={{
          p: ({ children }) => <p className="my-2 first:mt-0 last:mb-0">{children}</p>,
          h1: ({ children }) => <h1 className="mb-2 mt-4 text-lg font-bold first:mt-0">{children}</h1>,
          h2: ({ children }) => <h2 className="mb-2 mt-4 text-base font-bold first:mt-0">{children}</h2>,
          h3: ({ children }) => <h3 className="mb-1.5 mt-3 text-sm font-bold first:mt-0">{children}</h3>,
          ul: ({ children }) => <ul className="my-2 list-disc space-y-1 pl-5">{children}</ul>,
          ol: ({ children }) => <ol className="my-2 list-decimal space-y-1 pl-5">{children}</ol>,
          li: ({ children }) => <li className="pl-0.5">{children}</li>,
          blockquote: ({ children }) => (
            <blockquote className="my-2 border-l-2 border-accent/40 pl-3 text-text-muted">{children}</blockquote>
          ),
          a: ({ children, href }) => (
            <a className="font-medium text-accent underline underline-offset-2" href={href} rel="noreferrer" target="_blank">
              {children}
            </a>
          ),
          code: ({ children }) => (
            <code className="rounded bg-surface-alt px-1 py-0.5 font-mono text-[0.9em] text-text">{children}</code>
          ),
          pre: ({ children }) => (
            <pre className="my-3 max-w-full overflow-x-auto rounded-[8px] border border-border bg-surface-alt p-3 text-xs leading-5">
              {children}
            </pre>
          ),
          table: ({ children }) => <table className="my-3 w-full border-collapse text-left text-xs">{children}</table>,
          th: ({ children }) => <th className="border border-border bg-surface-alt px-2 py-1.5 font-bold">{children}</th>,
          td: ({ children }) => <td className="border border-border px-2 py-1.5 align-top">{children}</td>,
          hr: () => <hr className="my-4 border-border" />,
        }}
      >
        {value}
      </ReactMarkdown>
    </div>
  );
}

function PlanBlock({ data }: { data: Record<string, unknown> }) {
  const steps = Array.isArray(data.steps) ? data.steps : Array.isArray(data.plan) ? data.plan : [];
  return (
    <section className="border-l-2 border-accent/45 pl-4">
      <div className="text-[11px] font-black uppercase text-accent">执行计划</div>
      {data.title ? <div className="mt-1 text-sm font-bold text-text">{text(data.title)}</div> : null}
      <ol className="mt-2 grid gap-1.5">
        {steps.map((step, index) => {
          const stepRecord = step && typeof step === 'object' ? step as Record<string, unknown> : {};
          return (
            <li key={text(stepRecord.id, String(index))} className="flex gap-2 text-sm leading-5 text-text-muted">
              <span className="font-mono text-[11px] font-bold text-accent">{String(index + 1).padStart(2, '0')}</span>
              <span className="text-text">{typeof step === 'string' ? step : text(stepRecord.title) || text(stepRecord.summary) || '计划步骤'}</span>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

function ToolBlock({ data }: { data: Record<string, unknown> }) {
  const capability = data.capability ?? data.tool ?? data.name;
  const status = text(data.status, 'running');
  const statusLabels: Record<string, string> = {
    queued: '等待中',
    awaiting: '等待中',
    running: '进行中',
    completed: '已完成',
    failed: '未完成',
  };
  const error = status === 'failed' ? userFacingAgentError(data) : null;
  const occurrences = typeof data.occurrences === 'number' && data.occurrences > 1 ? data.occurrences : 1;
  return (
    <div
      className="agent-tool-item border-t border-border/70 px-3 py-2.5 first:border-t-0"
      data-agent-tool-action
      data-tool-status={status}
    >
      <div className="flex min-h-6 items-center gap-2.5">
        <span className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full ${
          status === 'failed'
            ? 'bg-status-danger/12 text-status-danger'
            : status === 'completed'
              ? 'bg-status-success/12 text-status-success'
              : 'bg-accent/10 text-accent'
        }`} aria-hidden="true">
          {status === 'failed' ? <AlertCircle className="h-3.5 w-3.5" /> : null}
          {status === 'completed' ? <Check className="h-3.5 w-3.5" strokeWidth={2.5} /> : null}
          {status === 'running' ? <LoaderCircle className="agent-tool-spinner h-3.5 w-3.5" /> : null}
          {status === 'queued' || status === 'awaiting' ? <Circle className="h-2.5 w-2.5" /> : null}
        </span>
        <span className="min-w-0 flex-1 text-xs font-semibold leading-5 text-text">
          {capabilityActionLabel(capability, status)}
          {occurrences > 1 ? <span className="ml-1.5 text-[10px] font-medium text-text-subtle">{occurrences} 次</span> : null}
        </span>
        <span className="shrink-0 text-[10px] font-semibold text-text-subtle">
          {statusLabels[status] || '进行中'}
        </span>
      </div>
      {error ? (
        <div className="ml-7 mt-1.5 rounded-[6px] bg-status-danger/8 px-2.5 py-2" data-agent-tool-error>
          <div className="text-[11px] font-bold text-status-danger">{error.title}</div>
          <p className="mt-0.5 text-[11px] leading-4 text-text-muted">{error.message}</p>
          {error.recoverable ? <div className="mt-1 text-[10px] font-semibold text-accent">修复后可重试</div> : null}
        </div>
      ) : null}
    </div>
  );
}

export interface ToolExecutionGroupSummary {
  state: 'running' | 'completed' | 'failed';
  count: number;
  completedCount: number;
  failedCount: number;
  label: string;
  expanded: boolean;
}

export function compactToolExecutionBlocks(blocks: AgentMessageBlock[]): AgentMessageBlock[] {
  const compacted = new Map<string, AgentMessageBlock>();
  blocks.forEach((block, index) => {
    const capability = text(block.data.capability ?? block.data.tool ?? block.data.name).trim().toLowerCase();
    const identity = capability || text(block.data.toolCallId, `tool-${index}`);
    const previous = compacted.get(identity);
    if (!previous) {
      compacted.set(identity, { ...block, data: { ...block.data, occurrences: 1 } });
      return;
    }
    compacted.set(identity, {
      ...block,
      data: {
        ...previous.data,
        ...block.data,
        occurrences: Number(previous.data.occurrences || 1) + 1,
      },
    });
  });
  return [...compacted.values()];
}

export function toolExecutionGroupSummary(
  blocks: AgentMessageBlock[],
  run?: AgentRun,
): ToolExecutionGroupSummary {
  const terminalRunToolStatus = run?.status === 'completed'
    ? 'completed'
    : run?.status === 'failed' || run?.status === 'cancelled'
      ? 'failed'
      : null;
  const statuses = blocks.map((block) => {
    const status = text(block.data.status, 'running');
    return terminalRunToolStatus
      && (status === 'queued' || status === 'awaiting' || status === 'running')
      ? terminalRunToolStatus
      : status;
  });
  const completedCount = statuses.filter((status) => status === 'completed').length;
  const failedCount = statuses.filter((status) => status === 'failed').length;
  if (failedCount > 0) {
    return {
      state: 'failed',
      count: blocks.length,
      completedCount,
      failedCount,
      label: `${failedCount} 步未完成`,
      expanded: true,
    };
  }
  if (statuses.some((status) => status === 'queued' || status === 'awaiting' || status === 'running')) {
    const activeCount = statuses.filter(
      (status) => status === 'queued' || status === 'awaiting' || status === 'running',
    ).length;
    return {
      state: 'running',
      count: blocks.length,
      completedCount,
      failedCount: 0,
      label: completedCount > 0
        ? `${activeCount} 步进行中 · ${completedCount} 步已完成`
        : activeCount === 1
          ? '正在执行'
          : `${activeCount} 步进行中`,
      expanded: true,
    };
  }
  return {
    state: 'completed',
    count: blocks.length,
    completedCount,
    failedCount: 0,
    label: `已完成 ${blocks.length} 步`,
    expanded: false,
  };
}

export function ToolExecutionGroup({
  blocks,
  run,
}: {
  blocks: AgentMessageBlock[];
  run?: AgentRun;
}) {
  const visibleBlocks = useMemo(() => compactToolExecutionBlocks(blocks), [blocks]);
  const summary = useMemo(() => toolExecutionGroupSummary(visibleBlocks, run), [visibleBlocks, run]);
  const [expanded, setExpanded] = useState(summary.expanded);
  const panelId = useId();

  useEffect(() => {
    setExpanded(summary.state !== 'completed');
  }, [summary.count, summary.state]);

  return (
    <section
      className="agent-tool-group overflow-hidden rounded-[8px] border border-border bg-surface-alt/30"
      data-agent-tool-group
      data-state={summary.state}
      data-expanded={expanded ? 'true' : 'false'}
    >
      <button
        type="button"
        className="flex min-h-10 w-full items-center gap-2.5 px-3 py-2 text-left hover:bg-hover/65"
        aria-expanded={expanded}
        aria-controls={panelId}
        onClick={() => setExpanded((value) => !value)}
      >
        <span className={`h-2 w-2 shrink-0 rounded-full ${
          summary.state === 'failed'
            ? 'bg-status-danger'
            : summary.state === 'completed'
              ? 'bg-status-success'
              : 'bg-accent'
        }`} />
        <span className="min-w-0 flex-1 text-xs font-bold text-text">执行过程</span>
        <span className={`shrink-0 text-[11px] font-semibold ${
          summary.state === 'failed' ? 'text-status-danger' : 'text-text-muted'
        }`}>{summary.label}</span>
        <ChevronDown className={`agent-tool-chevron h-3.5 w-3.5 shrink-0 text-text-subtle ${expanded ? 'rotate-180' : ''}`} aria-hidden="true" />
      </button>
      <div className="agent-tool-group__body" data-open={expanded ? 'true' : 'false'}>
        <div className="min-h-0 overflow-hidden">
          <div id={panelId} aria-hidden={!expanded} className="border-t border-border bg-surface/55">
            {visibleBlocks.map((block, index) => (
              <ToolBlock
                key={text(block.data.toolCallId, `${text(block.data.capability, 'tool')}-${index}`)}
                data={block.data}
              />
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

function AttachmentPreview({ attachment }: { attachment: Record<string, unknown> }) {
  const [failed, setFailed] = useState(false);
  const name = text(attachment.name, '媒体文件');
  const path = text(attachment.path);
  const mime = text(attachment.mime, text(attachment.type));
  const kind = text(attachment.kind);
  const isImage = kind === 'image' || mime.startsWith('image/');
  const isVideo = kind === 'video' || mime.startsWith('video/');
  const source = path ? localAttachmentUrl(path) : '';

  return (
    <li className="min-w-0 overflow-hidden rounded-[8px] border border-border bg-surface">
      {source && isImage && !failed ? (
        <div className="aspect-square w-full bg-surface-alt/45">
          <img
            src={source}
            alt={name}
            className="h-full w-full object-contain"
            onError={() => setFailed(true)}
          />
        </div>
      ) : null}
      {source && isVideo && !failed ? (
        <video
          src={source}
          controls
          preload="metadata"
          className="aspect-video w-full bg-black object-contain"
          onError={() => setFailed(true)}
        />
      ) : null}
      {failed ? (
        <div className="flex min-h-24 items-center justify-center px-4 text-center text-xs text-text-muted">
          预览暂不可用，文件已保存在本地
        </div>
      ) : null}
      <div className="flex min-w-0 items-center gap-2 px-3 py-2 text-xs text-text-muted">
        {isVideo ? <Video aria-hidden="true" className="h-3.5 w-3.5 shrink-0" /> : <ImageIcon aria-hidden="true" className="h-3.5 w-3.5 shrink-0" />}
        <span className="min-w-0 truncate" title={name}>{name}</span>
      </div>
    </li>
  );
}

function AttachmentBlock({ data }: { data: Record<string, unknown> }) {
  const attachments = Array.isArray(data.attachments)
    ? data.attachments.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object')
    : [];
  const phoneTransfer = data.phoneTransfer && typeof data.phoneTransfer === 'object'
    ? data.phoneTransfer as Record<string, unknown>
    : null;
  const transferStatus = text(phoneTransfer?.status);
  const transferMessage = text(phoneTransfer?.message);
  return (
    <section className="rounded-[8px] border border-border bg-surface-alt/35 px-3 py-2.5" data-agent-attachments>
      <div className="flex items-center gap-2 text-xs font-bold text-text">
        <Paperclip aria-hidden="true" className="h-4 w-4 shrink-0 text-text-subtle" />
        <span>生成结果</span>
      </div>
      <ul className="mt-2 grid gap-2 sm:grid-cols-2">
        {attachments.map((attachment, index) => (
          <AttachmentPreview key={`${text(attachment.name, 'attachment')}-${index}`} attachment={attachment} />
        ))}
      </ul>
      {phoneTransfer ? (
        <div className={`mt-2 rounded-[8px] px-2.5 py-2 text-xs font-semibold ${
          transferStatus === 'succeeded'
            ? 'bg-status-success/10 text-status-success'
            : transferStatus === 'failed'
              ? 'bg-status-danger/10 text-status-danger'
              : 'bg-surface-alt text-text-muted'
        }`} role="status">
          {transferMessage || (transferStatus === 'succeeded' ? '已传送到手机相册' : '媒体已保存在本地')}
        </div>
      ) : null}
    </section>
  );
}

function ErrorBlock({ data }: { data: Record<string, unknown> }) {
  const error = userFacingAgentError(data);
  return (
    <section className="rounded-[8px] border border-status-danger/30 bg-status-danger/10 p-3">
      <div className="flex items-center gap-2 text-xs font-black text-status-danger">
        <span aria-hidden="true">!</span>
        <span>{error.title}</span>
      </div>
      <p className="mt-1 text-sm leading-5 text-text">{error.message}</p>
      {error.recoverable ? <div className="mt-1 text-[11px] font-bold text-accent">可以重试</div> : null}
    </section>
  );
}

export function MessageBlockView({
  block,
  runs,
  busyKey,
  onRunAction,
  onOpenRunDetails,
  onResolveApproval,
  onOpenWorkbench,
}: MessageBlockViewProps) {
  if (block.type === 'text') {
    return <AgentMarkdown value={text(block.data.text)} />;
  }
  if (block.type === 'plan') return <PlanBlock data={block.data} />;
  if (block.type === 'tool') {
    return Array.isArray(block.data.attachments)
      ? <AttachmentBlock data={block.data} />
      : <ToolExecutionGroup blocks={[block]} run={runs[text(block.data.runId)]} />;
  }
  if (block.type === 'error') return <ErrorBlock data={block.data} />;
  if (block.type === 'approval') {
    const approvalId = text(block.data.approvalId);
    return <AgentApprovalCard data={block.data} busy={busyKey === approvalId} onResolve={onResolveApproval} />;
  }
  if (block.type === 'matrix') {
    const runId = text(block.data.runId);
    return (
      <AgentRunAttachment
        data={block.data}
        run={runs[runId]}
        busy={Boolean(runId && busyKey === runId)}
        onRunAction={onRunAction}
        onOpenRunDetails={onOpenRunDetails}
        onOpenWorkbench={onOpenWorkbench}
      />
    );
  }
  return null;
}
