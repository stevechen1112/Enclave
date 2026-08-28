/** P6 visual regression and core-shell performance budgets. */
import { expect, test, type Page } from '@playwright/test'

async function demoLogin(page: Page) {
  const response = await page.request.post('/api/v1/auth/login/demo', { data: { persona: 'admin' } })
  expect(response.ok(), await response.text()).toBe(true)
  const { access_token: token } = await response.json()
  await page.goto('/login')
  await page.evaluate(value => {
    window.localStorage.setItem('token', value)
    window.localStorage.setItem('enclave_readiness_dismissed_v1', '1')
  }, token)
}

test.use({ reducedMotion: 'reduce' })

test.describe('P6 visual regression', () => {
  test('public entry surfaces match desktop baselines', async ({ page }) => {
    await page.goto('/')
    await expect(page.getByRole('heading', { level: 1 })).toContainText('公司資料找得到')
    await expect(page).toHaveScreenshot('landing-desktop.png', { fullPage: true, animations: 'disabled', maxDiffPixelRatio: 0.01 })
    await page.goto('/login')
    await expect(page.getByRole('heading', { name: '登入企業知識平台' })).toBeVisible()
    await expect(page).toHaveScreenshot('login-desktop.png', { fullPage: true, animations: 'disabled', maxDiffPixelRatio: 0.01 })
  })

  test('mobile knowledge intake matches its responsive baseline', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    await demoLogin(page)
    await page.goto('/knowledge/new')
    await expect(page.getByRole('heading', { name: '新增知識' })).toBeVisible()
    await expect(page).toHaveScreenshot('knowledge-intake-mobile.png', { fullPage: true, animations: 'disabled', maxDiffPixelRatio: 0.01 })
  })
})

test('public shell stays within its performance budget', async ({ page }, testInfo) => {
  await page.goto('/', { waitUntil: 'load' })
  const metrics = await page.evaluate(() => {
    const navigation = performance.getEntriesByType('navigation')[0] as PerformanceNavigationTiming
    const resources = performance.getEntriesByType('resource') as PerformanceResourceTiming[]
    const jsResources = resources.filter(item => item.name.includes('.js'))
    return {
      domContentLoadedMs: navigation.domContentLoadedEventEnd - navigation.startTime,
      loadMs: navigation.loadEventEnd - navigation.startTime,
      transferBytes: resources.reduce((total, item) => total + item.transferSize, 0),
      largestJsTransferBytes: Math.max(0, ...jsResources.map(item => item.transferSize)),
      resourceCount: resources.length,
    }
  })
  await testInfo.attach('performance-budget.json', {
    body: JSON.stringify(metrics, null, 2),
    contentType: 'application/json',
  })
  expect(metrics.domContentLoadedMs).toBeLessThanOrEqual(3_000)
  expect(metrics.loadMs).toBeLessThanOrEqual(5_000)
  expect(metrics.transferBytes).toBeLessThanOrEqual(10 * 1024 * 1024)
  // Dev middleware serves uncompressed modules; production gzip is checked by
  // the build report and remains substantially smaller than this browser cap.
  expect(metrics.largestJsTransferBytes).toBeLessThanOrEqual(1_250 * 1024)
})
