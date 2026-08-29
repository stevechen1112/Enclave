import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../api', () => ({
  chatApi: {
    conversations: vi.fn(),
    messages: vi.fn(),
    stream: vi.fn(),
    deleteConversation: vi.fn(),
    exportConversation: vi.fn(),
    searchConversations: vi.fn(),
    submitFeedback: vi.fn(),
  },
  parseApiError: vi.fn(() => ({ message: 'error', retryable: true })),
  formatErrorWithTrace: vi.fn(() => 'error'),
}))

vi.mock('../auth', () => ({
  useAuth: () => ({ user: { full_name: '林組長' } }),
}))

vi.mock('../navigation/useCapabilities', () => ({
  useHasCapability: () => true,
}))

import { chatApi } from '../api'
import ChatPage from './ChatPage'

const conversation = {
  id: 'conv-1',
  user_id: 'user-1',
  tenant_id: 'tenant-1',
  title: 'A-03 安全門處理',
  created_at: '2026-08-29T01:00:00Z',
}

const source = {
  title: 'A 系列機台安全操作標準',
  document_id: 'doc-1',
  document_revision: 4,
  page: 12,
  snippet: '安全門紅燈時，不得強制復歸。',
  updated_at: '2026-08-28T00:00:00Z',
  accessible: true,
}

describe('ChatPage A decision workspace', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    Object.defineProperty(window, 'matchMedia', {
      configurable: true,
      value: vi.fn().mockReturnValue({ matches: false, addListener: vi.fn(), removeListener: vi.fn() }),
    })
    Element.prototype.scrollIntoView = vi.fn()
    vi.mocked(chatApi.conversations).mockResolvedValue([conversation])
    vi.mocked(chatApi.messages).mockResolvedValue([
      {
        id: 'user-1', conversation_id: conversation.id, role: 'user',
        content: 'A-03 安全門亮紅燈能直接復歸嗎？', created_at: '2026-08-29T01:01:00Z',
        sources: undefined,
      },
      {
        id: 'answer-1', conversation_id: conversation.id, role: 'assistant',
        content: '不可以。請先停機並檢查門鎖與感測器。', created_at: '2026-08-29T01:01:05Z',
        sources: [source],
      },
    ])
  })

  it('keeps the empty ask entry focused and moves history into a drawer', async () => {
    render(<MemoryRouter><ChatPage /></MemoryRouter>)

    expect(await screen.findByText('林組長，開始提問')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '開啟對話記錄' }))
    expect(screen.getByRole('dialog', { name: '對話記錄' })).toBeInTheDocument()
    expect(await screen.findByText('A-03 安全門處理')).toBeInTheDocument()
  })

  it('renders the latest question as a decision page with traceable evidence', async () => {
    render(<MemoryRouter><ChatPage /></MemoryRouter>)

    await userEvent.click(screen.getByRole('button', { name: '開啟對話記錄' }))
    await userEvent.click(await screen.findByRole('button', { name: /^A-03 安全門處理/ }))

    await waitFor(() => expect(chatApi.messages).toHaveBeenCalledWith(conversation.id))
    expect(await screen.findByRole('heading', { level: 3, name: 'A-03 安全門亮紅燈能直接復歸嗎？' })).toBeInTheDocument()
    expect(screen.getByText('建立可追溯回答')).toBeInTheDocument()
    expect(screen.getByText('直接回答')).toBeInTheDocument()
    expect(screen.getByText(/請先停機並檢查門鎖與感測器/)).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: /查看答案證據/ }))
    expect(screen.getByRole('dialog', { name: '答案證據' })).toBeInTheDocument()
    expect(screen.getByText('A 系列機台安全操作標準')).toBeInTheDocument()
  })
})
