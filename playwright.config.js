import { defineConfig, devices } from '@playwright/test';

const baseURL = process.env.MIRROR_E2E_FRONTEND_URL || 'http://127.0.0.1:5501';

export default defineConfig({
  testDir: './browser-tests',
  fullyParallel: false,
  retries: 0,
  reporter: [['list'], ['html', { outputFolder: 'playwright-report', open: 'never' }]],
  outputDir: 'test-results/browser',
  use: {
    ...devices['Desktop Chrome'],
    baseURL,
    headless: true,
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
    video: 'retain-on-failure',
  },
});
