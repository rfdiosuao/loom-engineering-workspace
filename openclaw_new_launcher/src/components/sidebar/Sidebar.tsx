import React from 'react';
import { LoomLogoMark } from '../brand/LoomBrand';
import { APP_DISPLAY_NAME } from '../../version';
import { showConfirm } from '../common';
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
  onStop: () => void;
}

type IconName = 'rocket' | 'box' | 'creative' | 'phone' | 'target' | 'matrix' | 'user' | 'capability' | 'model' | 'wrench' | 'settings' | 'power' | 'exit';

function iconFor(item: NavItem): IconName {
  const key = item.key;
  if (key === 'dashboard') return 'rocket';
  if (key === 'agents') return 'box';
  if (key === 'creative') return 'creative';
  if (key === 'acquisition') return 'target';
  if (key === 'phone') return 'phone';
  if (key === 'workbench') return 'matrix';
  if (key === 'agentAccess') return 'capability';
  if (key === 'capabilities') return 'capability';
  if (key === 'license') return 'user';
  if (key === 'models') return 'model';
  if (key === 'diagnostics') return 'wrench';
  return 'capability';
}

function statusTone(serviceRunning: boolean, isAuthorized: boolean, isApiConfigured: boolean): string {
  if (serviceRunning || isApiConfigured) return 'bg-status-success';
  if (isAuthorized) return 'bg-status-warning';
  return 'bg-status-danger';
}

const Icon: React.FC<{ name: IconName; className?: string }> = ({ name, className = '' }) => {
  const common = {
    className,
    viewBox: '0 0 24 24',
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: 2,
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
    'aria-hidden': true,
  };
  if (name === 'rocket') {
    return (
      <svg {...common}>
        <path d="M13.5 6.5c2.2-2.2 5-2.8 6.8-2.8 0 1.8-.6 4.6-2.8 6.8l-6.7 6.7-4-4 6.7-6.7Z" />
        <path d="M9.5 9.5H5.9L3.8 12l3.2.8" />
        <path d="M14.5 14.5v3.6L12 20.2l-.8-3.2" />
        <path d="M6.5 17.5 4 20" />
      </svg>
    );
  }
  if (name === 'box') {
    return (
      <svg {...common}>
        <path d="M7 7.5 12 5l5 2.5-5 2.5-5-2.5Z" />
        <path d="M7 7.5v6.8l5 2.7 5-2.7V7.5" />
        <path d="M12 10v7" />
        <path d="M5 17.5h14" />
      </svg>
    );
  }
  if (name === 'phone') {
    return (
      <svg {...common}>
        <rect x="7" y="2.8" width="10" height="18.4" rx="2.2" />
        <path d="M10.5 18.2h3" />
      </svg>
    );
  }
  if (name === 'creative') {
    return (
      <svg {...common}>
        <path d="M5 17.5c2.8-6.7 7.1-10.6 13-11.8" />
        <path d="M8.5 16.8c1.8-3.2 4.1-5.2 6.8-6" />
        <path d="M4.5 19.5c2.4.2 4.5-.3 6.4-1.5" />
        <path d="M16.4 4.2 19.8 7.6" />
        <path d="M13.9 5.6 18.4 10" />
      </svg>
    );
  }
  if (name === 'matrix') {
    return (
      <svg {...common}>
        <rect x="4" y="5" width="6" height="6" rx="1.2" />
        <rect x="14" y="5" width="6" height="6" rx="1.2" />
        <rect x="4" y="15" width="6" height="6" rx="1.2" />
        <rect x="14" y="15" width="6" height="6" rx="1.2" />
        <path d="M10 8h4" />
        <path d="M10 18h4" />
        <path d="M7 11v4" />
        <path d="M17 11v4" />
      </svg>
    );
  }
  if (name === 'target') {
    return (
      <svg {...common}>
        <circle cx="12" cy="12" r="7.2" />
        <circle cx="12" cy="12" r="2.4" />
        <path d="M12 2.8v3" />
        <path d="M12 18.2v3" />
        <path d="M2.8 12h3" />
        <path d="M18.2 12h3" />
        <path d="M16.8 16.8 20 20" />
      </svg>
    );
  }
  if (name === 'user') {
    return (
      <svg {...common}>
        <circle cx="12" cy="8" r="3.4" />
        <path d="M5 20c1.2-3.4 3.5-5 7-5s5.8 1.6 7 5" />
      </svg>
    );
  }
  if (name === 'wrench') {
    return (
      <svg {...common}>
        <path d="M14.8 6.2a4 4 0 0 0 4.9 4.9l-7.8 7.8a2.4 2.4 0 0 1-3.4-3.4l7.8-7.8Z" />
        <path d="m7.5 16.5-3.2 3.2" />
      </svg>
    );
  }
  if (name === 'settings') {
    return (
      <svg {...common}>
        <circle cx="12" cy="12" r="3" />
        <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 0 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 0 1-4 0v-.1a1.7 1.7 0 0 0-1-1.5 1.7 1.7 0 0 0-1.9.3l-.1.1A2 2 0 0 1 4.2 17l.1-.1a1.7 1.7 0 0 0 .3-1.9 1.7 1.7 0 0 0-1.5-1H3a2 2 0 0 1 0-4h.1a1.7 1.7 0 0 0 1.5-1 1.7 1.7 0 0 0-.3-1.9l-.1-.1A2 2 0 0 1 7 4.2l.1.1a1.7 1.7 0 0 0 1.9.3A1.7 1.7 0 0 0 10 3.1V3a2 2 0 0 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.9-.3l.1-.1A2 2 0 0 1 19.8 7l-.1.1a1.7 1.7 0 0 0-.3 1.9 1.7 1.7 0 0 0 1.5 1h.1a2 2 0 0 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1Z" />
      </svg>
    );
  }
  if (name === 'power') {
    return (
      <svg {...common}>
        <path d="M12 3v8" />
        <path d="M8.2 5.4a8 8 0 1 0 7.6 0" />
      </svg>
    );
  }
  if (name === 'capability') {
    return (
      <svg {...common}>
        <path d="M7 4.5h10" />
        <path d="M6 9h12" />
        <path d="M7 13.5h10" />
        <path d="M9 18h6" />
        <path d="M4.5 7.3 7 4.5l2.5 2.8" />
        <path d="m14.5 16.7 2.5 2.8 2.5-2.8" />
      </svg>
    );
  }
  if (name === 'model') {
    return (
      <svg {...common}>
        <path d="M12 3.5 18.5 7v10L12 20.5 5.5 17V7L12 3.5Z" />
        <path d="M12 10.8 18.5 7" />
        <path d="M12 10.8 5.5 7" />
        <path d="M12 10.8v9.7" />
        <path d="M8.3 14.2 5.5 12.7" />
        <path d="m15.7 14.2 2.8-1.5" />
      </svg>
    );
  }
  if (name === 'exit') {
    return (
      <svg {...common}>
        <path d="M9 4H5.8A1.8 1.8 0 0 0 4 5.8v12.4A1.8 1.8 0 0 0 5.8 20H9" />
        <path d="M14 7l5 5-5 5" />
        <path d="M19 12H9" />
      </svg>
    );
  }
  return null;
};

