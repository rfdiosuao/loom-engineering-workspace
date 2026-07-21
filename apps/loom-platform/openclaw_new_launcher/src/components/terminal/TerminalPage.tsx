import React from 'react';
import { invoke } from '@tauri-apps/api/core';
import { Button, showConfirm, showToast } from '../common';
import { useLogStore } from '../../stores/logStore';
import { logApi, parseErrorText } from '../../services/api';

type LogView = 'issues' | 'all';

const ERROR_OR_WARNING_PATTERN = /\b(?:error|failed|failure|warn(?:ing)?|exception|traceback|fatal|critical|timeout|denied|refused)\b|错误|失败|警告|异常|超时|拒绝/i;

export const TerminalPage: React.FC = () => {
  const lines = useLogStore((state) => state.lines);
  const clearLogs = useLogStore((state) => state.clear);
  const containerRef = React.useRef<HTMLDivElement>(null);
  const [exporting, setExporting] = React.useState(false);
  const [lastExportPath, setLastExportPath] = React.useState('');
  const [view, setView] = React.useState<LogView>('issues');
  const MAX_RENDER_LINES = 800;
  const allLines = React.useMemo(() => lines.split('\n').filter(Boolean), [lines]);
  const issueLines = React.useMemo(
    () => allLines.filter((line) => ERROR_OR_WARNING_PATTERN.test(line)),
    [allLines],
  );
  const selectedLines = view === 'issues' ? issueLines : allLines;
  const truncated = selectedLines.length > MAX_RENDER_LINES;
  const logLines = truncated ? selectedLines.slice(-MAX_RENDER_LINES) : selectedLines;

  const scrollToBottom = React.useCallback(() => {
    const el = containerRef.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' });
  }, []);

  const highlightLine = (line: string) => {
    const lowered = line.toLowerCase();
    if (line.includes('[Error]') || lowered.includes('error') || lowered.includes('failed')) {
      return <span className="text-[#FF6E86]">{line}</span>;
    }
    if (line.includes('[WARN]') || line.includes('[Warning]') || lowered.includes('warning')) {
      return <span className="text-status-warning">{line}</span>;
    }
    if (line.includes('[Lumi]') || line.includes('[Bridge]') || line.includes('[Core]')) {
      return <span className="text-terminal-text">{line}</span>;
    }
    return <span className="text-slate-100">{line}</span>;
  };

  const handleExport = async () => {
    if (!lines.trim()) {
      showToast('当前没有可导出的日志', 'info');
      return;
    }
    setExporting(true);
    try {
      const path = await invoke<string>('export_log', { content: lines });
      setLastExportPath(path);
      showToast(`日志已导出：${path}`, 'success');
    } catch (error: any) {
      showToast(`导出日志失败：${parseErrorText(error) || '无法导出日志，请检查写入权限。'}`, 'error');
    } finally {
      setExporting(false);
    }
  };

  const handleOpenLogDir = async () => {
    if (!lastExportPath) {
      showToast('请先导出日志', 'info');
      return;
    }
    const directory = lastExportPath.replace(/[\\/][^\\/]+$/, '');
    try {
      await invoke('open_path', { path: directory });
      showToast(`已打开目录：${directory}`, 'info');
    } catch (error: any) {
      showToast(`打开目录失败：${parseErrorText(error) || '无法打开日志目录。'}`, 'error');
    }
  };

  const handleClearLogs = async () => {
    const ok = await showConfirm({
      title: '清空当前日志',
      message: '已导出的诊断包不会受影响。确定清空当前界面日志吗？',
      confirmText: '清空',
      tone: 'danger',
    });
    if (!ok) return;
    clearLogs();
    try {
      const result = await logApi.clear();
      clearLogs();
      window.dispatchEvent(new CustomEvent('openclaw:logs-cleared', {
        detail: { generation: result.generation },
      }));
    } catch (error: any) {
      window.dispatchEvent(new Event('openclaw:logs-cleared'));
      showToast(`清空后端日志失败：${parseErrorText(error) || '后端日志清理失败。'}`, 'error');
    }
  };

  return (
    <div className="flex h-full flex-col bg-transparent">
      <div className="flex h-[64px] shrink-0 items-center justify-between border-b border-border bg-surface px-6">
        <div className="flex items-center">
          <span className="text-lg font-black tracking-wide text-text">系统日志</span>
          <div className="ml-4 flex h-8 items-center rounded-lg border border-border bg-surface-alt p-0.5" aria-label="日志范围">
            <button
              type="button"
              onClick={() => setView('issues')}
              className={`h-7 rounded-md px-3 text-xs font-bold transition-colors ${view === 'issues' ? 'bg-accent text-white' : 'text-text-muted hover:text-text'}`}
            >
              错误与警告
            </button>
            <button
              type="button"
              onClick={() => setView('all')}
              className={`h-7 rounded-md px-3 text-xs font-bold transition-colors ${view === 'all' ? 'bg-accent text-white' : 'text-text-muted hover:text-text'}`}
            >
              全部日志
            </button>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="quiet" className="px-3 py-1.5 text-xs" onClick={scrollToBottom}>
            跳到底部
          </Button>
          <Button variant="quiet" className="px-3 py-1.5 text-xs" onClick={handleExport} disabled={exporting}>
            {exporting ? '导出中...' : '导出日志'}
          </Button>
          {lastExportPath && (
            <Button variant="quiet" className="px-3 py-1.5 text-xs" onClick={handleOpenLogDir}>
              打开目录
            </Button>
          )}
          <Button variant="danger" className="px-3 py-1.5 text-xs" onClick={handleClearLogs}>
            清空
          </Button>
        </div>
      </div>

      <div className="flex min-h-0 flex-1 p-6">
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-lg border border-border bg-terminal-bg shadow-[0_24px_70px_rgba(0,0,0,0.32)]">
          <div className="flex h-10 shrink-0 items-center justify-between border-b border-border bg-terminal-header px-4">
            <span className="text-xs font-black text-accent">{view === 'issues' ? '真实报错日志' : '完整运行日志'}</span>
            <span className="text-xs text-text-muted">
              {truncated ? `显示最近 ${MAX_RENDER_LINES} / ${selectedLines.length} 行` : `${selectedLines.length} 行`}
            </span>
          </div>
          <div
            ref={containerRef}
            tabIndex={0}
            className="min-h-0 flex-1 overflow-auto overscroll-contain bg-terminal-bg p-5 font-mono text-sm leading-relaxed outline-none"
          >
            <div className="min-w-max whitespace-pre">
              {logLines.map((line, index) => (
                <div key={`${index}-${line.slice(0, 16)}`} className="min-h-[1.5em]">{highlightLine(line)}</div>
              ))}
              {logLines.length === 0 && (
                <span className="text-text-muted">{view === 'issues' ? '当前没有错误或警告' : '暂无运行日志'}</span>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
