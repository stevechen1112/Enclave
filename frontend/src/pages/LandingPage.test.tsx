import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import LandingPage from './LandingPage'

const auth = vi.hoisted(() => ({
  demoLogin: vi.fn(),
}))

vi.mock('../auth', () => ({
  useAuth: () => ({ demoLogin: auth.demoLogin }),
}))

vi.mock('react-hot-toast', () => ({
  default: { success: vi.fn(), error: vi.fn() },
}))

describe('LandingPage', () => {
  beforeEach(() => {
    auth.demoLogin.mockReset()
    auth.demoLogin.mockResolvedValue(undefined)
  })

  it('explains the manufacturing problem and exposes all six demo doors', () => {
    render(<MemoryRouter><LandingPage /></MemoryRouter>)

    expect(screen.getByRole('heading', { name: /公司資料找得到/ })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '工廠每天都在遇到的四件事' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /選一位同事/ })).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: /進入 Demo/ })).toHaveLength(6)
    expect(screen.getByAltText('老師傅與年輕技術人員在工廠設備旁討論設定')).toBeInTheDocument()
    expect(screen.getAllByText(/第 \d{2} 道門/)).toHaveLength(6)
    expect(screen.getAllByRole('link', { name: /企業.*登入/ })).toHaveLength(2)
    expect(screen.getAllByRole('link', { name: /企業.*登入/ }).every(link => link.getAttribute('href') === '/login')).toBe(true)
  })

  it('opens a selected demo persona without credentials', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/']}>
        <Routes>
          <Route path="/" element={<LandingPage />} />
          <Route path="/login" element={<p>登入導頁</p>} />
        </Routes>
      </MemoryRouter>,
    )

    await user.click(screen.getByRole('button', { name: '以班長／師傅進入 Demo' }))

    expect(auth.demoLogin).toHaveBeenCalledWith('master')
    expect(await screen.findByText('登入導頁')).toBeInTheDocument()
  })
})
