import React from 'react';
import { createPortal } from 'react-dom';
import {
  AlertTriangle,
  Check,
  CheckCircle2,
  Download,
  LoaderCircle,
  RefreshCw,
  RotateCcw,
  ShieldCheck,
  Sparkles,
  X,
} from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

import { Button, showToast } from '../common';
import {
  parseErrorText,
  shouldPresentUpdate,
  updateApi,
  type UpdateCheckResponse,
  type UpdateProgressResponse,
  type UpdateResultReceipt,
} from '../../services/api';

const UPDATE_CENTER_OPEN_EVENT = 'loom:update-center:open';
const SKIPPED_VERSION_KEY = 'loom.update.skippedVersion';
const LAST_CHECK_KEY = 'loom.update.lastAutomaticCheckAt';
const AUTO_CHECK_INTERVAL_MS = 6 * 60 * 60 * 1000;

type UpdatePhase =
  | 'idle'
  | 'checking'
  | 'available'
  | 'current'
  | 'downloading'
  | 'verifying'
  | 'ready'
  | 'restarting'
  | 'success'
  | 'cancelled'
  | 'failed';

export function shouldReuseUpdateSession(phase: string): boolean {
  return ['available', 'downloading', 'verifying', 'ready', 'restarting', 'success', 'cancelled'].includes(phase);
}

interface OpenUpdateCenterDetail {
  manual?: boolean;
}

export function requestUpdateCenterOpen(): void {
  window.dispatchEvent(new CustomEvent<OpenUpdateCenterDetail>(UPDATE_CENTER_OPEN_EVENT, {
    detail: { manual: true },
  }));
}

function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return '';
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
  if (bytes >= 1024 ** 2) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

function progressPhase(progress: UpdateProgressResponse): UpdatePhase {
  if (progress.phase === 'verifying_signature') return 'verifying';
  if (progress.phase === 'ready') return 'ready';
  if (progress.phase === 'cancelled') return 'cancelled';
  if (progress.phase === 'failed') return 'failed';
  return 'downloading';
}

function resultTitle(result: UpdateResultReceipt): string {
  return result.status === 'success' ? '更新成功' : '已恢复上一版本';
}

function resultMessage(result: UpdateResultReceipt): string {
  if (result.status === 'success') return `LOOM ${result.version} 已安装并通过运行健康检查。`;
  return result.message || '新版启动检查未通过，LOOM 已尝试恢复更新前的版本。';
}

