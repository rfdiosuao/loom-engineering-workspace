import React from 'react';
import { getCurrentWindow } from '@tauri-apps/api/window';
import { LoomTitleLockup } from '../brand/LoomBrand';

const appWindow = (() => {
  try {
    return getCurrentWindow();
  } catch {
    return null;
  }
})();

const WindowButton: React.FC<{
  title: string;
  danger?: boolean;
  onClick: () => void;
  children: React.ReactNode;
}> = ({ title, danger, onClick, children }) => (
  <button
    type="button"
    title={title}
    aria-label={title}
    onClick={(event) => {
      event.stopPropagation();
      onClick();
    }}
    className={`flex h-10 w-12 items-center justify-center rounded-none transition-colors ${
      danger
        ? 'text-white/60 hover:bg-[#E81123] hover:text-white'
        : 'text-white/58 hover:bg-white/[0.07] hover:text-white'
    }`}
  >
    <span className="pointer-events-none flex h-[14px] w-[14px] items-center justify-center">
      {children}
    </span>
  </button>
);

const MinimizeGlyph = () => (
  <svg viewBox="0 0 16 16" className="h-[14px] w-[14px]" aria-hidden="true">
    <path d="M3.5 8.5h9" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round" />
  </svg>
);

const MaximizeGlyph = () => (
  <svg viewBox="0 0 16 16" className="h-[14px] w-[14px]" aria-hidden="true">
    <rect x="4.25" y="4.25" width="7.5" height="7.5" fill="none" stroke="currentColor" strokeWidth="1.15" />
  </svg>
);

const CloseGlyph = () => (
  <svg viewBox="0 0 16 16" className="h-[14px] w-[14px]" aria-hidden="true">
    <path d="M4.25 4.25l7.5 7.5M11.75 4.25l-7.5 7.5" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round" />
  </svg>
);

export const WindowTitlebar: React.FC = () => {
  const toggleMaximize = () => {
    appWindow?.toggleMaximize().catch(() => {});
  };

  return (
    <div
      data-window-drag-above-overlays
      data-tauri-drag-region
      onDoubleClick={toggleMaximize}
      className="relative z-[100000] flex h-10 shrink-0 items-stretch border-b border-[#12343D]/75 bg-app-sidebar text-white"
    >
      <div data-tauri-drag-region className="flex w-[292px] shrink-0 items-center border-r border-[#12343D]/75 px-3 text-white">
        <LoomTitleLockup wordmarkTone="light" />
      </div>

      <div data-tauri-drag-region className="flex min-w-0 flex-1 items-stretch justify-end bg-app-sidebar">
        <div className="flex h-full items-stretch">
          <WindowButton title="最小化" onClick={() => appWindow?.minimize()}>
            <MinimizeGlyph />
          </WindowButton>
          <WindowButton title="最大化/还原" onClick={toggleMaximize}>
            <MaximizeGlyph />
          </WindowButton>
          <WindowButton title="关闭" danger onClick={() => appWindow?.close()}>
            <CloseGlyph />
          </WindowButton>
        </div>
      </div>
    </div>
  );
};
