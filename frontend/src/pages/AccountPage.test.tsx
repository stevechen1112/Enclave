import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import AccountPage from './AccountPage'

const mocks = vi.hoisted(() => ({
  changePassword: vi.fn(),
  logout: vi.fn(),
}))

vi.mock('../api', () => ({
  authApi: { changePassword: mocks.changePassword },
}))

vi.mock('../auth', () => ({
  useAuth: () => ({
    user: {
      email: 'steve_chen@premierbiz.com.tw',
      full_name: '陳宥竹',
      role: 'owner',
    },
    experience: {
      organization: {
        name: '八策股份有限公司',
        department_name: '管理部',
        environment_label: '正式企業工作區',
      },
    },
    logout: mocks.logout,
  }),
}))

describe('AccountPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.changePassword.mockResolvedValue(undefined)
  })

  it('shows the authenticated company environment', () => {
    render(<MemoryRouter><AccountPage /></MemoryRouter>)

    expect(screen.getByText('八策股份有限公司')).toBeInTheDocument()
    expect(screen.getByText('管理部')).toBeInTheDocument()
    expect(screen.getByText('正式企業工作區')).toBeInTheDocument()
    expect(screen.getByText('陳宥竹')).toBeInTheDocument()
    expect(screen.getByText('權限層級：擁有者')).toBeInTheDocument()
  })

  it('changes the password and requires a fresh login', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/me/account']}>
        <Routes>
          <Route path="/me/account" element={<AccountPage />} />
          <Route path="/login" element={<div>重新登入頁</div>} />
        </Routes>
      </MemoryRouter>,
    )

    await user.type(screen.getByLabelText('目前密碼'), 'OriginalPass123!')
    await user.type(screen.getByLabelText('新密碼', { exact: true }), 'ReplacementPass456!')
    await user.type(screen.getByLabelText('再輸入一次新密碼'), 'ReplacementPass456!')
    await user.click(screen.getByRole('button', { name: '更新密碼' }))

    expect(mocks.changePassword).toHaveBeenCalledWith('OriginalPass123!', 'ReplacementPass456!')
    expect(mocks.logout).toHaveBeenCalledOnce()
    expect(await screen.findByText('重新登入頁')).toBeInTheDocument()
  })

  it('rejects mismatched confirmation before calling the API', async () => {
    const user = userEvent.setup()
    render(<MemoryRouter><AccountPage /></MemoryRouter>)

    await user.type(screen.getByLabelText('目前密碼'), 'OriginalPass123!')
    await user.type(screen.getByLabelText('新密碼', { exact: true }), 'ReplacementPass456!')
    await user.type(screen.getByLabelText('再輸入一次新密碼'), 'DifferentPass789!')
    await user.click(screen.getByRole('button', { name: '更新密碼' }))

    expect(screen.getByRole('alert')).toHaveTextContent('兩次輸入的新密碼不一致')
    expect(mocks.changePassword).not.toHaveBeenCalled()
  })
})
