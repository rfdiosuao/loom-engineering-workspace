import React from 'react';
import { getCurrentWindow } from '@tauri-apps/api/window';
import logoImg from '../../assets/logo.png';
import { BrandLogo } from '../common';
import { useTheme } from '../../hooks/useTheme';

const appWindow = (() => {
  try {
    return getCurrentWindow();
  } catch {
    return null;
  }
})();

const WindowButton: React.FC<{
  label: string;
  title: string;
  danger?: boolean;
  onClick: () => void;
}> = ({ label, title, danger, onClick }) => (
  <button
    type="button"
    title={title}
    aria-label={title}
    onClick={(event) => {
      event.stopPropagation();
      onClick();
    }}
    className={`flex h-8 w-10 items-center justify-center rounded-lg text-sm font-semibold transition-colors ${
      danger
        ? 'text-text-muted hover:bg-status-danger hover:text-white'
        : 'text-text-muted hover:bg-hover hover:text-text'
    }`}
  >
    {label}
  </button>
);

export const WindowTitlebar: React.FC = () => {
  const { brandName, brandSubtitle, logoUrl } = useTheme();
  const brandLogo = logoUrl || logoImg;

  const toggleMaximize = () => {
    appWindow?.toggleMaximize().catch(() => {});
  };

  return (
    <div
      data-tauri-drag-region
      onDoubleClick={toggleMaximize}
      className="flex h-10 shrink-0 items-stretch border-b border-border bg-surface text-text"
    >
      <div data-tauri-drag-region className="flex w-[260px] shrink-0 items-center gap-2 bg-app-sidebar px-3">
        <div className="flex h-6 w-6 items-center justify-center rounded-lg border border-border bg-surface-alt">
          <BrandLogo src={brandLogo} fallbackSrc={logoImg} className="h-4 w-4 object-contain" />
        </div>
        <div data-tauri-drag-region className="truncate text-xs font-black tracking-wide">
          {brandName}
        </div>
        <div data-tauri-drag-region className="hidden truncate text-xs text-text-subtle sm:block">
          {brandSubtitle}
        </div>
      </div>

      <div data-tauri-drag-region className="flex min-w-0 flex-1 items-center justify-end bg-surface px-3">
        <div className="flex items-center gap-1">
          <WindowButton title="Minimize" label="-" onClick={() => appWindow?.minimize()} />
          <WindowButton title="Maximize / Restore" label="[]" onClick={toggleMaximize} />
          <WindowButton title="Close" label="x" danger onClick={() => appWindow?.close()} />
        </div>
      </div>
    </div>
  );
};
