export function maskSecret(value: string, visibleTail = 4): string {
  const text = String(value || '').trim();
  if (!text) return '未配置';
  if (text.length <= visibleTail) return '****';
  return `${'*'.repeat(Math.max(4, text.length - visibleTail))}${text.slice(-visibleTail)}`;
}

export function formatBytes(size: number): string {
  if (!Number.isFinite(size) || size <= 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let value = size;
  let index = 0;
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024;
    index += 1;
  }
  return `${value.toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

export function formatDateTime(value?: string | number | null): string {
  if (value === null || value === undefined || value === '') return '未记录';
  const date = typeof value === 'number' ? new Date(value) : new Date(value);
  if (Number.isNaN(date.getTime())) return '未记录';
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  });
}

export function formatRelativeTime(value?: string | number | null): string {
  if (value === null || value === undefined || value === '') return '未记录';
  const date = typeof value === 'number' ? new Date(value) : new Date(value);
  if (Number.isNaN(date.getTime())) return '未记录';
  const diff = Date.now() - date.getTime();
  const abs = Math.abs(diff);
  const direction = diff >= 0 ? '前' : '后';
  if (abs < 60_000) return `${Math.max(1, Math.round(abs / 1000))} 秒${direction}`;
  if (abs < 3_600_000) return `${Math.round(abs / 60_000)} 分钟${direction}`;
  if (abs < 86_400_000) return `${Math.round(abs / 3_600_000)} 小时${direction}`;
  return `${Math.round(abs / 86_400_000)} 天${direction}`;
}

export function formatPercent(value?: number | null): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '0%';
  return `${Math.round(value)}%`;
}

export function joinCompact(values: Array<string | undefined | null>, separator = ' · '): string {
  return values.map((value) => String(value || '').trim()).filter(Boolean).join(separator);
}

export function pickText(...values: Array<unknown>): string {
  for (const value of values) {
    if (typeof value === 'string' && value.trim()) return value.trim();
  }
  return '';
}

export function toNumber(value: unknown, fallback = 0): number {
  const num = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(num) ? num : fallback;
}

export function toBool(value: unknown): boolean {
  if (typeof value === 'boolean') return value;
  if (typeof value === 'string') {
    const text = value.trim().toLowerCase();
    return ['1', 'true', 'yes', 'on', 'ok'].includes(text);
  }
  return Boolean(value);
}

export function cleanArray(value: unknown): string[] {
  return Array.isArray(value)
    ? value.map((item) => (typeof item === 'string' ? item.trim() : '')).filter(Boolean)
    : [];
}

export function toText(value: unknown, fallback = ''): string {
  return typeof value === 'string' ? value.trim() || fallback : fallback;
}

// Collapse the long machine-specific install-root prefix
// (e.g. "D:\OpenClaw-Online-v2.0.6 (4)\OpenClawFiles\...") down to
// "…\OpenClawFiles\..." so paths in the UI stay readable. Works on a bare path
// or on a sentence with paths embedded (e.g. diagnostics detail strings), and
// leaves genuine system paths (Program Files, registry) untouched.
export function shortenPaths(value?: string | null): string {
  return String(value || '')
    .replace(/[A-Za-z]:\\[^\\\n;]+\\OpenClawFiles/g, '…\\OpenClawFiles')
    .replace(/[A-Za-z]:\/[^/\n;]+\/OpenClawFiles/g, '…/OpenClawFiles');
}

