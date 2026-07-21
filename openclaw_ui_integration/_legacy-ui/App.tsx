import React, { useEffect, useRef, useState } from 'react';
import { open } from '@tauri-apps/plugin-shell';
import { getCurrentWindow } from '@tauri-apps/api/window';
import { Sidebar } from './components/sidebar/Sidebar';
import { WindowTitlebar } from './components/window/WindowTitlebar';
import { ToastContainer, showToast } from './components/common';
import { useAppStore } from './stores/appStore';
import { useLogStore } from './stores/logStore';
import { processApi, logApi, updateApi, configApi, licenseApi, waitForProcessReady } from './services/api';
import { ThemeProvider } from './providers/ThemeProvider';
import { useTheme } from './hooks/useTheme';
import { getFeatureDefinition } from './features/registry';
import { renderFeaturePage } from './features/pages';
import { ApiConfigDialog as ModernApiConfigDialog } from './components/dialogs/ApiConfigDialog';
import { DingtalkConfigDialog, FeishuConfigDialog, WeixinConfigDialog } from './components/dialogs/FeishuConfigDialog';

function formatError(error: unknown): string {
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

const AUTH_PROFILES_PATH = 'data/.openclaw/agents/main/agent/auth-profiles.json';

function hasConfiguredApiProfile(data: unknown): boolean {
  const models = (data as any)?.models;
  const providers = models?.providers;
  if (!providers || typeof providers !== 'object') return false;

  return Object.values(providers).some((provider: any) => {
    const apiKey = String(provider?.apiKey || '').trim();
    const baseUrl = String(provider?.baseUrl || provider?.url || '').trim();
    return apiKey.length > 0 && baseUrl.length > 0;
  });
}

export default function App() {
  const {
    currentPage,
    setCurrentPage,
    serviceRunning,
    setServiceRunning,
    serviceStatus,
    setServiceStatus,
    isAuthorized,
    isLicenseChecking,
    checkLicense,
  } = useAppStore();
  const appendLog = useLogStore((s) => s.append);
  const replaceLog = useLogStore((s) => s.replace);
  const [activeDialog, setActiveDialog] = useState<'api' | 'feishu' | 'weixin' | 'dingtalk' | null>(null);
  const [apiConfigured, setApiConfigured] = useState(false);
  const logInterval = useRef<ReturnType<typeof setInterval> | null>(null);
  const logOffset = useRef(0);

  const refreshApiConfigured = React.useCallback(async () => {
    try {
      const resp = await configApi.read(AUTH_PROFILES_PATH, { models: { providers: {} } });
      if (hasConfiguredApiProfile(resp.data)) {
        setApiConfigured(true);
        return;
      }
      const licenseResp = await licenseApi.current();
      const license = ((licenseResp as any).gatewayProfile || licenseResp.license || (licenseResp as any).member) as any;
      const gateway = license?.gateway || {};
      setApiConfigured(Boolean(
        String(license?.gatewayBaseUrl || license?.gatewayUrl || license?.baseUrl || gateway?.baseUrl || gateway?.url || '').trim()
        && String(license?.gatewayAccessToken || license?.gatewayToken || license?.apiKey || license?.memberToken || gateway?.apiKey || gateway?.token || '').trim(),
      ));
    } catch {
      setApiConfigured(false);
    }
  }, []);

  const startLogPolling = () => {
    if (logInterval.current) return;
    logInterval.current = setInterval(async () => {
      try {
        const resp = await logApi.get(logOffset.current);
        logOffset.current = resp.offset ?? logOffset.current;
        if (resp.reset) {
          replaceLog(resp.log || '');
        } else if (resp.log) {
          appendLog(resp.log);
        }
      } catch (error) {
        appendLog(`[日志轮询] 错误: ${formatError(error)}\n`);
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
    refreshApiConfigured();
  }, [checkLicense, refreshApiConfigured]);

  useEffect(() => {
    const resetOffset = () => {
      logOffset.current = 0;
    };
    window.addEventListener('openclaw:logs-cleared', resetOffset);
    return () => window.removeEventListener('openclaw:logs-cleared', resetOffset);
  }, []);

  useEffect(() => {
    const feature = getFeatureDefinition(currentPage);
    const allowedWithoutLicense =
      ['license', 'diagnostics'].includes(currentPage) || !feature?.requiresLicense;
    if (!isLicenseChecking && !isAuthorized && !allowedWithoutLicense) {
      setCurrentPage('license');
    }
  }, [currentPage, isAuthorized, isLicenseChecking, setCurrentPage]);

  const handleStart = async () => {
    if (!isAuthorized) {
      showToast('请先完成授权', 'error');
      setCurrentPage('license');
      return;
    }
    setServiceRunning(false);
    setServiceStatus('starting');
    try {
      await processApi.start();
      startLogPolling();
      let lastNotice = 0;
      showToast('核心服务正在后台启动，低配机器会持续等待', 'info');
      const status = await waitForProcessReady({
        timeoutMs: 10 * 60 * 1000,
        intervalMs: 1500,
        onProgress: (progress) => {
          const elapsed = progress.startupElapsedSec || 0;
          const stage = progress.startupStage || 'starting';
          if (elapsed - lastNotice >= 20) {
            lastNotice = elapsed;
            appendLog(`[启动] 核心服务仍在启动中：${elapsed}s / ${progress.startupTimeoutSec || 420}s，当前阶段=${stage}，低配机器可能需要更久。\n`);
          }
        }
      });
      if (status.running) {
        setServiceRunning(true);
        setServiceStatus('running');
        appendLog('[启动] 核心服务已就绪\n');
        showToast('核心服务已启动', 'success');
        setTimeout(() => open('http://127.0.0.1:18790'), 1200);
        return;
      }
      setServiceStatus('starting');
      showToast('核心服务仍在启动中，请稍后查看状态或环境诊断', 'info');
    } catch (error: any) {
      setServiceRunning(false);
      setServiceStatus('idle');
      showToast(`启动失败: ${error?.error || error}`, 'error');
    }
  };

  const handleStop = async () => {
    setServiceStatus('stopping');
    try {
      await processApi.stop();
      setServiceRunning(false);
      setServiceStatus('idle');
      stopLogPolling();
      showToast('服务已停止', 'info');
    } catch {
      setServiceStatus('idle');
      showToast('停止失败', 'error');
    }
  };

  const handleNavigate = async (key: string) => {
    const feature = getFeatureDefinition(key);

    if (feature?.requiresLicense && !isAuthorized) {
      showToast('请先输入授权码完成在线激活', 'info');
      setCurrentPage('license');
      return;
    }

    if (feature?.action.type === 'external') {
      open(feature.action.url);
      return;
    }

    if (feature?.action.type === 'dialog') {
      setActiveDialog(feature.action.dialog);
      return;
    }

    if (feature?.action.type === 'command' && feature.action.command === 'update') {
      try {
        const resp = await updateApi.check();
        if (resp.hasUpdate) {
          showToast(`发现新版本 ${resp.current} -> ${resp.latest}`, 'info');
          if (confirm(`当前: ${resp.current}\n最新: ${resp.latest}\n是否更新？`)) {
            appendLog('[更新] 开始更新...\n');
            const updateResp = await updateApi.do();
            showToast(updateResp.success ? `更新成功: ${updateResp.current_version}` : '更新失败', updateResp.success ? 'success' : 'error');
          }
        } else {
          showToast(`已是最新版本 ${resp.current}`, 'info');
        }
      } catch {
        showToast('检查更新失败', 'error');
      }
      return;
    }

    setCurrentPage(key);
  };

  const currentFeature = getFeatureDefinition(currentPage);
  const canOpenCurrentPage = !currentFeature?.requiresLicense || isAuthorized || isLicenseChecking;
  const visiblePage = canOpenCurrentPage ? currentPage : 'license';

  return (
    <ThemeProvider>
      <DynamicTitle />
      <div className="flex h-screen w-screen flex-col overflow-hidden bg-surface text-text">
        <WindowTitlebar />
        <div className="flex min-h-0 flex-1 overflow-hidden bg-surface">
          <Sidebar
            activePage={visiblePage}
            serviceRunning={serviceRunning}
            serviceStatus={serviceStatus}
            isAuthorized={isAuthorized}
            isApiConfigured={apiConfigured}
            onNavigate={handleNavigate}
            onStart={handleStart}
            onStop={handleStop}
          />
          <main className="relative flex-1 overflow-hidden bg-surface">
            {renderFeaturePage(visiblePage)}
          </main>
        </div>

        <ToastContainer />
        {activeDialog === 'api' && <ModernApiConfigDialog onClose={() => setActiveDialog(null)} onSaved={refreshApiConfigured} />}
        {activeDialog === 'feishu' && <FeishuConfigDialog onClose={() => setActiveDialog(null)} />}
        {activeDialog === 'weixin' && <WeixinConfigDialog onClose={() => setActiveDialog(null)} />}
        {activeDialog === 'dingtalk' && <DingtalkConfigDialog onClose={() => setActiveDialog(null)} />}
      </div>
    </ThemeProvider>
  );
}
