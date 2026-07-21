import { useAppStore } from '../stores/appStore';
import {
  DEFAULT_THEME,
  applyThemeToCssVars,
  buildRuntimeTheme,
  normalizeNavItems,
  persistThemeMode,
  type BuiltinThemeMode,
} from '../theme/default';
import type { ThemeConfig } from '../types/theme';
import { convertFileSrc } from '@tauri-apps/api/core';

function resolveLogoUrl(value?: string): string | undefined {
  if (!value) return undefined;
  if (/^(data:|blob:|https?:|asset:|tauri:)/i.test(value)) return value;
  try {
    return convertFileSrc(value);
  } catch {
    return value;
  }
}

export function useTheme() {
  const {
    themeConfig,
    setThemeConfig,
    themeMode,
    setThemeMode,
    navItems,
    setNavItems,
  } = useAppStore();

  const current = themeConfig ?? DEFAULT_THEME;
  const currentNavItems = normalizeNavItems(navItems);

  const applyTheme = (config: ThemeConfig) => {
    const runtimeTheme = buildRuntimeTheme(config, themeMode);
    setThemeConfig(runtimeTheme);
    setNavItems(normalizeNavItems(runtimeTheme.navItems));
    applyThemeToCssVars(runtimeTheme);
  };

  const switchThemeMode = (mode: BuiltinThemeMode) => {
    persistThemeMode(mode);
    setThemeMode(mode);
    const runtimeTheme = buildRuntimeTheme(current, mode);
    setThemeConfig(runtimeTheme);
    setNavItems(normalizeNavItems(runtimeTheme.navItems));
    applyThemeToCssVars(runtimeTheme);
  };

  const toggleTheme = () => {
    switchThemeMode(themeMode === 'dark' ? 'light' : 'dark');
  };

  const resetTheme = () => {
    switchThemeMode('light');
  };

  return {
    theme: current,
    navItems: currentNavItems,
    themeMode,
    isCustom: false,
    brandName: current.brand.name,
    brandSubtitle: current.brand.subtitle,
    logoUrl: resolveLogoUrl(current.brand.logoUrl || current.brand.logo),
    windowTitle: current.window?.title || `${current.brand.name} - ${current.brand.subtitle}`,
    applyTheme,
    resetTheme,
    switchThemeMode,
    toggleTheme,
  };
}
