import React from 'react';
import { invoke } from '@tauri-apps/api/core';
import { Button, showToast } from '../common';
import {
  diagnosticsApi,
  type DiagnosticCheck,
  type DiagnosticExportResult,
  type DiagnosticReport,
  type DiagnosticRepairResult,
  type DiagnosticStatus,
} from '../../services/api';

const toneMap: Record<DiagnosticStatus, {
  label: string;
  dot: string;
  badge: string;
  panel: string;
}> = {
  ok: {
    label: '正常',
    dot: 'bg-status-success shadow-[0_0_12px_rgba(22,199,132,0.55)]',
    badge: 'border-status-success/30 bg-status-success/10 text-status-success',
    panel: 'border-status-success/25 bg-status-success/10',
  },
  warn: {
    label: '需处理',
    dot: 'bg-status-warning shadow-[0_0_12px_rgba(245,158,11,0.55)]',
    badge: 'border-status-warning/30 bg-status-warning/10 text-status-warning',
    panel: 'border-status-warning/25 bg-status-warning/10',
  },
  fail: {
    label: '阻塞',
    dot: 'bg-status-danger shadow-[0_0_12px_rgba(255,77,109,0.55)]',
    badge: 'border-status-danger/30 bg-status-danger/10 text-status-danger',
    panel: 'border-status-danger/25 bg-status-danger/10',
  },
};

function statusPriority(status: DiagnosticStatus): number {
  if (status === 'fail') return 0;
  if (status === 'warn') return 1;
  return 2;
}

const CheckRow: React.FC<{ check: DiagnosticCheck }> = ({ check }) => {
  const tone = toneMap[check.status] || toneMap.warn;
  return (
    <div className={`rounded-xl border p-4 ${tone.panel}`}>
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className={`h-2.5 w-2.5 shrink-0 rounded-full ${tone.dot}`} />
            <h3 className="text-sm font-bold text-text">{check.label}</h3>
          </div>
          <p className="mt-2 text-sm leading-relaxed text-text-muted">{check.message}</p>
        </div>
        <span className={`shrink-0 rounded-full border px-2.5 py-1 text-xs font-bold ${tone.badge}`}>
          {tone.label}
        </span>
      </div>
      {check.detail && (
        <div className="mt-3 break-all rounded-lg border border-border bg-black/10 px-3 py-2 font-mono text-xs leading-relaxed text-text-subtle">
          {check.detail}
        </div>
      )}
    </div>
  );
};

const ActionRow: React.FC<{ action: DiagnosticRepairResult['actions'][number] }> = ({ action }) => {
  const tone = toneMap[action.status || 'ok'] || toneMap.ok;
  return (
    <div className="flex items-center justify-between gap-4 rounded-lg border border-border bg-surface-alt/60 px-3 py-2">
      <div className="flex items-center gap-2">
        <span className={`h-2 w-2 rounded-full ${tone.dot}`} />
        <span className="text-sm font-medium text-text">{action.label}</span>
      </div>
      <span className="text-right text-xs text-text-muted">{action.message}</span>
    </div>
  );
};

