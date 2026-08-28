import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import EvidenceLocatorBanner from './EvidenceLocatorBanner'

describe('EvidenceLocatorBanner', () => {
  it('renders document, timeline, frame and image-region locators', () => {
    render(
      <MemoryRouter initialEntries={['/knowledge/assets/a1?page=3&section=%E5%AE%89%E5%85%A8&t=402000&end=438000&frame=42&bbox=1,2,3,4']}>
        <EvidenceLocatorBanner />
      </MemoryRouter>,
    )
    expect(screen.getByRole('status')).toHaveTextContent('第 3 頁')
    expect(screen.getByRole('status')).toHaveTextContent('段落：安全')
    expect(screen.getByRole('status')).toHaveTextContent('時間 6:42–7:18')
    expect(screen.getByRole('status')).toHaveTextContent('畫面 42')
    expect(screen.getByRole('status')).toHaveTextContent('已指定影像標記區域')
  })

  it('stays absent without a valid locator', () => {
    render(<MemoryRouter initialEntries={['/knowledge/assets/a1?t=bad&page=0']}><EvidenceLocatorBanner /></MemoryRouter>)
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })
})
