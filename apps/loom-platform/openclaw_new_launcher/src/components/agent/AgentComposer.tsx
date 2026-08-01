import { ArrowUp, Paperclip, Play, Square, X } from 'lucide-react';
import { useRef, useState } from 'react';
import type { AgentBootstrapResponse, AgentSession } from '../../types/agent';
import type { AgentDraft } from '../../stores/agentStore';
import { AgentModelMenu } from './AgentModelMenu';
import { AgentScopeMenu } from './AgentScopeMenu';
import {
  MAX_AGENT_ATTACHMENT_COUNT,
  MAX_AGENT_ATTACHMENT_TOTAL_BYTES,
  prepareAgentAttachments,
} from './agentAttachments';
import { APP_TASK_PLACEHOLDER } from '../../version';

interface AgentComposerProps {
  draft: AgentDraft;
  session: AgentSession | null;
  bootstrap: AgentBootstrapResponse | null;
  disabled?: boolean;
  disabledReason?: string;
  sending?: boolean;
  running?: boolean;
  paused?: boolean;
  controlBusy?: boolean;
  onChange: (draft: Partial<AgentDraft>) => void;
  onSubmit: () => void;
  onStop: () => void;
  onResume: () => void;
  onSelectModel: (modelId?: string) => Promise<void>;
  onSetDefaultModel: (modelId: string) => Promise<void>;
  onManageModels: () => void;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export function AgentComposer({
  draft,
  session,
  bootstrap,
  disabled,
  disabledReason = '',
  sending,
  running,
  paused,
  controlBusy,
  onChange,
  onSubmit,
  onStop,
  onResume,
  onSelectModel,
  onSetDefaultModel,
  onManageModels,
}: AgentComposerProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [attachmentsLoading, setAttachmentsLoading] = useState(false);
  const [attachmentError, setAttachmentError] = useState('');
  const busy = Boolean(sending || running);
  const canSend = !disabled && !busy && !attachmentsLoading && Boolean(draft.text.trim() || draft.attachments.length);

  return (
    <div className="shrink-0 border-t border-border bg-surface px-4 pb-4 pt-3">
      <div className="mx-auto w-full max-w-[920px] overflow-visible rounded-[8px] border border-border-strong bg-input shadow-[0_10px_30px_rgba(5,35,29,0.08)] focus-within:ring-2 focus-within:ring-accent/15">
        {disabled && disabledReason ? (
          <div
            id="agent-composer-disabled-reason"
            role="status"
            className="flex min-h-9 items-center border-b border-status-warning/25 bg-status-warning/8 px-4 text-xs font-semibold text-text-muted"
            data-agent-composer-disabled-reason
          >
            {disabledReason}
          </div>
        ) : null}
        {paused ? (
          <div role="status" className="flex min-h-9 items-center border-b border-status-warning/25 bg-status-warning/8 px-4 text-xs font-semibold text-text-muted">
            任务已安全暂停，可继续执行或中断本轮任务。
          </div>
        ) : null}
        {draft.attachments.length ? (
          <div className="flex flex-wrap gap-2 border-b border-border px-3 py-2">
            {draft.attachments.map((attachment, index) => (
              <span key={`${attachment.name}-${attachment.lastModified}`} className="flex max-w-[280px] items-center gap-2 rounded-[6px] border border-border bg-surface pl-2.5 text-[11px] text-text-muted">
                <span className="truncate font-semibold text-text">{attachment.name}</span>
                <span className="shrink-0">{formatBytes(attachment.size)}</span>
                <button
                  type="button"
                  title="移除附件"
                  aria-label={`移除附件 ${attachment.name}`}
                  onClick={() => onChange({ attachments: draft.attachments.filter((_, itemIndex) => itemIndex !== index) })}
                  className="flex h-8 w-8 shrink-0 items-center justify-center rounded-[5px] text-text-subtle hover:bg-hover hover:text-status-danger"
                >
                  <X size={14} aria-hidden="true" />
                </button>
              </span>
            ))}
          </div>
        ) : null}

        <textarea
          value={draft.text}
          disabled={disabled}
          onChange={(event) => onChange({ text: event.target.value })}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault();
              if (canSend) onSubmit();
            }
          }}
          placeholder={APP_TASK_PLACEHOLDER}
          aria-label="消息内容"
          aria-describedby={disabled && disabledReason ? 'agent-composer-disabled-reason' : undefined}
          rows={3}
          className="max-h-44 min-h-[86px] w-full resize-y bg-transparent px-4 py-3 text-sm leading-6 text-text outline-none placeholder:text-text-subtle disabled:opacity-60"
        />

        {attachmentError ? (
          <div role="alert" className="px-4 pb-2 text-right text-[11px] font-semibold text-status-danger">{attachmentError}</div>
        ) : null}

        <div className="flex min-h-14 items-center gap-1 border-t border-border px-2.5 py-2">
          <input
            ref={fileInputRef}
            type="file"
            multiple
            disabled={disabled || busy || attachmentsLoading}
            className="hidden"
            onChange={(event) => {
              const files = Array.from(event.currentTarget.files || []);
              event.target.value = '';
              if (!files.length || disabled || busy || attachmentsLoading) return;
              const nextCount = draft.attachments.length + files.length;
              const nextBytes = draft.attachments.reduce((total, item) => total + item.size, 0)
                + files.reduce((total, item) => total + item.size, 0);
              if (nextCount > MAX_AGENT_ATTACHMENT_COUNT) {
                setAttachmentError(`一条消息最多添加 ${MAX_AGENT_ATTACHMENT_COUNT} 个附件`);
                return;
              }
              if (nextBytes > MAX_AGENT_ATTACHMENT_TOTAL_BYTES) {
                setAttachmentError('一条消息的附件总大小不能超过 16 MB');
                return;
              }
              setAttachmentError('');
              setAttachmentsLoading(true);
              void Promise.allSettled(files.map((file) => prepareAgentAttachments([file])))
                .then((results) => {
                  const attachments = results.flatMap((result) => (
                    result.status === 'fulfilled' ? result.value : []
                  ));
                  const failures = results.flatMap((result) => (
                    result.status === 'rejected'
                      ? [result.reason instanceof Error ? result.reason.message : '附件读取失败，请重新选择']
                      : []
                  ));
                  if (attachments.length) {
                    onChange({ attachments: [...draft.attachments, ...attachments] });
                  }
                  setAttachmentError(failures.join('；'));
                })
                .finally(() => setAttachmentsLoading(false));
            }}
          />
          <button
            type="button"
            title="添加图片或文本附件"
            aria-label="添加附件"
            disabled={disabled || busy || attachmentsLoading}
            onClick={() => fileInputRef.current?.click()}
            className="flex h-10 w-10 shrink-0 items-center justify-center rounded-[7px] text-text-muted hover:bg-hover hover:text-text disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Paperclip size={17} aria-hidden="true" />
          </button>

          <AgentScopeMenu
            mode={draft.scopeMode}
            scope={draft.scope}
            disabled={disabled || busy}
            onChange={(scopeMode, scope) => onChange({ scopeMode, scope })}
          />

          <div className="min-w-0 flex-1" />

          <AgentModelMenu
            session={session}
            models={bootstrap?.models || []}
            defaultModelId={bootstrap?.defaultModelId}
            disabled={disabled || busy}
            onSelectModel={onSelectModel}
            onSetDefaultModel={onSetDefaultModel}
            onManageModels={onManageModels}
          />

          {busy ? (
            paused ? (
              <>
                <button
                  type="button"
                  title="继续任务"
                  aria-label="继续任务"
                  disabled={controlBusy}
                  onClick={onResume}
                  className="flex h-10 w-10 shrink-0 items-center justify-center rounded-[7px] bg-accent text-accent-ink hover:bg-accent-hover disabled:cursor-wait disabled:opacity-45"
                >
                  <Play size={16} fill="currentColor" aria-hidden="true" />
                </button>
                <button
                  type="button"
                  title="中断任务"
                  aria-label="中断任务"
                  disabled={!running || controlBusy}
                  onClick={onStop}
                  className="flex h-10 w-10 shrink-0 items-center justify-center rounded-[7px] border border-status-danger/30 bg-status-danger/10 text-status-danger hover:bg-status-danger/15 disabled:cursor-wait disabled:opacity-45"
                >
                  <Square size={14} fill="currentColor" aria-hidden="true" />
                </button>
              </>
            ) : (
              <button
                type="button"
                title="停止任务"
                aria-label="停止任务"
                disabled={!running || controlBusy}
                onClick={onStop}
                className="flex h-10 w-10 shrink-0 items-center justify-center rounded-[7px] bg-text text-surface hover:opacity-85 disabled:cursor-wait disabled:opacity-45"
              >
                <Square size={14} fill="currentColor" aria-hidden="true" />
              </button>
            )
          ) : (
            <button
              type="button"
              title="发送"
              aria-label="发送"
              disabled={!canSend}
              onClick={onSubmit}
              className="flex h-10 w-10 shrink-0 items-center justify-center rounded-[7px] bg-accent text-accent-ink hover:bg-accent-hover disabled:cursor-not-allowed disabled:bg-surface-alt disabled:text-text-subtle"
            >
              <ArrowUp size={18} strokeWidth={2.4} aria-hidden="true" />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
