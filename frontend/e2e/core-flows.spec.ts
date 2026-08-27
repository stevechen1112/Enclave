/** Browser acceptance for the server-composed application shell. */
import { test, expect, type Page } from '@playwright/test'

const ADMIN_EMAIL = process.env.E2E_USER || 'admin@example.com'
const ADMIN_PASS = process.env.E2E_PASS ?? ''

if (!ADMIN_PASS) {
  throw new Error('E2E_PASS must be injected for authenticated browser tests')
}

async function login(page: Page) {
  await page.goto('/login')
  await page.locator('input[type="email"]').fill(ADMIN_EMAIL)
  await page.locator('input[type="password"]').fill(ADMIN_PASS)
  await page.getByRole('button', { name: /登入|login|sign in/i }).click()
  await expect(page).not.toHaveURL(/\/login/, { timeout: 15_000 })
  await expect(page.getByRole('navigation', { name: '主要導覽' })).toBeVisible()
}

test.describe('Authentication and fail-closed shell', () => {
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

  test('admin login lands on the server-authorized home', async ({ page }) => {
    await login(page)
    await expect(page).toHaveURL(/\/overview$/)
    await expect(page.getByRole('heading', { name: '公司知識營運總覽' })).toBeVisible()
  })
})

test.describe('Canonical knowledge experience', () => {
  test.beforeEach(async ({ page }) => login(page))

  test('knowledge navigation opens the unified asset library', async ({ page }) => {
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
  })

  test('review inbox is reachable from the knowledge sub-navigation', async ({ page }) => {
    await page.goto('/knowledge/review')
    await expect(page).toHaveURL(/\/knowledge\/review$/)
    await expect(page.getByRole('heading', { name: /審核/ })).toBeVisible()
  })
})

test.describe('Composed navigation and compatibility', () => {
  test.beforeEach(async ({ page }) => login(page))

  test('command palette opens by keyboard and restores focus', async ({ page }) => {
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
