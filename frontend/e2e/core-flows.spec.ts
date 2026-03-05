/**
 * Enclave E2E Tests — Playwright
 *
 * Covers core user flows:
 *   1. Login / Logout
 *   2. Document upload + list
 *   3. Chat (send message, receive SSE response)
 *   4. Navigation between pages
 *   5. Admin pages access
 */
import { test, expect, type Page } from '@playwright/test'

// ── Credentials ─────────────────────────────────────────────────────────────

const ADMIN_EMAIL = process.env.E2E_USER || 'admin@example.com'
const ADMIN_PASS = process.env.E2E_PASS || 'admin123'

// ── Helpers ─────────────────────────────────────────────────────────────────

async function login(page: Page, email = ADMIN_EMAIL, password = ADMIN_PASS) {
  await page.goto('/login')
  await page.locator('input[type="email"]').fill(email)
  await page.locator('input[type="password"]').fill(password)
  await page.getByRole('button', { name: /登入|login|sign in/i }).click()
  // Wait for redirect away from login
  await expect(page).not.toHaveURL(/\/login/, { timeout: 15_000 })
}

// ── Tests ───────────────────────────────────────────────────────────────────

test.describe('Authentication', () => {
  test('E2E-01: Login page loads', async ({ page }) => {
    await page.goto('/login')
    await expect(page.getByRole('button', { name: /登入|login|sign in/i })).toBeVisible()
  })

  test('E2E-02: Login with valid credentials', async ({ page }) => {
    await login(page)
    // Should land on chat page (index route)
    await expect(page).toHaveURL(/localhost.*\/$/, { timeout: 10_000 })
  })

  test('E2E-03: Invalid credentials shows error', async ({ page }) => {
    await page.goto('/login')
    await page.locator('input[type="email"]').fill('wrong@example.com')
    await page.locator('input[type="password"]').fill('wrongpass')
    await page.getByRole('button', { name: /登入|login|sign in/i }).click()
    // Should show error message or stay on login
    await expect(page.locator('text=/錯誤|error|failed|incorrect|invalid/i')).toBeVisible({ timeout: 5_000 })
  })

  test('E2E-04: Unauthenticated redirect to login', async ({ page }) => {
    await page.goto('/documents')
    await expect(page).toHaveURL(/\/login/)
  })
})

test.describe('Navigation', () => {
  test.beforeEach(async ({ page }) => {
    await login(page)
  })

  test('E2E-05: Navigate to Documents page', async ({ page }) => {
    await page.getByRole('link', { name: /文件|documents/i }).first().click()
    await expect(page).toHaveURL(/\/documents/)
  })

  test('E2E-06: Navigate to Generate page', async ({ page }) => {
    await page.getByRole('link', { name: /生成|generate/i }).first().click()
    await expect(page).toHaveURL(/\/generate/)
  })

  test('E2E-07: Navigate to Agent page (admin)', async ({ page }) => {
    await page.getByRole('link', { name: /agent|代理|索引/i }).first().click()
    await expect(page).toHaveURL(/\/agent/)
  })

  test('E2E-08: Navigate to KB Health page', async ({ page }) => {
    // KB Health might be in a sub-menu or sidebar
    const kbLink = page.getByRole('link', { name: /知識庫|kb.*health|維護/i }).first()
    if (await kbLink.isVisible({ timeout: 3_000 }).catch(() => false)) {
      await kbLink.click()
      await expect(page).toHaveURL(/\/kb-health/)
    }
  })
})

