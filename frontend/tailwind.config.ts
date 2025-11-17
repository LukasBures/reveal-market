import type { Config } from 'tailwindcss';

const config: Config = {
  content: ['./app/**/*.{ts,tsx}', './components/**/*.{ts,tsx}', './lib/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        brand: {
          50: '#eef2ff',
          100: '#dde4ff',
          200: '#bbc6ff',
          300: '#94a3ff',
          400: '#6376f4',
          500: '#3c4fe4',
          600: '#2433c0',
          700: '#172492',
          800: '#10196a',
          900: '#070e41',
        },
        accent: {
          300: '#bdfd9f',
          400: '#7bf05e',
          500: '#4bc836',
        },
        midnight: {
          500: '#020c4c',
          600: '#01062b',
        },
      },
      boxShadow: {
        'glow-brand': '0 0 45px rgba(12, 39, 177, 0.45)',
      },
    },
  },
  plugins: [],
};

export default config;
