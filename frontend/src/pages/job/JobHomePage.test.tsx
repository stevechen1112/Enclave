import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { vi, describe, it, expect, beforeEach } from 'vitest'
import JobHomePage from './JobHomePage'

vi.mock('react-hot-toast', () => ({
  default: { error: vi.fn(), success: vi.fn() },
}))

const mockAuth: {
  user: { role: string; is_superuser: boolean; full_name?: string } | null
  experience?: Record<string, unknown>
  refreshExperience: ReturnType<typeof vi.fn>
} = {
  user: { role: 'employee', is_superuser: false, full_name: '阿明' },
  refreshExperience: vi.fn(async () => undefined),
}
vi.mock('../../auth', () => ({
  useAuth: () => ({
    user: mockAuth.user,
    experience: mockAuth.experience,
    refreshExperience: mockAuth.refreshExperience,
  }),
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
    mockAuth.experience = undefined
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

  it('進入工作台不會重複重新載入已由登入流程取得的體驗設定', async () => {
    mockAuth.experience = { workspace_entries: [], ui_modules: [] }
    renderPage()

    await screen.findByText(/阿明/)
    expect(mockAuth.refreshExperience).not.toHaveBeenCalled()
  })

  it('bootstrap 已載入但模組為空時不復活本地 fallback 工作', async () => {
    mockAuth.experience = { workspace_entries: [], ui_modules: [] }
    renderPage()

    await screen.findByText(/阿明/)
    expect(screen.queryByRole('button', { name: /開報價單/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /師傅經驗庫/ })).not.toBeInTheDocument()
  })

  it('沒有待處理單據時仍可進入我的表單查看已核准文件', async () => {
    renderPage()
    expect(await screen.findByRole('button', { name: /我的表單/ })).toBeInTheDocument()
    expect(screen.queryByText(/張待處理/)).not.toBeInTheDocument()
  })

  it('Demo 主管唯讀顯示可用的檢視入口，不誤稱等待職能指派', async () => {
    mockAuth.user = { role: 'viewer', is_superuser: false, full_name: '主管唯讀展示' }
    mockAuth.experience = {
      demo_mode: true,
      needs_job_role_assignment: true,
      workspace_entries: [],
      job_role_assignments: [],
    }

    renderPage()

    expect(await screen.findByText(/主管檢視模式/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /查看知識文件/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /查看師傅經驗/ })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /我的表單/ })).not.toBeInTheDocument()
    expect(screen.queryByText('尚未指派職能')).not.toBeInTheDocument()
    mockAuth.user = { role: 'employee', is_superuser: false, full_name: '阿明' }
  })
})
