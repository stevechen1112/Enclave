import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: 1,
  reporter: [
    ['html', { open: 'never' }],
    ['list'],
  ],
  snapshotPathTemplate: '{testDir}/{testFilePath}-snapshots/{arg}{ext}',
  use: {
    baseURL: process.env.E2E_BASE_URL || 'http://localhost:3001',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    locale: 'zh-TW',
    serviceWorkers: 'block',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
    {
      name: 'mobile-chromium',
      testMatch: /p6-device-media\.spec\.ts/,
      use: { ...devices['Pixel 7'] },
    },
    {
      name: 'iphone-chromium-emulation',
      testMatch: /p6-device-media\.spec\.ts/,
      use: { ...devices['iPhone 15'], browserName: 'chromium' },
    },
    {
      name: 'tablet-chromium',
      testMatch: /p6-device-media\.spec\.ts/,
      use: { ...devices['Galaxy Tab S9'] },
    },
  ],
  timeout: 60_000,
  expect: {
    timeout: 10_000,
  },
})