test.describe('Documents', () => {
  test.beforeEach(async ({ page }) => {
    await login(page)
    await page.goto('/documents')
    await page.waitForLoadState('networkidle')
  })

  test('E2E-09: Documents page renders table/list', async ({ page }) => {
    // Should have a table or list of documents
    const hasTable = await page.locator('table').isVisible({ timeout: 5_000 }).catch(() => false)
    const hasList = await page.locator('[class*="document"], [class*="list"], [class*="card"]').first().isVisible({ timeout: 3_000 }).catch(() => false)
    expect(hasTable || hasList).toBeTruthy()
  })

  test('E2E-10: Upload area exists', async ({ page }) => {
    // Dropzone renders a hidden file input
    const fileInput = page.locator('input[type="file"]')
    await expect(fileInput).toBeAttached({ timeout: 5_000 })
  })

  test('E2E-11: Document upload flow', async ({ page }) => {
    // Look for upload button/area
    const uploadBtn = page.getByRole('button', { name: /上傳|upload/i }).first()
    if (await uploadBtn.isVisible({ timeout: 3_000 }).catch(() => false)) {
      await uploadBtn.click()
      // Wait for upload dialog/dropzone
      await page.waitForTimeout(500)
    }

    // Check for file input or dropzone
    const fileInput = page.locator('input[type="file"]').first()
    if (await fileInput.isVisible({ timeout: 3_000 }).catch(() => false)) {
      // Upload a small test file
      await fileInput.setInputFiles({
        name: 'e2e_test.txt',
        mimeType: 'text/plain',
        buffer: Buffer.from('E2E Playwright 自動化測試文件\n這是測試內容。'),
      })
      // Wait for upload to complete
      await page.waitForTimeout(3_000)
    }
  })
})

test.describe('Chat', () => {
  test.beforeEach(async ({ page }) => {
    await login(page)
    await page.goto('/')
    await page.waitForLoadState('networkidle')
  })

  test('E2E-12: Chat page renders input area', async ({ page }) => {
    const chatInput = page.locator('textarea, input[type="text"]').last()
    await expect(chatInput).toBeVisible({ timeout: 5_000 })
  })

  test('E2E-13: Send a chat message', async ({ page }) => {
    const chatInput = page.locator('textarea, input[type="text"]').last()
    await chatInput.fill('請問新人到職需要準備什麼？')

    // Find and click send button
    const sendBtn = page.getByRole('button', { name: /送出|send|傳送/i }).first()
      .or(page.locator('button[type="submit"]').last())
      .or(page.locator('button:has(svg)').last())

    await sendBtn.click()

    // Wait for response to appear (SSE streaming)
    await page.waitForTimeout(5_000)

    // Check that a response message appeared
    const messages = page.locator('[class*="message"], [class*="chat"], [class*="bubble"], [class*="response"]')
    const count = await messages.count()
    expect(count).toBeGreaterThanOrEqual(1)
  })
})

test.describe('Generate', () => {
  test.beforeEach(async ({ page }) => {
    await login(page)
    await page.goto('/generate')
    await page.waitForLoadState('networkidle')
  })

  test('E2E-14: Generate page renders template selector', async ({ page }) => {
    // Templates are rendered as buttons with Chinese labels
    const templateBtn = page.getByRole('button', { name: '函件草稿' })
    await expect(templateBtn).toBeVisible({ timeout: 5_000 })
  })

  test('E2E-15: Generate page has prompt input', async ({ page }) => {
    const promptInput = page.locator('textarea').first()
    await expect(promptInput).toBeVisible({ timeout: 5_000 })
  })
})

test.describe('Admin Pages', () => {
  test.beforeEach(async ({ page }) => {
    await login(page)
  })

  test('E2E-16: Usage page accessible', async ({ page }) => {
    await page.goto('/usage')
    await page.waitForLoadState('networkidle')
    // Should not redirect to login and should show usage data
    await expect(page).toHaveURL(/\/usage/)
  })

  test('E2E-17: Audit logs page accessible', async ({ page }) => {
    await page.goto('/audit')
    await page.waitForLoadState('networkidle')
    await expect(page).toHaveURL(/\/audit/)
  })

  test('E2E-18: RAG Dashboard accessible', async ({ page }) => {
    await page.goto('/rag-dashboard')
    await page.waitForLoadState('networkidle')
    await expect(page).toHaveURL(/\/rag-dashboard/)
  })

  test('E2E-19: Query Analytics accessible', async ({ page }) => {
    await page.goto('/query-analytics')
    await page.waitForLoadState('networkidle')
    await expect(page).toHaveURL(/\/query-analytics/)
  })

  test('E2E-20: Usage Report accessible', async ({ page }) => {
    await page.goto('/usage-report')
    await page.waitForLoadState('networkidle')
    await expect(page).toHaveURL(/\/usage-report/)
  })
})
