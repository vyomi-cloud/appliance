import { defineConfig, devices } from '@playwright/test';

/**
 * Playwright config for cloudlearn-e2e.
 *
 *   ENDPOINT  — simulator base URL (default: http://192.168.252.7:9000)
 *   APP_HOST  — where the deployed app(s) listen (default: http://192.168.252.7)
 *
 * Specs live under tests/e2e/console-pass/. Each spec drives the simulator's
 * web console to provision resources, then asserts the app responds correctly.
 */
export default defineConfig({
  testDir: './console-pass',
  fullyParallel: false,   // resource-create sequences need ordering
  workers: 1,
  timeout: 5 * 60 * 1000, // wizard navigation + app boot can take a while
  expect: { timeout: 15000 },
  reporter: [['list'], ['html', { outputFolder: 'playwright-report', open: 'never' }]],
  use: {
    baseURL: process.env.ENDPOINT || 'http://192.168.252.7:9000',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    actionTimeout: 10000,
    navigationTimeout: 20000,
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
  ],
});
