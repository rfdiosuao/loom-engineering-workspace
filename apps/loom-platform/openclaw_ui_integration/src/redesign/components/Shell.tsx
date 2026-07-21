import React from 'react';
import {
  Activity,
  BellOff,
  Bot,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Copy,
  Cpu,
  Gauge,
  Layers3,
  Loader2,
  Maximize2,
  Minus,
  Phone,
  ScrollText,
  Settings2,
  ShieldCheck,
  Sparkles,
  SquareTerminal,
  Webhook,
  UserRound,
  X,
} from 'lucide-react';
import { getCurrentWindow } from '@tauri-apps/api/window';
import { Button, cx } from './ui';
import { usePreviewStore, type PreviewSettings } from '../store/appStore';
import type { RouteKey, ToastMessage } from '../types';
import { isTauriRuntime, resolveBridgeBaseUrl } from '../api/client';
import { loadAccountSnapshot } from '../api/adapters';
import { copyText } from '../lib/clipboard';
import type { AccountSnapshot } from '../types';

const NAV_ITEMS: Array<{ key: RouteKey; label: string; desc: string; icon: typeof Gauge }> = [
  { key: 'dashboard', label: '安装首页', desc: '四步完成配置', icon: Gauge },
  { key: 'license', label: '账号 / 授权', desc: '登录与模型同步', icon: ShieldCheck },
  { key: 'agents', label: '智能体', desc: 'Codex / Claude / Hermes', icon: Bot },
  { key: 'service', label: '核心服务', desc: '启动、日志、终端', icon: SquareTerminal },
  { key: 'diagnostics', label: '环境检测', desc: '检测与修复', icon: Activity },
  { key: 'settings', label: '统一设置', desc: '密钥与连接', icon: Settings2 },
  { key: 'studio', label: '图像 / 视频', desc: '生成任务入口', icon: Sparkles },
  { key: 'phone', label: '手机控制', desc: 'APKClaw 桥接', icon: Phone },
  { key: 'desktop', label: '桌面 RPA', desc: 'Luminode 控制', icon: Cpu },
  { key: 'integrations', label: '平台对接', desc: '飞书 / 微信 / Webhook', icon: Webhook },
  { key: 'skills', label: 'Skills', desc: '能力模块管理', icon: Layers3 },
];

const ROUTE_COPY: Record<RouteKey, { eyebrow: string; title: string }> = {
  agents: { eyebrow: 'Agents', title: '智能体安装' },
  dashboard: { eyebrow: 'Installer', title: 'OpenClaw 安装首页' },
  service: { eyebrow: 'Runtime / CLI', title: '核心服务与日志' },
  license: { eyebrow: 'Account', title: '账号 / 授权' },
  integrations: { eyebrow: 'Integrations', title: '平台对接' },
  studio: { eyebrow: 'Studio', title: '图像 / 视频' },
  phone: { eyebrow: 'APKClaw', title: '手机控制' },
  desktop: { eyebrow: 'Desktop RPA', title: '桌面 RPA' },
  skills: { eyebrow: 'Skills', title: 'Skills' },
  diagnostics: { eyebrow: 'Diagnostics', title: '环境检测' },
  settings: { eyebrow: 'Settings', title: '统一设置' },
};

function getBridgeLabel(settings: PreviewSettings): string {
  const bridgeBaseUrl = resolveBridgeBaseUrl(settings.bridgeBaseUrl);
  if (bridgeBaseUrl) return '已连接';
  if (settings.transportMode === 'mock') return '预览模式';
  if (isTauriRuntime()) return '已就绪';
  return '未连接';
}

const ROUTE_LABELS: Record<RouteKey, string> = {
  agents: '智能体',
  dashboard: '安装首页',
  service: '核心服务',
  license: '账号 / 授权',
  integrations: '平台对接',
  studio: '图像 / 视频',
  phone: '手机控制',
  desktop: '桌面 RPA',
  skills: 'Skills',
  diagnostics: '环境检测',
  settings: '统一设置',
};

