import { defineConfig } from '@playwright/test'

// Smoke tests run against the production build, served the way GitHub Pages would serve it. The live
// tests run against e2e/live-server.mjs, which serves the same build plus a replayed live mode.
export default defineConfig({
  testDir: 'e2e',
  timeout: 30_000,
  use: { baseURL: 'http://127.0.0.1:4173/', viewport: { width: 1280, height: 900 } },
  webServer: [
    {
      command: 'npm run build && npx vite preview --host 127.0.0.1 --port 4173 --strictPort',
      url: 'http://127.0.0.1:4173/',
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
    {
      command: 'node e2e/live-server.mjs',
      url: 'http://127.0.0.1:4174/live/status.json',
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
  ],
})
