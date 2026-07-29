import type { NavItem, ThemeConfig, ThemeElevation, ThemeMotion } from '../types/theme';
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

const BASE_MOTION: ThemeMotion = {
  fast: '150ms',
  standard: '200ms',
  deliberate: '300ms',
  ease_out: 'cubic-bezier(0.16, 1, 0.3, 1)',
  ease_in_out: 'cubic-bezier(0.65, 0, 0.35, 1)',
};

const LIGHT_ELEVATION: ThemeElevation = {
  low: '0 1px 2px rgba(13, 31, 25, 0.08)',
  medium: '0 12px 32px rgba(13, 31, 25, 0.12)',
  high: '0 28px 80px rgba(3, 18, 24, 0.22)',
};

const DARK_ELEVATION: ThemeElevation = {
  low: '0 1px 2px rgba(0, 0, 0, 0.28)',
  medium: '0 16px 38px rgba(0, 0, 0, 0.34)',
  high: '0 30px 88px rgba(0, 0, 0, 0.52)',
};

export const DEFAULT_NAV_ITEMS: NavItem[] = DEFAULT_FEATURE_NAV_ITEMS;

export const LIGHT_THEME: ThemeConfig = {
  name: `${APP_DISPLAY_NAME} Light`,
  colors: {
    app_bg: '#F3F5F4',
    sidebar_bg: '#071B24',
    surface: '#FFFFFF',
    surface_alt: '#EEF2F0',
    surface_deep: '#0B2930',
    surface_deeper: '#04151B',
    hover: '#E4EAE7',
    input: '#F8FAF9',
    border: '#D6DEDA',
    border_strong: '#91AAA0',
    text: '#17211D',
    text_muted: '#50605A',
    text_subtle: '#687770',
    accent: '#0B5A48',
    accent_hover: '#084839',
    accent_soft: '#E3F1EC',
    accent_ink: '#FFFFFF',
    info: '#1769A6',
    info_soft: '#EAF3FA',
    info_border: '#9BC6E4',
    info_ink: '#0B426C',
    success: '#117A5A',
    success_soft: '#E7F4EF',
    success_border: '#93CDB8',
    success_ink: '#0A503C',
    warning: '#956200',
    warning_soft: '#FFF4D3',
    warning_border: '#E2C56E',
    warning_ink: '#624000',
    danger: '#B43A4D',
    danger_hover: '#963040',
    danger_soft: '#FCECEF',
    danger_border: '#E6A5AF',
    danger_ink: '#7B2634',
    focus: '#147BC1',
    focus_soft: '#DCEFFA',
    selected: '#DCEDE7',
    selected_hover: '#CBE3DA',
    selected_ink: '#084839',
    disabled: '#E4E9E6',
    disabled_text: '#5E6B65',
    overlay: 'rgba(3, 18, 24, 0.64)',
    terminal_bg: '#061017',
    terminal_header: '#0B1D27',
    terminal_text: '#37E6D0',
    terminal_label: '#E2E8F0',
    terminal_label_muted: '#94A3B8',
    terminal_selection: '#1E3A5F',
  },
  elevation: LIGHT_ELEVATION,
  motion: BASE_MOTION,
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
    accent_soft: '#173B31',
    accent_ink: '#061017',
    info: '#65B8F3',
    info_soft: '#183548',
    info_border: '#336989',
    info_ink: '#C5E8FF',
    success: '#37D5A3',
    success_soft: '#173B31',
    success_border: '#2F765F',
    success_ink: '#B9F4DF',
    warning: '#F1C75B',
    warning_soft: '#3A3119',
    warning_border: '#755F29',
    warning_ink: '#FFE9A3',
    danger: '#F05B72',
    danger_hover: '#FF7588',
    danger_soft: '#442029',
    danger_border: '#843949',
    danger_ink: '#FFD2D9',
    focus: '#73C7FF',
    focus_soft: '#18384B',
    selected: '#193D34',
    selected_hover: '#225044',
    selected_ink: '#C9F6E5',
    disabled: '#253235',
    disabled_text: '#91A19B',
    overlay: 'rgba(0, 8, 12, 0.74)',
    terminal_bg: '#030B10',
    terminal_header: '#081923',
    terminal_text: '#37E6D0',
    terminal_label: '#E2E8F0',
    terminal_label_muted: '#94A3B8',
    terminal_selection: '#1E3A5F',
  },
  elevation: DARK_ELEVATION,
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
    elevation: palette.elevation,
    motion: palette.motion,
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
  info: '--color-info',
  info_soft: '--color-info-soft',
  info_border: '--color-info-border',
  info_ink: '--color-info-ink',
  success: '--color-success',
  success_soft: '--color-success-soft',
  success_border: '--color-success-border',
  success_ink: '--color-success-ink',
  warning: '--color-warning',
  warning_soft: '--color-warning-soft',
  warning_border: '--color-warning-border',
  warning_ink: '--color-warning-ink',
  danger: '--color-danger',
  danger_hover: '--color-danger-hover',
  danger_soft: '--color-danger-soft',
  danger_border: '--color-danger-border',
  danger_ink: '--color-danger-ink',
  focus: '--color-focus',
  focus_soft: '--color-focus-soft',
  selected: '--color-selected',
  selected_hover: '--color-selected-hover',
  selected_ink: '--color-selected-ink',
  disabled: '--color-disabled',
  disabled_text: '--color-disabled-text',
  overlay: '--color-overlay',
  terminal_bg: '--color-terminal-bg',
  terminal_header: '--color-terminal-header',
  terminal_text: '--color-terminal-text',
  terminal_label: '--color-terminal-label',
  terminal_label_muted: '--color-terminal-label-muted',
  terminal_selection: '--color-terminal-selection',
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
  const elevation = { ...LIGHT_ELEVATION, ...(theme.elevation ?? {}) };
  root.style.setProperty('--elevation-low', elevation.low);
  root.style.setProperty('--elevation-medium', elevation.medium);
  root.style.setProperty('--elevation-high', elevation.high);
  const motion = { ...BASE_MOTION, ...(theme.motion ?? {}) };
  root.style.setProperty('--motion-fast', motion.fast);
  root.style.setProperty('--motion-standard', motion.standard);
  root.style.setProperty('--motion-deliberate', motion.deliberate);
  root.style.setProperty('--ease-out', motion.ease_out);
  root.style.setProperty('--ease-in-out', motion.ease_in_out);
}

export function bootstrapThemeFromStorage(): void {
  if (typeof document === 'undefined') return;
  const mode = getStoredThemeMode();
  applyThemeModeMeta(mode);
  applyThemeToCssVars(getBuiltinTheme(mode));
}
