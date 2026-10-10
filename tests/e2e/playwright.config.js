// @ts-check
const { defineConfig, devices } = require('@playwright/test');

const fs = require('fs');
const path = require('path');
const REPO_ROOT = path.resolve(__dirname, '..', '..');

// This sandbox ships a pre-installed Chromium at a fixed path instead of the
// one `npx playwright install` would download. Use it only if it exists;
// otherwise let Playwright resolve its own browser (CI, other machines),
// after `npx playwright install chromium` has run.
const SANDBOX_CHROME = '/opt/pw-browsers/chromium-1194/chrome-linux/chrome';
const executablePath = process.env.CHROME_PATH
  || (fs.existsSync(SANDBOX_CHROME) ? SANDBOX_CHROME : undefined);

module.exports = defineConfig({
  testDir: '.',
  timeout: 30000,
  fullyParallel: false,
  workers: 1,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : [['list']],
  use: {
    baseURL: process.env.INZONE_BASE_URL || 'http://127.0.0.1:8080',
    ...(executablePath ? { launchOptions: { executablePath } } : {}),
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
  ],
  webServer: [
    {
      command: 'rm -f inzone.db && python3 -m uvicorn app:app --host 127.0.0.1 --port 8001',
      cwd: path.join(REPO_ROOT, 'backend'),
      url: 'http://127.0.0.1:8001/api/health',
      reuseExistingServer: false,
      timeout: 20000,
    },
    {
      command: 'python3 -m http.server 8080',
      cwd: REPO_ROOT,
      url: 'http://127.0.0.1:8080/inzone-espace-client.html',
      reuseExistingServer: false,
      timeout: 20000,
    },
  ],
});
