import { render, screen } from '@testing-library/react'
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
    experience: null,
    logout: auth.logout,
  }),
}))

vi.mock('../navigation/useCapabilities', () => ({
  useDefaultHomePath: () => '/job',
  useHasCapability: () => false,
  usePrimaryNav: () => [],
}))

vi.mock('./ReadinessBanner', () => ({ default: () => null }))
vi.mock('./InferenceBanner', () => ({ default: () => null }))

describe('Layout user menu', () => {
  beforeEach(() => {
    auth.logout.mockReset()
  })

  it('allows the visible desktop menu to log out when desktop and mobile sidebars coexist', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/job']}>
        <Routes>
          <Route path="/" element={<Layout />}>
            <Route path="job" element={<div>工作頁</div>} />
          </Route>
          <Route path="/login" element={<div>登入頁</div>} />
        </Routes>
      </MemoryRouter>,
    )

    await user.click(screen.getAllByRole('button', { name: /現場測試 李阿明/ })[0])
    await user.click(screen.getAllByRole('menuitem', { name: '登出' })[0])

    expect(auth.logout).toHaveBeenCalledOnce()
    expect(screen.getByText('登入頁')).toBeInTheDocument()
  })
})
