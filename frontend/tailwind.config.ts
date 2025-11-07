import type { Config } from 'tailwindcss';

const config: Config = {
  content: ['./app/**/*.{ts,tsx}', './components/**/*.{ts,tsx}', './lib/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        brand: {
          50: '#f2f6ff',
          100: '#dbe6ff',
          200: '#bccfff',
          300: '#93b0ff',
          400: '#6a8bff',
          500: '#3b5cff',
          600: '#2a3ed1',
          700: '#1d2c9f',
          800: '#141f70',
          900: '#0c1346',
        },
      },
      boxShadow: {
        'glow-brand': '0 0 45px rgba(59, 92, 255, 0.35)',
      },
    },
  },
  plugins: [],
};

export default config;
