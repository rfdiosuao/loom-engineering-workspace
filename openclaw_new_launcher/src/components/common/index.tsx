import React from 'react';
import { createPortal } from 'react-dom';
import { create } from 'zustand';
import { APP_DISPLAY_NAME } from '../../version';

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'danger' | 'success' | 'quiet' | 'default';
  children: React.ReactNode;
}

export const Button: React.FC<ButtonProps> = ({ variant = 'default', children, className = '', ...props }) => {
  const base = 'px-4 py-2 rounded-xl font-semibold transition-all cursor-pointer text-sm disabled:cursor-not-allowed disabled:border-border disabled:bg-surface-alt/60 disabled:text-text-subtle disabled:shadow-none';
  const variants: Record<string, string> = {
    primary: 'border border-[#0B4A3E]/45 bg-[#0B4A3E] text-[#F5FFF9] shadow-[0_12px_28px_rgba(8,60,49,0.20)] hover:border-[#146650]/60 hover:bg-[#12604F]',
    danger: 'bg-status-danger/12 hover:bg-status-danger/22 text-status-danger border border-status-danger/35',
    success: 'bg-status-success/14 hover:bg-status-success/24 text-status-success border border-status-success/35 shadow-[0_0_18px_rgba(63,224,143,0.16)]',
    quiet: 'bg-surface-alt/70 hover:bg-hover text-text-muted hover:text-text border border-border',
    default: 'bg-surface-alt/85 hover:bg-hover text-text border border-border',
  };
  return (
    <button className={`${base} ${variants[variant]} ${className}`} {...props}>
      {children}
    </button>
  );
};

export interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {}

export const Input: React.FC<InputProps> = ({ className = '', ...props }) => (
  <input
    className={`w-full rounded-xl border border-border bg-input px-3 py-2 text-sm text-text placeholder:text-text-subtle focus:border-border-strong focus:outline-none focus:ring-2 focus:ring-accent/30 ${className}`}
    {...props}
  />
);

export interface TextAreaProps extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {}

export const TextArea: React.FC<TextAreaProps> = ({ className = '', ...props }) => (
  <textarea
    className={`w-full resize-y rounded-xl border border-border bg-input px-3 py-2 text-sm text-text placeholder:text-text-subtle focus:border-border-strong focus:outline-none focus:ring-2 focus:ring-accent/30 ${className}`}
    {...props}
  />
);

export interface SelectProps extends React.SelectHTMLAttributes<HTMLSelectElement> {}

export const Select: React.FC<SelectProps> = ({ className = '', children, ...props }) => (
  <select
    className={`rounded-xl border border-border bg-input px-3 py-2 text-sm text-text focus:border-border-strong focus:outline-none focus:ring-2 focus:ring-accent/30 ${className}`}
    {...props}
  >
    {children}
  </select>
);

export const Modal: React.FC<{
  isOpen: boolean;
  onClose: () => void;
  title?: string;
  children: React.ReactNode;
}> = ({ isOpen, onClose, title, children }) => {
  const titleId = React.useId();
  if (!isOpen) return null;
  const modal = (
    <div
      data-viewport-modal
      role="dialog"
      aria-modal="true"
      aria-labelledby={title ? titleId : undefined}
      aria-label={title ? undefined : '对话框'}
      className="flex items-center justify-center px-4"
      style={{
        position: 'fixed',
        inset: 0,
        width: '100vw',
        height: '100dvh',
        zIndex: 2_147_483_000,
        overflow: 'hidden',
        overscrollBehavior: 'contain',
      }}
      onKeyDown={(event) => {
        if (event.key === 'Escape') onClose();
      }}
    >
      <button
        type="button"
        data-modal-backdrop
        aria-label={title ? `关闭${title}` : '关闭对话框'}
        onClick={onClose}
        className="absolute inset-0 h-full w-full bg-[#071916]/78 backdrop-blur-sm"
      />
      <div
        className="relative max-h-[min(82dvh,720px)] w-full max-w-lg overflow-auto rounded-[8px] border border-[#0B4A3E]/25 bg-surface p-6 shadow-[0_28px_90px_rgba(0,0,0,0.56),0_0_34px_rgba(11,74,62,0.12)]"
      >
        {title && (
          <div className="mb-4 flex items-center justify-between">
            <h2 id={titleId} className="text-lg font-bold text-text">{title}</h2>
            <button
              type="button"
              aria-label={title ? `关闭${title}` : '关闭对话框'}
              onClick={onClose}
              className="text-2xl leading-none text-text-muted hover:text-text"
            >
              &times;
            </button>
          </div>
        )}
        {children}
      </div>
    </div>
  );
  if (typeof document === 'undefined') return modal;
  return createPortal(modal, document.body);
};

