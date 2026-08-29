import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../../api', () => ({
  default: { get: vi.fn(), post: vi.fn(), patch: vi.fn() },
  knowledgeAssetApi: { create: vi.fn(), capabilities: vi.fn(), departments: vi.fn() },
  uploadSessionApi: { abort: vi.fn() },
  parseApiError: vi.fn(),
  formatErrorWithTrace: vi.fn(),
}))

import AddKnowledgePage from './AddKnowledgePage'
import { knowledgeAssetApi } from '../../api'

const create = vi.mocked(knowledgeAssetApi.create)
const capabilities = vi.mocked(knowledgeAssetApi.capabilities)
const departments = vi.mocked(knowledgeAssetApi.departments)

const capabilityContract = {
  contract_version: 'input.v1', registry_sha256: 'a'.repeat(64), tenant_id: 'tenant-1',
  policy: { accepted_modes: ['file'], data_classifications: ['public', 'internal', 'confidential', 'restricted'], generic_resumable_upload: false, resumable_part_size: 8_388_608, resumable_min_part_size: 262_144, resumable_max_part_size: 16_777_216, resumable_max_parts: 10_000, resumable_session_ttl_hours: 24, video_allowed_codecs: ['h264'] },
  formats: [
    { extension: '.pdf', media_type: 'application/pdf', parser_kind: 'document', asset_kind: 'document', capabilities: ['extract_text', 'layout'], evidence_state: 'internally_verified', ui_default: true, max_bytes: 1000, max_duration_seconds: null, processing_status: 'configured', degradation_reasons: [] },
    { extension: '.mp4', media_type: 'video/mp4', parser_kind: 'video', asset_kind: 'video', capabilities: ['transcribe', 'keyframes'], evidence_state: 'environment_validation_pending', ui_default: true, max_bytes: 1000, max_duration_seconds: null, processing_status: 'configured', degradation_reasons: [] },
  ],
  providers: [],
  quota: { max_documents: 10, current_documents: 0, remaining_documents: 10, max_storage_bytes: 10_000, current_storage_bytes: 0, remaining_storage_bytes: 10_000, warnings: [] },
} as const

describe('AddKnowledgePage', () => {
  beforeEach(() => {
    create.mockReset()
    create.mockResolvedValue({ id: 'asset-1', deduplicated: false } as never)
    capabilities.mockReset()
    capabilities.mockResolvedValue(capabilityContract as never)
    departments.mockReset()
    departments.mockResolvedValue([])
  })

  it('offers one accessible intake for files, URLs, and external records', async () => {
    render(<MemoryRouter><AddKnowledgePage /></MemoryRouter>)
    await screen.findByText(/此環境可處理/)
    expect(screen.getByRole('tab', { name: '上傳檔案' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('tab', { name: '現場擷取' })).toBeInTheDocument()
    expect(screen.getByText('選擇檔案、照片、錄音或影片')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('tab', { name: '貼上網址' }))
    expect(screen.getByRole('textbox', { name: '網址' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('tab', { name: '外部紀錄' }))
    expect(screen.getByRole('textbox', { name: '來源系統' })).toBeInTheDocument()
    expect(screen.getByRole('textbox', { name: '紀錄識別碼' })).toBeInTheDocument()
  })

  it('submits multiple files as independently tracked asset requests', async () => {
    render(<MemoryRouter><AddKnowledgePage /></MemoryRouter>)
    await screen.findByText(/此環境可處理/)
    const input = screen.getByLabelText('選擇檔案')
    const first = new File(['manual'], 'manual.pdf', { type: 'application/pdf', lastModified: 1 })
    const second = new File(['video'], 'changeover.mp4', { type: 'video/mp4', lastModified: 2 })
    await userEvent.upload(input, [first, second])
    expect(screen.getByText('manual.pdf')).toBeInTheDocument()
    expect(screen.getByText('changeover.mp4')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '加入 2 筆公司知識' }))
    await waitFor(() => expect(create).toHaveBeenCalledTimes(2))
    expect(create).toHaveBeenNthCalledWith(1, expect.objectContaining({ file: first, dataClassification: 'internal', idempotencyKey: expect.any(String) }), expect.objectContaining({ onProgress: expect.any(Function), signal: expect.any(AbortSignal) }))
    expect(create).toHaveBeenNthCalledWith(2, expect.objectContaining({ file: second, dataClassification: 'internal', idempotencyKey: expect.any(String) }), expect.objectContaining({ onProgress: expect.any(Function), signal: expect.any(AbortSignal) }))
  })
})
