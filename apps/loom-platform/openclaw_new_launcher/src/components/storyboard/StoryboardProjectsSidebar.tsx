import React from 'react';
import { Button, Input, showConfirm } from '../common';
import type { StoryboardProjectsIndexEntry } from './storyboardTypes';

interface Props {
  entries: StoryboardProjectsIndexEntry[];
  activeProjectId: string | null;
  loading: boolean;
  onRefresh: () => void;
  onSelect: (projectId: string) => void;
  onCreate: () => void;
  onRename: (projectId: string, title: string) => void;
  onDelete: (projectId: string) => void;
}

export const StoryboardProjectsSidebar: React.FC<Props> = ({
  entries, activeProjectId, loading, onRefresh, onSelect, onCreate, onRename, onDelete,
}) => {
  const [renamingId, setRenamingId] = React.useState<string | null>(null);
  const [renameValue, setRenameValue] = React.useState('');

  const startRename = (entry: StoryboardProjectsIndexEntry) => {
    setRenamingId(entry.projectId);
    setRenameValue(entry.title);
  };
  const commitRename = () => {
    if (renamingId) {
      onRename(renamingId, renameValue.trim() || '未命名项目');
      setRenamingId(null);
    }
  };
  const handleDelete = async (entry: StoryboardProjectsIndexEntry) => {
    const ok = await showConfirm({
      title: '删除项目',
      message: `确定删除「${entry.title}」吗？项目文件不会被物理删除，但会从列表移除。`,
      confirmText: '删除',
      tone: 'danger',
    });
    if (ok) onDelete(entry.projectId);
  };

  return (
    <aside data-storyboard-projects-sidebar className="flex w-60 shrink-0 flex-col gap-3 border-r border-border bg-surface-alt/30 p-3">
      <div className="flex items-center justify-between">
        <span className="text-sm font-black text-text">项目</span>
        <Button variant="quiet" onClick={onRefresh} disabled={loading}>刷新</Button>
      </div>
      <Button variant="primary" onClick={onCreate}>新建项目</Button>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {loading ? (
          <div className="px-2 py-4 text-xs text-text-muted">加载中...</div>
        ) : entries.length === 0 ? (
          <div className="px-2 py-4 text-xs text-text-muted">暂无项目，点「新建项目」开始。</div>
        ) : (
          <ul className="space-y-1">
            {entries.map((entry) => (
              <li key={entry.projectId}>
                {renamingId === entry.projectId ? (
                  <div className="flex gap-1">
                    <Input value={renameValue} onChange={(e) => setRenameValue(e.target.value)} className="text-xs" />
                    <Button variant="quiet" onClick={commitRename}>确定</Button>
                  </div>
                ) : (
                  <div
                    data-storyboard-project-item={entry.projectId}
                    className={`group flex cursor-pointer items-center justify-between rounded-lg px-2 py-1.5 text-xs ${entry.projectId === activeProjectId ? 'bg-accent-soft text-accent' : 'text-text-muted hover:bg-hover'}`}
                    onClick={() => onSelect(entry.projectId)}
                  >
                    <span className="truncate">{entry.title}</span>
                    <span className="hidden gap-1 group-hover:flex">
                      <button type="button" className="text-text-muted hover:text-text" onClick={(e) => { e.stopPropagation(); startRename(entry); }}>改名</button>
                      <button type="button" className="text-status-danger hover:opacity-80" onClick={(e) => { e.stopPropagation(); void handleDelete(entry); }}>删</button>
                    </span>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </aside>
  );
};
