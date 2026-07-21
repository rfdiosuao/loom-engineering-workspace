import type { NavItem, ThemeConfig } from '../types/theme';
import { DEFAULT_FEATURE_NAV_ITEMS, normalizeFeatureNavItems } from '../features/registry';
import { APP_DISPLAY_NAME, APP_DISPLAY_SUBTITLE } from '../version';

type ThemeColors = ThemeConfig['colors'];

export type BuiltinThemeMode = 'light' | 'dark' | 'system';

export const THEME_MODE_STORAGE_KEY = 'loom_theme_mode_v2';
const LEGACY_THEME_MODE_STORAGE_KEY = 'lumi_theme_mode';

const DISPLAY_FONT_STACK = '"HarmonyOS Sans SC", "MiSans", "Alibaba PuHuiTi", "Source Han Sans SC", "Microsoft YaHei UI", system-ui, sans-serif';

const BASE_FONTS: ThemeConfig['fonts'] = {
  display: [DISPLAY_FONT_STACK, 21, 'bold'],
  title: [DISPLAY_FONT_STACK, 14, 'bold'],
  section: [DISPLAY_FONT_STACK, 10, 'bold'],
  body: [DISPLAY_FONT_STACK, 10, 'normal'],
  small: [DISPLAY_FONT_STACK, 9, 'normal'],
  mono: ['Cascadia Mono', 10, 'normal'],
};

export const DEFAULT_NAV_ITEMS: NavItem[] = DEFAULT_FEATURE_NAV_ITEMS;

export const LIGHT_THEME: ThemeConfig = {
  name: `${APP_DISPLAY_NAME} Light`,
  colors: {
    app_bg: '#F4EFE5',
    sidebar_bg: '#071B24',
    surface: '#FFFDF7',
    surface_alt: '#EFE6D7',
    surface_deep: '#092633',
    surface_deeper: '#05141A',
    hover: '#E8DDCA',
    input: '#FFF9ED',
    border: 'rgba(8, 35, 48, 0.13)',
    border_strong: 'rgba(11, 74, 62, 0.42)',
    text: '#1B211E',
    text_muted: '#6B6357',
    text_subtle: '#766B5C',
    accent: '#0B4A3E',
    accent_hover: '#12604F',
    accent_soft: 'rgba(11, 74, 62, 0.14)',
    accent_ink: '#F5FFF9',
    success: '#0B8C6E',
    warning: '#4F705F',
    danger: '#C84B5F',
    danger_hover: '#DE5C70',
    terminal_bg: '#061017',
    terminal_header: '#0B1D27',
    terminal_text: '#37E6D0',
  },
  fonts: BASE_FONTS,
  brand: {
    name: APP_DISPLAY_NAME,
    subtitle: APP_DISPLAY_SUBTITLE,
    app_user_model_id: 'LOOM.Agent',
    terminal_header: `${APP_DISPLAY_NAME} 运行时`,
    logoUrl: '',
  },
  navItems: DEFAULT_NAV_ITEMS,
  window: {
    title: APP_DISPLAY_NAME,
    width: 1200,
    height: 800,
  },
};

export const DARK_THEME: ThemeConfig = {
  ...LIGHT_THEME,
  name: `${APP_DISPLAY_NAME} Dark`,
  colors: {
    app_bg: '#061017',
    sidebar_bg: '#05141A',
    surface: '#0A1820',
    surface_alt: '#10252D',
    surface_deep: '#132F3A',
    surface_deeper: '#030B10',
    hover: '#18323A',
    input: '#071820',
    border: 'rgba(55, 213, 163, 0.18)',
    border_strong: 'rgba(55, 213, 163, 0.42)',
    text: '#F8F1E2',
    text_muted: '#B7AD9A',
    text_subtle: '#A89E8B',
    accent: '#37D5A3',
    accent_hover: '#6EE7BF',
    accent_soft: 'rgba(55, 213, 163, 0.14)',
    accent_ink: '#061017',
    success: '#37D5A3',
    warning: '#77B79A',
    danger: '#F05B72',
    danger_hover: '#FF7588',
    terminal_bg: '#030B10',
    terminal_header: '#081923',
    terminal_text: '#37E6D0',
  },
};

export const DEFAULT_THEME = LIGHT_THEME;

