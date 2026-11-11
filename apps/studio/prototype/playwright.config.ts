import { defineConfig } from '@playwright/test';
// The default is the long-running dev server. VERITX_STUDIO_URL lets a run use
// its own server (and therefore its own gateway) without disturbing another
// session's processes.
const baseURL = process.env.VERITX_STUDIO_URL ?? 'http://127.0.0.1:5174';
export default defineConfig({
  testDir: './tests', workers: 1, timeout: 30000,
  use: { baseURL, headless: true, launchOptions: { executablePath: '/usr/bin/google-chrome', args: ['--no-sandbox'] } },
  webServer: { command: 'npm run dev', url: baseURL, reuseExistingServer: true, timeout: 30000 },
});
