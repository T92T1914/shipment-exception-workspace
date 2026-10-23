import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 30_000,
  use: {
    baseURL: process.env.WORKSPACE_BASE_URL ?? 'http://127.0.0.1:8765',
    headless: true,
    trace: 'off',
    screenshot: 'only-on-failure',
    launchOptions: {
      ...(process.env.WORKSPACE_BROWSER_EXECUTABLE ? { executablePath: process.env.WORKSPACE_BROWSER_EXECUTABLE } : {}),
      args: ['--disable-gpu', '--renderer-process-limit=2', '--disable-background-networking'],
    },
  },
  reporter: [['list'], ['json', { outputFile: 'test-results/results.json' }]],
});