type ConfirmTone = 'default' | 'danger';

interface ConfirmOptions {
  title?: string;
  message: string;
  confirmText?: string;
  cancelText?: string;
  tone?: ConfirmTone;
}

interface ConfirmRequest extends Required<ConfirmOptions> {
  id: number;
  resolve: (value: boolean) => void;
}

let confirmId = 0;

const confirmStore = create<{
  request: ConfirmRequest | null;
  open: (options: ConfirmOptions) => Promise<boolean>;
  settle: (value: boolean) => void;
}>((set, get) => ({
  request: null,
  open: (options) => new Promise<boolean>((resolve) => {
    const current = get().request;
    if (current) current.resolve(false);
    set({
      request: {
        id: ++confirmId,
        title: options.title || '请确认',
        message: options.message,
        confirmText: options.confirmText || '确定',
        cancelText: options.cancelText || '取消',
        tone: options.tone || 'default',
        resolve,
      },
    });
  }),
  settle: (value) => {
    const current = get().request;
    if (!current) return;
    current.resolve(value);
    set({ request: null });
  },
}));

export function showConfirm(options: string | ConfirmOptions): Promise<boolean> {
  const normalized = typeof options === 'string' ? { message: options } : options;
  return confirmStore.getState().open(normalized);
}

export const ConfirmDialogHost: React.FC = () => {
  const request = confirmStore((state) => state.request);
  const settle = confirmStore((state) => state.settle);
  const dialogPanelRef = React.useRef<HTMLDivElement>(null);
  const previouslyFocusedElementRef = React.useRef<HTMLElement | null>(null);

  React.useEffect(() => {
    if (!request) {
      const previouslyFocused = previouslyFocusedElementRef.current;
      previouslyFocusedElementRef.current = null;
      if (previouslyFocused?.isConnected) previouslyFocused.focus();
      return;
    }

    if (!previouslyFocusedElementRef.current && document.activeElement instanceof HTMLElement) {
      previouslyFocusedElementRef.current = document.activeElement;
    }
    dialogPanelRef.current?.querySelector<HTMLElement>('[data-confirm-cancel]')?.focus();
  }, [request?.id]);

  if (!request) return null;

  const handleConfirmKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      settle(false);
      return;
    }
    if (event.key !== 'Tab') return;

    const focusableElements = Array.from(dialogPanelRef.current?.querySelectorAll<HTMLElement>(
      'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
    ) ?? []);
    if (focusableElements.length === 0) {
      event.preventDefault();
      dialogPanelRef.current?.focus();
      return;
    }

    const firstElement = focusableElements[0];
    const lastElement = focusableElements[focusableElements.length - 1];
    const activeElement = document.activeElement;
    if (event.shiftKey && (activeElement === firstElement || !dialogPanelRef.current?.contains(activeElement))) {
      event.preventDefault();
      lastElement.focus();
    } else if (!event.shiftKey && (activeElement === lastElement || !dialogPanelRef.current?.contains(activeElement))) {
      event.preventDefault();
      firstElement.focus();
    }
  };

  return (
    <div
      className="fixed inset-0 z-[99970] flex items-center justify-center px-5"
      role="dialog"
      aria-modal="true"
      aria-labelledby={`confirm-title-${request.id}`}
      onKeyDown={handleConfirmKeyDown}
    >
      <button
        type="button"
        tabIndex={-1}
        aria-label="取消"
        className="absolute inset-0 h-full w-full bg-[#061017]/55 backdrop-blur-[2px]"
        onClick={() => settle(false)}
      />
      <div
        ref={dialogPanelRef}
        tabIndex={-1}
        className="relative w-full max-w-[440px] rounded-[18px] border border-border bg-surface/98 p-5 shadow-[0_30px_90px_rgba(5,25,22,0.28)]"
      >
        <div className={`mb-4 flex h-10 w-10 items-center justify-center rounded-full ${
          request.tone === 'danger'
            ? 'border border-status-danger/25 bg-status-danger/12 text-status-danger'
            : 'border border-[#0B4A3E]/20 bg-[#0B4A3E]/10 text-[#0B4A3E]'
        }`}>
          <span className="text-lg font-black">{request.tone === 'danger' ? '!' : '?'}</span>
        </div>
        <h2 id={`confirm-title-${request.id}`} className="text-lg font-black text-text">{request.title}</h2>
        <p className="mt-2 whitespace-pre-line text-sm leading-6 text-text-muted">{request.message}</p>
        <div className="mt-5 flex justify-end gap-3">
          <Button data-confirm-cancel variant="quiet" onClick={() => settle(false)}>{request.cancelText}</Button>
          <Button variant={request.tone === 'danger' ? 'danger' : 'primary'} onClick={() => settle(true)}>
            {request.confirmText}
          </Button>
        </div>
      </div>
    </div>
  );
};

