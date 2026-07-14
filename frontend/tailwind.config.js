/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        'canvas-bg': 'var(--color-canvas-bg)',
        'panel-bg': 'var(--color-panel-bg)',
        'panel-hover': 'var(--color-panel-hover)',
        'panel-border': 'var(--color-panel-border)',
        'accent': 'var(--color-accent)',
        'accent-glow': 'var(--color-accent-glow)',
        'success': 'var(--color-success)',
        'warning': 'var(--color-warning)',
        'error': 'var(--color-error)',
        'theme-bg': 'var(--color-canvas-bg)',
        'theme-text': 'var(--color-text-main)',
        'theme-card': 'var(--color-panel-bg)',
        'theme-border': 'var(--color-panel-border)',
        'theme-input': 'var(--color-input-bg)',
        'cyan': '#22d3ee',
        'node-pending': '#6b7280',
        'node-processing': '#3b82f6',
        'node-success': '#10b981',
        'node-failed': '#ef4444',
      },
      fontFamily: {
        mono: ['"JetBrains Mono"', '"Fira Code"', 'Consolas', 'monospace'],
        sans: ['"LXGW WenKai"', '"Noto Sans SC"', '"Segoe UI"', 'sans-serif'],
      },
      boxShadow: {
        'soft': '0 4px 20px -2px rgba(0, 0, 0, 0.08)',
        'soft-lg': '0 8px 32px -4px rgba(0, 0, 0, 0.12)',
        'glow': '0 0 20px rgba(13, 148, 136, 0.25)',
      },
      borderRadius: {
        '2xl': '1rem',
        '3xl': '1.5rem',
      },
      animation: {
        'pulse-glow': 'pulse-glow 2s ease-in-out infinite',
        'flow': 'flow 1.5s linear infinite',
        'fade-in': 'fade-in 0.3s ease-out',
        'slide-in': 'slide-in 0.2s ease-out',
        'float': 'float 3s ease-in-out infinite',
        'fade-up': 'fade-up 0.35s ease-out',
      },
      keyframes: {
        'pulse-glow': {
          '0%, 100%': { boxShadow: '0 0 5px rgba(13, 148, 136, 0.35)' },
          '50%': { boxShadow: '0 0 20px rgba(20, 184, 166, 0.55), 0 0 30px rgba(20, 184, 166, 0.25)' },
        },
        'flow': {
          '0%': { strokeDashoffset: '20' },
          '100%': { strokeDashoffset: '0' },
        },
        'fade-in': {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        'slide-in': {
          '0%': { transform: 'translateX(10px)', opacity: '0' },
          '100%': { transform: 'translateX(0)', opacity: '1' },
        },
        'float': {
          '0%, 100%': { transform: 'translateY(0)' },
          '50%': { transform: 'translateY(-8px)' },
        },
        'fade-up': {
          '0%': { opacity: '0', transform: 'translateY(12px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
      },
    },
  },
  plugins: [],
}
