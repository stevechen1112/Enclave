import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import VideoReviewPage from './VideoReviewPage'

vi.mock('react-hot-toast', () => ({
  default: { error: vi.fn(), success: vi.fn() },
}))

const getMock = vi.fn()
const reviewMock = vi.fn()
vi.mock('../../api', async () => {
  const actual = await vi.importActual<typeof import('../../api')>('../../api')
  return {
    ...actual,
    videoApi: {
      get: (...args: unknown[]) => getMock(...args),
      review: (...args: unknown[]) => reviewMock(...args),
    },
  }
})

const auth = { user: { role: 'admin', is_superuser: false } }
vi.mock('../../auth', () => ({ useAuth: () => auth }))

const DETAIL = {
  id: 'asset-1',
  title: '機台復歸示範',
  status: 'review_required',
  created_at: '2026-08-26T00:00:00Z',
  revision_id: 'revision-1',
  duration_ms: 10_000,
  media_type: 'video/mp4',
  probe: {},
  content_url: '/api/v1/media/videos/asset-1/content?token=signed',
  job: { id: 'job-1', status: 'review_required', phase: 'human_review', quality_state: 'review_required', readiness: {}, error: {} },
  artifacts: [
    {
      id: 'transcript-1', kind: 'transcript_segment', quality_state: 'review_required', confidence: 0.9,
      content: '先確認壓力歸零', metadata: { start_ms: 1000 }, content_url: null, review: null,
      evidence: [{ id: 'e1', locator_kind: 'video', start_ms: 1000, end_ms: 3000, frame_index: null, speaker: '師傅', deep_link: '/knowledge/videos/asset-1?t=1000' }],
    },
    {
      id: 'procedure-1', kind: 'procedure_candidate', quality_state: 'review_required', confidence: null,
      content: { steps: [{ sequence: 1, text: '先確認壓力歸零', start_ms: 1000, evidence_artifact_id: 'transcript-1' }] },
      metadata: {}, content_url: null, review: null,
      evidence: [{ id: 'e2', locator_kind: 'video', start_ms: 1000, end_ms: 3000, frame_index: null, speaker: null, deep_link: '/knowledge/videos/asset-1?t=1000' }],
    },
  ],
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/knowledge/videos/asset-1?t=1000']}>
      <Routes><Route path="/knowledge/videos/:assetId" element={<VideoReviewPage />} /></Routes>
    </MemoryRouter>,
  )
}

describe('VideoReviewPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    getMock.mockResolvedValue(structuredClone(DETAIL))
    reviewMock.mockResolvedValue({ decision: 'approved' })
  })

  it('顯示簽章影片、時間軸證據與待審步驟', async () => {
    const { container } = renderPage()
    expect(await screen.findByRole('heading', { name: '機台復歸示範' })).toBeInTheDocument()
    expect(screen.getAllByText('先確認壓力歸零')).toHaveLength(2)
    expect(container.querySelector('video')).toHaveAttribute('src', DETAIL.content_url)
    expect(screen.getAllByText('0:01')).toHaveLength(2)
  })

  it('管理者核准後重載發布狀態', async () => {
    renderPage()
    await userEvent.type(await screen.findByLabelText('覆核備註（選填）'), '已對照畫面')
    await userEvent.click(screen.getByRole('button', { name: /核准發布/ }))
    await waitFor(() => expect(reviewMock).toHaveBeenCalledWith(
      'procedure-1',
      'approved',
      '已對照畫面',
      { conflictResolutions: {}, acknowledgeHighRisk: false },
    ))
    expect(getMock).toHaveBeenCalledTimes(2)
  })
})
