/** P6 responsive device, capture entry, interruption and degraded-network acceptance. */
import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'

async function demoLogin(page: Page) {
  const response = await page.request.post('/api/v1/auth/login/demo', { data: { persona: 'admin' } })
  expect(response.ok(), await response.text()).toBe(true)
  const { access_token: token } = await response.json()
  await page.goto('/login')
  await page.evaluate(value => window.localStorage.setItem('token', value), token)
  await page.goto('/knowledge/new')
  await expect(page.getByRole('heading', { name: '新增知識' })).toBeVisible()
}

test.use({ reducedMotion: 'reduce' })

test.describe('P6 device and media intake', () => {
  test('responsive intake has no critical or serious accessibility violations', async ({ page }) => {
    await demoLogin(page)
    const result = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'])
      .analyze()
    expect(result.violations.filter(item => item.impact === 'critical' || item.impact === 'serious')).toEqual([])
  })

  test('responsive shell, capture inputs and queued media remain usable', async ({ page }) => {
    await demoLogin(page)
    const width = page.viewportSize()?.width || 1280

    if (width < 768) {
      const openMenu = page.getByRole('button', { name: '開啟選單' })
      await openMenu.click()
      const drawer = page.getByRole('dialog', { name: '行動版主要選單' })
      await expect(drawer).toBeVisible()
      await expect(drawer.getByRole('button', { name: '關閉選單' })).toBeFocused()
      await page.keyboard.press('Escape')
      await expect(drawer).toBeHidden()
      await expect(openMenu).toBeFocused()
    }

    const imageInput = page.locator('input[accept="image/*"]')
    const audioInput = page.locator('input[accept="audio/*"]')
    const videoInput = page.locator('input[accept="video/*"]')
    if (width < 640) {
      await expect(imageInput).toHaveAttribute('capture', 'environment')
      await expect(audioInput).toHaveAttribute('capture', '')
      await expect(videoInput).toHaveAttribute('capture', 'environment')
    }

    await page.getByLabel('選擇檔案').setInputFiles([
      { name: 'line-photo.png', mimeType: 'image/png', buffer: Buffer.from('synthetic-image') },
      { name: 'factory-noise.wav', mimeType: 'audio/wav', buffer: Buffer.from('synthetic-noise-audio') },
      { name: 'changeover.mp4', mimeType: 'video/mp4', buffer: Buffer.from('synthetic-video') },
    ])
    await expect(page.getByText('line-photo.png')).toBeVisible()
    await expect(page.getByText('factory-noise.wav')).toBeVisible()
    await expect(page.getByText('changeover.mp4')).toBeVisible()
    await expect(page.getByText(/此環境可處理/)).toBeVisible()
    await expect(page.getByRole('listitem').filter({ hasText: 'factory-noise.wav' })).toContainText(/語音轉寫|等待能力檢查/)
    await expect(page.getByRole('listitem').filter({ hasText: 'changeover.mp4' })).toContainText(/關鍵畫面|等待能力檢查/)
    await expect(page.getByRole('combobox', { name: '資料分類' })).toBeVisible()
    await expect(page.getByRole('combobox', { name: '適用部門（選填）' })).toBeVisible()

    const primaryButton = page.getByRole('button', { name: '加入 3 筆公司知識' })
    const box = await primaryButton.boundingBox()
    expect(box?.height).toBeGreaterThanOrEqual(44)
    expect(box?.width).toBeGreaterThanOrEqual(44)
  })

  test('offline and long-task recovery states survive navigation', async ({ page, context }) => {
    await demoLogin(page)
    await context.setOffline(true)
    await expect(page.getByRole('status').filter({ hasText: '裝置目前離線' })).toBeVisible()
    await context.setOffline(false)
    await expect(page.getByText('裝置目前離線')).toBeHidden()

    await page.evaluate(() => {
      window.localStorage.setItem('enclave.recoverable-knowledge-tasks.v1', JSON.stringify([{
        assetId: 'asset-recovery-1',
        title: '長時間換線影片',
        assetKind: 'video',
        createdAt: new Date().toISOString(),
      }]))
    })
    await page.reload()
    const recovery = page.getByRole('status').filter({ hasText: '背景處理可繼續追蹤' })
    await expect(recovery).toBeVisible()
    await expect(recovery.getByRole('link', { name: '查看進度' })).toHaveAttribute('href', '/knowledge/assets/asset-recovery-1')
  })

  test('slow knowledge responses expose a loading state and recover', async ({ page }) => {
    await demoLogin(page)
    await page.route('**/api/v1/knowledge/assets**', async route => {
      await new Promise(resolve => setTimeout(resolve, 900))
      await route.continue()
    })
    await page.goto('/knowledge/assets')
    await expect(page.getByRole('status', { name: '載入中' })).toBeVisible()
    await expect(page.getByRole('heading', { name: '所有資產' })).toBeVisible()
  })
})
