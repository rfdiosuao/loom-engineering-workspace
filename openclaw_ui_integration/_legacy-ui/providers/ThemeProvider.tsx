import React, { useCallback, useEffect, useRef } from 'react';
import {
  DEFAULT_THEME,
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
      applyModeTheme(sourceThemeRef.current);
    }
  }, [themeMode, applyModeTheme]);

  (window as any).__reloadTheme = loadTheme;

  return <>{children}</>;
};
