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
    mocks.loginOptions.mockResolvedValue({ password_enabled: true, demo_enabled: true })
    render(<MemoryRouter initialEntries={['/login?mode=enterprise']}><LoginPage /></MemoryRouter>)

    await user.type(screen.getByLabelText('電子郵件'), 'admin@example.com')
    await user.type(screen.getByLabelText('密碼'), 'correct horse battery staple')
    await user.click(screen.getByRole('button', { name: '登入' }))

    expect(mocks.login).toHaveBeenCalledWith(
      'admin@example.com',
      'correct horse battery staple',
    )
    expect(screen.getByText('正式企業工作區')).toBeInTheDocument()
    expect(screen.queryByText('查看合成 Demo 角色')).not.toBeInTheDocument()
  })

  it('fails closed when login-mode discovery is unavailable', async () => {
    mocks.loginOptions.mockRejectedValue(new Error('offline'))
    render(<MemoryRouter><LoginPage /></MemoryRouter>)

    await waitFor(() => expect(mocks.loginOptions).toHaveBeenCalledOnce())
    expect(screen.getByLabelText('電子郵件')).toBeInTheDocument()
    expect(screen.queryByText('查看合成 Demo 角色')).not.toBeInTheDocument()
  })

  it('confirms a completed password rotation without exposing Demo', async () => {
    mocks.loginOptions.mockResolvedValue({ password_enabled: true, demo_enabled: true })
    render(
      <MemoryRouter initialEntries={['/login?mode=enterprise&password=changed']}>
        <LoginPage />
      </MemoryRouter>,
    )

    expect(screen.getByRole('status')).toHaveTextContent('密碼已更新')
    expect(screen.queryByText('查看合成 Demo 角色')).not.toBeInTheDocument()
  })

  it('does not misreport gateway throttling as invalid credentials', async () => {
    mocks.login.mockRejectedValue(
      Object.assign(new Error('Request failed'), {
        isAxiosError: true,
        response: { status: 429, data: '' },
      }),
    )
    const user = userEvent.setup()
    render(<MemoryRouter><LoginPage /></MemoryRouter>)

    await user.type(screen.getByLabelText('電子郵件'), 'admin@example.com')
    await user.type(screen.getByLabelText('密碼'), 'password')
    await user.click(screen.getByRole('button', { name: '登入' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('登入嘗試過於頻繁')
    expect(screen.getByRole('alert')).not.toHaveTextContent('帳號或密碼不正確')
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
