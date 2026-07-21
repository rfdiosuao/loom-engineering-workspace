import React from 'react';
import { Button, Select, showConfirm, showToast } from '../common';
import { useTheme } from '../../hooks/useTheme';
import { useAppStore } from '../../stores/appStore';
import { parseErrorText, resolveUpdateDisposition, updateApi } from '../../services/api';
import { storyboardApi } from '../../services/storyboardApi';
import type { BuiltinThemeMode } from '../../theme/default';
import type { AppLanguage } from '../../i18n/language';
import { APP_DISPLAY_NAME, APP_DISPLAY_SUBTITLE, APP_VERSION } from '../../version';

type SettingsTab = 'appearance' | 'updates' | 'data' | 'about';
type UpdateBusy = 'check' | 'install' | null;

interface UpdateStatus {
  tone: 'info' | 'success' | 'error';
  message: string;
  current?: string;
  latest?: string;
  hasUpdate?: boolean;
  checkedAt?: string;
  log?: string[];
  errorCode?: string;
  retryable?: boolean;
  remediation?: string[];
}

interface SettingsCopy {
  eyebrow: string;
  title: string;
  tabs: Record<SettingsTab, string>;
  appearance: {
    languageTitle: string;
    languageDesc: string;
    themeTitle: string;
    themeDesc: string;
    windowTitle: string;
    windowDesc: string;
    windowReady: string;
    themeLabels: Record<BuiltinThemeMode, string>;
  };
  updates: {
    checkTitle: string;
    checkDesc: string;
    checkButton: string;
    installButton: string;
    checking: string;
    installing: string;
    idle: string;
    upToDate: string;
    found: string;
    failedCheck: string;
    failedInstall: string;
    confirmTitle: string;
    confirmMessage: string;
    confirmText: string;
    current: string;
    latest: string;
    checkedAt: string;
    logTitle: string;
    recoveryTitle: string;
  };
  data: {
    diagnosticsTitle: string;
    diagnosticsDesc: string;
    diagnosticsButton: string;
    logsButton: string;
    accountTitle: string;
    accountDesc: string;
    accountButton: string;
    componentsTitle: string;
    componentsDesc: string;
    componentsButton: string;
    developerTitle: string;
    developerDesc: string;
    developerButton: string;
    storyboard: { title: string; desc: string; importButton: string; importing: string };
  };
  about: {
    appTitle: string;
    appDesc: string;
    name: string;
    version: string;
    positioning: string;
    positioningValue: string;
    capabilitiesTitle: string;
    capabilitiesDesc: string;
    capabilities: string[];
  };
  toast: {
    languageChanged: string;
    themeChanged: string;
    updateSuccess: string;
  };
}

