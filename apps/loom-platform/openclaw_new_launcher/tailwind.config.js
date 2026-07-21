/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        accent: { DEFAULT: 'var(--color-accent)', hover: 'var(--color-accent-hover)', soft: 'var(--color-accent-soft)', ink: 'var(--color-accent-ink)' },
        surface: { DEFAULT: 'var(--color-surface)', alt: 'var(--color-surface-alt)', deep: 'var(--color-surface-deep)', deeper: 'var(--color-surface-deeper)' },
        text: { DEFAULT: 'var(--color-text)', muted: 'var(--color-text-muted)', subtle: 'var(--color-text-subtle)' },
        status: { success: 'var(--color-success)', warning: 'var(--color-warning)', danger: 'var(--color-danger)' },
        terminal: { bg: 'var(--color-terminal-bg)', header: 'var(--color-terminal-header)', text: 'var(--color-terminal-text)', label: '#E2E8F0', labelMuted: '#94A3B8', selection: '#1E3A5F' },
        app: { bg: 'var(--color-app-bg)', sidebar: 'var(--color-sidebar-bg)' },
        border: { DEFAULT: 'var(--color-border)', strong: 'var(--color-border-strong)' },
        hover: 'var(--color-hover)',
        input: 'var(--color-input)',
      },
      fontFamily: {
        sans: ['var(--font-display)', 'system-ui', 'sans-serif'],
        mono: ['var(--font-mono)', 'monospace'],
      },
    },
  },
  plugins: [],
};
