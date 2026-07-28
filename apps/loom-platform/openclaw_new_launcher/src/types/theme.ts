export interface ThemeColors {
  app_bg: string;
  sidebar_bg: string;
  surface: string;
  surface_alt: string;
  surface_deep: string;
  surface_deeper: string;
  hover: string;
  input: string;
  border: string;
  border_strong: string;
  text: string;
  text_muted: string;
  text_subtle: string;
  accent: string;
  accent_hover: string;
  accent_soft: string;
  accent_ink: string;
  info: string;
  info_soft: string;
  info_border: string;
  info_ink: string;
  success: string;
  success_soft: string;
  success_border: string;
  success_ink: string;
  warning: string;
  warning_soft: string;
  warning_border: string;
  warning_ink: string;
  danger: string;
  danger_hover: string;
  danger_soft: string;
  danger_border: string;
  danger_ink: string;
  focus: string;
  focus_soft: string;
  selected: string;
  selected_hover: string;
  selected_ink: string;
  disabled: string;
  disabled_text: string;
  overlay: string;
  terminal_bg: string;
  terminal_header: string;
  terminal_text: string;
}

export type ThemeColorOverrides = Partial<ThemeColors>;

export interface ThemeElevation {
  low: string;
  medium: string;
  high: string;
}

export interface ThemeMotion {
  fast: string;
  standard: string;
  deliberate: string;
  ease_out: string;
  ease_in_out: string;
}

export interface ThemeFonts {
  display: [string, number, string];
  title: [string, number, string];
  section: [string, number, string];
  body: [string, number, string];
  small: [string, number, string];
  mono: [string, number, string];
}

export interface ThemeBrand {
  name: string;
  subtitle: string;
  app_user_model_id: string;
  terminal_header: string;
  logoUrl?: string;
  logo?: string;
}

export interface ThemeWindow {
  title: string;
  width: number;
  height: number;
}

export interface ThemeConfig {
  name: string;
  colors: ThemeColors;
  modes?: {
    light?: ThemeColorOverrides;
    dark?: ThemeColorOverrides;
  };
  elevation?: Partial<ThemeElevation>;
  motion?: Partial<ThemeMotion>;
  fonts: ThemeFonts;
  brand: ThemeBrand;
  navItems?: NavItem[];
  window?: ThemeWindow;
}

export interface NavItem {
  key: string;
  label: string;
  desc?: string;
  icon?: string;
  group: string;
  accent?: boolean;
}

export interface ThemePayload {
  theme: ThemeConfig;
  isCustom?: boolean;
  merchantId?: string | null;
}
