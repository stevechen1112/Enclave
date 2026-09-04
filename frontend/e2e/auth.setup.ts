import { mkdirSync } from 'node:fs'
import { dirname } from 'node:path'
import { test as setup, expect } from '@playwright/test'

const authFile = 'test-results/.auth/user.json'
const user = process.env.E2E_USER || 'admin@example.com'
const password = process.env.E2E_PASS ?? ''

setup('authenticate once for the release journey', async ({ page }) => {
  if (!password) throw new Error('E2E_PASS must be injected for authenticated browser tests')

  await page.goto('/login')
  await page.locator('input[type="email"]').fill(user)
  await page.locator('input[type="password"]').fill(password)
  await page.getByRole('button', { name: /登入|login|sign in/i }).click()
  await expect(page).not.toHaveURL(/\/login/, { timeout: 15_000 })
  await expect(page.getByRole('navigation', { name: '主要導覽' })).toBeVisible()

  mkdirSync(dirname(authFile), { recursive: true })
  await page.context().storageState({ path: authFile })
})