let toastId = 0;
const TOAST_TTL_MS = 3200;
const TOAST_DEDUPE_WINDOW_MS = 1800;
const MAX_VISIBLE_TOASTS = 3;
const TITLEBAR_HEIGHT_PX = 40;
const TOAST_SAFE_GAP_PX = 12;
const TOAST_LAYER_Z_INDEX = 99_990;

interface ToastItem {
  id: number;
  message: string;
  type: 'success' | 'error' | 'info';
  createdAt: number;
}

const toastStore = create<{
  toasts: ToastItem[];
  addToast: (message: string, type: 'success' | 'error' | 'info') => void;
  removeToast: (id: number) => void;
}>((set) => ({
  toasts: [],
  addToast: (message: string, type: 'success' | 'error' | 'info') => {
    const now = Date.now();
    let scheduledId: number | null = null;
    let shouldSchedule = false;

    const id = ++toastId;
    set((state) => ({
      toasts: (() => {
        const duplicate = state.toasts.find(
          (toast) => toast.type === type && toast.message === message && now - toast.createdAt < TOAST_DEDUPE_WINDOW_MS
        );
        if (duplicate) return state.toasts;

        scheduledId = id;
        shouldSchedule = true;
        return [...state.toasts, { id, message, type, createdAt: now }].slice(-MAX_VISIBLE_TOASTS);
      })(),
    }));

    if (shouldSchedule && scheduledId !== null) {
      window.setTimeout(() => {
        toastStore.getState().removeToast(scheduledId as number);
      }, TOAST_TTL_MS);
    }
  },
  removeToast: (id: number) =>
    set((state) => ({
      toasts: state.toasts.filter((toast) => toast.id !== id),
    })),
}));

export const useToastStore = toastStore;

export const ToastContainer: React.FC = () => {
  const toasts = useToastStore((state) => state.toasts);
  const removeToast = useToastStore((state) => state.removeToast);
  const colors: Record<string, string> = {
    success: 'bg-status-success text-[#04140D]',
    error: 'bg-status-danger text-white',
    info: 'border border-[#0B4A3E]/35 bg-[#0B4A3E] text-[#F5FFF9]',
  };
  return (
    <div
      data-toast-container
      className="pointer-events-none fixed right-5 flex w-[min(560px,calc(100vw-2.5rem))] flex-col gap-2"
      style={{
        top: TITLEBAR_HEIGHT_PX + TOAST_SAFE_GAP_PX,
        zIndex: TOAST_LAYER_Z_INDEX,
      }}
    >
      {toasts.map((toast) => (
        <div
          key={toast.id}
          className={`${colors[toast.type]} toast-enter pointer-events-auto flex items-center gap-3 rounded-xl border border-white/15 px-4 py-3 text-sm font-semibold shadow-[0_18px_44px_rgba(0,0,0,0.42)]`}
        >
          <span
            className="min-w-0 flex-1 break-words"
            role="status"
            aria-live="polite"
            aria-atomic="true"
          >
            {toast.message}
          </span>
          <button
            type="button"
            aria-label={`关闭通知：${toast.message}`}
            onClick={() => removeToast(toast.id)}
            className="opacity-70 hover:opacity-100"
          >
            &times;
          </button>
        </div>
      ))}
    </div>
  );
};

