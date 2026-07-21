import React, { useEffect, useRef, useState } from 'react';
import { open } from '@tauri-apps/plugin-shell';
import { getCurrentWindow } from '@tauri-apps/api/window';
import { Sidebar } from './components/sidebar/Sidebar';
import { WindowTitlebar } from './components/window/WindowTitlebar';
import { ConfirmDialogHost, ToastContainer, showConfirm, showToast } from './components/common';
import { useAppStore } from './stores/appStore';
import { useLogStore } from './stores/logStore';
import { processApi, logApi, parseErrorText, resolveUpdateDisposition, updateApi } from './services/api';
import { detectApiConfigured } from './services/apiStatus';
import { ThemeProvider } from './providers/ThemeProvider';
import { useTheme } from './hooks/useTheme';
import { getFeatureDefinition } from './features/registry';
import { renderFeaturePage } from './features/pages';
import { SetupGate } from './components/SetupGate';
import { LoomSplash } from './components/brand/LoomSplash';

const NAV_PARENT_BY_PAGE: Record<string, string> = {
  models: 'license',
  diagnostics: 'agentAccess',
  settings: 'settings',
  terminal: 'agentAccess',
};

function formatError(error: unknown): string {
  const friendly = parseErrorText(error);
  if (friendly) return friendly;
  if (typeof error === 'string') return error;
  if (error && typeof error === 'object') {
    const value = error as { error?: unknown; message?: unknown };
    if (typeof value.error === 'string') return value.error;
    if (typeof value.message === 'string') return value.message;
    try {
      return JSON.stringify(error);
    } catch {
      return String(error);
    }
  }
  return String(error);
}

function safeCurrentWindow() {
  try {
    return getCurrentWindow();
  } catch {
    return null;
  }
}

function DynamicTitle() {
  const { windowTitle } = useTheme();

  useEffect(() => {
    document.title = windowTitle;
    safeCurrentWindow()?.setTitle(windowTitle).catch(() => {});
  }, [windowTitle]);

  return null;
}

