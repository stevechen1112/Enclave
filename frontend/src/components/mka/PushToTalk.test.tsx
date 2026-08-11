import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { vi, describe, it, expect } from 'vitest'
import PushToTalk from './PushToTalk'

vi.mock('react-hot-toast', () => ({
  default: { error: vi.fn(), success: vi.fn() },
}))

describe('PushToTalk', () => {
  it('預設顯示「點一下開始說話」與大按鈕', () => {
    render(<PushToTalk onResult={vi.fn()} />)
    expect(screen.getByText('點一下開始說話')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '開始語音輸入' })).toBeEnabled()
  })

  it('瀏覽器不支援錄音時回報可執行的錯誤訊息', async () => {
    // jsdom 無 MediaRecorder → 走降級錯誤路徑
    const onError = vi.fn()
    render(<PushToTalk onResult={vi.fn()} onError={onError} />)
    await userEvent.click(screen.getByRole('button', { name: '開始語音輸入' }))
    expect(onError).toHaveBeenCalledWith(
      expect.stringContaining('不支援錄音'),
    )
  })

  it('disabled 時按鈕不可點', () => {
    render(<PushToTalk onResult={vi.fn()} disabled />)
    expect(screen.getByRole('button', { name: '開始語音輸入' })).toBeDisabled()
  })
})
