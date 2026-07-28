/** @type {import('tailwindcss').Config} */
const colorToken = (name) => ({ opacityValue }) => {
  const value = `var(--color-${name})`;
  const opacity = Number(opacityValue);
  if (opacityValue === undefined || !Number.isFinite(opacity)) return value;
  return `color-mix(in srgb, ${value} ${opacity * 100}%, transparent)`;
};

export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        accent: { DEFAULT: colorToken('accent'), hover: colorToken('accent-hover'), soft: colorToken('accent-soft'), ink: colorToken('accent-ink') },
        surface: { DEFAULT: colorToken('surface'), alt: colorToken('surface-alt'), deep: colorToken('surface-deep'), deeper: colorToken('surface-deeper') },
        text: { DEFAULT: colorToken('text'), muted: colorToken('text-muted'), subtle: colorToken('text-subtle') },
        info: { DEFAULT: colorToken('info'), soft: colorToken('info-soft'), ink: colorToken('info-ink') },
        status: {
          success: { DEFAULT: colorToken('success'), soft: colorToken('success-soft'), ink: colorToken('success-ink') },
          warning: { DEFAULT: colorToken('warning'), soft: colorToken('warning-soft'), ink: colorToken('warning-ink') },
          danger: { DEFAULT: colorToken('danger'), hover: colorToken('danger-hover'), soft: colorToken('danger-soft'), ink: colorToken('danger-ink') },
        },
        focus: { DEFAULT: colorToken('focus'), soft: colorToken('focus-soft') },
        selected: { DEFAULT: colorToken('selected'), hover: colorToken('selected-hover'), ink: colorToken('selected-ink') },
        disabled: colorToken('disabled'),
        overlay: colorToken('overlay'),
        terminal: {
          bg: colorToken('terminal-bg'),
          header: colorToken('terminal-header'),
          text: colorToken('terminal-text'),
          label: colorToken('terminal-label'),
          labelMuted: colorToken('terminal-label-muted'),
          selection: colorToken('terminal-selection'),
        },
        app: { bg: colorToken('app-bg'), sidebar: colorToken('sidebar-bg') },
        border: { DEFAULT: colorToken('border'), strong: colorToken('border-strong') },
        hover: colorToken('hover'),
        input: colorToken('input'),
      },
      borderColor: {
        info: colorToken('info-border'),
        'status-success': colorToken('success-border'),
        'status-warning': colorToken('warning-border'),
        'status-danger': colorToken('danger-border'),
      },
      textColor: {
        disabled: colorToken('disabled-text'),
      },
      boxShadow: {
        'elevation-low': 'var(--elevation-low)',
        'elevation-medium': 'var(--elevation-medium)',
        'elevation-high': 'var(--elevation-high)',
      },
      transitionDuration: {
        fast: 'var(--motion-fast)',
        standard: 'var(--motion-standard)',
        deliberate: 'var(--motion-deliberate)',
      },
      fontFamily: {
        sans: ['var(--font-display)', 'system-ui', 'sans-serif'],
        mono: ['var(--font-mono)', 'monospace'],
      },
    },
  },
  plugins: [],
};
