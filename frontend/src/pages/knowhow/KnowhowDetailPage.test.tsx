import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import KnowhowDetailPage from './KnowhowDetailPage'

vi.mock('react-hot-toast', () => ({
  default: { error: vi.fn(), success: vi.fn() },
}))

const authState = vi.hoisted(() => ({ roleKey: 'newcomer', securityRole: 'employee' }))
const getMock = vi.fn()

vi.mock('../../auth', () => ({
  useAuth: () => ({
    user: { role: authState.securityRole, is_superuser: false },
    experience: { active_job_role: { role_key: authState.roleKey } },
  }),
}))

vi.mock('../../services/mka', () => ({
  knowhowApi: {
    get: (...args: unknown[]) => getMock(...args),
    update: vi.fn(),
    submit: vi.fn(),
    retire: vi.fn(),
  },
}))

const APPROVED_CARD = {
  id: 'k1',
  card_id: 'KH-001',
  title: '合成設備校正經驗',
  summary: '僅供 Demo',
  status: 'approved',
  authority_level: 80,
  risk_level: 'low',
  applicable_roles: [],
  equipment_ids: [],
  product_ids: [],
  customer_ids: [],
  steps: ['停機確認'],
  cautions: [],
  recommended_actions: [],
  source_quotes: [],
  version: 1,
  reviewed_at: null,
  retired_at: null,
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/knowhow/k1']}>
      <Routes>
        <Route path="/knowhow/:id" element={<KnowhowDetailPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('KnowhowDetailPage permissions', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    authState.roleKey = 'newcomer'
    authState.securityRole = 'employee'
    getMock.mockResolvedValue(APPROVED_CARD)
  })

  it('新人可讀核准卡，但不顯示管理操作', async () => {
    renderPage()

    expect(await screen.findByText('合成設備校正經驗')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '退休' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '編輯' })).not.toBeInTheDocument()
  })

  it('公司管理員可看到核准卡退休操作', async () => {
    authState.securityRole = 'owner'
    renderPage()

    expect(await screen.findByRole('button', { name: '退休' })).toBeInTheDocument()
  })

  it('師傅看到正式 SOP 差異與修正說明，不誤報為版本衝突', async () => {
    authState.roleKey = 'master'
    getMock.mockResolvedValue({
      ...APPROVED_CARD,
      status: 'draft',
      conflict_report: [{
        conflict_type: 'mutual_exclusion',
        description: '注意事項互斥（SOP: 合成安全SOP）',
        knowhow_value: '可以直接短接安全迴路',
        sop_value: '不得直接短接安全迴路',
        resolved: false,
      }],
    })
    renderPage()

    expect(await screen.findByRole('region', { name: '正式 SOP 差異' })).toBeInTheDocument()
    expect(screen.getByText('內容與正式 SOP 有差異，暫時不能送審')).toBeInTheDocument()
    expect(screen.getByText(/目前經驗：/)).toBeInTheDocument()
    expect(screen.getByText(/正式 SOP：/)).toBeInTheDocument()
  })
})
