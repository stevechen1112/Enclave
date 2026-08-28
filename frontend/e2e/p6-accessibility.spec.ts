/** P6 automated accessibility and keyboard acceptance. */
import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page, type TestInfo } from '@playwright/test'

const WCAG_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']

test.use({ reducedMotion: 'reduce' })

async function highImpactViolations(page: Page, testInfo: TestInfo, label: string) {
  const result = await new AxeBuilder({ page }).withTags(WCAG_TAGS).analyze()
  const violations = result.violations.filter(item =>
    item.impact === 'critical' || item.impact === 'serious',
  )
  await testInfo.attach(`axe-${label.replace(/[^a-z0-9]+/gi, '-') || 'root'}`, {
    body: JSON.stringify(result, null, 2),
    contentType: 'application/json',
  })
  return violations.map(item => ({
    route: label,
    id: item.id,
    help: item.help,
    nodes: item.nodes.map(node => ({ target: node.target, html: node.html, failureSummary: node.failureSummary })),
  }))
}

async function demoLogin(page: Page, persona = 'admin') {
  const response = await page.request.post('/api/v1/auth/login/demo', {
    data: { persona },
  })
  expect(response.ok(), await response.text()).toBe(true)
  const { access_token: token } = await response.json()
  await page.goto('/login')
  await page.evaluate(value => window.localStorage.setItem('token', value), token)
  await page.goto('/overview')
  await expect(page.getByRole('navigation', { name: '主要導覽' })).toBeVisible()
}

test.describe('P6 accessibility baseline', () => {
  test('public landing and login have no critical or serious WCAG violations', async ({ page }, testInfo) => {
    const violations = []
    for (const route of ['/', '/login']) {
      await page.goto(route)
      violations.push(...await highImpactViolations(page, testInfo, route))
    }
    expect(violations, JSON.stringify(violations, null, 2)).toEqual([])
  })

  test('authenticated core surfaces have no critical or serious WCAG violations', async ({ page }, testInfo) => {
    await demoLogin(page)
    const violations = []
    for (const route of [
      '/overview',
      '/ask',
      '/knowledge/assets',
      '/knowledge/new',
      '/knowledge/review',
      '/knowledge/quality',
      '/system/health',
      '/job',
    ]) {
      await test.step(route, async () => {
        await page.goto(route)
        await expect(page.locator('#main-content')).toBeVisible()
        violations.push(...await highImpactViolations(page, testInfo, route))
      })
    }
    expect(violations, JSON.stringify(violations, null, 2)).toEqual([])
  })

  test('keyboard users can skip navigation and operate the command palette', async ({ page }) => {
    await demoLogin(page)
    await page.keyboard.press('Tab')
    const skipLink = page.getByRole('link', { name: '跳到主要內容' })
    await expect(skipLink).toBeFocused()
    await skipLink.press('Enter')
    await expect(page.locator('#main-content')).toBeFocused()

    const trigger = page.getByRole('button', { name: '搜尋可用功能' })
    await trigger.focus()
    await page.keyboard.press('Control+K')
    await expect(page.getByRole('dialog')).toBeVisible()
    await expect(page.getByRole('textbox', { name: /搜尋/ })).toBeFocused()
    await page.keyboard.press('Escape')
    await expect(trigger).toBeFocused()
  })
})
