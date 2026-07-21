import { Archive, Pencil, Plus, RefreshCw, Search } from 'lucide-react';
import { useState } from 'react';
import type { AgentSession } from '../../types/agent';
import { showConfirm } from '../common';

interface ConversationSidebarProps {
  sessions: AgentSession[];
  currentSessionId: string | null;
  query: string;
  loading: boolean;
  error: string | null;
  onQueryChange: (query: string) => void;
  onRetry: () => void;
  onSelect: (sessionId: string) => void;
  onNew: () => void;
  onRename: (session: AgentSession, title: string) => Promise<void>;
  onArchive: (session: AgentSession) => Promise<void>;
}

function relativeTime(value: string): string {
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) return '';
  const minutes = Math.max(0, Math.round((Date.now() - timestamp) / 60_000));
  if (minutes < 1) return '刚刚';
  if (minutes < 60) return `${minutes} 分钟前`;
  if (minutes < 1440) return `${Math.floor(minutes / 60)} 小时前`;
  return `${Math.floor(minutes / 1440)} 天前`;
}

export function ConversationSidebar({
  sessions,
  currentSessionId,
  query,
  loading,
  error,
  onQueryChange,
  onRetry,
  onSelect,
  onNew,
  onRename,
  onArchive,
}: ConversationSidebarProps) {
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [title, setTitle] = useState('');

  const startRename = (session: AgentSession) => {
    setRenamingId(session.sessionId);
    setTitle(session.title);
  };

  const finishRename = async (session: AgentSession) => {
    const nextTitle = title.trim();
    if (nextTitle && nextTitle !== session.title) await onRename(session, nextTitle);
    setRenamingId(null);
  };

  const archive = async (session: AgentSession) => {
    const confirmed = await showConfirm({
      title: '归档对话',
      message: `归档“${session.title}”？运行中的后台任务不会被取消。`,
      confirmText: '归档',
    });
    if (confirmed) await onArchive(session);
  };

  return (
    <aside className="flex w-[clamp(210px,24vw,270px)] min-w-[210px] shrink-0 flex-col border-r border-border bg-surface-alt/35 max-[760px]:w-[190px] max-[760px]:min-w-[190px]">
      <div className="border-b border-border px-3 py-3">
        <div className="flex items-center gap-2">
          <label className="relative min-w-0 flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-text-subtle" aria-hidden="true" />
            <input
              value={query}
              onChange={(event) => onQueryChange(event.target.value)}
              placeholder="搜索对话"
              aria-label="搜索对话"
              className="h-9 w-full rounded-[8px] border border-border bg-input pl-8 pr-3 text-sm text-text outline-none placeholder:text-text-subtle focus:border-border-strong focus:ring-2 focus:ring-accent/20"
            />
          </label>
          <button
            type="button"
            title="新建对话"
            aria-label="新建对话"
            onClick={onNew}
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-[8px] border border-border bg-surface text-text hover:bg-hover"
          >
            <Plus className="h-4 w-4" aria-hidden="true" />
          </button>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-2">
        {error ? (
          <div role="alert" className="mb-2 flex items-center gap-2 rounded-[6px] border border-status-danger/30 bg-status-danger/10 px-2.5 py-2 text-[11px] leading-4 text-status-danger">
            <span className="min-w-0 flex-1">{error}</span>
            <button
              type="button"
              title="重试搜索"
              aria-label="重试搜索"
              onClick={onRetry}
              className="flex shrink-0 items-center gap-1 rounded-[6px] px-1.5 py-1 font-bold hover:bg-status-danger/10"
            >
              <RefreshCw className="h-3 w-3" aria-hidden="true" />
              重试
            </button>
          </div>
        ) : null}
        {loading ? <div className="px-3 py-4 text-xs text-text-muted">正在搜索...</div> : null}
        {!loading && !error && sessions.length === 0 ? (
          <div className="px-3 py-8 text-center text-xs leading-5 text-text-muted">
            {query ? '没有匹配的对话' : '还没有对话'}
          </div>
        ) : null}
        {sessions.map((session) => {
          const selected = session.sessionId === currentSessionId;
          return (
            <div
              key={session.sessionId}
              className={`group mb-1 rounded-[8px] border px-3 py-2.5 transition-colors ${
                selected ? 'border-accent/35 bg-accent/10' : 'border-transparent hover:border-border hover:bg-surface/70'
              }`}
            >
              {renamingId === session.sessionId ? (
                <input
                  autoFocus
                  value={title}
                  onChange={(event) => setTitle(event.target.value)}
                  onBlur={() => void finishRename(session)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter') void finishRename(session);
                    if (event.key === 'Escape') setRenamingId(null);
                  }}
                  className="h-7 w-full rounded-[6px] border border-border-strong bg-input px-2 text-sm font-bold text-text outline-none"
                />
              ) : (
                <button type="button" onClick={() => onSelect(session.sessionId)} className="w-full text-left">
                  <div className="flex items-start gap-2">
                    <span className="min-w-0 flex-1 truncate text-sm font-bold text-text">{session.title}</span>
                    {session.activeRunId ? <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-status-success" title="后台运行中" /> : null}
                  </div>
                  <div className="mt-1 line-clamp-2 min-h-[16px] text-[11px] leading-4 text-text-muted">
                    {session.lastMessagePreview || (session.status === 'archived' ? '已归档' : '新对话')}
                  </div>
                </button>
              )}
              <div className="mt-1.5 flex h-5 items-center justify-between">
                <span className="text-[10px] text-text-subtle">{relativeTime(session.updatedAt)}</span>
                <div className="flex opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
                  <button type="button" title="重命名" aria-label={`重命名 ${session.title}`} onClick={() => startRename(session)} className="flex h-6 w-7 items-center justify-center text-text-muted hover:text-text">
                    <Pencil className="h-3.5 w-3.5" aria-hidden="true" />
                  </button>
                  {session.status !== 'archived' ? (
                    <button type="button" title="归档" aria-label={`归档 ${session.title}`} onClick={() => void archive(session)} className="flex h-6 w-7 items-center justify-center text-text-muted hover:text-status-danger">
                      <Archive className="h-3.5 w-3.5" aria-hidden="true" />
                    </button>
                  ) : null}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </aside>
  );
}
