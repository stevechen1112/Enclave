import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page, type Route } from '@playwright/test'

const tenantId = '11111111-1111-1111-1111-111111111111'
const user = { id: '22222222-2222-2222-2222-222222222222', email: 'admin@example.com', full_name: 'Admin', role: 'admin', tenant_id: tenantId, is_superuser: false }
const formats = [
  { extension: '.pdf', media_type: 'application/pdf', parser_kind: 'document', asset_kind: 'document', capabilities: ['extract_text', 'layout'], evidence_state: 'internally_verified', ui_default: true, max_bytes: 10, max_duration_seconds: null, processing_status: 'configured', degradation_reasons: [] },
  { extension: '.mp4', media_type: 'video/mp4', parser_kind: 'video', asset_kind: 'video', capabilities: ['transcribe', 'keyframes'], evidence_state: 'environment_validation_pending', ui_default: true, max_bytes: 1000, max_duration_seconds: null, processing_status: 'degraded', degradation_reasons: ['runtime codec verification required'] },
]

async function respond(route: Route) {
  const path = new URL(route.request().url()).pathname
  const json = path.endsWith('/users/me') ? user
    : path.endsWith('/experience/bootstrap') ? {
      product: { name: 'Enclave', version_label: 'test', maturity: 'pilot', maturity_label: 'Pilot' },
      user,
      capabilities: ['home', 'upload_documents'],
      default_home: '/overview',
      packs: {},
      inference: { mode: 'local', main_provider: 'test', data_stays_on_prem_for_inference: true, message: '' },
      features: {},
      primary_navigation: [{ to: '/knowledge/assets', label: '知識' }],
      ui_modules: [],
    }
    : path.endsWith('/knowledge/input-capabilities') ? {
      contract_version: 'input-capabilities.v1', registry_sha256: 'a'.repeat(64), tenant_id: tenantId,
      policy: { accepted_modes: ['file'], data_classifications: ['public', 'internal', 'confidential', 'restricted'], generic_resumable_upload: false, video_allowed_codecs: ['h264'] },
      formats,
      providers: [],
      quota: { max_documents: 5, current_documents: 1, remaining_documents: 4, max_storage_bytes: 1000, current_storage_bytes: 0, remaining_storage_bytes: 1000, warnings: [] },
    }
    : path.endsWith('/departments/options') ? [{ id: '33333333-3333-3333-3333-333333333333', name: '製造部' }]
    : []
  await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(json) })
}

async function openIntake(page: Page) {
  await page.route('**/api/v1/**', respond)
  await page.addInitScript(() => localStorage.setItem('token', 'e2e-token'))
  await page.goto('/knowledge/new')
  await expect(page.getByRole('heading', { name: '新增知識' })).toBeVisible()
  await expect(page.getByText(/此環境可處理 1 種格式/)).toBeVisible()
}

test.describe('Input I1 browser acceptance', () => {
  test('capability policy drives preflight, governance metadata and actionable errors', async ({ page }) => {
    await openIntake(page)
    await expect(page.getByLabel('選擇檔案')).toHaveAttribute('accept', /\.pdf/)
    await expect(page.getByLabel('選擇檔案')).toHaveAttribute('accept', /\.mp4/)
    await expect(page.getByRole('combobox', { name: '適用部門（選填）' })).toContainText('製造部')
    await page.getByLabel('選擇檔案').setInputFiles({ name: 'oversized.pdf', mimeType: 'application/pdf', buffer: Buffer.from('more-than-ten') })
    await expect(page.getByText(/檔案超過 10 B 上限/)).toBeVisible()
    await expect(page.getByRole('button', { name: '加入公司知識' })).toBeDisabled()
    await expect(page.getByRole('button', { name: '移除 oversized.pdf' })).toBeVisible()
  })

  test('has no critical or serious accessibility violations', async ({ page }) => {
    await openIntake(page)
    const result = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa']).analyze()
    expect(result.violations.filter(item => item.impact === 'critical' || item.impact === 'serious')).toEqual([])
  })
})
