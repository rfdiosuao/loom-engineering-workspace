import React from 'react';
import type { LucideIcon } from 'lucide-react';
import { AlertCircle, CheckCircle2, Loader2, MinusCircle, X } from 'lucide-react';
import type { StatusTone } from '../types';

type ButtonVariant = 'primary' | 'secondary' | 'quiet' | 'danger' | 'success';

export function cx(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(' ');
}

export function Panel(props: React.HTMLAttributes<HTMLDivElement>) {
  return <div {...props} className={cx('panel', props.className)} />;
}

export function SectionHeader({
  eyebrow,
  title,
  subtitle,
  action,
}: {
  eyebrow?: string;
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <div className="section-header">
      <div>
        {eyebrow ? <div className="eyebrow">{eyebrow}</div> : null}
        <h2>{title}</h2>
        {subtitle ? <p>{subtitle}</p> : null}
      </div>
      {action ? <div className="section-action">{action}</div> : null}
    </div>
  );
}

export function Button({
  variant = 'secondary',
  icon: Icon,
  children,
  className,
  type = 'button',
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  icon?: LucideIcon;
}) {
  return (
    <button
      {...props}
      type={type}
      className={cx('button', `button-${variant}`, className)}
    >
      {Icon ? <Icon size={16} /> : null}
      <span>{children}</span>
    </button>
  );
}

export function Chip({
  tone = 'neutral',
  children,
  className,
}: {
  tone?: Exclude<StatusTone, 'busy'> | 'neutral';
  children: React.ReactNode;
  className?: string;
}) {
  return <span className={cx('chip', `chip-${tone}`, className)}>{children}</span>;
}

export function StatTile({
  label,
  value,
  hint,
  tone = 'neutral',
}: {
  label: string;
  value: React.ReactNode;
  hint?: React.ReactNode;
  tone?: Exclude<StatusTone, 'busy'> | 'neutral';
}) {
  return (
    <div className={cx('stat-tile', `stat-tile-${tone}`)}>
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      {hint ? <div className="stat-hint">{hint}</div> : null}
    </div>
  );
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description?: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <div className="empty-state">
      <div className="empty-state-mark">/</div>
      <div className="empty-state-title">{title}</div>
      {description ? <div className="empty-state-desc">{description}</div> : null}
      {action ? <div className="empty-state-action">{action}</div> : null}
    </div>
  );
}

export function InlineState({
  tone,
  title,
  description,
  icon: Icon,
}: {
  tone: Exclude<StatusTone, 'busy'> | 'neutral';
  title: string;
  description?: React.ReactNode;
  icon?: LucideIcon;
}) {
  const icon = Icon || (tone === 'danger' ? AlertCircle : tone === 'ok' ? CheckCircle2 : tone === 'warn' ? MinusCircle : Loader2);
  const IconNode = icon;
  return (
    <div className={cx('inline-state', `inline-state-${tone}`)}>
      <IconNode size={16} />
      <div>
        <div className="inline-state-title">{title}</div>
        {description ? <div className="inline-state-desc">{description}</div> : null}
      </div>
    </div>
  );
}

export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <label className="field">
      <div className="field-head">
        <span className="field-label">{label}</span>
        {hint ? <span className="field-hint">{hint}</span> : null}
      </div>
      {children}
    </label>
  );
}

export function Input(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={cx('input', props.className)} />;
}

export function TextArea(props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...props} className={cx('textarea', props.className)} />;
}

export function Select(props: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return <select {...props} className={cx('select', props.className)} />;
}

export function Toggle({
  checked,
  onChange,
  label,
  hint,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: string;
  hint?: React.ReactNode;
}) {
  return (
    <button type="button" className={cx('toggle', checked && 'toggle-on')} onClick={() => onChange(!checked)}>
      <span className="toggle-text">
        <span className="field-label">{label}</span>
        {hint ? <span className="field-hint">{hint}</span> : null}
      </span>
      <span className="toggle-track">
        <span className="toggle-thumb" />
      </span>
    </button>
  );
}

export function Tabs({
  value,
  onChange,
  items,
}: {
  value: string;
  onChange: (value: string) => void;
  items: Array<{ key: string; label: string }>;
}) {
  return (
    <div className="tabs" role="tablist">
      {items.map((item) => (
        <button
          type="button"
          key={item.key}
          role="tab"
          aria-selected={item.key === value}
          className={cx('tab', item.key === value && 'tab-active')}
          onClick={() => onChange(item.key)}
        >
          {item.label}
        </button>
      ))}
    </div>
  );
}

export function Modal({
  open,
  title,
  subtitle,
  onClose,
  children,
  actions,
}: {
  open: boolean;
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  onClose: () => void;
  children: React.ReactNode;
  actions?: React.ReactNode;
}) {
  if (!open) return null;
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(event) => event.stopPropagation()}>
        <div className="modal-head">
          <div>
            <div className="modal-title">{title}</div>
            {subtitle ? <div className="modal-subtitle">{subtitle}</div> : null}
          </div>
          <button type="button" className="icon-button" onClick={onClose} aria-label="关闭">
            <X size={16} />
          </button>
        </div>
        <div className="modal-body">{children}</div>
        {actions ? <div className="modal-actions">{actions}</div> : null}
      </div>
    </div>
  );
}

export function CodeBlock({
  text,
  maxHeight = 320,
}: {
  text: string;
  maxHeight?: number;
}) {
  return (
    <pre className="code-block" style={{ maxHeight }}>
      {text}
    </pre>
  );
}

export function Skeleton() {
  return <div className="skeleton" />;
}
