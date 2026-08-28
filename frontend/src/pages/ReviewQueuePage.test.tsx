import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../api', () => ({
  knowledgeReviewApi: { list: vi.fn(), decide: vi.fn(), batchApprove: vi.fn() },
  parseApiError: vi.fn(() => ({ message: 'error', retryable: true })),
  formatErrorWithTrace: vi.fn(() => 'error'),
}))

import { knowledgeReviewApi } from '../api'
import ReviewQueuePage from './ReviewQueuePage'

const item = {
  id: 'artifact:00000000-0000-0000-0000-000000000001', provider: 'core.asset_artifact',
  source_type: 'transcript_segment', asset_kind: 'audio', title: '交接錄音', subtitle: '逐字稿',
  status: 'pending', risk_level: 'low' as const, confidence: 0.72, created_at: '2026-08-27T00:00:00Z',
  due_at: '2026-09-03T00:00:00Z', department_ids: [], policy_key: 'artifact-human-review-v1',
  policy_version: 1, assignee: null, batch_eligible: false, blocked_reasons: [],
  proposal: { content: '壓力歸零後才能開門' },
  evidence: [{ id: 'ev-1', kind: 'audio' as const, start_ms: 402000, end_ms: 438000, deep_link: '/knowledge/assets/a1?t=402' }],
  publication: { unit_key: 'artifact:a1', next_revision: 1, effective_from: 'on_approval', acl: { visibility: 'tenant' }, rollback: 'retire release', sop_precedence: false },
}

describe('ReviewQueuePage', () => {
  beforeEach(() => {
    vi.mocked(knowledgeReviewApi.list).mockResolvedValue({ items: [item], total: 1, limit: 100, offset: 0, facets: { source_types: ['transcript_segment'], policy_keys: ['artifact-human-review-v1'], assignees: [] } })
    vi.mocked(knowledgeReviewApi.decide).mockResolvedValue({ decision: 'approved' })
  })

  it('renders evidence locator and fail-closed low-confidence acknowledgement', async () => {
    render(<MemoryRouter><ReviewQueuePage /></MemoryRouter>)
    expect((await screen.findAllByText('交接錄音')).length).toBeGreaterThan(0)
    expect(screen.getByRole('link', { name: /音訊 6:42–7:18/ })).toHaveAttribute('href', '/knowledge/assets/a1?t=402')
    const approve = screen.getByRole('button', { name: /核准並發布/ })
    expect(approve).toBeDisabled()
    await userEvent.click(screen.getByText(/我已逐一核對低信心/))
    expect(approve).toBeEnabled()
    await userEvent.click(approve)
    await waitFor(() => expect(knowledgeReviewApi.decide).toHaveBeenCalledWith(item.id, expect.objectContaining({ decision: 'approved', acknowledgeLowConfidence: true })))
  })

  it('exposes all governance filters', async () => {
    render(<MemoryRouter><ReviewQueuePage /></MemoryRouter>)
    await screen.findAllByText('交接錄音')
    expect(screen.getByLabelText('風險')).toBeInTheDocument()
    expect(screen.getByLabelText('來源類型')).toBeInTheDocument()
    expect(screen.getByLabelText('審核政策')).toBeInTheDocument()
    expect(screen.getByLabelText('指派對象')).toBeInTheDocument()
    expect(screen.getByLabelText('部門 ID')).toBeInTheDocument()
    expect(screen.getByLabelText('已逾期')).toBeInTheDocument()
  })

  it('fails closed when evidence points outside the knowledge workspace', async () => {
    vi.mocked(knowledgeReviewApi.list).mockResolvedValue({
      items: [{ ...item, confidence: 0.99, evidence: [{ ...item.evidence[0], deep_link: 'https://evil.example/steal' }] }],
      total: 1,
      limit: 100,
      offset: 0,
      facets: { source_types: ['transcript_segment'], policy_keys: ['artifact-human-review-v1'], assignees: [] },
    })
    render(<MemoryRouter><ReviewQueuePage /></MemoryRouter>)
    expect(await screen.findByText(/缺少有效的站內證據定位器/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /核准並發布/ })).toBeDisabled()
  })
})
