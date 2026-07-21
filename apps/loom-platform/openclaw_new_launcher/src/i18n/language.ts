export type AppLanguage = 'zh-CN' | 'en-US';

export const APP_LANGUAGE_STORAGE_KEY = 'loom_language_v1';

export function applyAppLanguage(language: AppLanguage): void {
  if (typeof document === 'undefined') return;
  document.documentElement.lang = language;
  document.documentElement.dataset.language = language;
}

export function getStoredAppLanguage(): AppLanguage {
  if (typeof window === 'undefined') return 'zh-CN';
  try {
    const next = window.localStorage.getItem(APP_LANGUAGE_STORAGE_KEY);
    if (next === 'zh-CN' || next === 'en-US') return next;
  } catch {
    // ignore storage failures
  }
  return 'zh-CN';
}

export function persistAppLanguage(language: AppLanguage): void {
  if (typeof window !== 'undefined') {
    try {
      window.localStorage.setItem(APP_LANGUAGE_STORAGE_KEY, language);
    } catch {
      // ignore storage failures
    }
  }
  applyAppLanguage(language);
}

export function bootstrapAppLanguageFromStorage(): void {
  applyAppLanguage(getStoredAppLanguage());
}
