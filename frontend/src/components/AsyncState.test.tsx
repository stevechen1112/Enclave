import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import AsyncState from './AsyncState'

describe('AsyncState', () => {
  it('renders loading, empty and partial states with accessible status', () => {
    const { rerender } = render(<AsyncState loading><p>content</p></AsyncState>)
    expect(screen.getByRole('status', { name: '載入中' })).toBeInTheDocument()

    rerender(<AsyncState empty emptyTitle="沒有來源" emptyDescription="請新增第一筆來源"><p>content</p></AsyncState>)
    expect(screen.getByText('沒有來源')).toBeInTheDocument()
    expect(screen.queryByText('content')).not.toBeInTheDocument()

    rerender(<AsyncState partial="影片畫面仍在分析"><p>已完成逐字稿</p></AsyncState>)
    expect(screen.getByRole('status')).toHaveTextContent('影片畫面仍在分析')
    expect(screen.getByText('已完成逐字稿')).toBeInTheDocument()
  })

  it('shows request trace and only exposes retry when allowed', async () => {
    const retry = vi.fn()
    const { rerender } = render(
      <AsyncState error={{ message: '服務逾時', requestId: 'req-42', retryable: true }} onRetry={retry}>
        <p>content</p>
      </AsyncState>,
    )
    expect(screen.getByText('追蹤：req-42')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '重試' }))
    expect(retry).toHaveBeenCalledOnce()

    rerender(
      <AsyncState error={{ message: '權限不足', retryable: false }} onRetry={retry}>
        <p>content</p>
      </AsyncState>,
    )
    expect(screen.queryByRole('button', { name: '重試' })).not.toBeInTheDocument()
  })
})
