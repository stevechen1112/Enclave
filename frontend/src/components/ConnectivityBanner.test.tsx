import { act, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import ConnectivityBanner from './ConnectivityBanner'

function setOnline(value: boolean) {
  Object.defineProperty(window.navigator, 'onLine', { configurable: true, value })
  window.dispatchEvent(new Event(value ? 'online' : 'offline'))
}

describe('ConnectivityBanner', () => {
  it('appears while offline and clears after connectivity returns', () => {
    setOnline(true)
    render(<ConnectivityBanner />)
    expect(screen.queryByRole('status')).not.toBeInTheDocument()

    act(() => setOnline(false))
    expect(screen.getByRole('status')).toHaveTextContent('裝置目前離線')

    act(() => setOnline(true))
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })
})
