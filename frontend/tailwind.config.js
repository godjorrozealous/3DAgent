/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{vue,js}'],
  theme: {
    extend: {
      fontFamily: {
        mono: ['"JetBrains Mono"', 'Menlo', 'Consolas', 'monospace'],
      },
      colors: {
        cyber: {
          bg: '#030712',
          panel: 'rgba(8, 20, 38, 0.72)',
          cyan: '#22d3ee',
          amber: '#fbbf24',
          green: '#34d399',
          red: '#f87171',
        },
      },
    },
  },
  plugins: [],
}
