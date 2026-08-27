import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import HomeDashboardView from './HomeDashboardView'
import type { HomeDashboardModel } from './useHomeDashboard'

const baseModel: HomeDashboardModel = {
  title: '我的工作首頁',
  subtitle: '測試摘要',
  loading: false,
  error: null,
  assets: [],
  stats: { total: 5, ready: 2, processing: 1, review: 1, failed: 1 },
  canUpload: true,
  canReview: true,
  canManage: true,
  applications: [{ to: '/job', label: '現場作業', pack: 'mka' }],
  reload: vi.fn(async () => undefined),
}

describe('HomeDashboardView', () => {
  it('presents personal tasks, knowledge health and enabled applications with landmarks', () => {
    render(<MemoryRouter><HomeDashboardView model={baseModel} /></MemoryRouter>)
    expect(screen.getByRole('heading', { level: 1, name: '我的工作首頁' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '我的待辦' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '知識健康與處理狀態' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /開始覆核/ })).toHaveAttribute('href', '/knowledge/review')
    expect(screen.getByRole('link', { name: /現場作業/ })).toHaveAttribute('href', '/job')
  })

  it('does not imply a field application for a Base-only tenant', () => {
    render(<MemoryRouter><HomeDashboardView model={{ ...baseModel, applications: [], canReview: false, canManage: false, stats: { total: 1, ready: 1, processing: 0, review: 0, failed: 0 } }} /></MemoryRouter>)
    expect(screen.queryByRole('link', { name: /現場作業/ })).not.toBeInTheDocument()
    expect(screen.getByText(/未啟用額外職能應用/)).toBeInTheDocument()
  })
})
