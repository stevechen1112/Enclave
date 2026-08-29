import { expect, test, type Route } from '@playwright/test'

const tenantId = '11111111-1111-1111-1111-111111111111'
const captureId = '55555555-5555-5555-5555-555555555555'
const assetId = '66666666-6666-6666-6666-666666666666'
const user = { id: '22222222-2222-2222-2222-222222222222', email: 'admin@example.com', full_name: 'Admin', role: 'admin', tenant_id: tenantId, is_superuser: false }

function capabilities() {
  return {
    contract_version: 'input-capabilities.v1', registry_sha256: 'a'.repeat(64), tenant_id: tenantId,
    policy: {
      accepted_modes: ['file', 'capture_manifest'], data_classifications: ['internal', 'confidential', 'restricted'], generic_resumable_upload: true,
      resumable_part_size: 8, resumable_min_part_size: 4, resumable_max_part_size: 16,
      resumable_max_parts: 10_000, resumable_session_ttl_hours: 24, video_allowed_codecs: ['h264'],
    },
    formats: [
      { extension: '.webm', media_type: 'audio/webm', parser_kind: 'audio', asset_kind: 'audio', capabilities: ['transcribe', 'timestamp'], evidence_state: 'internally_verified', ui_default: true, max_bytes: 10_000, max_duration_seconds: 3600, processing_status: 'configured', degradation_reasons: [] },
      { extension: '.jpg', media_type: 'image/jpeg', parser_kind: 'image', asset_kind: 'image', capabilities: ['ocr'], evidence_state: 'internally_verified', ui_default: true, max_bytes: 10_000, max_duration_seconds: null, processing_status: 'configured', degradation_reasons: [] },
      { extension: '.mp4', media_type: 'video/mp4', parser_kind: 'video', asset_kind: 'video', capabilities: ['transcribe'], evidence_state: 'internally_verified', ui_default: true, max_bytes: 10_000, max_duration_seconds: 3600, processing_status: 'configured', degradation_reasons: [] },
    ],
    providers: [],
    quota: { max_documents: 10, current_documents: 0, remaining_documents: 10, max_storage_bytes: 100_000, current_storage_bytes: 0, remaining_storage_bytes: 100_000, warnings: [] },
  }
}

function capture(status: 'recording' | 'uploading' | 'queued' = 'recording') {
  return {
    id: captureId, title: '夜班交接', equipment_id: null, interviewee: null, interviewer: null,
    status, received_chunks: status === 'recording' ? 0 : 1, expected_chunks: status === 'queued' ? 1 : null,
    total_duration_ms: status === 'recording' ? 0 : 1000, error: {}, source_asset_id: assetId,
    capture_metadata: { source_module: 'core' }, policy: {}, created_at: new Date().toISOString(), completed_at: status === 'queued' ? new Date().toISOString() : null,
  }
}

async function fallback(route: Route) {
  const path = new URL(route.request().url()).pathname
  const body = path.endsWith('/users/me') ? user
    : path.endsWith('/experience/bootstrap') ? {
      product: { name: 'Enclave', version_label: 'test', maturity: 'pilot', maturity_label: 'Pilot' }, user,
      capabilities: ['home', 'upload_documents'], default_home: '/overview', packs: {},
      inference: { mode: 'local', main_provider: 'test', data_stays_on_prem_for_inference: true, message: '' },
      features: {}, primary_navigation: [{ to: '/knowledge/assets', label: '知識' }], ui_modules: [],
    }
    : path.endsWith('/knowledge/input-capabilities') ? capabilities()
    : path.endsWith('/departments/options') ? []
    : []
  await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
}

test('core capture works from knowledge intake without an MKA surface', async ({ page }) => {
  const calls: string[] = []
  await page.addInitScript(() => {
    localStorage.setItem('token', 'input-i3-token')
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { getUserMedia: async () => ({ getTracks: () => [{ stop() {} }] }) },
    })
    Object.defineProperty(navigator, 'storage', {
      configurable: true,
      value: { estimate: async () => ({ quota: 100_000_000, usage: 10_000_000 }) },
    })
    class BrowserMediaRecorder {
      static isTypeSupported() { return true }
      state = 'inactive'
      ondataavailable: ((event: { data: Blob }) => void) | null = null
      onstop: (() => void) | null = null
      constructor() {}
      start() { this.state = 'recording' }
      requestData() {}
      stop() {
        this.state = 'inactive'
        queueMicrotask(() => {
          this.ondataavailable?.({ data: new Blob(['factory-audio'], { type: 'audio/webm;codecs=opus' }) })
          queueMicrotask(() => this.onstop?.())
        })
      }
    }
    Object.defineProperty(window, 'MediaRecorder', { configurable: true, value: BrowserMediaRecorder })
  })
  await page.route('**/api/v1/**', async route => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    if (path.endsWith('/knowledge/captures/policy')) {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({
        consent_version: 'core-capture-v1', max_duration_seconds: 3600, chunk_max_seconds: 30, chunk_max_bytes: 8_388_608, max_chunks: 240,
        audio_retention_days: 30, transcript_retention_days: 365, save_audio: true, save_transcript: true, encrypt_at_rest: true,
        terminology_count: 8, terminology_sha256: 'b'.repeat(64), default_metadata: { data_classification: 'confidential', source_module: 'core', purpose: 'knowledge_capture' }, device_limitations: [],
      }) })
    } else if (path.endsWith('/knowledge/captures') && request.method() === 'POST') {
      calls.push('create'); await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(capture()) })
    } else if (path.endsWith(`/knowledge/captures/${captureId}/chunks`)) {
      calls.push('chunk'); await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ id: 'chunk-1', sequence: 0, duplicate: false, received_chunks: 1 }) })
    } else if (path.endsWith(`/knowledge/captures/${captureId}/complete`)) {
      calls.push('complete'); await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ...capture('queued'), queue_enqueued: false }) })
    } else {
      await fallback(route)
    }
  })

  await page.goto('/knowledge/new')
  await page.getByRole('tab', { name: '現場擷取' }).click()
  await expect(page.getByText('拍攝照片')).toBeVisible()
  await expect(page.getByText('拍攝影片')).toBeVisible()
  await page.getByRole('checkbox').check()
  await page.getByRole('button', { name: '開始訪談' }).click()
  await expect(page.getByRole('button', { name: '結束訪談' })).toBeVisible()
  await page.getByRole('button', { name: '結束訪談' }).click()
  await expect(page.getByRole('button', { name: '查看錄音知識資產' })).toBeVisible()
  expect(calls).toEqual(['create', 'chunk', 'complete'])
})
