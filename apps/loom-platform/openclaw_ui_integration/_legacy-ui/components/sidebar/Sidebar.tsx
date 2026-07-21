import React from 'react';
import { useTheme } from '../../hooks/useTheme';
import { DEFAULT_NAV_ITEMS, normalizeNavItems } from '../../theme/default';
import type { NavItem } from '../../types/theme';

interface SidebarProps {
  activePage: string;
  serviceRunning: boolean;
  serviceStatus: string;
  isAuthorized: boolean;
  isApiConfigured: boolean;
  onNavigate: (key: string) => void;
  onStart: () => void;
  onStop: () => void;
}

function statusLabel(serviceRunning: boolean, serviceStatus: string, isAuthorized: boolean, isApiConfigured: boolean): string {
  if (!isAuthorized) return '未授权';
  if (serviceRunning) return '服务运行中';
  if (serviceStatus === 'starting') return '启动中';
  if (serviceStatus === 'stopping') return '停止中';
  if (isApiConfigured) return 'API 已配置';
  return '未配置 API';
}

function statusTone(serviceRunning: boolean, isAuthorized: boolean, isApiConfigured: boolean): string {
  if (!isAuthorized) return 'bg-status-danger shadow-[0_0_10px_rgba(255,77,109,0.55)]';
  if (serviceRunning || isApiConfigured) return 'bg-status-success shadow-[0_0_10px_rgba(63,224,143,0.52)]';
  return 'bg-status-warning shadow-[0_0_10px_rgba(255,180,84,0.38)]';
}

const NavButton: React.FC<{
  item: NavItem;
  isActive: boolean;
  onClick: () => void;
}> = ({ item, isActive, onClick }) => (
  <button
    onClick={onClick}
    className={`group relative w-full overflow-hidden rounded-[14px] px-3 py-3 text-left transition-all duration-150 ${
      isActive
        ? 'border border-border-strong/80 bg-accent/[0.075] text-text shadow-[inset_0_0_0_1px_rgba(216,184,102,0.05)]'
        : 'border border-transparent text-text-muted hover:border-border/80 hover:bg-hover/60 hover:text-text'
    } ${item.accent ? 'font-medium' : ''}`}
  >
    {isActive && (
      <span className="absolute bottom-3 left-0 top-3 w-[2px] rounded-r bg-accent shadow-[0_0_10px_rgba(216,184,102,0.55)]" />
    )}
    <div className="flex items-center gap-3">
      <span
        className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-[10px] border text-[9px] font-black tracking-[0.08em] transition-all ${
          isActive
            ? 'border-accent/50 bg-accent/[0.09] text-accent'
            : 'border-border/75 bg-surface-alt/50 text-text-subtle group-hover:border-border-strong/60 group-hover:text-text'
        }`}
      >
        {item.icon}
      </span>
      <div className="min-w-0 flex-1">
        <div className="truncate text-[13px] font-bold leading-tight">{item.label}</div>
        {item.desc && <div className="mt-1 truncate text-[11px] text-text-subtle">{item.desc}</div>}
      </div>
    </div>
  </button>
);

export const Sidebar: React.FC<SidebarProps> = ({
  activePage,
  serviceRunning,
  serviceStatus,
  isAuthorized,
  isApiConfigured,
  onNavigate,
  onStart,
  onStop,
}) => {
  const { theme, navItems, themeMode, toggleTheme } = useTheme();
  const items = React.useMemo(() => normalizeNavItems(navItems.length > 0 ? navItems : DEFAULT_NAV_ITEMS), [navItems]);

  const groups = React.useMemo(() => {
    const groupSet = new Set(items.map((item) => item.group));
    return Array.from(groupSet);
  }, [items]);

  return (
    <aside className="relative z-10 flex h-full w-[260px] shrink-0 flex-col border-r border-border/80 bg-app-sidebar">
      <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(180deg,rgba(255,255,255,0.025),transparent_46%)]" />

      <div className="relative flex shrink-0 flex-col items-center px-5 pb-5 pt-6 text-center">
        <div className="text-[11px] font-black uppercase tracking-[0.42em] text-text-subtle">Launcher</div>
        <div className="mt-2 text-base font-black tracking-[0.14em] text-text">{theme.brand.name}</div>
        <div className="mt-1 max-w-[16rem] text-[11px] text-text-subtle">{theme.brand.subtitle}</div>
      </div>

      <div className="relative shrink-0 px-4 pb-5">
        <button
          onClick={onStart}
          disabled={serviceRunning || serviceStatus === 'starting'}
          className={`w-full rounded-[14px] px-4 py-3 text-[13px] font-black transition-all disabled:cursor-not-allowed ${
            serviceRunning
              ? 'border border-status-success/25 bg-status-success/10 text-status-success opacity-90'
              : 'bg-accent text-accent-ink shadow-[0_12px_30px_rgba(216,184,102,0.15)] hover:bg-accent-hover disabled:opacity-55'
          }`}
        >
          {serviceStatus === 'starting' ? '启动中...' : serviceRunning ? '服务已运行' : '启动核心服务'}
        </button>
      </div>

      <nav className="relative flex-1 overflow-y-auto px-3 pb-3">
        {groups.map((group) => {
          const groupItems = items.filter((item) => item.group === group);
          return (
            <section key={group} className="mb-4">
              <div className="px-3 pb-2 pt-1 text-[10px] font-bold uppercase tracking-[0.22em] text-text-subtle">{group}</div>
              <div className="space-y-1.5">
                {groupItems.map((item) => (
                  <NavButton
                    key={item.key}
                    item={item}
                    isActive={activePage === item.key}
                    onClick={() => onNavigate(item.key)}
                  />
                ))}
              </div>
            </section>
          );
        })}
      </nav>

      <div className="relative shrink-0 border-t border-border/80 p-3">
        <div className="mb-2.5 grid grid-cols-[1fr_38px] gap-2">
          <button
            onClick={onStop}
            disabled={!serviceRunning && serviceStatus !== 'starting'}
            className="rounded-[13px] border border-status-danger/30 bg-status-danger/[0.055] px-3 py-2 text-[13px] font-bold text-status-danger transition-all hover:bg-status-danger/10 disabled:cursor-not-allowed disabled:opacity-40"
          >
            停止服务
          </button>
          <button
            onClick={toggleTheme}
            className="flex h-[38px] w-[38px] items-center justify-center rounded-[13px] border border-border/80 bg-surface-alt/50 text-sm font-black text-accent transition-all hover:border-border-strong/70 hover:bg-hover"
            title={themeMode === 'dark' ? '切换浅色风格' : '切换深色风格'}
            aria-label={themeMode === 'dark' ? '切换浅色风格' : '切换深色风格'}
          >
            {themeMode === 'dark' ? '☀' : '☾'}
          </button>
        </div>
        <div className="rounded-[14px] border border-border/80 bg-surface-alt/40 p-3">
          <div className="mb-2 flex items-center justify-between gap-3">
            <span className="text-[11px] font-medium text-text-muted">系统状态</span>
            <span className="text-[9px] uppercase tracking-[0.24em] text-text-subtle">LUMI</span>
          </div>
          <div className="flex items-center gap-2">
            <span className={`h-2 w-2 shrink-0 rounded-full ${statusTone(serviceRunning, isAuthorized, isApiConfigured)}`} />
            <span className="truncate text-[11px] font-medium text-text">{statusLabel(serviceRunning, serviceStatus, isAuthorized, isApiConfigured)}</span>
          </div>
        </div>
      </div>
    </aside>
  );
};
