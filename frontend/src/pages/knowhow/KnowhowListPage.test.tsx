import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { vi, describe, it, expect, beforeEach } from 'vitest'
import KnowhowListPage from './KnowhowListPage'

vi.mock('react-hot-toast', () => ({
  default: { error: vi.fn(), success: vi.fn() },
}))

const listMock = vi.fn()
const authState = vi.hoisted(() => ({ roleKey: 'master', securityRole: 'employee' }))
vi.mock('../../auth', () => ({
  useAuth: () => ({
    user: { role: authState.securityRole, is_superuser: false },
    experience: { active_job_role: { role_key: authState.roleKey } },
  }),
}))
vi.mock('../../services/mka', () => ({
  knowhowApi: {
    list: (...args: unknown[]) => listMock(...args),
    create: vi.fn(),
  },
}))

const CARD = {
  id: 'k1',
  card_id: 'KH-001',
  title: 'CNC 車床換刀校正',
  summary: '換刀後必校',
  status: 'approved',
  authority_level: 80,
  risk_level: 'high',
  applicable_roles: [],
  equipment_ids: ['CNC-A01'],
  steps: ['停機', '卸刀'],
  cautions: ['戴手套'],
  recommended_actions: [],
  source_quotes: [],
  version: 2,
  reviewed_at: null,
  retired_at: null,
}

function renderPage() {
  return render(
    <MemoryRouter>
      <KnowhowListPage />
    </MemoryRouter>,
  )
}

describe('KnowhowListPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    authState.roleKey = 'master'
    authState.securityRole = 'employee'
  })

  it('列出卡片並以中文徽章顯示狀態與風險', async () => {
    listMock.mockResolvedValue([CARD])
    renderPage()
    expect(await screen.findByText('CNC 車床換刀校正')).toBeInTheDocument()
    expect(screen.getByText('已核准')).toBeInTheDocument()
    expect(screen.getByText('高風險')).toBeInTheDocument()
    expect(screen.getByText(/CNC-A01/)).toBeInTheDocument()
  })

  it('空列表顯示引導文案', async () => {
    listMock.mockResolvedValue([])
    renderPage()
    expect(await screen.findByText('還沒有經驗卡片')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /開始師傅訪談/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /手動建立經驗卡/ })).toBeInTheDocument()
  })

  it('主要入口直接前往長時間訪談頁', async () => {
    listMock.mockResolvedValue([])
    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/knowhow']}>
        <Routes>
          <Route path="/knowhow" element={<KnowhowListPage />} />
          <Route path="/knowhow/interview" element={<div>長時間訪談頁</div>} />
        </Routes>
      </MemoryRouter>,
    )

    await user.click(screen.getByRole('button', { name: /開始師傅訪談/ }))

    expect(screen.getByText('長時間訪談頁')).toBeInTheDocument()
  })

  it('新人只讀卡片，不顯示訪談或手動建立入口', async () => {
    authState.roleKey = 'newcomer'
    listMock.mockResolvedValue([CARD])
    renderPage()

    expect(await screen.findByText('CNC 車床換刀校正')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /開始師傅訪談/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /手動建立經驗卡/ })).not.toBeInTheDocument()
  })
})
