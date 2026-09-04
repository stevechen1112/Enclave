/** Browser acceptance for the server-composed application shell. */
import { test, expect } from '@playwright/test'

test.describe('Authentication and fail-closed shell', () => {
  test.use({ storageState: { cookies: [], origins: [] } })

  test('login page and invalid-credential feedback work', async ({ page }) => {
    await page.goto('/login')
    await expect(page.getByRole('button', { name: /登入|login|sign in/i })).toBeVisible()
    await page.locator('input[type="email"]').fill('wrong@example.invalid')
    await page.locator('input[type="password"]').fill('wrongpass')
    await page.getByRole('button', { name: /登入|login|sign in/i }).click()
    await expect(page).toHaveURL(/\/login/)
    await expect(page.getByRole('alert')).toContainText('不正確')
  })

  test('protected canonical route redirects an anonymous user', async ({ page }) => {
    await page.goto('/knowledge/assets')
    await expect(page).toHaveURL(/\/login/)
  })

})

test.describe('Authenticated shell', () => {
  test('authenticated owner lands on the server-authorized home', async ({ page }) => {
    await page.goto('/overview')
    await expect(page).toHaveURL(/\/overview$/)
    await expect(page.getByRole('heading', { name: /公司知識工作區|公司知識營運總覽/ })).toBeVisible()
  })
})

test.describe('Canonical knowledge experience', () => {
  test('knowledge navigation opens the unified asset library', async ({ page }) => {
    await page.goto('/overview')
    await page.getByRole('link', { name: '知識', exact: true }).click()
    await expect(page).toHaveURL(/\/knowledge\/assets$/)
    await expect(page.getByRole('heading', { name: '所有資產' })).toBeVisible()
    await expect(page.getByLabel('資產類型')).toBeVisible()
    await expect(page.getByLabel('處理狀態')).toBeVisible()
  })

  test('legacy document bookmark redirects to the canonical library', async ({ page }) => {
    await page.goto('/documents')
    await expect(page).toHaveURL(/\/knowledge\/assets$/)
    await expect(page.getByRole('heading', { name: '所有資產' })).toBeVisible()
  })

  test('unified intake exposes file, URL and external-record modes', async ({ page }) => {
    await page.goto('/knowledge/new')
    await expect(page.getByRole('heading', { name: '新增知識' })).toBeVisible()
    await expect(page.getByRole('tab', { name: '上傳／拍攝' })).toBeVisible()
    await expect(page.getByRole('tab', { name: '貼上網址' })).toBeVisible()
    await expect(page.getByRole('tab', { name: '外部紀錄' })).toBeVisible()
    await expect(page.locator('input[type="file"]').first()).toBeAttached()
    await expect(page.getByText(/此環境可處理/)).toBeVisible()
    await expect(page.getByRole('combobox', { name: '資料分類' })).toBeVisible()
    await expect(page.getByRole('combobox', { name: '適用部門（選填）' })).toBeVisible()
  })

  test('review inbox is reachable from the knowledge sub-navigation', async ({ page }) => {
    await page.goto('/knowledge/review')
    await expect(page).toHaveURL(/\/knowledge\/review$/)
    await expect(page.getByRole('heading', { name: /審核/ })).toBeVisible()
  })
})

test.describe('Composed navigation and compatibility', () => {
  test('command palette opens by keyboard and restores focus', async ({ page }) => {
    await page.goto('/overview')
    const trigger = page.getByRole('button', { name: '搜尋可用功能' })
    await trigger.focus()
    await page.keyboard.press('Control+K')
    await expect(page.getByRole('dialog')).toBeVisible()
    await expect(page.getByRole('textbox', { name: /搜尋/ })).toBeFocused()
    await page.keyboard.press('Escape')
    await expect(page.getByRole('dialog')).toBeHidden()
    await expect(trigger).toBeFocused()
  })

  test('legacy governance bookmarks resolve to canonical routes', async ({ page }) => {
    await page.goto('/audit')
    await expect(page).toHaveURL(/\/governance\/audit$/)
    await page.goto('/query-analytics')
    await expect(page).toHaveURL(/\/governance\/insights$/)
    await page.goto('/usage')
    await expect(page).toHaveURL(/\/me\/usage$/)
  })

  test('stable v1 bootstrap is not marked deprecated', async ({ page }) => {
    await page.goto('/overview')
    const metadata = await page.evaluate(async () => {
      const token = window.localStorage.getItem('token')
      const response = await fetch('/api/v1/experience/bootstrap', {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      })
      return {
        status: response.status,
        version: response.headers.get('x-api-version'),
        deprecation: response.headers.get('deprecation'),
      }
    })
    expect(metadata.status).toBe(200)
    expect(metadata.version).toBe('v1')
    expect(metadata.deprecation).toBeNull()
  })
})