export function Shell({ children }: { children: React.ReactNode }) {
  const route = usePreviewStore((state) => state.route);
  const navigate = usePreviewStore((state) => state.navigate);
  const settings = usePreviewStore((state) => state.settings);
  const toggleSidebar = usePreviewStore((state) => state.toggleSidebar);
  const sidebarCollapsed = usePreviewStore((state) => state.sidebarCollapsed);
  const toasts = usePreviewStore((state) => state.toasts);
  const dismissToast = usePreviewStore((state) => state.dismissToast);
  const clearToasts = usePreviewStore((state) => state.clearToasts);
  const studioImageBusy = usePreviewStore((state) => state.studio.imageBusy);
  const studioVideoBusy = usePreviewStore((state) => state.studio.videoBusy);
  const studioBusyLabel = studioImageBusy && studioVideoBusy
    ? '图像/视频生成中'
    : studioVideoBusy
      ? '视频生成中'
      : studioImageBusy
        ? '图像生成中'
        : '';
  const [account, setAccount] = React.useState<AccountSnapshot | null>(null);

  const handleWindowAction = React.useCallback(async (action: 'minimize' | 'toggleMaximize' | 'close') => {
    if (!isTauriRuntime()) return;
    const currentWindow = getCurrentWindow();
    if (action === 'minimize') await currentWindow.minimize();
    else if (action === 'toggleMaximize') await currentWindow.toggleMaximize();
    else await currentWindow.close();
  }, []);

  React.useEffect(() => {
    if (!toasts.length) return;
    // Errors (and anything explicitly marked sticky) stay until dismissed so the
    // user has time to read, expand and copy the diagnostic. The rest fade out.
    const timers = toasts
      .filter((toast) => !(toast.sticky ?? toast.tone === 'danger'))
      .map((toast) =>
        window.setTimeout(() => {
          dismissToast(toast.id);
        }, 4600)
      );
    return () => timers.forEach((timer) => window.clearTimeout(timer));
  }, [toasts, dismissToast]);

  React.useEffect(() => {
    let cancelled = false;
    loadAccountSnapshot(settings)
      .then((snapshot) => {
        if (!cancelled) setAccount(snapshot);
      })
      .catch(() => {
        if (!cancelled) setAccount(null);
      });
    return () => {
      cancelled = true;
    };
  }, [settings, route]);

  return (
    <div className={cx('app-shell', sidebarCollapsed && 'app-shell-sidebar-collapsed')}>
      <aside className={cx('sidebar', sidebarCollapsed && 'sidebar-collapsed')}>
        <div className="brand-block" data-tauri-drag-region>
          <div className="brand-copy">
            <div className="brand-title" data-tauri-drag-region>OpenClaw</div>
            <div className="brand-subtitle" data-tauri-drag-region>Agent Installer</div>
          </div>
        </div>

        <div className="sidebar-toolbar">
          <Button
            variant="quiet"
            icon={sidebarCollapsed ? ChevronRight : ChevronLeft}
            className="sidebar-toggle-button"
            onClick={toggleSidebar}
            title={sidebarCollapsed ? '展开侧栏' : '收起侧栏'}
            aria-label={sidebarCollapsed ? '展开侧栏' : '收起侧栏'}
          >
            {sidebarCollapsed ? '' : '收起侧栏'}
          </Button>
        </div>

        <nav className="nav-list" aria-label="OpenClaw preview navigation">
          {NAV_ITEMS.map((item) => {
            const Icon = item.icon;
            const active = route === item.key;
            return (
              <button
                key={item.key}
                type="button"
                className={cx('nav-item', active && 'nav-item-active')}
                onClick={() => navigate(item.key)}
              >
                <Icon size={16} />
                <span className="nav-item-text">
                  <span className="nav-item-label">{item.label}</span>
                  <span className="nav-item-desc">{item.desc}</span>
                </span>
              </button>
            );
          })}
        </nav>

        <div className="sidebar-foot">
          <button type="button" className="account-chip" onClick={() => navigate('license')}>
            <UserRound size={15} />
            <span className="account-chip-main">
              <span className="account-chip-label">{account?.loggedIn ? account.account : '账号未登录'}</span>
              <span className="account-chip-meta">
                {account?.loggedIn ? `${account.models.text.length + account.models.image.length + account.models.video.length} 个模型` : '点击登录中转站'}
              </span>
            </span>
          </button>
          <div className="sidebar-foot-note">
            当前 {ROUTE_LABELS[route] || route}<br />
            服务 {getBridgeLabel(settings)} · 手机 {settings.phoneBaseUrl ? '已绑定' : '未绑定'}
          </div>
        </div>
      </aside>

      <div className="shell-main">
        <header className="topbar" data-tauri-drag-region>
          <div className="topbar-left" data-tauri-drag-region>
            <div className="topbar-kicker" data-tauri-drag-region>{ROUTE_COPY[route]?.eyebrow || 'Preview'}</div>
            <div className="topbar-title" data-tauri-drag-region>{ROUTE_COPY[route]?.title || 'OpenClaw preview'}</div>
          </div>
          <div className="topbar-right">
            {studioBusyLabel ? (
              <Button
                type="button"
                variant="quiet"
                icon={Loader2}
                className="topbar-task-badge"
                onClick={() => navigate('studio')}
                title="正在生成，点此查看进度"
              >
                {studioBusyLabel}
              </Button>
            ) : null}
            <Button type="button" variant="quiet" icon={BellOff} onClick={clearToasts}>
              清除提示
            </Button>
            <div className="window-controls" aria-label="窗口控制">
              <Button
                type="button"
                variant="quiet"
                icon={Minus}
                className="window-control-button"
                onClick={() => void handleWindowAction('minimize')}
                title="最小化"
                aria-label="最小化"
              />
              <Button
                type="button"
                variant="quiet"
                icon={Maximize2}
                className="window-control-button"
                onClick={() => void handleWindowAction('toggleMaximize')}
                title="最大化 / 还原"
                aria-label="最大化或还原"
              />
              <Button
                type="button"
                variant="quiet"
                icon={X}
                className="window-control-button window-control-close"
                onClick={() => void handleWindowAction('close')}
                title="关闭"
                aria-label="关闭"
              />
            </div>
          </div>
        </header>

        <main className="page-wrap">{children}</main>
      </div>

      <div className="toast-stack" aria-live="polite">
        {toasts.map((toast) => (
          <ToastCard
            key={toast.id}
            toast={toast}
            onDismiss={() => dismissToast(toast.id)}
            onOpenLog={(logRoute) => {
              navigate(logRoute);
              dismissToast(toast.id);
            }}
          />
        ))}
      </div>
    </div>
  );
}

