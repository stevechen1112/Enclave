import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { vi, describe, it, expect, beforeEach } from 'vitest'
import ApprovalsPage from './ApprovalsPage'

vi.mock('react-hot-toast', () => ({
  default: { error: vi.fn(), success: vi.fn() },
}))
import toast from 'react-hot-toast'

const decideMock = vi.fn()
const inboxMock = vi.fn()
vi.mock('../../services/mka', () => ({
  approvalsApi: {
    inbox: (...args: unknown[]) => inboxMock(...args),
    decide: (...args: unknown[]) => decideMock(...args),
  },
}))

const PENDING = {
  id: 'a1b2c3d4-0000-0000-0000-000000000001',
  object_type: 'form_instance',
  object_id: 'f1',
  current_step: 1,
  record_version: 3,
  status: 'pending',
  submitted_by: 'u1',
  reviewers: ['owner'],
  decision_log: [],
  immutable_snapshot: {
    values: { customer: '台中精機', part_number: 'P-100', quantity: 200, unit_price: 120 },
  },
  created_at: '2026-08-06T01:00:00+00:00',
}

function renderPage() {
  return render(
    <MemoryRouter>
      <ApprovalsPage />
    </MemoryRouter>,
  )
}

describe('ApprovalsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    inboxMock.mockResolvedValue([PENDING])
    decideMock.mockResolvedValue({ ...PENDING, status: 'approved' })
  })

  it('載入待審核清單並顯示快照摘要', async () => {
    renderPage()
    expect(await screen.findByText('表單')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /表單/ }))
    expect(await screen.findByText('台中精機')).toBeInTheDocument()
    expect(screen.getByText('P-100')).toBeInTheDocument()
  })

  it('核准需二次確認，確認後帶 record_version 送出', async () => {
    renderPage()
    await userEvent.click(await screen.findByRole('button', { name: /表單/ }))
    await userEvent.click(screen.getByRole('button', { name: '核准' }))
    // 二次確認面板出現
    expect(screen.getByText(/核准後就不能再修改內容/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '確定核准' }))
    await waitFor(() =>
      expect(decideMock).toHaveBeenCalledWith(PENDING.id, 'approve', 3, ''),
    )
  })

  it('駁回未填原因時阻擋並提示', async () => {
    renderPage()
    await userEvent.click(await screen.findByRole('button', { name: /表單/ }))
    await userEvent.click(screen.getByRole('button', { name: /駁回/ }))
    expect(toast.error).toHaveBeenCalledWith(expect.stringContaining('原因'))
    expect(decideMock).not.toHaveBeenCalled()
  })

  it('空收件匣顯示友善空狀態', async () => {
    inboxMock.mockResolvedValue([])
    renderPage()
    expect(await screen.findByText('目前沒有待審核的單據')).toBeInTheDocument()
  })
})