export const UpdateCenter: React.FC = () => {
  const [visible, setVisible] = React.useState(false);
  const [phase, setPhase] = React.useState<UpdatePhase>('idle');
  const [release, setRelease] = React.useState<UpdateCheckResponse | null>(null);
  const [progress, setProgress] = React.useState<UpdateProgressResponse | null>(null);
  const [receipt, setReceipt] = React.useState<UpdateResultReceipt | null>(null);
  const [installerPath, setInstallerPath] = React.useState('');
  const [errorMessage, setErrorMessage] = React.useState('');
  const [remediation, setRemediation] = React.useState<string[]>([]);
  const [cancelPending, setCancelPending] = React.useState(false);
  const requestSequence = React.useRef(0);
  const phaseRef = React.useRef<UpdatePhase>('idle');
  const visibleRef = React.useRef(false);

  React.useEffect(() => {
    phaseRef.current = phase;
  }, [phase]);

  React.useEffect(() => {
    visibleRef.current = visible;
  }, [visible]);

  const checkForUpdate = React.useCallback(async (manual: boolean) => {
    if (!manual && shouldReuseUpdateSession(phaseRef.current)) return;
    const sequence = ++requestSequence.current;
    if (manual) setVisible(true);
    setPhase('checking');
    setErrorMessage('');
    setRemediation([]);
    try {
      const nextRelease = await updateApi.check();
      if (sequence !== requestSequence.current) return;
      setRelease(nextRelease);
      window.localStorage.setItem(LAST_CHECK_KEY, String(Date.now()));
      if (!nextRelease.hasUpdate) {
        setPhase('current');
        if (manual) setVisible(true);
        return;
      }
      const skipped = window.localStorage.getItem(SKIPPED_VERSION_KEY) || '';
      if (!shouldPresentUpdate(nextRelease.latest, skipped, manual)) {
        setPhase('idle');
        return;
      }
      setPhase('available');
      setVisible(true);
    } catch (error) {
      if (sequence !== requestSequence.current) return;
      if (!manual) {
        setPhase('idle');
        return;
      }
      setErrorMessage(parseErrorText(error) || '暂时无法连接更新服务器。');
      setPhase('failed');
      setVisible(true);
    }
  }, []);

  React.useEffect(() => {
    const handleOpen = () => {
      if (shouldReuseUpdateSession(phaseRef.current)) {
        setVisible(true);
        return;
      }
      void checkForUpdate(true);
    };
    window.addEventListener(UPDATE_CENTER_OPEN_EVENT, handleOpen);
    return () => window.removeEventListener(UPDATE_CENTER_OPEN_EVENT, handleOpen);
  }, [checkForUpdate]);

  React.useEffect(() => {
    const lastCheck = Number(window.localStorage.getItem(LAST_CHECK_KEY) || 0);
    if (Date.now() - lastCheck < AUTO_CHECK_INTERVAL_MS) return undefined;
    const timer = window.setTimeout(() => void checkForUpdate(false), 8_000);
    return () => window.clearTimeout(timer);
  }, [checkForUpdate]);

  React.useEffect(() => {
    let stopped = false;
    let attempts = 0;
    const pollResult = async () => {
      if (stopped || attempts >= 90) return;
      attempts += 1;
      try {
        const response = await updateApi.result();
        if (stopped) return;
        if (response.result) {
          setReceipt(response.result);
          setPhase(response.result.status === 'success' ? 'success' : 'failed');
          setErrorMessage(response.result.status === 'failed' ? resultMessage(response.result) : '');
          setRemediation(response.result.remediation || []);
          setVisible(true);
          return;
        }
        if (!response.pending) return;
      } catch {
        // Bridge may still be starting during a post-update health handshake.
      }
      window.setTimeout(pollResult, attempts < 12 ? 1_000 : 4_000);
    };
    const timer = window.setTimeout(pollResult, 1_200);
    return () => {
      stopped = true;
      window.clearTimeout(timer);
    };
  }, []);

  React.useEffect(() => {
    if (!visible) return undefined;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && phaseRef.current !== 'restarting') setVisible(false);
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [visible]);

  const startDownload = async () => {
    setPhase('downloading');
    setProgress({
      phase: 'downloading',
      downloaded: 0,
      total: release?.size || 0,
      percent: 0,
      version: release?.latest || '',
      message: '正在连接更新服务器',
      errorCode: '',
      retryable: false,
      remediation: [],
    });
    setErrorMessage('');
    setRemediation([]);
    setCancelPending(false);

    const pollTimer = window.setInterval(() => {
      void updateApi.status().then((next) => {
        setProgress(next);
        setPhase(progressPhase(next));
      }).catch(() => undefined);
    }, 350);
    try {
      const response = await updateApi.do();
      if (response.outcome === 'cancelled') {
        setPhase('cancelled');
        setRemediation(response.remediation || []);
        return;
      }
      if (response.outcome === 'already_current') {
        setPhase('current');
        return;
      }
      if (!response.success || response.outcome !== 'ready' || !response.installer_path.trim()) {
        throw response;
      }
      setInstallerPath(response.installer_path);
      setPhase('ready');
      setProgress((current) => current ? { ...current, phase: 'ready', percent: 100 } : current);
      if (!visibleRef.current) {
        showToast(`LOOM ${response.current_version} 已下载完成，等待重启安装`, 'success');
      }
    } catch (error) {
      const detail = error && typeof error === 'object'
        ? error as { remediation?: string[] }
        : {};
      setErrorMessage(parseErrorText(error) || '更新下载失败，当前版本没有受到影响。');
      setRemediation(Array.isArray(detail.remediation) ? detail.remediation : []);
      setPhase('failed');
      setVisible(true);
    } finally {
      window.clearInterval(pollTimer);
      setCancelPending(false);
    }
  };

  const cancelDownload = async () => {
    setCancelPending(true);
    try {
      const response = await updateApi.cancel();
      if (!response.cancelRequested) {
        setCancelPending(false);
        showToast('更新已进入校验阶段，无法取消，请稍候。', 'info');
      }
    } catch (error) {
      setCancelPending(false);
      showToast(parseErrorText(error) || '取消更新失败', 'error');
    }
  };

  const restartAndInstall = async () => {
    if (!installerPath) return;
    setPhase('restarting');
    try {
      await updateApi.prepareInstall(installerPath);
    } catch (error) {
      setErrorMessage(parseErrorText(error) || '无法启动安全更新接力。');
      setPhase('failed');
    }
  };

  const skipVersion = () => {
    if (release?.latest) window.localStorage.setItem(SKIPPED_VERSION_KEY, release.latest);
    setVisible(false);
  };

  if (!visible) return null;

  const percent = progress?.percent || 0;
  const busy = phase === 'downloading' || phase === 'verifying' || phase === 'restarting';
  const title = receipt
    ? resultTitle(receipt)
    : phase === 'current'
      ? '已是最新版本'
      : phase === 'ready'
        ? '更新已准备好'
        : phase === 'failed'
          ? '更新没有完成'
          : phase === 'cancelled'
            ? '已暂停更新'
            : phase === 'checking'
              ? '正在检查更新'
              : '发现新版本';

  return createPortal(
    <div className="fixed inset-0 z-[180] flex items-center justify-center bg-[#001820]/60 px-5 py-8 backdrop-blur-[7px]">
      <section
        role="dialog"
        aria-modal="true"
        aria-labelledby="loom-update-title"
        data-update-phase={phase}
        className="update-center-enter flex max-h-[min(82vh,760px)] w-full max-w-[680px] flex-col overflow-hidden rounded-[8px] border border-border-strong bg-surface shadow-[0_32px_110px_rgba(0,18,24,0.48)]"
      >
        <header className="flex shrink-0 items-center gap-4 border-b border-border bg-surface-alt/50 px-6 py-5">
          <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-[8px] border ${
            phase === 'success'
              ? 'border-status-success/35 bg-status-success/12 text-status-success'
              : phase === 'failed'
                ? 'border-status-danger/35 bg-status-danger/10 text-status-danger'
                : 'border-accent/25 bg-accent/10 text-accent'
          }`}>
            {phase === 'success' ? <CheckCircle2 size={21} /> : phase === 'failed' ? <AlertTriangle size={21} /> : <Sparkles size={21} />}
          </div>
          <div className="min-w-0 flex-1">
            <h2 id="loom-update-title" className="text-[18px] font-black text-text">{title}</h2>
            <p className="mt-0.5 truncate text-xs font-semibold text-text-muted">
              {release ? `LOOM ${release.current}  →  ${release.latest}` : 'LOOM 安全更新中心'}
            </p>
          </div>
          <button
            type="button"
            aria-label={busy ? '隐藏更新窗口' : '关闭更新窗口'}
            title={busy ? '后台继续' : '关闭'}
            onClick={() => setVisible(false)}
            disabled={phase === 'restarting'}
            className="flex h-9 w-9 items-center justify-center rounded-[8px] text-text-muted transition hover:bg-hover hover:text-text disabled:opacity-40"
          >
            <X size={18} />
          </button>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto px-7 py-6">
          {phase === 'checking' ? (
            <div className="flex min-h-[240px] flex-col items-center justify-center text-center">
              <LoaderCircle size={34} className="animate-spin text-accent" />
              <div className="mt-5 text-base font-black text-text">正在连接正式发布通道</div>
              <div className="mt-2 text-sm text-text-muted">检查版本、发布说明与完整性信息</div>
            </div>
          ) : null}

          {phase === 'current' ? (
            <div className="flex min-h-[230px] flex-col items-center justify-center text-center">
              <div className="flex h-14 w-14 items-center justify-center rounded-full bg-status-success/12 text-status-success">
                <Check size={28} />
              </div>
              <div className="mt-5 text-xl font-black text-text">当前版本 {release?.current}</div>
              <div className="mt-2 text-sm text-text-muted">已经安装正式通道的最新版本。</div>
            </div>
          ) : null}

          {phase === 'available' ? (
            <>
              <div className="grid gap-4 border-b border-border pb-5 sm:grid-cols-[1fr_auto] sm:items-end">
                <div>
                  <div className="text-[11px] font-black tracking-[0.24em] text-accent">正式版本</div>
                  <div className="mt-2 text-[28px] font-black leading-none text-text">v{release?.latest}</div>
                  <div className="mt-3 text-sm text-text-muted">当前版本 v{release?.current}，新版本已可用。</div>
                </div>
                <div className="text-left text-xs font-semibold leading-5 text-text-muted sm:text-right">
                  {release?.size ? <div>{formatBytes(release.size)}</div> : null}
                  {release?.publishedAt ? <div>{new Date(release.publishedAt).toLocaleDateString('zh-CN')}</div> : null}
                </div>
              </div>
              <div className="mt-5">
                <div className="mb-3 flex items-center gap-2 text-sm font-black text-text">
                  <ShieldCheck size={17} className="text-accent" />
                  更新内容
                </div>
                <div className="update-release-notes max-h-[330px] overflow-y-auto pr-3 text-sm leading-6 text-text-muted">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {release?.notes || '本次版本包含稳定性、兼容性与使用体验改进。'}
                  </ReactMarkdown>
                </div>
              </div>
            </>
          ) : null}

          {phase === 'downloading' || phase === 'verifying' || phase === 'ready' || phase === 'restarting' ? (
            <div className="space-y-6">
              <div className="flex items-start gap-4">
                <div className="mt-0.5 flex h-11 w-11 items-center justify-center rounded-[8px] border border-accent/20 bg-accent/8 text-accent">
                  {phase === 'ready' ? <ShieldCheck size={22} /> : phase === 'restarting' ? <RotateCcw size={22} className="animate-spin" /> : <Download size={22} />}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="text-base font-black text-text">
                    {phase === 'verifying'
                      ? '正在验证 LOOM 官方发布签名'
                      : phase === 'ready'
                        ? '下载与安全校验已完成'
                        : phase === 'restarting'
                          ? '正在移交安全更新进程'
                          : progress?.message || '正在下载安装包'}
                  </div>
                  <div className="mt-1 text-sm leading-6 text-text-muted">
                    {phase === 'ready'
                      ? '重启后会自动备份数据、静默安装并执行健康检查；失败时恢复上一版本。'
                      : phase === 'restarting'
                        ? 'LOOM 即将关闭，更新将在后台静默完成。'
                        : '可以隐藏此窗口，下载会在后台继续。'}
                  </div>
                </div>
              </div>
              <div>
                <div className="h-2 overflow-hidden rounded-full bg-surface-deep/15">
                  <div
                    className={`h-full rounded-full bg-accent transition-[width] duration-300 ${phase === 'verifying' ? 'update-progress-pulse' : ''}`}
                    style={{ width: `${phase === 'ready' || phase === 'restarting' ? 100 : Math.max(2, percent)}%` }}
                  />
                </div>
                <div className="mt-2 flex items-center justify-between text-xs font-semibold text-text-muted">
                  <span>{phase === 'verifying' ? 'SHA256 与 LOOM 官方发布签名校验' : progress?.total ? `${formatBytes(progress.downloaded)} / ${formatBytes(progress.total)}` : '准备下载'}</span>
                  <span>{phase === 'ready' || phase === 'restarting' ? '100%' : `${percent}%`}</span>
                </div>
              </div>
              <div className="border-y border-border py-4 text-xs leading-6 text-text-muted">
                <div className="flex items-center gap-2 font-black text-text"><ShieldCheck size={15} className="text-status-success" />安全更新保护已启用</div>
                <div className="mt-1">断点续传、签名校验、数据备份、启动健康检查与失败回滚均由本机完成。</div>
              </div>
            </div>
          ) : null}

          {phase === 'success' && receipt ? (
            <div className="flex min-h-[260px] flex-col items-center justify-center text-center">
              <div className="flex h-16 w-16 items-center justify-center rounded-full border border-status-success/25 bg-status-success/10 text-status-success">
                <CheckCircle2 size={32} />
              </div>
              <div className="mt-5 text-[26px] font-black text-text">LOOM {receipt.version}</div>
              <div className="mt-2 max-w-[440px] text-sm leading-6 text-text-muted">{resultMessage(receipt)}</div>
              <div className="mt-5 rounded-[8px] border border-status-success/20 bg-status-success/8 px-4 py-3 text-xs font-semibold text-status-success">
                新版本运行时与 Bridge 已通过健康检查
              </div>
            </div>
          ) : null}

          {phase === 'cancelled' ? (
            <div className="flex min-h-[230px] flex-col items-center justify-center text-center">
              <div className="flex h-14 w-14 items-center justify-center rounded-full bg-accent/10 text-accent"><Download size={26} /></div>
              <div className="mt-5 text-xl font-black text-text">下载已暂停</div>
              <div className="mt-2 text-sm text-text-muted">已下载的有效内容会被保留，下次可继续。</div>
            </div>
          ) : null}

          {phase === 'failed' ? (
            <div className="space-y-5">
              <div className="rounded-[8px] border border-status-danger/25 bg-status-danger/8 p-4">
                <div className="flex items-center gap-2 text-sm font-black text-status-danger"><AlertTriangle size={17} />{receipt ? resultTitle(receipt) : '更新没有完成'}</div>
                <div className="mt-2 text-sm leading-6 text-text">{errorMessage || '当前版本保持不变，可以稍后重试。'}</div>
              </div>
              {remediation.length ? (
                <div>
                  <div className="text-sm font-black text-text">建议处理</div>
                  <ul className="mt-2 space-y-2 text-sm leading-6 text-text-muted">
                    {remediation.map((item) => <li key={item} className="flex gap-2"><span className="text-accent">•</span><span>{item}</span></li>)}
                  </ul>
                </div>
              ) : null}
            </div>
          ) : null}
        </div>

        <footer className="flex min-h-[74px] shrink-0 flex-wrap items-center justify-end gap-3 border-t border-border bg-surface-alt/65 px-6 py-4">
          {phase === 'available' ? (
            <>
              <Button variant="quiet" onClick={() => setVisible(false)}>稍后</Button>
              <Button variant="quiet" onClick={skipVersion}>跳过此版本</Button>
              <Button variant="primary" onClick={() => void startDownload()}><Download size={16} className="mr-2 inline" />立即更新</Button>
            </>
          ) : null}
          {phase === 'checking' ? <Button variant="quiet" onClick={() => setVisible(false)}>后台检查</Button> : null}
          {phase === 'current' || phase === 'success' ? <Button variant="primary" onClick={() => setVisible(false)}>我知道了</Button> : null}
          {phase === 'downloading' || phase === 'verifying' ? (
            <>
              <Button variant="quiet" onClick={() => setVisible(false)}>后台下载</Button>
              <Button variant="danger" disabled={cancelPending || phase === 'verifying'} onClick={() => void cancelDownload()}>
                {cancelPending ? '正在取消' : '取消下载'}
              </Button>
            </>
          ) : null}
          {phase === 'ready' ? (
            <>
              <Button variant="quiet" onClick={() => setVisible(false)}>稍后重启</Button>
              <Button variant="primary" onClick={() => void restartAndInstall()}><RefreshCw size={16} className="mr-2 inline" />立即重启</Button>
            </>
          ) : null}
          {phase === 'restarting' ? <Button variant="quiet" disabled>正在重启...</Button> : null}
          {phase === 'cancelled' ? (
            <>
              <Button variant="quiet" onClick={() => setVisible(false)}>关闭</Button>
              <Button variant="primary" onClick={() => void startDownload()}>继续下载</Button>
            </>
          ) : null}
          {phase === 'failed' ? (
            <>
              <Button variant="quiet" onClick={() => setVisible(false)}>关闭</Button>
              {!receipt ? <Button variant="primary" onClick={() => void checkForUpdate(true)}><RefreshCw size={16} className="mr-2 inline" />重新检查</Button> : null}
            </>
          ) : null}
        </footer>
      </section>
    </div>,
    document.body,
  );
};
