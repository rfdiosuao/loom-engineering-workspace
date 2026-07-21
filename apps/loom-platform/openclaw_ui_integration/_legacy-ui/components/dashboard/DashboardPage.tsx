import React, { useCallback, useEffect, useState } from 'react';
import { useAppStore } from '../../stores/appStore';
import { useTheme } from '../../hooks/useTheme';
import { configApi, licenseApi, processApi, skillsApi, systemApi, waitForProcessReady } from '../../services/api';
import { showToast } from '../common';
import packageJson from '../../../package.json';

interface StatusCard {
  key: string;
  label: string;
  status: 'ok' | 'warn' | 'off' | 'loading';
  detail: string;
}

interface QuickAction {
  key: string;
  label: string;
  desc: string;
  icon: string;
  featured?: boolean;
}

const STATUS_STYLES: Record<StatusCard['status'], { dot: string; rail: string; text: string }> = {
  ok: {
    dot: 'bg-status-success shadow-[0_0_10px_rgba(63,224,143,0.55)]',
    rail: 'bg-status-success/50',
    text: 'text-status-success',
  },
  warn: {
    dot: 'bg-status-warning shadow-[0_0_10px_rgba(255,180,84,0.38)]',
    rail: 'bg-status-warning/50',
    text: 'text-status-warning',
  },
  off: {
    dot: 'bg-text-subtle',
    rail: 'bg-border',
    text: 'text-text-muted',
  },
  loading: {
    dot: 'bg-accent shadow-[0_0_10px_rgba(216,184,102,0.42)]',
    rail: 'bg-accent/50',
    text: 'text-accent',
  },
};

const AUTH_PROFILES_PATH = 'data/.openclaw/agents/main/agent/auth-profiles.json';
const LARK_PLUGIN_PATH = 'data/.openclaw/extensions/openclaw-lark';
const WEIXIN_PLUGIN_PATH = 'data/.openclaw/extensions/openclaw-weixin';

function hasConfiguredApiProfile(data: unknown): boolean {
  const providers = (data as any)?.models?.providers;
  if (!providers || typeof providers !== 'object') return false;
  return Object.values(providers).some((provider: any) => {
    const apiKey = String(provider?.apiKey || '').trim();
    const baseUrl = String(provider?.baseUrl || provider?.url || '').trim();
    return apiKey.length > 0 && baseUrl.length > 0;
  });
}

function getGreeting(): string {
  const hour = new Date().getHours();
  if (hour < 6) return '夜深好';
  if (hour < 12) return '早上好';
  if (hour < 14) return '中午好';
  if (hour < 18) return '下午好';
  return '晚上好';
}