function ToastCard({
  toast,
  onDismiss,
  onOpenLog,
}: {
  toast: ToastMessage;
  onDismiss: () => void;
  onOpenLog: (route: RouteKey) => void;
}) {
  const [expanded, setExpanded] = React.useState(false);
  const [copied, setCopied] = React.useState(false);
  const diagnostic = (toast.diagnostic || toast.detail || '').trim();
  // Only errors (or anything carrying a long diagnostic) get the action row.
  const hasActions = toast.tone === 'danger' || Boolean(toast.diagnostic);
  const logRoute = toast.logRoute || 'service';

  return (
    <div className={cx('toast', `toast-${toast.tone}`)}>
      <div className="toast-main">
        <div className="toast-title">{toast.title}</div>
        {toast.detail ? <div className="toast-detail">{toast.detail}</div> : null}
        {hasActions ? (
          <div className="toast-actions">
            {diagnostic ? (
              <button type="button" className="toast-action" onClick={() => setExpanded((value) => !value)}>
                <ChevronDown size={13} className={cx('toast-chevron', expanded && 'toast-chevron-open')} />
                展开详情
              </button>
            ) : null}
            {diagnostic ? (
              <button
                type="button"
                className="toast-action"
                onClick={async () => {
                  const ok = await copyText(diagnostic);
                  setCopied(ok);
                  window.setTimeout(() => setCopied(false), 1800);
                }}
              >
                <Copy size={13} />
                {copied ? '已复制' : '复制诊断'}
              </button>
            ) : null}
            <button type="button" className="toast-action" onClick={() => onOpenLog(logRoute)}>
              <ScrollText size={13} />
              打开日志
            </button>
          </div>
        ) : null}
        {hasActions && expanded && diagnostic ? (
          <pre className="toast-diagnostic">{diagnostic}</pre>
        ) : null}
      </div>
      <button type="button" className="icon-button" onClick={onDismiss} aria-label="关闭提示">
        <X size={14} />
      </button>
    </div>
  );
}
