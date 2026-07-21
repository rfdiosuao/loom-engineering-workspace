import React from 'react';
import { invoke } from '@tauri-apps/api/core';
import { BusyOverlay, Button, showConfirm, showToast } from '../common';
import {
  diagnosticsApi,
  parseErrorText,
  type DiagnosticCheck,
  type DiagnosticExportResult,
  type DiagnosticReport,
  type DiagnosticRepairResult,
  type DiagnosticStatus,
} from '../../services/api';
import { APP_DISPLAY_NAME } from '../../version';

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
    dot: 'bg-status-warning shadow-[0_0_12px_rgba(79,112,95,0.45)]',
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

function isRetiredOpenClawCheck(check: DiagnosticCheck): boolean {
  return /^OpenClaw\s*(启动入口|本体|基础配置)$/i.test(String(check.label || '').trim());
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
        <details className="mt-3 rounded-lg border border-border bg-black/10 px-3 py-2">
          <summary className="cursor-pointer text-xs font-bold text-text-muted">高级详情</summary>
          <div className="mt-2 break-all font-mono text-xs leading-relaxed text-text-subtle">
            {check.detail}
          </div>
        </details>
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
        const message = parseErrorText(error) || 'Bridge 启动失败，请查看诊断详情。';
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
        const message = parseErrorText(fallbackError) || parseErrorText(error) || `诊断服务不可用，请使用 ${APP_DISPLAY_NAME} 桌面应用重新打开。`;
        showToast(`诊断失败: ${message}`, 'error');
      }
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    runDiagnostics();
  }, [runDiagnostics]);

  const handleRepair = async () => {
    if (!canRepair) {
      showToast('当前没有可自动修复的检查项，请先重新诊断或导出诊断包。', 'info');
      return;
    }
    const ok = await showConfirm({
      title: '执行环境修复',
      message: '可能会停止残留进程并清理临时状态。确定继续吗？',
      confirmText: '开始修复',
      tone: 'danger',
    });
    if (!ok) return;
    setRepairing(true);
    try {
      const result = await diagnosticsApi.repair({ confirmed: true });
      setActions(result.actions || []);
      setReport(result.diagnostics);
      const hasFailedAction = result.actions.some((action) => action.status === 'fail');
      const hasWarnAction = result.actions.some((action) => action.status === 'warn');
      if (hasFailedAction) {
        showToast('环境修复未完成，请查看失败项并重新诊断', 'error');
      } else if (hasWarnAction) {
        showToast('环境修复后仍有需要手动处理的项目', 'info');
      } else {
        showToast('一键修复已完成，可以重新检测运行状态', 'success');
      }
    } catch (error: any) {
      showToast(`修复失败: ${parseErrorText(error) || '环境修复未完成，请重新诊断。'}`, 'error');
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
      showToast(`导出失败: ${parseErrorText(error) || '诊断包导出失败，请检查写入权限。'}`, 'error');
    } finally {
      setExporting(false);
    }
  };

  const handleOpenExportDir = async () => {
    if (!exportInfo?.directory) return;
    try {
      await invoke('open_path', { path: exportInfo.directory });
    } catch (error: any) {
      showToast(`打开目录失败: ${parseErrorText(error) || '无法打开诊断包目录。'}`, 'error');
    }
  };

  const handleCopySummary = async () => {
    if (!report) {
      showToast('暂无诊断结果可复制', 'info');
      return;
    }
    const checks = [...(report.checks || [])]
      .filter((check) => !isRetiredOpenClawCheck(check))
      .sort((a, b) => statusPriority(a.status) - statusPriority(b.status));
    const failed = checks.filter((check) => check.status === 'fail').length;
    const warnings = checks.filter((check) => check.status === 'warn').length;
    const ok = checks.filter((check) => check.status === 'ok').length;
    const lines = [
      `${APP_DISPLAY_NAME} 环境诊断摘要`,
      `状态: ${failed ? 'fail' : warnings ? 'warn' : 'ok'} | 正常 ${ok} / 警告 ${warnings} / 阻塞 ${failed}`,
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
      showToast(`复制失败: ${parseErrorText(error) || '浏览器剪贴板暂不可用。'}`, 'error');
    }
  };

  const sortedChecks = React.useMemo(() => {
    return [...(report?.checks || [])]
      .filter((check) => !isRetiredOpenClawCheck(check))
      .sort((a, b) => statusPriority(a.status) - statusPriority(b.status));
  }, [report]);

  const visibleSummary = React.useMemo(() => {
    const failed = sortedChecks.filter((check) => check.status === 'fail').length;
    const warnings = sortedChecks.filter((check) => check.status === 'warn').length;
    const ok = sortedChecks.filter((check) => check.status === 'ok').length;
    return { failed, warnings, ok, total: sortedChecks.length, status: failed ? 'fail' : warnings ? 'warn' : 'ok' } as const;
  }, [sortedChecks]);
  const summaryTone = toneMap[visibleSummary.status];
  const canRepair = sortedChecks.some((item) => item.repairable);
  const startupDurationText = typeof report?.startupDurationMs === 'number'
    ? `${(report.startupDurationMs / 1000).toFixed(1)}s`
    : '-';
  const startupElapsedText = typeof report?.startupElapsedSec === 'number'
    ? `${report.startupElapsedSec}s`
    : '-';

  const busyOverlayTitle = repairing
    ? '正在修复环境'
    : exporting
      ? '正在导出诊断包'
      : '正在诊断环境';

  return (
    <div className="flex h-full flex-col overflow-hidden bg-transparent">
      <BusyOverlay
        active={loading || repairing || exporting}
        title={busyOverlayTitle}
        detail={`${APP_DISPLAY_NAME} 正在检查本机运行环境，请稍候。`}
      />
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
          <Button variant="primary" onClick={handleRepair} disabled={loading || repairing || !canRepair}>
            {repairing ? '修复中...' : canRepair ? '一键修复' : '无可修复项'}
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
                  <div className="text-lg font-black text-status-success">{visibleSummary.ok}</div>
                  <div className="text-[11px] text-text-subtle">正常</div>
                </div>
                <div className="rounded-xl border border-border bg-black/10 p-3">
                  <div className="text-lg font-black text-status-warning">{visibleSummary.warnings}</div>
                  <div className="text-[11px] text-text-subtle">需处理</div>
                </div>
                <div className="rounded-xl border border-border bg-black/10 p-3">
                  <div className="text-lg font-black text-status-danger">{visibleSummary.failed}</div>
                  <div className="text-[11px] text-text-subtle">阻塞</div>
                </div>
              </div>
            </section>

            <section className="rounded-2xl border border-border bg-surface-alt/70 p-5">
              <h2 className="text-sm font-bold text-text">安装状态</h2>
              <div className="mt-3 rounded-lg border border-border bg-black/10 px-3 py-2 text-sm font-bold text-text">
                {report?.basePath ? '已定位安装目录' : '等待诊断结果...'}
              </div>
              <div className="mt-4 flex items-center justify-between text-sm">
                <span className="text-text-muted">核心服务</span>
                <span className="font-bold text-text">{report?.servicePid ? '已运行' : '未运行'}</span>
              </div>
              {report?.basePath || report?.servicePid ? (
                <details className="mt-3 rounded-lg border border-border bg-black/10 px-3 py-2">
                  <summary className="cursor-pointer text-xs font-bold text-text-muted">高级详情</summary>
                  <div className="mt-2 space-y-2 break-all font-mono text-xs text-text-subtle">
                    <div>basePath: {report?.basePath || '-'}</div>
                    <div>pid: {report?.servicePid || '-'}</div>
                  </div>
                </details>
              ) : null}
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
              {report?.startupError || report?.startupSnapshotPath ? (
                <details className="mt-3 rounded-lg border border-border bg-black/10 px-3 py-2">
                  <summary className="cursor-pointer text-xs font-bold text-text-muted">高级启动详情</summary>
                  <div className="mt-2 space-y-2 break-all font-mono text-xs text-text-subtle">
                    {report?.startupError ? <div>error: {report.startupError}</div> : null}
                    {report?.startupSnapshotPath ? <div>snapshot: {report.startupSnapshotPath}</div> : null}
                  </div>
                </details>
              ) : null}
            </section>

            {exportInfo && (
              <section className="rounded-2xl border border-border bg-surface-alt/70 p-5">
                <div className="flex items-center justify-between gap-3">
                  <h2 className="text-sm font-bold text-text">诊断包</h2>
                  <Button variant="quiet" className="px-3 py-1.5 text-xs" onClick={handleOpenExportDir}>
                    打开目录
                  </Button>
                </div>
                <div className="mt-3 truncate rounded-lg border border-border bg-black/10 px-3 py-2 text-sm font-bold text-text" title={exportInfo.filename}>
                  {exportInfo.filename}
                </div>
                <div className="mt-3 text-xs text-text-muted">
                  大小: {Math.max(1, Math.round(exportInfo.size / 1024))} KB
                </div>
                <details className="mt-3 rounded-lg border border-border bg-black/10 px-3 py-2">
                  <summary className="cursor-pointer text-xs font-bold text-text-muted">高级详情</summary>
                  <div className="mt-2 space-y-2 break-all font-mono text-xs text-text-subtle">
                    <div>path: {exportInfo.path}</div>
                    <div>directory: {exportInfo.directory}</div>
                  </div>
                </details>
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
              <span className="text-xs text-text-muted">{visibleSummary.total} 项</span>
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