export const DashboardPage: React.FC = () => {
  const {
    serviceRunning,
    serviceStatus,
    isAuthorized,
    setCurrentPage,
    setServiceRunning,
    setServiceStatus,
    phoneAgentStatus,
    phoneAgentTaskId,
    phoneAgentSummary,
    phoneAgentProgress,
    phoneAgentUpdatedAt,
  } = useAppStore();
  const { theme } = useTheme();
  const [apiConfigured, setApiConfigured] = useState<boolean | null>(null);
  const [larkInstalled, setLarkInstalled] = useState<boolean | null>(null);
  const [weixinInstalled, setWeixinInstalled] = useState<boolean | null>(null);
  const [skillsCount, setSkillsCount] = useState<number>(0);
  const [bridgeMode, setBridgeMode] = useState<string>('FastAPI');
  const [greetingTime, setGreetingTime] = useState('');

  const refreshStatus = useCallback(async () => {
    try {
      const resp = await configApi.read(AUTH_PROFILES_PATH, { models: { providers: {} } });
      if (hasConfiguredApiProfile(resp.data)) {
        setApiConfigured(true);
      } else {
        const licenseResp = await licenseApi.current();
        const license = ((licenseResp as any).gatewayProfile || licenseResp.license || (licenseResp as any).member) as any;
        const gateway = license?.gateway || {};
        setApiConfigured(Boolean(
          String(license?.gatewayBaseUrl || license?.gatewayUrl || license?.baseUrl || gateway?.baseUrl || gateway?.url || '').trim()
          && String(license?.gatewayAccessToken || license?.gatewayToken || license?.apiKey || license?.memberToken || gateway?.apiKey || gateway?.token || '').trim(),
        ));
      }
    } catch {
      setApiConfigured(false);
    }

    try {
      const larkResp = await configApi.read(LARK_PLUGIN_PATH, null);
      setLarkInstalled(larkResp.data !== null && larkResp.data !== undefined);
    } catch {
      setLarkInstalled(false);
    }

    try {
      const weixinResp = await configApi.read(WEIXIN_PLUGIN_PATH, null);
      setWeixinInstalled(weixinResp.data !== null && weixinResp.data !== undefined);
    } catch {
      setWeixinInstalled(false);
    }

    try {
      const skillsResp = await skillsApi.list();
      const enabled = skillsResp.skills?.filter((s) => s.enabled).length ?? 0;
      setSkillsCount(enabled);
    } catch {
      setSkillsCount(0);
    }

    try {
      await systemApi.info();
      setBridgeMode('FastAPI');
    } catch {
      setBridgeMode('Legacy');
    }
  }, []);

  useEffect(() => {
    refreshStatus();
    setGreetingTime(getGreeting());
  }, [refreshStatus]);

  const statusCards: StatusCard[] = [
    {
      key: 'service',
      label: 'OpenClaw 服务',
      status: serviceRunning ? 'ok' : serviceStatus === 'starting' ? 'loading' : 'off',
      detail: serviceRunning ? '运行中' : serviceStatus === 'starting' ? '启动中' : '未启动',
    },
    {
      key: 'bridge',
      label: 'Bridge 引擎',
      status: serviceRunning ? 'ok' : 'off',
      detail: bridgeMode,
    },
    {
      key: 'license',
      label: '授权状态',
      status: isAuthorized ? 'ok' : 'warn',
      detail: isAuthorized ? '已授权' : '未授权',
    },
    {
      key: 'api',
      label: 'API 配置',
      status: apiConfigured === null ? 'loading' : apiConfigured ? 'ok' : 'warn',
      detail: apiConfigured === null ? '检测中' : apiConfigured ? '已配置' : '未配置',
    },
    {
      key: 'lark',
      label: '飞书机器人',
      status: larkInstalled === null ? 'loading' : larkInstalled ? 'ok' : 'off',
      detail: larkInstalled === null ? '检测中' : larkInstalled ? '已安装' : '未安装',
    },
    {
      key: 'weixin',
      label: '微信机器人',
      status: weixinInstalled === null ? 'loading' : weixinInstalled ? 'ok' : 'off',
      detail: weixinInstalled === null ? '检测中' : weixinInstalled ? '已安装' : '未安装',
    },
    {
      key: 'skills',
      label: 'Skills 扩展',
      status: skillsCount > 0 ? 'ok' : 'off',
      detail: `${skillsCount} 个已启用`,
    },
  ];

  const quickActions: QuickAction[] = [
    { key: 'terminal', label: '服务日志', desc: '查看控制台', icon: 'LOG' },
    { key: 'storyboard', label: '广告视频', desc: '分镜工作台', icon: 'AD', featured: true },
    { key: 'image', label: 'AI 生图', desc: '创作图片', icon: 'IMG', featured: true },
    { key: 'video', label: 'AI 视频', desc: '生成视频', icon: 'VID', featured: true },
    { key: 'publish', label: '平台发布', desc: '手机发帖/发视频', icon: 'PUB', featured: true },
    { key: 'skills', label: 'Skills', desc: '扩展中心', icon: 'SK' },
    { key: 'license', label: '授权码', desc: '激活管理', icon: 'LIC' },
  ];

  const handleQuickAction = (key: string) => {
    if (key === 'storyboard' || key === 'image' || key === 'video' || key === 'phone' || key === 'publish' || key === 'desktop') {
      if (!isAuthorized) {
        showToast('请先完成授权', 'info');
        setCurrentPage('license');
        return;
      }
    }
    setCurrentPage(key);
  };

  const handleStartService = async () => {
    if (!isAuthorized) {
      showToast('请先完成授权', 'info');
      setCurrentPage('license');
      return;
    }
    setServiceRunning(false);
    setServiceStatus('starting');
    try {
      await processApi.start();
      showToast('核心服务正在后台启动，低配机器会持续等待', 'info');
      const status = await waitForProcessReady({ timeoutMs: 10 * 60 * 1000, intervalMs: 1500 });
      if (status.running) {
        setServiceRunning(true);
        setServiceStatus('running');
        showToast('核心服务已启动', 'success');
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

  return (
    <div className="flex h-full flex-col overflow-hidden bg-surface">
      <header className="shrink-0 border-b border-border/70 bg-surface px-8 py-7">
        <div className="flex items-end justify-between gap-8">
          <div className="min-w-0">
            <div className="text-[11px] font-bold uppercase tracking-[0.42em] text-accent">
              {theme.brand.terminal_header}
            </div>
            <h1 className="mt-2 text-[28px] font-black leading-tight text-text">
              {greetingTime}，欢迎回来
            </h1>
            <p className="mt-1 text-sm text-text-muted">
              {theme.brand.name} · {theme.brand.subtitle}
            </p>
          </div>

          {!serviceRunning ? (
            <button
              onClick={handleStartService}
              disabled={serviceStatus === 'starting'}
              className="min-w-[132px] rounded-[18px] bg-accent px-6 py-3 text-sm font-black text-accent-ink shadow-[0_16px_34px_rgba(216,184,102,0.16)] transition-all hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-55"
            >
              {serviceStatus === 'starting' ? '启动中...' : '启动核心服务'}
            </button>
          ) : (
            <div className="flex items-center gap-2 rounded-[18px] border border-status-success/25 bg-status-success/10 px-5 py-3">
              <span className="h-2 w-2 rounded-full bg-status-success shadow-[0_0_10px_rgba(63,224,143,0.55)]" />
              <span className="text-sm font-bold text-status-success">服务运行中</span>
            </div>
          )}
        </div>
      </header>

      <div className="flex-1 overflow-y-auto px-8 py-7">
        <section className="mb-8">
          <div className="mb-4 text-xs font-bold uppercase tracking-[0.24em] text-text-subtle">
            系统状态
          </div>
          <div className="grid grid-cols-4 gap-3">
            {statusCards.map((card) => {
              const style = STATUS_STYLES[card.status];
              return (
                <div
                  key={card.key}
                  className="group relative min-h-[82px] overflow-hidden rounded-[14px] border border-border/80 bg-surface-alt/30 p-4 transition-all hover:border-border-strong/70 hover:bg-surface-alt/50"
                >
                  <span className={`absolute left-0 top-4 h-9 w-[2px] rounded-r ${style.rail}`} />
                  <div className="mb-3 flex items-center gap-2.5">
                    <span className={`h-2 w-2 rounded-full ${style.dot}`} />
                    <span className="truncate text-xs font-medium text-text-muted">{card.label}</span>
                  </div>
                  <div className={`text-[15px] font-black ${card.status === 'off' ? 'text-text' : style.text}`}>
                    {card.detail}
                  </div>
                </div>
              );
            })}
          </div>
        </section>

        <section className="mb-8">
          <div className="mb-4 text-xs font-bold uppercase tracking-[0.24em] text-text-subtle">
            快捷入口
          </div>
          <div className="grid grid-cols-3 gap-3">
            {quickActions.map((action) => (
              <button
                key={action.key}
                onClick={() => handleQuickAction(action.key)}
                className={`group relative flex min-h-[78px] items-center gap-4 overflow-hidden rounded-[14px] border p-4 text-left transition-all ${
                  action.featured
                    ? 'border-border-strong/50 bg-surface-alt/50 hover:border-accent/70 hover:bg-accent/[0.055]'
                    : 'border-border/80 bg-surface-alt/30 hover:border-border-strong/70 hover:bg-surface-alt/50'
                }`}
              >
                <div
                  className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border text-[10px] font-black tracking-[0.08em] transition-all ${
                    action.featured
                      ? 'border-accent/40 bg-accent/[0.08] text-accent group-hover:bg-accent/[0.13]'
                      : 'border-border bg-surface-deeper text-text-subtle group-hover:border-border-strong group-hover:text-text'
                  }`}
                >
                  {action.icon}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-black text-text">{action.label}</div>
                  <div className="mt-0.5 truncate text-xs text-text-subtle">{action.desc}</div>
                </div>
                <span className="text-xl leading-none text-text-subtle transition-all group-hover:translate-x-0.5 group-hover:text-accent">
                  →
                </span>
              </button>
            ))}
          </div>
        </section>

        <section className="mb-8">
          <div className="mb-4 text-xs font-bold uppercase tracking-[0.24em] text-text-subtle">
            手机 Agent
          </div>
          <div className="rounded-[16px] border border-accent/25 bg-accent/[0.06] p-4">
            <div className="flex items-start justify-between gap-4">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className={`h-2.5 w-2.5 rounded-full ${
                    phoneAgentStatus === 'running'
                      ? 'bg-accent shadow-[0_0_10px_rgba(216,184,102,0.45)]'
                      : phoneAgentStatus === 'success'
                        ? 'bg-status-success'
                        : phoneAgentStatus === 'error'
                          ? 'bg-status-danger'
                          : phoneAgentStatus === 'queued'
                            ? 'bg-status-warning'
                            : 'bg-text-subtle'
                  }`} />
                  <div className="text-sm font-black text-text">
                    {phoneAgentStatus === 'running'
                      ? '手机 Agent 正在执行'
                      : phoneAgentStatus === 'queued'
                        ? '手机 Agent 已接收任务'
                        : phoneAgentStatus === 'success'
                          ? '手机 Agent 已完成'
                          : phoneAgentStatus === 'error'
                            ? '手机 Agent 执行异常'
                            : phoneAgentStatus === 'cancelled'
                              ? '手机 Agent 已取消'
                              : '手机 Agent 空闲'}
                  </div>
                </div>
                <div className="mt-2 text-xs leading-5 text-text-muted">
                  {phoneAgentProgress || phoneAgentSummary || '等待手机端任务进度回传。'}
                </div>
                <div className="mt-1 text-[11px] text-text-subtle">
                  {phoneAgentTaskId ? `Task ${phoneAgentTaskId.slice(0, 8)}` : '暂无任务'}
                  {phoneAgentUpdatedAt ? ` · ${new Date(phoneAgentUpdatedAt).toLocaleTimeString('zh-CN', { hour12: false })}` : ''}
                </div>
              </div>
              <button
                type="button"
                onClick={() => setCurrentPage('phone')}
                className="shrink-0 rounded-[14px] border border-border/70 bg-surface/45 px-4 py-2 text-xs font-black text-text transition hover:border-accent/60 hover:text-accent"
              >
                打开手机控制
              </button>
            </div>
          </div>
        </section>

        <section>
          <div className="mb-4 text-xs font-bold uppercase tracking-[0.24em] text-text-subtle">
            关于
          </div>
          <div className="rounded-[16px] border border-border/80 bg-surface-alt/30 p-5">
            <div className="flex items-center gap-4">
              <div className="flex h-14 w-14 shrink-0 items-center justify-center rounded-[16px] border border-border-strong/70 bg-surface-alt shadow-[0_0_26px_rgba(216,184,102,0.08)]">
                <span className="text-2xl font-black text-accent">L</span>
              </div>
              <div>
                <div className="text-base font-black tracking-wide text-text">{theme.brand.name}</div>
                <div className="text-sm text-text-muted">{theme.brand.subtitle}</div>
                <div className="mt-1 text-xs text-text-subtle">
                  {theme.name} · v{packageJson.version}
                </div>
              </div>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
};