export default function App() {
  const {
    currentPage,
    openFeature,
    serviceRunning,
    setServiceRunning,
    serviceStatus,
    setServiceStatus,
    isAuthorized,
    checkLicense,
  } = useAppStore();
  const appendLog = useLogStore((s) => s.append);
  const replaceLog = useLogStore((s) => s.replace);
  const [apiConfigured, setApiConfigured] = useState(false);
  const logInterval = useRef<ReturnType<typeof setInterval> | null>(null);
  const logOffset = useRef(0);
  const logGeneration = useRef('');
  const logCursorRevision = useRef(0);
  const logRequestInFlight = useRef(false);
  const lastLogPollingError = useRef('');

  const refreshApiConfigured = React.useCallback(async () => {
    setApiConfigured(await detectApiConfigured());
  }, []);

  const startLogPolling = () => {
    if (logInterval.current) return;
    logInterval.current = setInterval(async () => {
      if (logRequestInFlight.current) return;
      logRequestInFlight.current = true;
      const cursorRevision = logCursorRevision.current;
      try {
        const resp = await logApi.get({
          offset: logOffset.current,
          generation: logGeneration.current,
        });
        if (cursorRevision !== logCursorRevision.current) return;
        logOffset.current = resp.offset ?? logOffset.current;
        logGeneration.current = resp.generation || logGeneration.current;
        if (resp.reset) {
          replaceLog(resp.log || '');
        } else if (resp.log) {
          appendLog(resp.log);
        }
        lastLogPollingError.current = '';
      } catch (error) {
        const message = formatError(error);
        if (message !== lastLogPollingError.current) {
          appendLog(`[日志轮询] 错误: ${message}\n`);
          lastLogPollingError.current = message;
        }
      } finally {
        logRequestInFlight.current = false;
      }
    }, 1000);
  };

  const stopLogPolling = () => {
    if (logInterval.current) {
      clearInterval(logInterval.current);
      logInterval.current = null;
    }
  };

  useEffect(() => {
    checkLicense();
  }, [checkLicense]);

  useEffect(() => {
    refreshApiConfigured();
  }, [refreshApiConfigured]);

  // Reflect an already-running core service when the launcher is reopened, so
  // status and log polling don't require the user to hit "start" again.
  useEffect(() => {
    let cancelled = false;
    processApi.status().then((status) => {
      if (!cancelled && status.running) {
        setServiceRunning(true);
        setServiceStatus('running');
      }
    }).catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [setServiceRunning, setServiceStatus]);

  // Bridge owns the persisted application log, so keep polling it even when
  // the optional OpenClaw core service is stopped.
  useEffect(() => {
    startLogPolling();
    return () => stopLogPolling();
    // startLogPolling/stopLogPolling are stable closures over refs.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const resetOffset = (event: Event) => {
      logCursorRevision.current += 1;
      logOffset.current = 0;
      const generation = (event as CustomEvent<{ generation?: string }>).detail?.generation;
      if (generation) logGeneration.current = generation;
    };
    window.addEventListener('openclaw:logs-cleared', resetOffset);
    return () => window.removeEventListener('openclaw:logs-cleared', resetOffset);
  }, []);

  const handleStop = async () => {
    setServiceStatus('stopping');
    try {
      await processApi.stop();
      setServiceRunning(false);
      setServiceStatus('idle');
      showToast('服务已停止', 'info');
    } catch {
      setServiceStatus('idle');
      showToast('停止失败', 'error');
    }
  };

  const handleNavigate = async (key: string) => {
    const feature = getFeatureDefinition(key);

    if (feature?.action.type === 'external') {
      open(feature.action.url);
      return;
    }

    if (feature?.action.type === 'command' && feature.action.command === 'update') {
      let updateStarted = false;
      try {
        const resp = await updateApi.check();
        if (resp.hasUpdate) {
          showToast(`发现新版本 ${resp.current} -> ${resp.latest}`, 'info');
          const ok = await showConfirm({
            title: '发现新版本',
            message: `当前版本：${resp.current}\n最新版本：${resp.latest}\n是否现在更新？`,
            confirmText: '立即更新',
          });
          if (ok) {
            updateStarted = true;
            appendLog('[更新] 开始更新...\n');
            const updateResp = await updateApi.do();
            const disposition = resolveUpdateDisposition(updateResp);
            if (disposition === 'prepare_install') {
              await updateApi.prepareInstall(updateResp.installer_path);
            }
            showToast(
              disposition === 'prepare_install'
                ? `LOOM ${updateResp.current_version} 已完成校验，正在安全更新`
                : `已是最新版本 ${updateResp.current_version}`,
              disposition === 'prepare_install' ? 'success' : 'info',
            );
          }
        } else {
          showToast(`已是最新版本 ${resp.current}`, 'info');
        }
      } catch (error) {
        const message = formatError(error) || (updateStarted ? '更新失败' : '检查更新失败');
        if (updateStarted && error && typeof error === 'object') {
          const remediation = (error as { remediation?: unknown }).remediation;
          if (Array.isArray(remediation) && remediation.length) {
            appendLog(`[更新失败] ${message}\n${remediation.join('\n')}\n`);
          }
        }
        showToast(message, 'error');
      }
      return;
    }

    openFeature(key);
  };

  const visiblePage = currentPage;
  const activeNavPage = NAV_PARENT_BY_PAGE[visiblePage] || visiblePage;

  return (
    <ThemeProvider>
      <DynamicTitle />
      <div className="flex h-full w-full flex-col overflow-hidden bg-surface text-text">
        <WindowTitlebar />
        <div data-commercial-app-shell className="flex min-h-0 flex-1 flex-col overflow-hidden bg-surface">
          <div className="flex min-h-0 flex-1 overflow-hidden">
            <Sidebar
              activePage={activeNavPage}
              serviceRunning={serviceRunning}
              serviceStatus={serviceStatus}
              isAuthorized={isAuthorized}
              isApiConfigured={apiConfigured}
              onNavigate={handleNavigate}
              onStop={handleStop}
            />
            <main className="relative min-h-0 flex-1 overflow-hidden bg-surface">
              {renderFeaturePage(visiblePage)}
            </main>
          </div>
        </div>

        <ToastContainer />
        <ConfirmDialogHost />
        <LoomSplash />
        <SetupGate />
      </div>
    </ThemeProvider>
  );
}
