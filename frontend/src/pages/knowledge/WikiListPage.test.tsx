import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom'
import { vi, describe, it, expect, beforeEach } from 'vitest'
import WikiListPage from './WikiListPage'

vi.mock('react-hot-toast', () => ({
  default: { error: vi.fn(), success: vi.fn() },
}))
import toast from 'react-hot-toast'

const PAGES = [
  {
    id: 'p1',
    slug: 'summary-kb1',
    title: '公司制度總覽',
    page_type: 'summary',
    status: 'published',
    active_revision: 3,
  },
  {
    id: 'p2',
    slug: 'faq-kb1',
    title: '常見問題',
    page_type: 'faq',
    status: 'draft',
    active_revision: 1,
  },
]

function LocationDisplay() {
  const loc = useLocation()
  return <div data-testid="location">{loc.pathname}</div>
}

function renderList() {
  return render(
    <MemoryRouter initialEntries={['/knowledge/wiki']}>
      <Routes>
        <Route path="/knowledge/wiki" element={<WikiListPage />} />
        <Route path="*" element={<LocationDisplay />} />
      </Routes>
    </MemoryRouter>,
  )
}

function mockFetchOnce(payload: unknown, ok = true) {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({
      ok,
      json: () => Promise.resolve(payload),
    }),
  )
}

describe('WikiListPage', () => {
  beforeEach(() => {
    localStorage.setItem('token', 'test-token')
    vi.clearAllMocks()
  })

  it('renders fetched wiki pages with type/status badges', async () => {
    mockFetchOnce(PAGES)
    renderList()
    expect(await screen.findByText('公司制度總覽')).toBeInTheDocument()
    expect(screen.getByText('常見問題')).toBeInTheDocument()
    expect(screen.getByText('摘要')).toBeInTheDocument()
    expect(screen.getByText('常見問答')).toBeInTheDocument()
    expect(screen.getByText('已發布')).toBeInTheDocument()
    expect(screen.getByText('草稿')).toBeInTheDocument()
    expect(screen.getByText('版本 3')).toBeInTheDocument()
    expect(screen.getByText(/2 頁/)).toBeInTheDocument()
  })

  it('sends Authorization header from stored token', async () => {
    mockFetchOnce(PAGES)
    renderList()
    await screen.findByText('公司制度總覽')
    const [, init] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0]
    expect(init.headers.Authorization).toBe('Bearer test-token')
  })

  it('shows empty state when no pages exist', async () => {
    mockFetchOnce([])
    renderList()
    expect(await screen.findByText('尚未有知識頁')).toBeInTheDocument()
  })

  it('shows error toast when fetch fails', async () => {
    mockFetchOnce({}, false)
    renderList()
    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith('載入知識頁失敗'),
    )
  })

  it('navigates to detail page on click', async () => {
    mockFetchOnce(PAGES)
    renderList()
    await userEvent.click(await screen.findByText('公司制度總覽'))
    expect(screen.getByTestId('location')).toHaveTextContent('/knowledge/wiki/p1')
  })

  it('refetches with q param when searching', async () => {
    mockFetchOnce(PAGES)
    renderList()
    await screen.findByText('公司制度總覽')
    mockFetchOnce([PAGES[1]])
    await userEvent.type(screen.getByPlaceholderText('搜尋知識頁標題…'), '常見')
    await userEvent.click(screen.getByRole('button', { name: '搜尋' }))
    await waitFor(() => {
      const calls = (fetch as ReturnType<typeof vi.fn>).mock.calls
      expect(calls[calls.length - 1][0]).toContain('q=%E5%B8%B8%E8%A6%8B')
    })
  })
})
