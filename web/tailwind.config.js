/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // Professional indigo accent
        primary: {
          50: '#eef2ff',
          100: '#e0e7ff',
          200: '#c7d2fe',
          300: '#a5b4fc',
          400: '#818cf8',
          500: '#6366f1',
          600: '#4f46e5',
          700: '#4338ca',
          800: '#3730a3',
          900: '#312e81',
          950: '#1e1b4b',
        },
        // Dark theme surfaces
        surface: {
          50: '#f8fafc',
          100: '#f1f5f9',
          200: '#e2e8f0',
          300: '#cbd5e1',
          400: '#94a3b8',
          500: '#64748b',
          600: '#475569',
          700: '#334155',
          800: '#1e293b',
          900: '#0f172a',
          950: '#020617',
        },
      },
      boxShadow: {
        'glow': '0 0 20px rgba(99, 102, 241, 0.15)',
        'glow-lg': '0 0 40px rgba(99, 102, 241, 0.2)',
      },
      backdropBlur: {
        xs: '2px',
      },
      typography: {
        invert: {
          css: {
            '--tw-prose-body': 'rgb(226 232 240)',
            '--tw-prose-headings': 'rgb(241 245 249)',
            '--tw-prose-links': 'rgb(129 140 248)',
            '--tw-prose-bold': 'rgb(241 245 249)',
            '--tw-prose-code': 'rgb(241 245 249)',
            '--tw-prose-pre-bg': 'rgb(30 41 59)',
            '--tw-prose-pre-code': 'rgb(226 232 240)',
            '--tw-prose-quotes': 'rgb(203 213 225)',
            '--tw-prose-quote-borders': 'rgb(99 102 241)',
            '--tw-prose-bullets': 'rgb(148 163 184)',
            '--tw-prose-counters': 'rgb(148 163 184)',
            '--tw-prose-hr': 'rgb(51 65 85)',
          },
        },
      },
    },
  },
  plugins: [
    require('@tailwindcss/typography'),
  ],
}
