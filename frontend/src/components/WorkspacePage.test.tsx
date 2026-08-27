import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { MetadataList, SectionPanel, WorkspacePage } from './WorkspacePage'

describe('WorkspacePage primitives', () => {
  it('provides one task heading and an accessible return path', () => {
    render(
      <MemoryRouter>
        <WorkspacePage title="資產詳情" subtitle="來源與處理狀態" backTo="/knowledge/assets" backLabel="回所有資產">
          <p>內容</p>
        </WorkspacePage>
      </MemoryRouter>,
    )
    expect(screen.getByRole('heading', { name: '資產詳情', level: 2 })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '回所有資產' })).toHaveAttribute('href', '/knowledge/assets')
  })

  it('connects panel headings and renders metadata semantics', () => {
    render(
      <SectionPanel title="來源資訊">
        <MetadataList items={[{ label: '版本', value: 'v3' }]} />
      </SectionPanel>,
    )
    expect(screen.getByRole('region', { name: '來源資訊' })).toBeInTheDocument()
    expect(screen.getByText('版本').tagName).toBe('DT')
    expect(screen.getByText('v3').tagName).toBe('DD')
  })
})
