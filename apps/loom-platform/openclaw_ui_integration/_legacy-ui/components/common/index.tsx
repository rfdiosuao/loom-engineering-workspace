import React from 'react';
import { create } from 'zustand';

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'danger' | 'success' | 'quiet' | 'default';
  children: React.ReactNode;
}

export const Button: React.FC<ButtonProps> = ({ variant = 'default', children, className = '', ...props }) => {
  const base = 'px-4 py-2 rounded-xl font-semibold transition-all cursor-pointer text-sm disabled:opacity-50 disabled:cursor-not-allowed';
  const variants: Record<string, string> = {
    primary: 'bg-accent hover:bg-accent-hover text-accent-ink shadow-[0_14px_34px_rgba(214,180,106,0.18)]',
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
  if (!isOpen) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" onClick={onClose}>
      <div className="absolute inset-0 bg-black/70 backdrop-blur-md" />
      <div
        className="relative mx-4 max-h-[82vh] w-full max-w-lg overflow-auto rounded-2xl border border-border bg-surface/95 p-6 shadow-[0_28px_90px_rgba(0,0,0,0.56),0_0_34px_rgba(214,180,106,0.12)]"
        onClick={(event) => event.stopPropagation()}
      >
        {title && (
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-lg font-bold text-text">{title}</h2>
            <button onClick={onClose} className="text-2xl leading-none text-text-muted hover:text-text">&times;</button>
          </div>
        )}
        {children}
      </div>
    </div>
  );
};

let toastId = 0;
const TOAST_TTL_MS = 3200;
const TOAST_DEDUPE_WINDOW_MS = 1800;
const MAX_VISIBLE_TOASTS = 3;

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
    info: 'bg-accent text-accent-ink',
  };
  return (
    <div className="pointer-events-none fixed right-5 top-5 z-[100] flex w-[min(560px,calc(100vw-2.5rem))] flex-col gap-2">
      {toasts.map((toast) => (
        <div
          key={toast.id}
          className={`${colors[toast.type]} toast-enter pointer-events-auto flex items-center gap-3 rounded-xl border border-white/15 px-4 py-3 text-sm font-semibold shadow-[0_18px_44px_rgba(0,0,0,0.42)]`}
        >
          <span className="min-w-0 flex-1 break-words">{toast.message}</span>
          <button onClick={() => removeToast(toast.id)} className="opacity-70 hover:opacity-100">&times;</button>
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
    <div className="h-8 w-8 animate-spin rounded-full border-4 border-accent border-t-transparent" />
    <span className="text-sm text-text-muted">{text}</span>
  </div>
);

export const SectionLabel: React.FC<{ text: string }> = ({ text }) => (
  <div className="mt-2 px-3 py-1 text-xs font-semibold text-text-subtle">{text}</div>
);

export const FieldLabel: React.FC<{ text: string; required?: boolean }> = ({ text, required }) => (
  <label className="mb-1 block text-xs font-medium text-text-muted">
    {text}{required && <span className="ml-1 text-status-danger">*</span>}
  </label>
);
