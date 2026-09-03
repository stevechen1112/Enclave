import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const get = vi.fn()
const events = vi.fn()

vi.mock('../../api', () => ({
  knowledgeAssetApi: { get: (...args: unknown[]) => get(...args), events: (...args: unknown[]) => events(...args), retry: vi.fn() },
  formatErrorWithTrace: vi.fn(),
  parseApiError: vi.fn(),
}))
vi.mock('../../lib/longTaskRecovery', () => ({ forgetKnowledgeTask: vi.fn() }))

import AssetDetailPage from './AssetDetailPage'

const asset = {
  id: 'asset-1', asset_kind: 'audio', title: '現場錄音.wav', source_system: 'upload', data_classification: 'internal',
  status: 'failed', current_revision: 1, created_at: '2026-09-03T00:00:00Z', updated_at: null, tombstoned_at: null,
  metadata: {}, revision: null, revisions: [], answer_ready: false, lifecycle_status: 'needs_attention', pending_review_count: 0,
  job: { id: 'job-1', status: 'failed', phase: 'audio_probe', quality_state: 'failed', adapter_key: 'core.audio', adapter_version: '1', requested_capabilities: [], readiness: {}, error: { code: 'unsupported_audio_codec', retryable: false, user_message: '此音訊格式目前無法處理。' }, correlation_id: 'trace-123', attempt: 1, created_at: '2026-09-03T00:00:00Z', completed_at: '2026-09-03T00:01:00Z' },
}

function renderPage() {
  return render(<MemoryRouter initialEntries={['/knowledge/assets/asset-1']}><Routes><Route path="/knowledge/assets/:assetId" element={<AssetDetailPage />} /></Routes></MemoryRouter>)
}

describe('AssetDetailPage recovery guidance', () => {
  beforeEach(() => { get.mockReset(); events.mockReset(); events.mockResolvedValue([]) })

  it('shows safe permanent-error guidance and trace without a misleading retry', async () => {
    get.mockResolvedValue(asset)
    renderPage()
    expect(await screen.findByText('此音訊格式目前無法處理。')).toBeInTheDocument()
    expect(screen.getByText(/追蹤碼：trace-123/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /重新處理/ })).not.toBeInTheDocument()
  })

  it('takes an answer-ready user directly to Ask', async () => {
    get.mockResolvedValue({ ...asset, status: 'active', answer_ready: true, lifecycle_status: 'answer_ready', job: { ...asset.job, status: 'ready', error: {} } })
    renderPage()
    expect(await screen.findByRole('link', { name: /前往問知識/ })).toHaveAttribute('href', '/ask')
  })
})