export function showToast(message: string, type: 'success' | 'error' | 'info' = 'info') {
  toastStore.getState().addToast(message, type);
}

export const BrandLogo: React.FC<{
  src?: string;
  fallbackSrc: string;
  alt?: string;
  className?: string;
}> = ({ src, fallbackSrc, alt = '', className = '' }) => {
  const [activeSrc, setActiveSrc] = React.useState(src || fallbackSrc);
  const fallbackUsedRef = React.useRef(false);

  React.useEffect(() => {
    fallbackUsedRef.current = false;
    setActiveSrc(src || fallbackSrc);
  }, [src, fallbackSrc]);

  return (
    <img
      src={activeSrc}
      alt={alt}
      className={className}
      onError={() => {
        if (fallbackUsedRef.current) return;
        fallbackUsedRef.current = true;
        setActiveSrc(fallbackSrc);
      }}
      draggable={false}
    />
  );
};

export const Loading: React.FC<{ text?: string }> = ({ text = '加载中...' }) => (
  <div className="flex flex-col items-center justify-center gap-3 py-12">
    <div className="h-8 w-8 animate-spin rounded-full border-4 border-[#0B4A3E] border-t-transparent" />
    <span className="text-sm text-text-muted">{text}</span>
  </div>
);

export const BusyOverlay: React.FC<{
  active: boolean;
  title?: string;
  detail?: string;
  mode?: 'blocking' | 'corner';
}> = ({
  active,
  title = '正在处理',
  detail = `请稍候，${APP_DISPLAY_NAME} 正在完成当前操作。`,
  mode = 'blocking',
}) => {
  if (!active) return null;

  const isCorner = mode === 'corner';
  const overlay = (
    <div
      data-busy-overlay
      data-busy-overlay-mode={mode}
      role="status"
      aria-live="polite"
      className={
        isCorner
          ? 'pointer-events-none fixed left-[calc(var(--sidebar-width,88px)+16px)] top-14 z-[99940] flex max-w-[min(360px,calc(100vw-2rem))] items-start'
          : 'pointer-events-auto fixed bottom-0 left-0 right-0 top-10 z-[99940] flex items-center justify-center bg-[#071916]/64 px-6'
      }
    >
      {isCorner ? (
        <div
          data-busy-overlay-corner-card
          className="pointer-events-none flex min-w-[220px] items-center gap-3 rounded-[14px] border border-[#0B4A3E]/18 bg-surface/95 px-4 py-3 text-left shadow-[0_14px_34px_rgba(5,35,29,0.16)]"
        >
          <span className="loom-busy-ring shrink-0" aria-hidden="true" />
          <div className="min-w-0">
            <div className="truncate text-sm font-black text-text">{title}</div>
            {detail ? <div className="mt-0.5 max-w-full truncate text-xs leading-5 text-text-muted">{detail}</div> : null}
          </div>
        </div>
      ) : (
        <div
          data-busy-overlay-card
          className="flex min-w-[280px] max-w-[420px] max-h-[min(80vh,420px)] flex-col items-center overflow-auto rounded-[8px] border border-[#0B4A3E]/28 bg-[#FFFCF4] px-6 py-5 text-center shadow-[0_26px_74px_rgba(5,35,29,0.34)]"
        >
          <span className="loom-busy-ring" aria-hidden="true" />
          <div className="mt-4 text-base font-black text-text">{title}</div>
          {detail ? <div className="mt-1 max-w-full whitespace-pre-wrap break-words text-xs leading-5 text-text-muted">{detail}</div> : null}
        </div>
      )}
    </div>
  );

  if (typeof document === 'undefined') return overlay;
  return createPortal(overlay, document.body);
};

export const SectionLabel: React.FC<{ text: string }> = ({ text }) => (
  <div className="mt-2 px-3 py-1 text-xs font-semibold text-text-subtle">{text}</div>
);

export const FieldLabel: React.FC<{ text: string; required?: boolean }> = ({ text, required }) => (
  <label className="mb-1 block text-xs font-medium text-text-muted">
    {text}{required && <span className="ml-1 text-status-danger">*</span>}
  </label>
);
