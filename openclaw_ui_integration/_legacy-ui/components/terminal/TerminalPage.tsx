import React from 'react';
import { invoke } from '@tauri-apps/api/core';
import { Button, showToast } from '../common';
import { useLogStore } from '../../stores/logStore';
import { useTheme } from '../../hooks/useTheme';
import { logApi } from '../../services/api';

export const TerminalPage: React.FC = () => {
  const lines = useLogStore((state) => state.lines);
  const clearLogs = useLogStore((state) => state.clear);
  const { theme } = useTheme();
  const containerRef = React.useRef<HTMLDivElement>(null);
  const [exporting, setExporting] = React.useState(false);
  const [lastExportPath, setLastExportPath] = React.useState('');
  const logLines = lines.split('\n').filter(Boolean);

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
      return <span className="text-[#FFB454]">{line}</span>;
    }
    if (line.includes('[OpenClaw]') || line.includes('[Bridge]')) {
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
      showToast(`导出日志失败：${error?.error || error}`, 'error');
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
      showToast(`打开目录失败：${error?.error || error}`, 'error');
    }
  };

  const handleClearLogs = async () => {
    clearLogs();
    window.dispatchEvent(new Event('openclaw:logs-cleared'));
    try {
      await logApi.clear();
    } catch (error: any) {
      showToast(`清空后端日志失败：${error?.error || error}`, 'error');
    }
  };

  return (
    <div className="flex h-full flex-col bg-transparent">
      <div className="flex h-[64px] shrink-0 items-center justify-between border-b border-border bg-surface px-6">
        <div className="flex items-center">
          <div className="mr-5 flex items-center gap-2">
            <div className="h-3 w-3 rounded-full bg-status-danger shadow-[0_0_10px_rgba(255,77,109,0.65)]" />
            <div className="h-3 w-3 rounded-full bg-status-warning shadow-[0_0_10px_rgba(255,180,84,0.55)]" />
            <div className="h-3 w-3 rounded-full bg-status-success shadow-[0_0_10px_rgba(63,224,143,0.55)]" />
          </div>
          <span className="text-lg font-black tracking-wide text-text">{theme.brand.terminal_header}</span>
          <span className="ml-3 rounded-full border border-border bg-surface-alt px-3 py-1 text-xs text-text-muted">
            127.0.0.1:18790
          </span>
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
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-2xl border border-border bg-terminal-bg shadow-[0_24px_70px_rgba(0,0,0,0.32)]">
          <div className="flex h-10 shrink-0 items-center justify-between border-b border-border bg-terminal-header px-4">
            <span className="text-xs font-black uppercase tracking-[0.22em] text-accent">Live Output</span>
            <span className="text-xs text-text-muted">{logLines.length} lines</span>
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
              {lines.length === 0 && (
                <span className="text-text-muted">等待服务启动...</span>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