export function getStoredThemeMode(): BuiltinThemeMode {
  if (typeof window === 'undefined') return 'light';
  try {
    const next = window.localStorage.getItem(THEME_MODE_STORAGE_KEY);
    if (next === 'light' || next === 'dark' || next === 'system') return next;
    window.localStorage.removeItem(LEGACY_THEME_MODE_STORAGE_KEY);
    window.localStorage.removeItem('loom_theme_mode');
    return 'light';
  } catch {
    return 'light';
  }
}

export function resolveThemeMode(mode: BuiltinThemeMode): 'light' | 'dark' {
  if (mode !== 'system') return mode;
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return 'light';
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

export function applyThemeModeMeta(mode: BuiltinThemeMode): void {
  if (typeof document === 'undefined') return;
  const resolvedMode = resolveThemeMode(mode);
  document.documentElement.dataset.themeMode = mode;
  document.documentElement.dataset.effectiveThemeMode = resolvedMode;
  document.documentElement.style.colorScheme = resolvedMode;
}

export function persistThemeMode(mode: BuiltinThemeMode): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(THEME_MODE_STORAGE_KEY, mode);
    window.localStorage.removeItem(LEGACY_THEME_MODE_STORAGE_KEY);
    applyThemeModeMeta(mode);
  } catch {
    // ignore storage failures
  }
}

export function getBuiltinTheme(requestedMode: BuiltinThemeMode): ThemeConfig {
  const mode = resolveThemeMode(requestedMode);
  return mode === 'dark' ? DARK_THEME : LIGHT_THEME;
}

export function normalizeNavItems(items?: NavItem[]): NavItem[] {
  return normalizeFeatureNavItems(items);
}

export function buildRuntimeTheme(baseTheme: ThemeConfig | null | undefined, mode: BuiltinThemeMode): ThemeConfig {
  const resolvedMode = resolveThemeMode(mode);
  const palette = resolvedMode === 'dark' ? DARK_THEME : LIGHT_THEME;
  const brand = baseTheme?.brand ? { ...palette.brand, ...baseTheme.brand } : palette.brand;
  const windowConfig = baseTheme?.window ? { ...palette.window, ...baseTheme.window } : palette.window;
  const modeColors = baseTheme?.modes?.[resolvedMode];
  const colors = {
    ...palette.colors,
    ...(modeColors ?? {}),
  };

  return {
    ...palette,
    name: baseTheme?.name ?? palette.name,
    colors,
    modes: baseTheme?.modes,
    brand,
    window: windowConfig,
    fonts: { ...palette.fonts, ...(baseTheme?.fonts ?? {}) },
    navItems: normalizeNavItems(baseTheme?.navItems),
  };
}

const CSS_VAR_MAP: Record<keyof ThemeColors, string> = {
  app_bg: '--color-app-bg',
  sidebar_bg: '--color-sidebar-bg',
  surface: '--color-surface',
  surface_alt: '--color-surface-alt',
  surface_deep: '--color-surface-deep',
  surface_deeper: '--color-surface-deeper',
  hover: '--color-hover',
  input: '--color-input',
  border: '--color-border',
  border_strong: '--color-border-strong',
  text: '--color-text',
  text_muted: '--color-text-muted',
  text_subtle: '--color-text-subtle',
  accent: '--color-accent',
  accent_hover: '--color-accent-hover',
  accent_soft: '--color-accent-soft',
  accent_ink: '--color-accent-ink',
  success: '--color-success',
  warning: '--color-warning',
  danger: '--color-danger',
  danger_hover: '--color-danger-hover',
  terminal_bg: '--color-terminal-bg',
  terminal_header: '--color-terminal-header',
  terminal_text: '--color-terminal-text',
};

export function applyThemeToCssVars(theme: ThemeConfig): void {
  const root = document.documentElement;
  const colors = theme.colors;
  for (const [key, cssVar] of Object.entries(CSS_VAR_MAP)) {
    const value = colors[key as keyof ThemeColors];
    if (value) {
      root.style.setProperty(cssVar, value);
    }
  }
  root.style.setProperty('--font-display', theme.fonts.display[0]);
  root.style.setProperty('--font-mono', theme.fonts.mono[0]);
  root.style.setProperty('--brand-name', theme.brand.name);
  root.style.setProperty('--brand-subtitle', theme.brand.subtitle);
}

export function bootstrapThemeFromStorage(): void {
  if (typeof document === 'undefined') return;
  const mode = getStoredThemeMode();
  applyThemeModeMeta(mode);
  applyThemeToCssVars(getBuiltinTheme(mode));
}
