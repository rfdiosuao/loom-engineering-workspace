import type { NavItem, ThemeConfig } from '../types/theme';
import { DEFAULT_FEATURE_NAV_ITEMS, normalizeFeatureNavItems } from '../features/registry';

type ThemeColors = ThemeConfig['colors'];

export type BuiltinThemeMode = 'light' | 'dark';

export const THEME_MODE_STORAGE_KEY = 'lumi_theme_mode';

const BASE_FONTS: ThemeConfig['fonts'] = {
  display: ['Microsoft YaHei UI', 21, 'bold'],
  title: ['Microsoft YaHei UI', 14, 'bold'],
  section: ['Microsoft YaHei UI', 10, 'bold'],
  body: ['Microsoft YaHei UI', 10, 'normal'],
  small: ['Microsoft YaHei UI', 9, 'normal'],
  mono: ['Cascadia Mono', 10, 'normal'],
};

export const DEFAULT_NAV_ITEMS: NavItem[] = DEFAULT_FEATURE_NAV_ITEMS;

export const LIGHT_THEME: ThemeConfig = {
  name: 'OpenClaw Porcelain Theme',
  colors: {
    app_bg: '#F6F3EC',
    sidebar_bg: '#FBF8F0',
    surface: '#FFFCF5',
    surface_alt: '#F4EFE4',
    surface_deep: '#24211B',
    surface_deeper: '#14110D',
    hover: '#EEE5D5',
    input: '#FFF9EF',
    border: 'rgba(151, 119, 58, 0.22)',
    border_strong: 'rgba(187, 146, 68, 0.48)',
    text: '#201B12',
    text_muted: '#756B5B',
    text_subtle: '#A59A88',
    accent: '#B98936',
    accent_hover: '#D6A64A',
    accent_soft: 'rgba(214, 180, 106, 0.18)',
    accent_ink: '#6E4D12',
    success: '#0F9F6E',
    warning: '#D88915',
    danger: '#E54764',
    danger_hover: '#FF5E78',
    terminal_bg: '#0A0C12',
    terminal_header: '#111827',
    terminal_text: '#37E6D0',
  },
  fonts: BASE_FONTS,
  brand: {
    name: 'OpenClaw',
    subtitle: 'AI Creative Console',
    app_user_model_id: 'OpenClaw.Launcher',
    terminal_header: 'OpenClaw Console',
    logoUrl: 'logo.png',
  },
  navItems: DEFAULT_NAV_ITEMS,
  window: {
    title: 'OpenClaw - AI Creative Console',
    width: 1200,
    height: 800,
  },
};

export const DARK_THEME: ThemeConfig = {
  ...LIGHT_THEME,
  name: 'OpenClaw Obsidian Gold',
  colors: {
    app_bg: '#07080D',
    sidebar_bg: '#0A0C14',
    surface: '#0D0F18',
    surface_alt: '#111827',
    surface_deep: '#171D2B',
    surface_deeper: '#05070D',
    hover: '#1A1F2E',
    input: '#0B1020',
    border: 'rgba(214, 180, 106, 0.18)',
    border_strong: 'rgba(214, 180, 106, 0.48)',
    text: '#F7F1E3',
    text_muted: '#A9B2C3',
    text_subtle: '#63708A',
    accent: '#D6B46A',
    accent_hover: '#F2D48A',
    accent_soft: 'rgba(214, 180, 106, 0.12)',
    accent_ink: '#2B1D05',
    success: '#3FE08F',
    warning: '#FFB454',
    danger: '#FF4D6D',
    danger_hover: '#FF6E86',
    terminal_bg: '#05070D',
    terminal_header: '#0D1320',
    terminal_text: '#37E6D0',
  },
};

export const DEFAULT_THEME = DARK_THEME;

export function getStoredThemeMode(): BuiltinThemeMode {
  if (typeof window === 'undefined') return 'dark';
  try {
    return window.localStorage.getItem(THEME_MODE_STORAGE_KEY) === 'light' ? 'light' : 'dark';
  } catch {
    return 'dark';
  }
}

export function persistThemeMode(mode: BuiltinThemeMode): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(THEME_MODE_STORAGE_KEY, mode);
    document.documentElement.dataset.themeMode = mode;
    document.documentElement.style.colorScheme = mode;
  } catch {
    // ignore storage failures
  }
}

export function getBuiltinTheme(mode: BuiltinThemeMode): ThemeConfig {
  return mode === 'light' ? LIGHT_THEME : DARK_THEME;
}

export function normalizeNavItems(items?: NavItem[]): NavItem[] {
  return normalizeFeatureNavItems(items);
}

export function buildRuntimeTheme(baseTheme: ThemeConfig | null | undefined, mode: BuiltinThemeMode): ThemeConfig {
  const palette = getBuiltinTheme(mode);
  const brand = baseTheme?.brand ? { ...palette.brand, ...baseTheme.brand } : palette.brand;
  const windowConfig = baseTheme?.window ? { ...palette.window, ...baseTheme.window } : palette.window;
  const modeColors = baseTheme?.modes?.[mode];
  const hasModeSpecificColors = Boolean(baseTheme?.modes?.light || baseTheme?.modes?.dark);
  const colors = {
    ...palette.colors,
    ...(modeColors ?? (hasModeSpecificColors ? {} : (mode === 'light' ? (baseTheme?.colors ?? {}) : {}))),
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
  document.documentElement.dataset.themeMode = mode;
  document.documentElement.style.colorScheme = mode;
  applyThemeToCssVars(getBuiltinTheme(mode));
}
