import typography from '@tailwindcss/typography'

/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        // ── Surfaces (deep navy-black AI Minimalism) ──────────
        background:                  '#07090f',
        surface:                     '#07090f',
        'surface-bright':            '#0c1020',
        'surface-dim':               '#050609',
        'surface-container-lowest':  '#050710',
        'surface-container-low':     '#0e1222',
        'surface-container':         '#131828',
        'surface-container-high':    '#181f32',
        'surface-container-highest': '#1d253c',
        'surface-variant':           '#141c2e',
        'surface-tint':              '#818cf8',

        // ── Text ────────────────────────────────────────────
        'on-background':       '#dde1f4',
        'on-surface':          '#dde1f4',
        'on-surface-variant':  '#7e88a4',

        // ── Primary — vivid indigo ───────────────────────────
        primary:                '#818cf8',
        'primary-dim':          '#5f6bd8',
        'on-primary':           '#0f1235',
        'primary-container':    '#1e2355',
        'on-primary-container': '#c0c8ff',
        'primary-fixed':        '#dae2fd',
        'primary-fixed-dim':    '#818cf8',
        'inverse-primary':      '#4050b8',
        'on-primary-fixed':     '#373f54',
        'on-primary-fixed-variant': '#535b71',

        // ── Secondary — emerald ──────────────────────────────
        secondary:                '#34d399',
        'secondary-dim':          '#1fa870',
        'on-secondary':           '#052e18',
        'secondary-container':    '#0a3d22',
        'on-secondary-container': '#6afac0',
        'secondary-fixed':        '#6ffbbe',
        'secondary-fixed-dim':    '#34d399',
        'on-secondary-fixed':     '#004930',
        'on-secondary-fixed-variant': '#006947',

        // ── Tertiary — amber ────────────────────────────────
        tertiary:                '#fbbf24',
        'tertiary-dim':          '#c99010',
        'on-tertiary':           '#1c1000',
        'tertiary-container':    '#3d2800',
        'on-tertiary-container': '#fde68a',
        'tertiary-fixed':        '#f8a010',
        'tertiary-fixed-dim':    '#e08c00',
        'on-tertiary-fixed':     '#2a1700',
        'on-tertiary-fixed-variant': '#563400',

        // ── Error — coral ────────────────────────────────────
        error:                   '#f87171',
        'error-dim':             '#c45252',
        'on-error':              '#1c0606',
        'error-container':       '#3d1010',
        'on-error-container':    '#ffb4ab',

        // ── Outlines / borders ───────────────────────────────
        outline:          '#1e2638',
        'outline-variant': '#131928',

        // ── Inverse ─────────────────────────────────────────
        'inverse-surface':    '#dde1f4',
        'inverse-on-surface': '#07090f',
      },

      borderRadius: {
        DEFAULT: '0.5rem',
        sm:   '0.375rem',
        lg:   '0.75rem',
        xl:   '1rem',
        '2xl':'1.5rem',
        full: '9999px',
      },

      fontFamily: {
        headline: ['Manrope', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        body:     ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        manrope:  ['Manrope', 'ui-sans-serif', 'system-ui', 'sans-serif'],
      },

      boxShadow: {
        'glow-primary': '0 0 24px oklch(68% 0.21 285 / 0.30), 0 2px 8px oklch(0% 0 0 / 0.40)',
        'glow-sm': '0 0 12px oklch(68% 0.21 285 / 0.20)',
        card: '0 1px 3px oklch(0% 0 0 / 0.35), 0 1px 1px oklch(0% 0 0 / 0.25)',
      },
    },
  },
  plugins: [typography],
}
