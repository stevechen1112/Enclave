import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../../api', () => ({
  default: { get: vi.fn(() => Promise.resolve({ data: [] })) },
  knowledgeAssetApi: { list: vi.fn() },
  parseApiError: vi.fn(() => ({ message: 'error', retryable: true })),
}))
vi.mock('../../navigation/useCapabilities', () => ({ useHasCapability: vi.fn(() => true) }))

import { knowledgeAssetApi } from '../../api'
import AssetLibraryPage from './AssetLibraryPage'

const list = vi.mocked(knowledgeAssetApi.list)

describe('AssetLibraryPage', () => {
  beforeEach(() => {
    list.mockReset()
    list.mockResolvedValue([
      { id: 'asset-1', asset_kind: 'video', title: '換線教學', source_system: 'upload', data_classification: 'internal', status: 'processing', current_revision: 1, created_at: '2026-08-27T00:00:00Z', updated_at: null, tombstoned_at: null, metadata: {}, revision: null, job: { id: 'job-1', status: 'running', phase: 'ocr', quality_state: 'provisional', adapter_key: 'core.video', adapter_version: '1', requested_capabilities: [], readiness: {}, error: {}, attempt: 1, created_at: '2026-08-27T00:00:00Z', completed_at: null } },
      { id: 'asset-2', asset_kind: 'document', title: '安全規範', source_system: 'nas_smb', data_classification: 'internal', status: 'active', current_revision: 2, created_at: '2026-08-26T00:00:00Z', updated_at: null, tombstoned_at: null, metadata: {}, revision: null, job: null },
    ])
  })

  it('shows mixed media in one library and filters by name', async () => {
    render(<MemoryRouter><AssetLibraryPage /></MemoryRouter>)
    expect(await screen.findByText('換線教學')).toBeInTheDocument()
    expect(screen.getByText('安全規範')).toBeInTheDocument()
    await userEvent.type(screen.getByPlaceholderText('搜尋名稱'), '安全')
    expect(screen.queryByText('換線教學')).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: /新增知識/ })).toHaveAttribute('href', '/knowledge/new')
  })

  it('sends lifecycle filters to the unified endpoint', async () => {
    render(<MemoryRouter><AssetLibraryPage /></MemoryRouter>)
    await screen.findByText('換線教學')
    await userEvent.selectOptions(screen.getByLabelText('資產類型'), 'video')
    await waitFor(() => expect(list).toHaveBeenLastCalledWith(expect.objectContaining({ kind: 'video' })))
    expect(screen.getAllByRole('button', { name: '清除篩選' })).toHaveLength(1)
  })

  it('honours a lifecycle deep link from the dashboard', async () => {
    render(<MemoryRouter initialEntries={['/knowledge/assets?status=needs_attention']}><AssetLibraryPage /></MemoryRouter>)
    await waitFor(() => expect(list).toHaveBeenCalledWith(expect.objectContaining({ processing_status: 'needs_attention' })))
    expect(screen.getByLabelText('處理狀態')).toHaveValue('needs_attention')
  })
})
