/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        abyss: '#0a0e1a',
        navy: '#111832',
        panel: '#161f3d',
        neon: {
          purple: '#8b5cf6',
          cyan: '#22d3ee',
          pink: '#e879f9',
        },
      },
      fontFamily: {
        display: ['"Space Grotesk"', 'system-ui', 'sans-serif'],
      },
      boxShadow: {
        glow: '0 0 24px rgba(139, 92, 246, 0.35)',
        card: '0 8px 32px rgba(2, 6, 23, 0.6)',
      },
      keyframes: {
        rise: {
          '0%': { opacity: '0', transform: 'translateY(12px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        pop: {
          '0%': { transform: 'scale(0.9)' },
          '60%': { transform: 'scale(1.04)' },
          '100%': { transform: 'scale(1)' },
        },
        pulseWin: {
          '0%, 100%': { boxShadow: '0 0 24px rgba(34, 211, 238, 0.5)' },
          '50%': { boxShadow: '0 0 48px rgba(34, 211, 238, 0.8)' },
        },
      },
      animation: {
        rise: 'rise 0.35s ease-out both',
        pop: 'pop 0.25s ease-out both',
        pulseWin: 'pulseWin 1.6s ease-in-out infinite',
      },
    },
  },
  plugins: [],
};
