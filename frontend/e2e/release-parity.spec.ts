/** Production post-deploy acceptance for immutable release and canonical routes. */
import { expect, test } from '@playwright/test'

const canonicalRoutes = [
  '/overview',
  '/ask',
  '/knowledge/assets',
  '/knowledge/new',
  '/knowledge/review',
  '/knowledge/quality',
  '/system/health',
  '/job',
]

test.skip(process.env.RELEASE_PARITY_E2E !== 'true', 'release parity runs only after deployment')

test('frontend and backend expose one clean release identity', async ({ request }) => {
  const [healthResponse, frontendResponse] = await Promise.all([
    request.get('/health'),
    request.get('/release.json'),
  ])
  expect(healthResponse.ok()).toBe(true)
  expect(frontendResponse.ok()).toBe(true)
  expect(frontendResponse.headers()['content-type']).toContain('application/json')

  const health = await healthResponse.json()
  const frontend = await frontendResponse.json()
  const backend = health.release
  expect(backend.identifiable).toBe(true)
  expect(backend.source_dirty).toBe('false')
  for (const key of ['release_id', 'source_commit', 'source_dirty', 'schema_head', 'route_contract_hash']) {
    expect(frontend[key], `${key} must match`).toBe(backend[key])
  }
  expect(new Set(frontend.canonical_routes)).toEqual(new Set(canonicalRoutes))
})

test('demo administrator can open every canonical product route', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: /以公司管理進入 Demo/ }).click()
  await expect(page).toHaveURL(/\/overview$/)
  await expect(page.getByRole('navigation', { name: '主要導覽' })).toBeVisible()

  for (const route of canonicalRoutes) {
    await page.goto(route)
    await expect(page, `${route} must not fall through or redirect`).toHaveURL(
      new RegExp(`${route.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}$`),
    )
    await expect(page.locator('main')).toBeVisible()
  }
})