export const DiagnosticsPage: React.FC = () => {
  const [report, setReport] = React.useState<DiagnosticReport | null>(null);
  const [actions, setActions] = React.useState<DiagnosticRepairResult['actions']>([]);
  const [exportInfo, setExportInfo] = React.useState<DiagnosticExportResult | null>(null);
  const [loading, setLoading] = React.useState(false);
  const [repairing, setRepairing] = React.useState(false);
  const [exporting, setExporting] = React.useState(false);

  const runDiagnostics = React.useCallback(async () => {
    setLoading(true);
    try {
      const result = await diagnosticsApi.run();
      setReport(result);
      setActions([]);
    } catch (error: any) {
      try {
        const fallback = await diagnosticsApi.bridgeStartupReport();
        const message = String(error?.error || error || 'Bridge 启动失败');
        const checks: DiagnosticCheck[] = [
          {
            id: 'diagnostics_bridge_unavailable',
            label: '诊断服务不可用',
            status: 'fail',
            message,
            detail: 'Python Bridge 未能启动，当前显示的是 Tauri 外层诊断结果。',
            repairable: false,
          },
          ...(fallback.checks || []),
        ];
        const failed = checks.filter((item) => item.status === 'fail').length;
        const warnings = checks.filter((item) => item.status === 'warn').length;
        const ok = checks.filter((item) => item.status === 'ok').length;
        setReport({
          ...fallback,
          checks,
          summary: {
            status: failed ? 'fail' : warnings ? 'warn' : 'ok',
            ok,
            warnings,
            failed,
            total: checks.length,
          },
        });
        setActions([]);
        showToast('Bridge 未启动，已切换到外层诊断', 'error');
      } catch (fallbackError: any) {
        showToast(`诊断失败: ${fallbackError?.error || fallbackError || error?.error || error}`, 'error');
      }
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    runDiagnostics();
  }, [runDiagnostics]);

  const handleRepair = async () => {
    setRepairing(true);
    try {
      const result = await diagnosticsApi.repair();
      setActions(result.actions || []);
      setReport(result.diagnostics);
      showToast('一键修复已完成，可以重新启动核心服务', 'success');
    } catch (error: any) {
      showToast(`修复失败: ${error?.error || error}`, 'error');
    } finally {
      setRepairing(false);
    }
  };

  const handleExport = async () => {
    setExporting(true);
    try {
      const result = await diagnosticsApi.export();
      setExportInfo(result);
      showToast(`诊断包已生成: ${result.filename}`, 'success');
    } catch (error: any) {
      showToast(`导出失败: ${error?.error || error}`, 'error');
    } finally {
      setExporting(false);
    }
  };

  const handleOpenExportDir = async () => {
    if (!exportInfo?.directory) return;
    try {
      await invoke('open_path', { path: exportInfo.directory });
    } catch (error: any) {
      showToast(`打开目录失败: ${error?.error || error}`, 'error');
    }
  };

  const handleCopySummary = async () => {
    if (!report) {
      showToast('暂无诊断结果可复制', 'info');
      return;
    }
    const checks = [...(report.checks || [])].sort((a, b) => statusPriority(a.status) - statusPriority(b.status));
    const lines = [
      'OpenClaw 环境诊断摘要',
      `状态: ${report.summary?.status || 'unknown'} | 正常 ${report.summary?.ok ?? 0} / 警告 ${report.summary?.warnings ?? 0} / 阻塞 ${report.summary?.failed ?? 0}`,
      `安装目录: ${report.basePath || '-'}`,
      `服务 PID: ${report.servicePid || '未运行'}`,
      '',
      ...checks.map((check) => [
        `[${check.status.toUpperCase()}] ${check.label}: ${check.message}`,
        check.detail ? `  ${check.detail}` : '',
      ].filter(Boolean).join('\n')),
    ];
    try {
      await navigator.clipboard.writeText(lines.join('\n'));
      showToast('诊断摘要已复制', 'success');
    } catch (error: any) {
      showToast(`复制失败: ${error?.message || error}`, 'error');
    }
  };

  const sortedChecks = React.useMemo(() => {
    return [...(report?.checks || [])].sort((a, b) => statusPriority(a.status) - statusPriority(b.status));
  }, [report]);

  const summaryTone = toneMap[report?.summary?.status || 'warn'];
  const canRepair = Boolean(report?.repairAvailable) || sortedChecks.some((item) => item.repairable);
  const startupDurationText = typeof report?.startupDurationMs === 'number'
    ? `${(report.startupDurationMs / 1000).toFixed(1)}s`
    : '-';
  const startupElapsedText = typeof report?.startupElapsedSec === 'number'
    ? `${report.startupElapsedSec}s`
    : '-';

  return (
    <div className="flex h-full flex-col overflow-hidden bg-transparent">
      <div className="flex h-[76px] shrink-0 items-center justify-between border-b border-border bg-surface px-8">
        <div>
          <h1 className="text-xl font-bold text-text">环境诊断</h1>
          <p className="mt-1 text-sm text-text-muted">无需授权即可检查并修复端口占用、残留进程、U盘读写和启动目录</p>
        </div>
        <div className="flex items-center gap-3">
          <Button variant="quiet" onClick={handleCopySummary} disabled={!report || loading || repairing}>
            复制摘要
          </Button>
          <Button variant="quiet" onClick={runDiagnostics} disabled={loading || repairing}>
            {loading ? '诊断中...' : '重新诊断'}
          </Button>
          <Button variant="quiet" onClick={handleExport} disabled={loading || repairing || exporting}>
            {exporting ? '导出中...' : '导出诊断包'}
          </Button>
          <Button variant="primary" onClick={handleRepair} disabled={loading || repairing}>
            {repairing ? '修复中...' : canRepair ? '一键修复' : '重新整理环境'}
          </Button>
        </div>
      </div>

      <div className="flex-1 overflow-auto p-8">
        <div className="grid gap-4 xl:grid-cols-[330px_minmax(0,1fr)]">
          <aside className="space-y-4">
            <section className={`rounded-2xl border p-5 ${summaryTone.panel}`}>
              <div className="flex items-center gap-3">
                <span className={`h-3 w-3 rounded-full ${summaryTone.dot}`} />
                <div>
                  <div className="text-sm font-bold text-text">整体状态</div>
                  <div className="text-2xl font-black text-text">{summaryTone.label}</div>
                </div>
              </div>
              <div className="mt-5 grid grid-cols-3 gap-2 text-center">
                <div className="rounded-xl border border-border bg-black/10 p-3">
                  <div className="text-lg font-black text-status-success">{report?.summary?.ok ?? '-'}</div>
                  <div className="text-[11px] text-text-subtle">正常</div>
                </div>
                <div className="rounded-xl border border-border bg-black/10 p-3">
                  <div className="text-lg font-black text-status-warning">{report?.summary?.warnings ?? '-'}</div>
                  <div className="text-[11px] text-text-subtle">需处理</div>
                </div>
                <div className="rounded-xl border border-border bg-black/10 p-3">
                  <div className="text-lg font-black text-status-danger">{report?.summary?.failed ?? '-'}</div>
                  <div className="text-[11px] text-text-subtle">阻塞</div>
                </div>
              </div>
            </section>

            <section className="rounded-2xl border border-border bg-surface-alt/70 p-5">
              <h2 className="text-sm font-bold text-text">当前安装目录</h2>
              <div className="mt-3 break-all rounded-lg border border-border bg-black/10 px-3 py-2 font-mono text-xs text-text-subtle">
                {report?.basePath || '等待诊断结果...'}
              </div>
              <div className="mt-4 flex items-center justify-between text-sm">
                <span className="text-text-muted">服务 PID</span>
                <span className="font-mono text-text">{report?.servicePid || '未运行'}</span>
              </div>
            </section>

            <section className="rounded-2xl border border-border bg-surface-alt/70 p-5">
              <h2 className="text-sm font-bold text-text">启动耗时</h2>
              <div className="mt-4 grid grid-cols-2 gap-2">
                <div className="rounded-xl border border-border bg-black/10 p-3">
                  <div className="text-[11px] text-text-subtle">最近完成</div>
                  <div className="mt-1 font-mono text-base font-bold text-text">{startupDurationText}</div>
                </div>
                <div className="rounded-xl border border-border bg-black/10 p-3">
                  <div className="text-[11px] text-text-subtle">当前等待</div>
                  <div className="mt-1 font-mono text-base font-bold text-text">{startupElapsedText}</div>
                </div>
              </div>
              <div className="mt-3 space-y-2 text-xs text-text-muted">
                <div className="flex items-center justify-between gap-3">
                  <span>状态</span>
                  <span className="font-mono text-text">{report?.startupState || '-'}</span>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <span>阶段</span>
                  <span className="font-mono text-text">{report?.startupStage || '-'}</span>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <span>超时</span>
                  <span className="font-mono text-text">{report?.startupTimeoutSec ? `${report.startupTimeoutSec}s` : '-'}</span>
                </div>
              </div>
              {report?.startupError && (
                <div className="mt-3 break-all rounded-lg border border-border bg-black/10 px-3 py-2 font-mono text-xs text-text-subtle">
                  {report.startupError}
                </div>
              )}
              {report?.startupSnapshotPath && (
                <div className="mt-3 break-all rounded-lg border border-border bg-black/10 px-3 py-2 font-mono text-xs text-text-subtle">
                  {report.startupSnapshotPath}
                </div>
              )}
            </section>

            {exportInfo && (
              <section className="rounded-2xl border border-border bg-surface-alt/70 p-5">
                <div className="flex items-center justify-between gap-3">
                  <h2 className="text-sm font-bold text-text">诊断包</h2>
                  <Button variant="quiet" className="px-3 py-1.5 text-xs" onClick={handleOpenExportDir}>
                    打开目录
                  </Button>
                </div>
                <div className="mt-3 break-all rounded-lg border border-border bg-black/10 px-3 py-2 font-mono text-xs text-text-subtle">
                  {exportInfo.path}
                </div>
                <div className="mt-3 text-xs text-text-muted">
                  大小: {Math.max(1, Math.round(exportInfo.size / 1024))} KB
                </div>
              </section>
            )}

            {actions.length > 0 && (
              <section className="rounded-2xl border border-border bg-surface-alt/70 p-5">
                <h2 className="text-sm font-bold text-text">修复记录</h2>
                <div className="mt-3 space-y-2">
                  {actions.map((action, index) => (
                    <ActionRow key={`${action.label}-${index}`} action={action} />
                  ))}
                </div>
              </section>
            )}
          </aside>

          <section className="min-w-0 rounded-2xl border border-border bg-surface-alt/70 p-5">
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-sm font-bold uppercase tracking-[0.18em] text-text-subtle">检查项</h2>
              <span className="text-xs text-text-muted">{report?.summary?.total ?? 0} items</span>
            </div>
            <div className="space-y-3">
              {sortedChecks.map((check) => (
                <CheckRow key={check.id} check={check} />
              ))}
              {!loading && sortedChecks.length === 0 && (
                <div className="rounded-xl border border-border bg-black/10 p-8 text-center text-sm text-text-muted">
                  暂无诊断结果
                </div>
              )}
              {loading && (
                <div className="rounded-xl border border-border bg-black/10 p-8 text-center text-sm text-text-muted">
                  正在检查本机环境...
                </div>
              )}
            </div>
          </section>
        </div>
      </div>
    </div>
  );
};
