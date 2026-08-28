/** P6 persona × capability × route contract acceptance. */
import { expect, test, type Page } from '@playwright/test'

type Persona = 'sales' | 'field' | 'master' | 'newcomer' | 'viewer' | 'admin'
type Bootstrap = {
  capabilities: string[]
  default_home: string
  primary_navigation: Array<{ to: string; label: string }>
}

const personas: Persona[] = ['sales', 'field', 'master', 'newcomer', 'viewer', 'admin']
const guardedRoutes: Array<[string, string]> = [
  ['/knowledge/new', 'upload_documents'],
  ['/knowledge/sources', 'manage_sources'],
  ['/knowledge/review', 'review_queue'],
  ['/knowledge/quality', 'governance'],
  ['/governance/organization', 'governance'],
  ['/system/health', 'system_ops'],
  ['/create', 'create_content'],
]

async function loginAs(page: Page, persona: Persona) {
  const response = await page.request.post('/api/v1/auth/login/demo', { data: { persona } })
  expect(response.ok(), `${persona}: ${await response.text()}`).toBe(true)
  const { access_token: token } = await response.json()
  const bootstrapResponse = await page.request.get('/api/v1/experience/bootstrap', {
    headers: { Authorization: `Bearer ${token}` },
  })
  expect(bootstrapResponse.ok(), `${persona}: ${await bootstrapResponse.text()}`).toBe(true)
  const bootstrap = await bootstrapResponse.json() as Bootstrap
  await page.goto('/login')
  await page.evaluate(value => window.localStorage.setItem('token', value), token)
  await page.goto(`/${bootstrap.default_home}`)
  await expect(page.getByRole('navigation', { name: '主要導覽' })).toBeVisible()
  return { token, bootstrap }
}

test.describe('P6 persona route contracts', () => {
  for (const persona of personas) {
    test(`${persona} only sees and reaches server-authorized surfaces`, async ({ page }) => {
      const { token, bootstrap } = await loginAs(page, persona)
      const navigation = page.getByRole('navigation', { name: '主要導覽' })
      for (const item of bootstrap.primary_navigation) {
        await expect(navigation.getByRole('link', { name: item.label, exact: true })).toHaveAttribute('href', item.to)
      }

      for (const [route, capability] of guardedRoutes) {
        await test.step(`${route} requires ${capability}`, async () => {
          await page.goto(route)
          if (bootstrap.capabilities.includes(capability)) {
            await expect(page).toHaveURL(new RegExp(`${route.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}/?$`))
            await expect(page.locator('#main-content')).toBeVisible()
          } else {
            await expect(page).toHaveURL(new RegExp(`/${bootstrap.default_home}/?$`))
            await expect(page.locator('#main-content')).toBeVisible()
          }
        })
      }

      if (persona === 'viewer') {
        const adminResponse = await page.request.get('/api/v1/admin/dashboard', {
          headers: { Authorization: `Bearer ${token}` },
        })
        expect(adminResponse.status()).toBe(403)
      }
    })
  }
})