const SETTINGS_COPY: Record<AppLanguage, SettingsCopy> = {
  'zh-CN': {
    eyebrow: '系统',
    title: '系统设置',
    tabs: {
      appearance: '外观',
      updates: '更新',
      data: '数据',
      about: '关于',
    },
    appearance: {
      languageTitle: '语言',
      languageDesc: '切换启动器界面语言，设置会保存在本机。',
      themeTitle: '主题',
      themeDesc: '主题会立即应用到当前窗口，并在下次启动时保持。',
      windowTitle: '窗口按钮',
      windowDesc: '窗口控制使用系统级最小化、最大化和关闭按钮。',
      windowReady: '已启用标准窗口控制',
      themeLabels: {
        light: '米白',
        dark: '深色',
        system: '跟随系统',
      },
    },
    updates: {
      checkTitle: 'LOOM 应用更新',
      checkDesc: '检查正式发布的完整安装包，校验 SHA256 后启动覆盖安装。',
      checkButton: '检查更新',
      installButton: '立即更新',
      checking: '正在检查更新...',
      installing: '正在下载并校验完整安装包...',
      idle: '还没有检查更新。',
      upToDate: '当前已经是最新版本。',
      found: '发现可用新版本。',
      failedCheck: '检查更新失败',
      failedInstall: '更新失败',
      confirmTitle: '确认更新',
      confirmMessage: '更新会下载经过 SHA256 校验的 LOOM 完整安装包并启动安装器。请先保存正在运行的任务。',
      confirmText: '立即更新',
      current: '当前版本',
      latest: '最新版本',
      checkedAt: '检查时间',
      logTitle: '更新日志',
      recoveryTitle: '恢复操作',
    },
    data: {
      diagnosticsTitle: '诊断与日志',
      diagnosticsDesc: '日志、诊断包和环境修复集中到高级诊断页，避免主流程信息过载。',
      diagnosticsButton: '打开诊断',
      logsButton: '查看日志',
      accountTitle: '账号与模型',
      accountDesc: '账号登录、模型同步和运行配置都集中在模型账号页。',
      accountButton: '打开模型账号',
      componentsTitle: '安装数据',
      componentsDesc: '智能体由安装页统一检测、安装、启动、升级、卸载和回滚。',
      componentsButton: '打开安装',
      developerTitle: '开发者接入',
      developerDesc: 'Codex / Claude Code 的高级接入配置集中在这里，普通用户可以忽略。',
      developerButton: '打开开发者接入',
      storyboard: {
        title: '全案九步参数配置',
        desc: '导入 全案九步_参数配置.json，每个选项对应一条系统提示词，用于组合九步生成的上下文。空值由内置默认提示词兜底。',
        importButton: '导入 JSON',
        importing: '导入中...',
      },
    },
    about: {
      appTitle: '应用',
      appDesc: `${APP_DISPLAY_NAME} 演示稳定版。`,
      name: '名称：',
      version: '版本：',
      positioning: '定位：',
      positioningValue: APP_DISPLAY_SUBTITLE,
      capabilitiesTitle: '开放能力',
      capabilitiesDesc: '第一版演示只保留安装器、手机控制、模型账号和诊断。',
      capabilities: ['安装器', '手机控制', '模型账号', '诊断'],
    },
    toast: {
      languageChanged: '语言已切换',
      themeChanged: '主题已切换',
      updateSuccess: '更新完成',
    },
  },
  'en-US': {
    eyebrow: 'System',
    title: 'Settings',
    tabs: {
      appearance: 'Appearance',
      updates: 'Updates',
      data: 'Data',
      about: 'About',
    },
    appearance: {
      languageTitle: 'Language',
      languageDesc: 'Switch the launcher UI language. The preference is stored locally.',
      themeTitle: 'Theme',
      themeDesc: 'Theme changes apply immediately and are kept for the next launch.',
      windowTitle: 'Window Controls',
      windowDesc: 'The app uses native minimize, maximize, and close controls.',
      windowReady: 'Native window controls enabled',
      themeLabels: {
        light: 'Warm Light',
        dark: 'Dark',
        system: 'System',
      },
    },
    updates: {
      checkTitle: 'LOOM Application Updates',
      checkDesc: 'Check the complete release installer, verify SHA256, and start the upgrade.',
      checkButton: 'Check',
      installButton: 'Update Now',
      checking: 'Checking for updates...',
      installing: 'Downloading and verifying the complete installer...',
      idle: 'No update check has run yet.',
      upToDate: 'You are on the latest version.',
      found: 'A new version is available.',
      failedCheck: 'Update check failed',
      failedInstall: 'Update failed',
      confirmTitle: 'Confirm Update',
      confirmMessage: `${APP_DISPLAY_NAME} will download a SHA256-verified complete installer. Save running work before continuing.`,
      confirmText: 'Update Now',
      current: 'Current Version',
      latest: 'Latest Version',
      checkedAt: 'Checked At',
      logTitle: 'Update Log',
      recoveryTitle: 'Recovery Actions',
    },
    data: {
      diagnosticsTitle: 'Diagnostics & Logs',
      diagnosticsDesc: 'Diagnostics, logs, and environment repair are kept in the advanced diagnostics page.',
      diagnosticsButton: 'Open Diagnostics',
      logsButton: 'View Logs',
      accountTitle: 'Account & Models',
      accountDesc: 'Relay login, model sync, and runtime configuration are handled in the model account page.',
      accountButton: 'Open Model Account',
      componentsTitle: 'Components',
      componentsDesc: 'Agent components are detected, installed, launched, updated, removed, and rolled back from the installer.',
      componentsButton: 'Open Installer',
      developerTitle: 'Developer Access',
      developerDesc: 'Advanced Codex / Claude Code access settings live here. Most users can ignore this.',
      developerButton: 'Open Developer Access',
      storyboard: {
        title: 'Nine-Step Param Config',
        desc: 'Import the nine-step param config JSON. Each option maps to a system prompt used to assemble generation context. Empty values fall back to built-in defaults.',
        importButton: 'Import JSON',
        importing: 'Importing...',
      },
    },
    about: {
      appTitle: 'App',
      appDesc: `${APP_DISPLAY_NAME} demo-stable launcher.`,
      name: 'Name:',
      version: 'Version:',
      positioning: 'Role:',
      positioningValue: 'AI matrix customer acquisition workbench',
      capabilitiesTitle: 'Enabled Areas',
      capabilitiesDesc: 'The first demo keeps installer, phone control, model account, and diagnostics only.',
      capabilities: ['Installer', 'Phone', 'Models', 'Diagnostics'],
    },
    toast: {
      languageChanged: 'Language switched',
      themeChanged: 'Theme switched',
      updateSuccess: 'Update complete',
    },
  },
};

