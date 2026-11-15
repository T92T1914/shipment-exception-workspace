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
    // A recording of the automated run, switched on only for the demo artifact.
    ...(process.env.WORKSPACE_RECORD_DEMO ? { video: { mode: 'on' as const, size: { width: 1280, height: 889 } }, colorScheme: 'dark' as const } : {}),
    launchOptions: {
      ...(process.env.WORKSPACE_BROWSER_EXECUTABLE ? { executablePath: process.env.WORKSPACE_BROWSER_EXECUTABLE } : {}),
      args: ['--disable-gpu', '--renderer-process-limit=2', '--disable-background-networking'],
    },
  },
  reporter: [['list'], ['json', { outputFile: 'test-results/results.json' }]],
});