const NavButton: React.FC<{
  item: NavItem;
  isActive: boolean;
  onClick: () => void;
}> = ({ item, isActive, onClick }) => (
  <button
    type="button"
    onClick={onClick}
    title={item.label}
    aria-label={item.label}
    className={`group relative flex min-h-[64px] w-full flex-col items-center justify-center gap-1.5 rounded-[8px] px-1 py-2 text-center transition-all ${
      isActive
        ? 'bg-white/[0.075] text-accent shadow-[inset_0_0_0_1px_rgba(55,213,163,0.16)]'
        : 'text-white/58 hover:bg-white/[0.05] hover:text-white'
    }`}
  >
    {isActive && <span className="absolute right-[-8px] top-2 h-11 w-[3px] rounded-l bg-accent" />}
    <Icon name={iconFor(item)} className="h-[22px] w-[22px]" />
    <span className={`text-[11px] font-black leading-none ${isActive ? 'text-accent' : 'text-white/68 group-hover:text-white'}`}>
      {item.label}
    </span>
  </button>
);

const UtilityButton: React.FC<{
  label: string;
  icon: IconName;
  disabled?: boolean;
  onClick: () => void;
}> = ({ label, icon, disabled, onClick }) => (
  <button
    type="button"
    title={label}
    aria-label={label}
    disabled={disabled}
    onClick={onClick}
    className="flex h-10 w-10 items-center justify-center rounded-[8px] text-white/58 transition hover:bg-white/[0.06] hover:text-white disabled:cursor-not-allowed disabled:opacity-35"
  >
    <Icon name={icon} className="h-[21px] w-[21px]" />
  </button>
);

export const Sidebar: React.FC<SidebarProps> = ({
  activePage,
  serviceRunning,
  serviceStatus,
  isAuthorized,
  isApiConfigured,
  onNavigate,
  onStop,
}) => {
  const { navItems } = useTheme();
  const items = React.useMemo(() => normalizeNavItems(navItems.length > 0 ? navItems : DEFAULT_NAV_ITEMS), [navItems]);

  return (
    <aside className="relative z-10 flex h-full w-[72px] shrink-0 flex-col border-r border-[#12343D]/75 bg-app-sidebar text-white shadow-[inset_-1px_0_rgba(55,213,163,0.08)]">
      <div className="pointer-events-none absolute inset-y-0 right-0 w-6 bg-[linear-gradient(90deg,transparent,rgba(55,213,163,0.08))]" />

      <div className="relative flex shrink-0 items-center justify-center pb-3 pt-4">
        <LoomLogoMark className="h-10 w-10 shadow-[0_14px_30px_rgba(0,0,0,0.34),0_0_0_1px_rgba(223,250,255,0.04)]" />
      </div>

      <nav className="relative flex-1 overflow-y-auto px-2 pb-3">
        <div className="space-y-2">
          {items.map((item) => (
            <NavButton
              key={item.key}
              item={item}
              isActive={activePage === item.key}
              onClick={() => onNavigate(item.key)}
            />
          ))}
        </div>
      </nav>

      <div className="relative flex shrink-0 flex-col items-center gap-2 px-2 pb-4">
        <span
          title={serviceRunning ? '核心运行中' : isApiConfigured ? '配置已就绪' : isAuthorized ? '待启动' : '未登录'}
          className={`mb-1 h-2 w-2 rounded-full ${statusTone(serviceRunning, isAuthorized, isApiConfigured)}`}
        />
        {(serviceRunning || serviceStatus === 'starting') ? (
          <UtilityButton
            label="停止运行环境"
            icon="power"
            onClick={() => {
              void (async () => {
                const ok = await showConfirm({
                  title: '停止运行环境',
                  message: `正在运行的任务可能中断，确定要停止 ${APP_DISPLAY_NAME} 本地运行环境吗？`,
                  confirmText: '停止',
                  tone: 'danger',
                });
                if (ok) onStop();
              })();
            }}
          />
        ) : null}
        <UtilityButton label="系统设置" icon="settings" onClick={() => onNavigate('settings')} />
        <UtilityButton label={isApiConfigured ? '模型账户' : '登录模型账户'} icon="exit" onClick={() => onNavigate('license')} />
      </div>
    </aside>
  );
};
