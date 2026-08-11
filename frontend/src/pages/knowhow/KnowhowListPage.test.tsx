import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { vi, describe, it, expect, beforeEach } from 'vitest'
import KnowhowListPage from './KnowhowListPage'

vi.mock('react-hot-toast', () => ({
  default: { error: vi.fn(), success: vi.fn() },
}))

const listMock = vi.fn()
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
    expect(screen.getByRole('button', { name: /記下一筆經驗/ })).toBeInTheDocument()
  })
})