const SettingRow: React.FC<{
  title: string;
  desc: string;
  children: React.ReactNode;
}> = ({ title, desc, children }) => (
  <div className="grid gap-4 border-t border-border/75 py-5 md:grid-cols-[220px_minmax(0,1fr)]">
    <div>
      <div className="text-sm font-black text-text">{title}</div>
      <div className="mt-1 text-xs leading-5 text-text-muted">{desc}</div>
    </div>
    <div className="min-w-0">{children}</div>
  </div>
);

function formatUpdateError(error: unknown, fallback: string): string {
  return parseErrorText(error) || fallback;
}

export const SettingsPage: React.FC = () => {
  const [activeTab, setActiveTab] = React.useState<SettingsTab>('appearance');
  const [updateBusy, setUpdateBusy] = React.useState<UpdateBusy>(null);
  const [updateStatus, setUpdateStatus] = React.useState<UpdateStatus | null>(null);
  const [paramImportBusy, setParamImportBusy] = React.useState(false);
  const [paramImportStatus, setParamImportStatus] = React.useState<{ tone: 'info' | 'success' | 'error'; message: string } | null>(null);
  const fileInputRef = React.useRef<HTMLInputElement | null>(null);
  const { themeMode, switchThemeMode } = useTheme();
  const setCurrentPage = useAppStore((state) => state.setCurrentPage);
  const language = useAppStore((state) => state.language);
  const setLanguage = useAppStore((state) => state.setLanguage);
  const copy = SETTINGS_COPY[language];
  const tabs = React.useMemo(
    () => (Object.keys(copy.tabs) as SettingsTab[]).map((key) => ({ key, label: copy.tabs[key] })),
    [copy],
  );

  const handleLanguageChange = (event: React.ChangeEvent<HTMLSelectElement>) => {
    const next = event.target.value as AppLanguage;
    setLanguage(next);
    showToast(SETTINGS_COPY[next].toast.languageChanged, 'success');
  };

  const handleThemeChange = (mode: BuiltinThemeMode) => {
    switchThemeMode(mode);
    showToast(copy.toast.themeChanged, 'success');
  };

  const handleCheckUpdate = async () => {
    setUpdateBusy('check');
    setUpdateStatus({ tone: 'info', message: copy.updates.checking });
    try {
      const result = await updateApi.check();
      const nextStatus: UpdateStatus = {
        tone: result.hasUpdate ? 'info' : 'success',
        message: result.hasUpdate ? copy.updates.found : copy.updates.upToDate,
        current: result.current,
        latest: result.latest,
        hasUpdate: result.hasUpdate,
        checkedAt: new Date().toLocaleString(language),
      };
      setUpdateStatus(nextStatus);
      showToast(nextStatus.message, result.hasUpdate ? 'info' : 'success');
    } catch (error) {
      const message = formatUpdateError(error, copy.updates.failedCheck);
      setUpdateStatus({ tone: 'error', message, checkedAt: new Date().toLocaleString(language) });
      showToast(message, 'error');
    } finally {
      setUpdateBusy(null);
    }
  };

  const handleInstallUpdate = async () => {
    const ok = await showConfirm({
      title: copy.updates.confirmTitle,
      message: copy.updates.confirmMessage,
      confirmText: copy.updates.confirmText,
    });
    if (!ok) return;

    setUpdateBusy('install');
    setUpdateStatus((prev) => ({
      ...(prev ?? { tone: 'info' as const }),
      tone: 'info',
      message: copy.updates.installing,
    }));
    const progressTimer = window.setInterval(() => {
      void updateApi.status().then((progress) => {
        if (progress.phase === 'downloading') {
          setUpdateStatus((prev) => ({
            ...(prev ?? { tone: 'info' as const }),
            tone: 'info',
            message: `${copy.updates.installing} ${progress.percent}%`,
          }));
        } else if (progress.phase === 'failed') {
          setUpdateStatus((prev) => ({
            ...(prev ?? { tone: 'error' as const }),
            tone: 'error',
            message: progress.message || copy.updates.failedInstall,
            errorCode: progress.errorCode,
            retryable: progress.retryable,
            remediation: progress.remediation,
          }));
        }
      }).catch(() => undefined);
    }, 500);
    try {
      const result = await updateApi.do();
      window.clearInterval(progressTimer);
      const disposition = resolveUpdateDisposition(result);
      if (disposition === 'prepare_install') {
        await updateApi.prepareInstall(result.installer_path);
      }
      const message = disposition === 'prepare_install'
        ? `${copy.toast.updateSuccess}: ${result.current_version}`
        : `${copy.updates.upToDate} ${result.current_version}`;
      setUpdateStatus({
        tone: disposition === 'prepare_install' ? 'success' : 'info',
        message,
        current: result.current_version,
        log: result.log,
        checkedAt: new Date().toLocaleString(language),
      });
      showToast(message, disposition === 'prepare_install' ? 'success' : 'info');
    } catch (error) {
      window.clearInterval(progressTimer);
      const message = formatUpdateError(error, copy.updates.failedInstall);
      const errorDetail = error && typeof error === 'object'
        ? error as { errorCode?: string; retryable?: boolean; remediation?: string[]; log?: string[] }
        : {};
      setUpdateStatus((prev) => ({
        ...(prev ?? { tone: 'error' as const }),
        tone: 'error',
        message,
        errorCode: errorDetail.errorCode,
        retryable: errorDetail.retryable,
        remediation: Array.isArray(errorDetail.remediation) ? errorDetail.remediation : [],
        log: Array.isArray(errorDetail.log) ? errorDetail.log : prev?.log,
        checkedAt: new Date().toLocaleString(language),
      }));
      showToast(message, 'error');
    } finally {
      window.clearInterval(progressTimer);
      setUpdateBusy(null);
    }
  };

  const handleImportParamConfig = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    setParamImportBusy(true);
    try {
      const text = await file.text();
      const parsed = JSON.parse(text);
      const result = await storyboardApi.importParamConfig(parsed);
      const missing = result.warnings?.missing ?? [];
      const message = missing.length
        ? `已导入 ${result.optionCount} 个选项；缺失模块：${missing.join('、')}`
        : `已导入 ${result.optionCount} 个选项`;
      setParamImportStatus({ tone: missing.length ? 'info' : 'success', message });
      showToast(message, missing.length ? 'info' : 'success');
    } catch (error) {
      const message = parseErrorText(error) || '导入失败，请检查 JSON 格式';
      setParamImportStatus({ tone: 'error', message });
      showToast(message, 'error');
    } finally {
      setParamImportBusy(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  return (
    <div className="h-full overflow-y-auto bg-app-bg">
      <div className="mx-auto flex w-full max-w-[1080px] flex-col gap-6 px-8 py-7">
        <header className="flex flex-wrap items-end justify-between gap-5">
          <div>
            <div className="text-[11px] font-bold tracking-[0.42em] text-accent">{copy.eyebrow}</div>
            <h1 className="mt-2 text-[36px] font-black leading-tight text-text">{copy.title}</h1>
          </div>
          <div className="max-w-[360px] text-right">
            <div className="truncate text-[22px] font-black leading-tight text-text">{APP_DISPLAY_NAME}</div>
            <div className="mt-1 truncate text-xs font-bold text-text-muted">{APP_DISPLAY_SUBTITLE}</div>
          </div>
        </header>

        <div className="flex border-b border-border">
          {tabs.map((tab) => (
            <button
              key={tab.key}
              type="button"
              onClick={() => setActiveTab(tab.key)}
              className={`border-b-2 px-4 py-3 text-sm font-black transition ${
                activeTab === tab.key
                  ? 'border-accent text-accent'
                  : 'border-transparent text-text-muted hover:text-text'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        <section className="border-y border-border bg-surface/58 px-6">
          {activeTab === 'appearance' ? (
            <>
              <SettingRow title={copy.appearance.languageTitle} desc={copy.appearance.languageDesc}>
                <Select aria-label={copy.appearance.languageTitle} value={language} onChange={handleLanguageChange} className="w-full max-w-[360px]">
                  <option value="zh-CN">中文</option>
                  <option value="en-US">English</option>
                </Select>
              </SettingRow>
              <SettingRow title={copy.appearance.themeTitle} desc={copy.appearance.themeDesc}>
                <div className="flex flex-wrap gap-3">
                  {(['light', 'dark', 'system'] as BuiltinThemeMode[]).map((mode) => (
                    <Button
                      key={mode}
                      variant={themeMode === mode ? 'primary' : 'quiet'}
                      onClick={() => handleThemeChange(mode)}
                    >
                      {copy.appearance.themeLabels[mode]}
                    </Button>
                  ))}
                </div>
              </SettingRow>
              <SettingRow title={copy.appearance.windowTitle} desc={copy.appearance.windowDesc}>
                <div className="text-sm font-bold text-status-success">{copy.appearance.windowReady}</div>
              </SettingRow>
            </>
          ) : null}

          {activeTab === 'updates' ? (
            <SettingRow title={copy.updates.checkTitle} desc={copy.updates.checkDesc}>
              <div className="space-y-4">
                <div className="flex flex-wrap gap-3">
                  <Button variant="primary" disabled={Boolean(updateBusy)} onClick={handleCheckUpdate}>
                    {updateBusy === 'check' ? copy.updates.checking : copy.updates.checkButton}
                  </Button>
                  <Button
                    variant={updateStatus?.hasUpdate ? 'success' : 'quiet'}
                    disabled={Boolean(updateBusy) || updateStatus?.hasUpdate !== true}
                    onClick={handleInstallUpdate}
                  >
                    {updateBusy === 'install' ? copy.updates.installing : copy.updates.installButton}
                  </Button>
                </div>
                <div className={`rounded-[16px] border p-4 ${
                  updateStatus?.tone === 'error'
                    ? 'border-status-danger/30 bg-status-danger/8 text-status-danger'
                    : updateStatus?.tone === 'success'
                      ? 'border-status-success/25 bg-status-success/10 text-text'
                      : 'border-border bg-surface-alt/55 text-text'
                }`}>
                  <div className="text-sm font-black">{updateStatus?.message ?? copy.updates.idle}</div>
                  {updateStatus ? (
                    <div className="mt-3 grid gap-2 text-xs text-text-muted md:grid-cols-3">
                      {updateStatus.current ? <div><span className="font-black text-text">{copy.updates.current}：</span>{updateStatus.current}</div> : null}
                      {updateStatus.latest ? <div><span className="font-black text-text">{copy.updates.latest}：</span>{updateStatus.latest}</div> : null}
                      {updateStatus.checkedAt ? <div><span className="font-black text-text">{copy.updates.checkedAt}：</span>{updateStatus.checkedAt}</div> : null}
                    </div>
                  ) : null}
                  {updateStatus?.log?.length ? (
                    <details className="mt-4">
                      <summary className="cursor-pointer text-xs font-black text-text">{copy.updates.logTitle}</summary>
                      <pre className="mt-2 max-h-44 overflow-auto rounded-xl bg-terminal-bg p-3 text-xs leading-5 text-terminal-text">
                        {updateStatus.log.slice(-16).join('\n')}
                      </pre>
                    </details>
                  ) : null}
                  {updateStatus?.remediation?.length ? (
                    <div className="mt-4 rounded-xl border border-current/15 bg-surface/55 p-3 text-xs leading-5">
                      <div className="font-black text-text">{copy.updates.recoveryTitle}</div>
                      <ul className="mt-1 list-disc space-y-1 pl-5 text-text-muted">
                        {updateStatus.remediation.map((item) => <li key={item}>{item}</li>)}
                      </ul>
                    </div>
                  ) : null}
                </div>
              </div>
            </SettingRow>
          ) : null}

          {activeTab === 'data' ? (
            <>
              <SettingRow title={copy.data.diagnosticsTitle} desc={copy.data.diagnosticsDesc}>
                <div className="flex flex-wrap gap-3">
                  <Button variant="primary" onClick={() => setCurrentPage('diagnostics')}>{copy.data.diagnosticsButton}</Button>
                  <Button variant="quiet" onClick={() => setCurrentPage('terminal')}>{copy.data.logsButton}</Button>
                </div>
              </SettingRow>
              <SettingRow title={copy.data.accountTitle} desc={copy.data.accountDesc}>
                <Button variant="primary" onClick={() => setCurrentPage('license')}>{copy.data.accountButton}</Button>
              </SettingRow>
              <SettingRow title={copy.data.componentsTitle} desc={copy.data.componentsDesc}>
                <Button variant="primary" onClick={() => setCurrentPage('agents')}>{copy.data.componentsButton}</Button>
              </SettingRow>
              <SettingRow title={copy.data.developerTitle} desc={copy.data.developerDesc}>
                <Button variant="quiet" onClick={() => setCurrentPage('agentAccess')}>{copy.data.developerButton}</Button>
              </SettingRow>
              <SettingRow title={copy.data.storyboard.title} desc={copy.data.storyboard.desc}>
                <div className="space-y-3">
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept=".json,application/json"
                    className="hidden"
                    onChange={(e) => void handleImportParamConfig(e)}
                  />
                  <div className="flex flex-wrap gap-3">
                    <Button variant="primary" disabled={paramImportBusy} onClick={() => fileInputRef.current?.click()}>
                      {paramImportBusy ? copy.data.storyboard.importing : copy.data.storyboard.importButton}
                    </Button>
                  </div>
                  {paramImportStatus ? (
                    <div className={`rounded-xl border px-4 py-3 text-xs font-semibold ${
                      paramImportStatus.tone === 'error'
                        ? 'border-status-danger/30 bg-status-danger/8 text-status-danger'
                        : paramImportStatus.tone === 'success'
                          ? 'border-status-success/25 bg-status-success/10 text-text'
                          : 'border-border bg-surface-alt/55 text-text'
                    }`}>{paramImportStatus.message}</div>
                  ) : null}
                </div>
              </SettingRow>
            </>
          ) : null}

          {activeTab === 'about' ? (
            <>
              <SettingRow title={copy.about.appTitle} desc={copy.about.appDesc}>
                <div className="space-y-2 text-sm text-text-muted">
                  <div><span className="font-black text-text">{copy.about.name}</span>{APP_DISPLAY_NAME}</div>
                  <div><span className="font-black text-text">{copy.about.version}</span>{APP_VERSION}</div>
                  <div><span className="font-black text-text">{copy.about.positioning}</span>{copy.about.positioningValue}</div>
                </div>
              </SettingRow>
              <SettingRow title={copy.about.capabilitiesTitle} desc={copy.about.capabilitiesDesc}>
                <div className="flex flex-wrap gap-2 text-xs font-bold">
                  {copy.about.capabilities.map((item) => (
                    <span key={item} className="rounded-full border border-[#0B4A3E]/20 bg-[#0B4A3E]/10 px-3 py-1.5 text-[#0B4A3E]">{item}</span>
                  ))}
                </div>
              </SettingRow>
            </>
          ) : null}
        </section>
      </div>
    </div>
  );
};
