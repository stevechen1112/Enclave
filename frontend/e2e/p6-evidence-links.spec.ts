/** P6 browser acceptance for document, image, audio and video evidence locators. */
import { expect, test, type Page, type Route } from '@playwright/test'

const headers = { 'content-type': 'application/json' }

async function json(route: Route, body: unknown) {
  await route.fulfill({ status: 200, headers, body: JSON.stringify(body) })
}

async function demoLogin(page: Page) {
  const response = await page.request.post('/api/v1/auth/login/demo', { data: { persona: 'admin' } })
  expect(response.ok(), await response.text()).toBe(true)
  const { access_token: token } = await response.json()
  await page.goto('/login')
  await page.evaluate(value => window.localStorage.setItem('token', value), token)
}

test('evidence links open the intended locator on every core media surface', async ({ page }) => {
  await demoLogin(page)

  await page.route('**/api/v1/documents/doc-1', route => json(route, {
    id: 'doc-1', filename: '安全規範.pdf', file_type: 'pdf', status: 'completed', tenant_id: 'tenant-1',
    uploaded_by: null, department_id: null, file_size: 100, chunk_count: 2, error_message: null,
    answer_ready: true, published_revision: 1, published_chunk_count: 2, readiness_reasons: [],
    created_at: '2026-08-28T00:00:00Z', updated_at: null, is_new: false,
  }))
  await page.route('**/api/v1/kb-maintenance/documents/doc-1/versions', route => json(route, []))
  await page.route('**/api/v1/knowledge/assets/**', async route => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/events')) return json(route, [])
    const id = path.split('/').pop() || 'asset'
    return json(route, {
      id, asset_kind: id.includes('image') ? 'image' : 'audio', title: id.includes('image') ? '機台銘牌' : '交接錄音',
      source_system: 'upload', data_classification: 'internal', status: 'ready', current_revision: 1,
      created_at: '2026-08-28T00:00:00Z', updated_at: null, tombstoned_at: null, metadata: {},
      revision: null, revisions: [], job: null,
    })
  })
  await page.route('**/api/v1/media/videos/video-1', route => json(route, {
    id: 'video-1', title: '換線教學', status: 'ready', created_at: '2026-08-28T00:00:00Z',
    revision_id: 'rev-1', duration_ms: 500000, media_type: 'video/mp4', probe: {}, job: null,
    content_url: '/media/video-1.mp4', artifacts: [],
  }))

  await page.goto('/knowledge/documents/doc-1?page=3&section=%E5%AE%89%E5%85%A8%E9%96%80')
  await expect(page.getByRole('status').filter({ hasText: '已開啟引用證據位置' })).toContainText('第 3 頁 · 段落：安全門')

  await page.goto('/knowledge/assets/asset-image?bbox=1,2,3,4&region=label-A')
  await expect(page.getByRole('status').filter({ hasText: '已開啟引用證據位置' })).toContainText('已指定影像標記區域')

  await page.goto('/knowledge/assets/asset-audio?t=402000&end=438000')
  await expect(page.getByRole('status').filter({ hasText: '已開啟引用證據位置' })).toContainText('時間 6:42–7:18')

  await page.goto('/knowledge/videos/video-1?t=9000&frame=42')
  const locator = page.getByRole('status').filter({ hasText: '已開啟引用證據位置' })
  await expect(locator).toContainText('時間 0:09')
  await expect(locator).toContainText('畫面 42')
})
