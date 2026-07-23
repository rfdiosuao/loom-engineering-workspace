import { ArrowUp, Paperclip, Play, Square, X } from 'lucide-react';
import { useRef, useState } from 'react';
import type { AgentBootstrapResponse, AgentSession } from '../../types/agent';
import type { AgentAttachmentMetadata, AgentDraft } from '../../stores/agentStore';
import { AgentModelMenu } from './AgentModelMenu';
import { AgentScopeMenu } from './AgentScopeMenu';

interface AgentComposerProps {
  draft: AgentDraft;
  session: AgentSession | null;
  bootstrap: AgentBootstrapResponse | null;
  disabled?: boolean;
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

const MAX_ATTACHMENT_BYTES = 1_048_576;
const MAX_ATTACHMENT_CHARS = 32_768;
const TEXT_APPLICATION_TYPES = new Set([
  'application/json',
  'application/ld+json',
  'application/javascript',
  'application/xml',
  'application/yaml',
  'application/x-yaml',
]);

function isReadableTextFile(file: File): boolean {
  const type = file.type.toLowerCase();
  return type.startsWith('text/')
    || TEXT_APPLICATION_TYPES.has(type)
    || /\.(?:txt|md|markdown|csv|tsv|json|jsonl|xml|ya?ml|log)$/i.test(file.name);
}

function readFileText(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(reader.error || new Error(`无法读取附件 ${file.name}`));
    reader.onload = () => resolve(typeof reader.result === 'string' ? reader.result : '');
    reader.readAsText(file.slice(0, MAX_ATTACHMENT_BYTES));
  });
}

async function fileMetadata(files: readonly File[]): Promise<AgentAttachmentMetadata[]> {
  const readable = files.filter(isReadableTextFile);
  return Promise.all(readable.map(async (file) => {
    const loaded = await readFileText(file);
    const content = loaded.slice(0, MAX_ATTACHMENT_CHARS);
    const truncated = file.size > MAX_ATTACHMENT_BYTES || loaded.length > MAX_ATTACHMENT_CHARS;
    return {
      name: file.name,
      size: file.size,
      type: file.type || 'text/plain',
      lastModified: file.lastModified,
      content,
      truncated,
      contentTruncated: truncated,
    };
  }));
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
          placeholder="输入任务或问题"
          aria-label="消息内容"
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
            className="hidden"
            onChange={(event) => {
              const files = Array.from(event.currentTarget.files || []);
              event.target.value = '';
              if (!files.length) return;
              setAttachmentError('');
              setAttachmentsLoading(true);
              void fileMetadata(files)
                .then((attachments) => {
                  if (attachments.length) onChange({ attachments: [...draft.attachments, ...attachments] });
                })
                .catch(() => setAttachmentError('附件读取失败，请重新选择'))
                .finally(() => setAttachmentsLoading(false));
            }}
          />
          <button
            type="button"
            title="添加文本附件"
            aria-label="添加附件"
            disabled={disabled || attachmentsLoading}
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
