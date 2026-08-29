import { expect, test, type Route } from '@playwright/test'

const tenantId = '11111111-1111-1111-1111-111111111111'
const sessionId = '44444444-4444-4444-4444-444444444444'
const user = { id: '22222222-2222-2222-2222-222222222222', email: 'admin@example.com', full_name: 'Admin', role: 'admin', tenant_id: tenantId, is_superuser: false }

function capabilityContract() {
  return {
    contract_version: 'input-capabilities.v1', registry_sha256: 'a'.repeat(64), tenant_id: tenantId,
    policy: {
      accepted_modes: ['file'], data_classifications: ['internal'], generic_resumable_upload: true,
      resumable_part_size: 4, resumable_min_part_size: 4, resumable_max_part_size: 16,
      resumable_max_parts: 10_000, resumable_session_ttl_hours: 24, video_allowed_codecs: [],
    },
    formats: [{ extension: '.pdf', media_type: 'application/pdf', parser_kind: 'pdf', asset_kind: 'document', capabilities: ['extract_text'], evidence_state: 'internally_verified', ui_default: true, max_bytes: 1000, max_duration_seconds: null, processing_status: 'configured', degradation_reasons: [] }],
    providers: [],
    quota: { max_documents: 5, current_documents: 0, remaining_documents: 5, max_storage_bytes: 1000, current_storage_bytes: 0, remaining_storage_bytes: 1000, warnings: [] },
  }
}

function session(acknowledged = false) {
  return {
    id: sessionId, status: 'uploading', filename: 'shift-note.pdf', media_type: 'application/pdf',
    byte_size: 8, part_size: 4, total_parts: 2,
    received_bytes: acknowledged ? 4 : 0, received_parts: acknowledged ? 1 : 0,
    acknowledged_parts: acknowledged ? [{ part_number: 1, byte_size: 4, sha256: 'a'.repeat(64) }] : [],
    expires_at: new Date(Date.now() + 60_000).toISOString(), asset_id: null, content_sha256: null,
  }
}

async function common(route: Route) {
  const path = new URL(route.request().url()).pathname
  const body = path.endsWith('/users/me') ? user
    : path.endsWith('/experience/bootstrap') ? {
      product: { name: 'Enclave', version_label: 'test', maturity: 'pilot', maturity_label: 'Pilot' }, user,
      capabilities: ['home', 'upload_documents'], default_home: '/overview', packs: {},
      inference: { mode: 'local', main_provider: 'test', data_stays_on_prem_for_inference: true, message: '' },
      features: {}, primary_navigation: [{ to: '/knowledge/assets', label: '知識' }], ui_modules: [],
    }
    : path.endsWith('/knowledge/input-capabilities') ? capabilityContract()
    : path.endsWith('/departments/options') ? []
    : []
  await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
}

test('auth expiry keeps acknowledged chunks and resumes after login', async ({ page }) => {
  let resumed = false
  const partCalls: number[] = []
  await page.route('**/api/v1/**', async route => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    const match = path.match(/upload-sessions\/[^/]+\/parts\/(\d+)$/)
    if (path.endsWith('/knowledge/upload-sessions') && request.method() === 'POST') {
      await route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify(session()) })
    } else if (path.endsWith(`/knowledge/upload-sessions/${sessionId}`) && request.method() === 'GET') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(session(true)) })
    } else if (match) {
      const number = Number(match[1]); partCalls.push(number)
      if (!resumed && number === 2) {
        await new Promise(resolve => setTimeout(resolve, 600))
        await route.fulfill({ status: 401, contentType: 'application/json', body: JSON.stringify({ detail: 'expired' }) })
      } else {
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(session(number === 1 || resumed)) })
      }
    } else if (path.endsWith(`/knowledge/upload-sessions/${sessionId}/commit`)) {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ id: 'asset-1', title: 'shift-note.pdf', asset_kind: 'document' }) })
    } else {
      await common(route)
    }
  })
  await page.addInitScript(() => {
    if (!sessionStorage.getItem('input-i2-bootstrapped')) {
      localStorage.setItem('token', 'initial-token')
      sessionStorage.setItem('input-i2-bootstrapped', '1')
    }
  })
  await page.goto('/knowledge/new')
  await expect(page.getByLabel('選擇檔案')).toHaveAttribute('accept', /.pdf/)
  await page.getByLabel('選擇檔案').setInputFiles({ name: 'shift-note.pdf', mimeType: 'application/pdf', buffer: Buffer.from('abcdefgh') })
  await expect(page.getByText('shift-note.pdf')).toBeVisible()
  await page.getByRole('button', { name: '加入公司知識' }).click()
  await expect.poll(() => page.evaluate(() => localStorage.getItem('token'))).toBeNull()
  await expect(page).not.toHaveURL(/\/knowledge\/new/)
  expect(partCalls).toContain(1)

  resumed = true
  await page.evaluate(() => localStorage.setItem('token', 'renewed-token'))
  await page.goto('/knowledge/new')
  await expect(page.getByText('shift-note.pdf')).toBeVisible()
  await page.getByRole('button', { name: '加入公司知識' }).click()
  await expect(page).toHaveURL(/\/knowledge\/assets\/asset-1/)
  expect(partCalls.filter(number => number === 1)).toHaveLength(1)
  expect(partCalls.filter(number => number === 2)).toHaveLength(2)
})
