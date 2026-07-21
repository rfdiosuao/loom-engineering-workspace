import type { AccountSnapshot, DiagnosticReport } from './api';

export const STARTUP_CACHE_TTL_MS = 24 * 60 * 60 * 1000;
export const PREFLIGHT_NON_OK_CACHE_TTL_MS = STARTUP_CACHE_TTL_MS;
export const LOOM_PREFLIGHT_CACHE_KEY = 'loom.startup.preflight.v1';
export const LOOM_ACCOUNT_CACHE_KEY = 'loom.startup.account.v1';

type CacheEnvelope<T> = {
  schema: 'loom.startup-cache.v1';
  savedAt: number;
  data: T;
};

function getStorage(): Storage | null {
  if (typeof window === 'undefined') return null;
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

function readCache<T>(key: string): T | null {
  return readCacheWithTtl<T>(key, STARTUP_CACHE_TTL_MS);
}

function readCacheWithTtl<T>(key: string, ttlMs: number): T | null {
  const storage = getStorage();
  if (!storage) return null;
  try {
    const raw = storage.getItem(key);
    if (!raw) return null;
    const envelope = JSON.parse(raw) as CacheEnvelope<T>;
    if (!envelope || envelope.schema !== 'loom.startup-cache.v1') return null;
    if (!Number.isFinite(envelope.savedAt) || Date.now() - envelope.savedAt > ttlMs) {
      storage.removeItem(key);
      return null;
    }
    return envelope.data || null;
  } catch {
    storage.removeItem(key);
    return null;
  }
}

function writeCache<T>(key: string, data: T | null): void {
  const storage = getStorage();
  if (!storage) return;
  try {
    if (!data) {
      storage.removeItem(key);
      return;
    }
    const envelope: CacheEnvelope<T> = {
      schema: 'loom.startup-cache.v1',
      savedAt: Date.now(),
      data,
    };
    storage.setItem(key, JSON.stringify(envelope));
  } catch {
    // Cache is only an optimization; ignore quota or privacy-mode failures.
  }
}

export function preflightCacheUsable(report: DiagnosticReport | null): boolean {
  if (!report) return false;
  const status = report.summary?.status;
  if (status === 'ok') return true;
  if ((status === 'warn' || status === 'fail') && Array.isArray(report.checks) && report.checks.length > 0) return true;
  return Array.isArray(report.checks) && report.checks.length > 0;
}

export function loadCachedPreflight(): DiagnosticReport | null {
  const quickReport = readCacheWithTtl<DiagnosticReport>(LOOM_PREFLIGHT_CACHE_KEY, PREFLIGHT_NON_OK_CACHE_TTL_MS);
  if (quickReport?.summary?.status && quickReport.summary.status !== 'ok') {
    return preflightCacheUsable(quickReport) ? quickReport : null;
  }
  const report = readCache<DiagnosticReport>(LOOM_PREFLIGHT_CACHE_KEY);
  return preflightCacheUsable(report) ? report : null;
}

export function saveCachedPreflight(report: DiagnosticReport | null): void {
  writeCache(LOOM_PREFLIGHT_CACHE_KEY, preflightCacheUsable(report) ? report : null);
}

export function accountCacheUsable(account: AccountSnapshot | null): boolean {
  return Boolean(account?.loggedIn);
}

export function sanitizeAccountForCache(account: AccountSnapshot): AccountSnapshot {
  const safe: AccountSnapshot = {
    ...account,
    offline: true,
    stale: true,
  };
  delete safe.tokenMasked;
  delete safe.baseUrl;
  delete safe.gatewayBaseUrl;
  delete safe.syncResults;
  if (safe.subscription) {
    safe.subscription = {
      ...safe.subscription,
      offline: true,
      stale: true,
    };
  }
  return safe;
}

export function loadCachedAccount(): AccountSnapshot | null {
  const account = readCache<AccountSnapshot>(LOOM_ACCOUNT_CACHE_KEY);
  return accountCacheUsable(account) ? account : null;
}

export function saveCachedAccount(account: AccountSnapshot | null): void {
  writeCache(LOOM_ACCOUNT_CACHE_KEY, accountCacheUsable(account) ? sanitizeAccountForCache(account as AccountSnapshot) : null);
}
