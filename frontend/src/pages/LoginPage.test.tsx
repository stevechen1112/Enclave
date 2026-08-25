import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import LoginPage from './LoginPage'

const auth = vi.hoisted(() => ({
  demoLogin: vi.fn(),
}))

vi.mock('../auth', () => ({
  useAuth: () => ({ demoLogin: auth.demoLogin }),
}))

vi.mock('react-hot-toast', () => ({
  default: { success: vi.fn(), error: vi.fn() },
}))

describe('LoginPage demo doors', () => {
  beforeEach(() => {
    auth.demoLogin.mockReset()
    auth.demoLogin.mockResolvedValue(undefined)
  })

  it('shows six passwordless persona doors', () => {
    render(<MemoryRouter><LoginPage /></MemoryRouter>)

    expect(screen.getAllByRole('button')).toHaveLength(6)
    expect(screen.getByRole('button', { name: '以業務進入 Demo' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '以設備現場進入 Demo' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '以班長／師傅進入 Demo' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '以新人進入 Demo' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '以主管檢視進入 Demo' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '以公司管理進入 Demo' })).toBeInTheDocument()
    expect(screen.getByText(/系統設定不開放修改/)).toBeInTheDocument()
    expect(screen.getByText(/請勿輸入真實客戶資料/)).toBeInTheDocument()
    expect(screen.queryByLabelText('密碼')).not.toBeInTheDocument()
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
  })

  it('enters the selected persona without credentials', async () => {
    const user = userEvent.setup()
    render(<MemoryRouter><LoginPage /></MemoryRouter>)

    await user.click(screen.getByRole('button', { name: '以業務進入 Demo' }))

    expect(auth.demoLogin).toHaveBeenCalledOnce()
    expect(auth.demoLogin).toHaveBeenCalledWith('sales')
  })
})
