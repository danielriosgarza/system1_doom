import { defineConfig } from '@playwright/test'

// The browser tests run against the production build. Port 4173 serves it the way GitHub Pages would, with the
// shipped recordings; 4175 serves it with the fixture recording (e2e/fixtures, played by the fake d1-ultra);
// 4174 adds a replayed live mode on top of the fixture (e2e/live-server.mjs).
export const RECORDINGS = 'http://127.0.0.1:4173/'
export const FIXTURE = 'http://127.0.0.1:4175/'
export const LIVE = 'http://127.0.0.1:4174/'

export default defineConfig({
  testDir: 'e2e',
  timeout: 30_000,
  use: { baseURL: FIXTURE, viewport: { width: 1280, height: 900 } },
  webServer: [
    {
      command: 'npm run build && npx vite preview --host 127.0.0.1 --port 4173 --strictPort',
      url: RECORDINGS,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
    {
      command: 'node e2e/live-server.mjs',
      env: { PORT: '4175', LIVE: '0' },
      url: `${FIXTURE}episodes/index.json`,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
    {
      command: 'node e2e/live-server.mjs',
      env: { PORT: '4174', LIVE: '1' },
      url: `${LIVE}live/status.json`,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
  ],
})
