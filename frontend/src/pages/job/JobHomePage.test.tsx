import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { vi, describe, it, expect, beforeEach } from 'vitest'
import JobHomePage from './JobHomePage'

vi.mock('react-hot-toast', () => ({
  default: { error: vi.fn(), success: vi.fn() },
}))

const mockAuth: { user: { role: string; is_superuser: boolean; full_name?: string } | null } = {
  user: { role: 'employee', is_superuser: false, full_name: '阿明' },
}
vi.mock('../../auth', () => ({
  useAuth: () => ({ user: mockAuth.user }),
}))

const inboxMock = vi.fn()
const listInstancesMock = vi.fn()
vi.mock('../../services/mka', () => ({
  voiceApi: { transcribe: vi.fn(), confirmTranscript: vi.fn() },
  sceneApi: { resolve: vi.fn() },
  approvalsApi: { inbox: (...args: unknown[]) => inboxMock(...args) },
  formsApi: { listInstances: (...args: unknown[]) => listInstancesMock(...args) },
}))

function renderPage() {
  return render(
    <MemoryRouter>
      <JobHomePage />
    </MemoryRouter>,
  )
}

describe('JobHomePage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    inboxMock.mockResolvedValue([])
    listInstancesMock.mockResolvedValue([])
  })

  it('顯示語音、掃碼、所有常用工作入口', async () => {
    renderPage()
    expect(await screen.findByText(/阿明/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '開始語音輸入' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /掃描設備/ })).toBeInTheDocument()
    // bootstrap 無 workspace_entries 時的 fallback 入口（現況快照）
    expect(screen.getByRole('button', { name: /開報價單/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /異常回報/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /交接班/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /師傅經驗庫/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /問知識庫/ })).toBeInTheDocument()
  })

  it('一般員工不顯示審核提醒', async () => {
    renderPage()
    await screen.findByText(/阿明/)
    expect(inboxMock).not.toHaveBeenCalled()
    expect(screen.queryByText(/等你審核/)).not.toBeInTheDocument()
  })

  it('主管有待審單據時顯示提醒橫幅', async () => {
    mockAuth.user = { role: 'owner', is_superuser: false, full_name: '老闆' }
    inboxMock.mockResolvedValue([{ id: 'a1' }, { id: 'a2' }])
    renderPage()
    expect(await screen.findByText(/2 張單據等你審核/)).toBeInTheDocument()
    mockAuth.user = { role: 'employee', is_superuser: false, full_name: '阿明' }
  })
})
