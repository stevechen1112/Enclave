import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import LoginPage from './LoginPage'

const mocks = vi.hoisted(() => ({
  login: vi.fn(),
  demoLogin: vi.fn(),
  loginOptions: vi.fn(),
}))

vi.mock('../auth', () => ({
  useAuth: () => ({ login: mocks.login, demoLogin: mocks.demoLogin }),
}))

vi.mock('../api', () => ({
  authApi: { loginOptions: mocks.loginOptions },
}))

describe('LoginPage authentication modes', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.login.mockResolvedValue(undefined)
    mocks.demoLogin.mockResolvedValue(undefined)
    mocks.loginOptions.mockResolvedValue({ password_enabled: true, demo_enabled: false })
  })

  it('uses company credentials as the primary login path', async () => {
    const user = userEvent.setup()
    render(<MemoryRouter><LoginPage /></MemoryRouter>)

    await user.type(screen.getByLabelText('電子郵件'), 'admin@example.com')
    await user.type(screen.getByLabelText('密碼'), 'correct horse battery staple')
    await user.click(screen.getByRole('button', { name: '登入' }))

    expect(mocks.login).toHaveBeenCalledWith(
      'admin@example.com',
      'correct horse battery staple',
    )
    expect(screen.queryByText('查看合成 Demo 角色')).not.toBeInTheDocument()
  })

  it('fails closed when login-mode discovery is unavailable', async () => {
    mocks.loginOptions.mockRejectedValue(new Error('offline'))
    render(<MemoryRouter><LoginPage /></MemoryRouter>)

    await waitFor(() => expect(mocks.loginOptions).toHaveBeenCalledOnce())
    expect(screen.getByLabelText('電子郵件')).toBeInTheDocument()
    expect(screen.queryByText('查看合成 Demo 角色')).not.toBeInTheDocument()
  })

  it('shows passwordless personas only when the server enables Demo', async () => {
    mocks.loginOptions.mockResolvedValue({ password_enabled: true, demo_enabled: true })
    const user = userEvent.setup()
    render(<MemoryRouter><LoginPage /></MemoryRouter>)

    const disclosure = await screen.findByText('查看合成 Demo 角色')
    await user.click(disclosure)
    const doors = screen.getAllByRole('button', { name: /進入 Demo/ })
    expect(doors).toHaveLength(6)
    await user.click(screen.getByRole('button', { name: '以業務進入 Demo' }))
    expect(mocks.demoLogin).toHaveBeenCalledWith('sales')
  })
})
