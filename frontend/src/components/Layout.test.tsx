import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import Layout from './Layout'

const auth = vi.hoisted(() => ({
  logout: vi.fn(),
}))

vi.mock('../auth', () => ({
  useAuth: () => ({
    user: {
      email: 'field-door@demo.enclave.invalid',
      full_name: '現場測試 李阿明',
      role: 'employee',
      is_superuser: false,
    },
    experience: {
      organization: { name: '八策股份有限公司' },
    },
    logout: auth.logout,
  }),
}))

vi.mock('../navigation/useCapabilities', () => ({
  useDefaultHomePath: () => '/overview',
  useHasCapability: () => false,
  usePrimaryNav: () => [
    { to: '/overview', label: '總覽', capability: 'home' },
    { to: '/ask', label: '問答', capability: 'ask' },
  ],
}))

vi.mock('./ReadinessBanner', () => ({ default: () => null }))
vi.mock('./InferenceBanner', () => ({ default: () => null }))

describe('Layout user menu', () => {
  beforeEach(() => {
    auth.logout.mockReset()
  })

  it('allows the visible desktop account disclosure to log out', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/overview']}>
        <Routes>
          <Route path="/" element={<Layout />}>
            <Route path="overview" element={<div>工作頁</div>} />
          </Route>
          <Route path="/login" element={<div>登入頁</div>} />
        </Routes>
      </MemoryRouter>,
    )

    await user.click(screen.getAllByRole('button', { name: /現場測試 李阿明/ })[0])
    await user.click(screen.getAllByRole('button', { name: '登出' })[0])

    expect(auth.logout).toHaveBeenCalledOnce()
    expect(screen.getByText('登入頁')).toBeInTheDocument()
  })

  it('shows the tenant workspace and exposes account security', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/overview']}>
        <Routes>
          <Route path="/" element={<Layout />}>
            <Route path="overview" element={<div>工作頁</div>} />
            <Route path="me/account" element={<div>帳號安全頁</div>} />
          </Route>
        </Routes>
      </MemoryRouter>,
    )

    expect(screen.getByRole('link', { name: /八策股份有限公司/ })).toBeInTheDocument()
    await user.click(screen.getAllByRole('button', { name: /現場測試 李阿明/ })[0])
    await user.click(screen.getAllByRole('link', { name: '我的帳號' })[0])
    expect(screen.getByText('帳號安全頁')).toBeInTheDocument()
  })

  it('uses the same server navigation in shell, mobile menu and command palette', async () => {
    const user = userEvent.setup()
    render(<MemoryRouter initialEntries={['/overview']}><Routes><Route path="/" element={<Layout />}><Route path="overview" element={<div>工作頁</div>} /></Route></Routes></MemoryRouter>)

    expect(screen.getAllByRole('link', { name: '總覽' })).toHaveLength(1)
    expect(screen.getAllByRole('link', { name: '問答' })).toHaveLength(1)
    await user.click(screen.getByRole('button', { name: '開啟選單' }))
    expect(screen.getAllByRole('link', { name: '總覽' })).toHaveLength(2)
    expect(screen.getAllByRole('link', { name: '問答' })).toHaveLength(2)
    await user.keyboard('{Control>}k{/Control}')
    expect(screen.getByRole('dialog', { name: '前往功能' })).toBeInTheDocument()
    expect(screen.getAllByRole('link', { name: /總覽/ })).toHaveLength(3)
    expect(screen.queryByRole('link', { name: /現場作業/ })).not.toBeInTheDocument()
    await waitFor(() => expect(screen.getByRole('textbox', { name: '搜尋可用功能' })).toHaveFocus())
  })
})
