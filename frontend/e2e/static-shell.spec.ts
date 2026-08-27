/** Browser smoke that is valid against the frontend-only CI artifact. */
import { expect, test } from '@playwright/test'

test('production build renders the public login shell', async ({ page }) => {
  await page.goto('/login')
  await expect(page.getByRole('button', { name: /登入|login|sign in/i })).toBeVisible()
  await expect(page.locator('input[type="email"]')).toBeVisible()
  await expect(page.locator('input[type="password"]')).toBeVisible()
})
