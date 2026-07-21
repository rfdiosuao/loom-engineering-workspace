import React, { useCallback, useEffect, useRef } from 'react';
import {
  DEFAULT_THEME,
  applyThemeModeMeta,
  applyThemeToCssVars,
  buildRuntimeTheme,
  normalizeNavItems,
} from '../theme/default';
import { useAppStore } from '../stores/appStore';
import { themeApi } from '../services/api';
import type { ThemeConfig } from '../types/theme';

const applyThemeToDOM = applyThemeToCssVars;

export { applyThemeToDOM };

export const ThemeProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { setThemeConfig, setNavItems, themeMode } = useAppStore();
  const loadedRef = useRef(false);
  const sourceThemeRef = useRef<ThemeConfig>(DEFAULT_THEME);

  const applyModeTheme = useCallback((sourceTheme: ThemeConfig) => {
    const mode = useAppStore.getState().themeMode;
    const runtimeTheme = buildRuntimeTheme(sourceTheme, mode);
    setThemeConfig(runtimeTheme);
    setNavItems(normalizeNavItems(runtimeTheme.navItems));
    applyThemeToDOM(runtimeTheme);
  }, [setThemeConfig, setNavItems]);

  const loadTheme = useCallback(async () => {
    try {
      const resp = await themeApi.current();
      sourceThemeRef.current = resp.theme ?? DEFAULT_THEME;
    } catch {
      sourceThemeRef.current = DEFAULT_THEME;
    }
    applyModeTheme(sourceThemeRef.current);
  }, [applyModeTheme]);

  useEffect(() => {
    if (!loadedRef.current) {
      loadedRef.current = true;
      loadTheme();
    }
  }, [loadTheme]);

  useEffect(() => {
    if (loadedRef.current) {
      applyThemeModeMeta(themeMode);
      applyModeTheme(sourceThemeRef.current);
    }
  }, [themeMode, applyModeTheme]);

  useEffect(() => {
    if (themeMode !== 'system' || typeof window === 'undefined' || typeof window.matchMedia !== 'function') return;
    const media = window.matchMedia('(prefers-color-scheme: dark)');
    const handleSystemThemeChange = () => {
      applyThemeModeMeta(themeMode);
      applyModeTheme(sourceThemeRef.current);
    };
    if (typeof media.addEventListener === 'function') {
      media.addEventListener('change', handleSystemThemeChange);
      return () => media.removeEventListener('change', handleSystemThemeChange);
    }
    media.addListener(handleSystemThemeChange);
    return () => media.removeListener(handleSystemThemeChange);
  }, [themeMode, applyModeTheme]);

  (window as any).__reloadTheme = loadTheme;

  return <>{children}</>;
};
