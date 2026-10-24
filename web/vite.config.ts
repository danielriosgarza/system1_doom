import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// `base: './'` keeps every URL relative, so the same build works on GitHub Pages and from a local folder.
export default defineConfig({
  base: './',
  plugins: [react()],
  // Live mode: `python -m system1_doom.serve` answers these, so `npm run dev` shows the stream without a build.
  server: {
    proxy: {
      '/live': 'http://127.0.0.1:8765',
      '^/episodes/live-': 'http://127.0.0.1:8765',
    },
  },
  // `vite preview` is the static build, as GitHub Pages serves it: no live mode, whatever runs on 8765.
  preview: { proxy: {} },
  test: {
    include: ['src/**/*.test.ts'],
    environment: 'node',
  },
})
