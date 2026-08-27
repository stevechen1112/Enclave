import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../../api', () => ({
  knowledgeAssetApi: { create: vi.fn() },
  parseApiError: vi.fn(),
  formatErrorWithTrace: vi.fn(),
}))

import AddKnowledgePage from './AddKnowledgePage'
import { knowledgeAssetApi } from '../../api'

const create = vi.mocked(knowledgeAssetApi.create)

describe('AddKnowledgePage', () => {
  beforeEach(() => {
    create.mockReset()
    create.mockResolvedValue({ id: 'asset-1', deduplicated: false } as never)
  })

  it('offers one accessible intake for files, URLs, and external records', async () => {
    render(<MemoryRouter><AddKnowledgePage /></MemoryRouter>)
    expect(screen.getByRole('tab', { name: '上傳／拍攝' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByText('選擇檔案、照片、錄音或影片')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('tab', { name: '貼上網址' }))
    expect(screen.getByRole('textbox', { name: '網址' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('tab', { name: '外部紀錄' }))
    expect(screen.getByRole('textbox', { name: '來源系統' })).toBeInTheDocument()
    expect(screen.getByRole('textbox', { name: '紀錄識別碼' })).toBeInTheDocument()
  })

  it('submits multiple files as independently tracked asset requests', async () => {
    render(<MemoryRouter><AddKnowledgePage /></MemoryRouter>)
    const input = screen.getByLabelText('選擇檔案')
    const first = new File(['manual'], 'manual.pdf', { type: 'application/pdf', lastModified: 1 })
    const second = new File(['video'], 'changeover.mp4', { type: 'video/mp4', lastModified: 2 })
    await userEvent.upload(input, [first, second])
    expect(screen.getByText('manual.pdf')).toBeInTheDocument()
    expect(screen.getByText('changeover.mp4')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '加入 2 筆公司知識' }))
    await waitFor(() => expect(create).toHaveBeenCalledTimes(2))
    expect(create).toHaveBeenNthCalledWith(1, expect.objectContaining({ file: first, dataClassification: 'internal' }), expect.any(Function))
    expect(create).toHaveBeenNthCalledWith(2, expect.objectContaining({ file: second, dataClassification: 'internal' }), expect.any(Function))
  })
})
