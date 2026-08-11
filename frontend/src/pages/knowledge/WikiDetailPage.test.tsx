import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom'
import { vi, describe, it, expect, beforeEach } from 'vitest'
import WikiDetailPage from './WikiDetailPage'

vi.mock('react-hot-toast', () => ({
  default: { error: vi.fn(), success: vi.fn() },
}))
import toast from 'react-hot-toast'

const mockAuth: { user: { role: string; is_superuser: boolean } | null } = {
  user: { role: 'admin', is_superuser: false },
}
vi.mock('../../auth', () => ({
  useAuth: () => ({ user: mockAuth.user }),
}))

const DETAIL = {
  id: 'p1',
  slug: 'summary-kb1',
  title: '公司制度總覽',
  page_type: 'summary',
  status: 'published',
  content: '# 總覽\n\n本文整理公司制度。',
  citation_map: [
    { document_id: 'doc-12345678-abcd', revision: 1, filename: '員工手冊.pdf' },
    { title: '外部法規' },
  ],
  source_document_ids: ['doc-12345678-abcd'],
  backlinks: ['summary-kb2'],
}

function LocationDisplay() {
  const loc = useLocation()
  return <div data-testid="location">{loc.pathname}</div>
}

function renderDetail() {
  return render(
    <MemoryRouter initialEntries={['/knowledge/wiki/p1']}>
      <Routes>
        <Route path="/knowledge/wiki/:id" element={<WikiDetailPage />} />
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

describe('WikiDetailPage', () => {
  beforeEach(() => {
    localStorage.setItem('token', 'test-token')
    vi.clearAllMocks()
    mockAuth.user = { role: 'admin', is_superuser: false }
  })

  it('renders title and markdown content', async () => {
    mockFetchOnce(DETAIL)
    renderDetail()
    expect(await screen.findByText('公司制度總覽')).toBeInTheDocument()
    // Markdown heading rendered as h1 text
    expect(screen.getByRole('heading', { name: '總覽' })).toBeInTheDocument()
    expect(screen.getByText(/本文整理公司制度/)).toBeInTheDocument()
  })

  it('links document citations to document detail page', async () => {
    mockFetchOnce(DETAIL)
    renderDetail()
    const link = await screen.findByRole('link', { name: /員工手冊\.pdf/ })
    expect(link).toHaveAttribute('href', '/knowledge/documents/doc-12345678-abcd')
  })

  it('renders citations without document_id as plain text', async () => {
    mockFetchOnce(DETAIL)
    renderDetail()
    const text = await screen.findByText('外部法規')
    expect(text.tagName).not.toBe('A')
  })

  it('renders backlinks', async () => {
    mockFetchOnce(DETAIL)
    renderDetail()
    expect(await screen.findByText('summary-kb2')).toBeInTheDocument()
  })

  it('shows error state with retry when page missing or forbidden', async () => {
    mockFetchOnce({}, false)
    renderDetail()
    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith('知識頁不存在或無權限檢視'),
    )
    expect(await screen.findByText('知識頁不存在或無權限檢視')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /重試/ })).toBeInTheDocument()
  })

  it('admin sees edit button and saves via PATCH', async () => {
    mockFetchOnce(DETAIL)
    const { container } = renderDetail()
    await userEvent.click(await screen.findByRole('button', { name: /編輯/ }))
    const textarea = container.querySelector('textarea')!
    expect(textarea.value).toBe(DETAIL.content)
    await userEvent.clear(textarea)
    await userEvent.type(textarea, '# 修正後')
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve({}) }),
    )
    await userEvent.click(screen.getByRole('button', { name: '儲存' }))
    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith('已儲存（新增版本）'),
    )
    const [url, init] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0]
    expect(url).toBe('/api/v1/wiki/pages/p1')
    expect(init.method).toBe('PATCH')
    expect(JSON.parse(init.body)).toEqual({ title: DETAIL.title, content: '# 修正後' })
  })

  it('save failure shows error toast and stays in edit mode', async () => {
    mockFetchOnce(DETAIL)
    renderDetail()
    await userEvent.click(await screen.findByRole('button', { name: /編輯/ }))
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ ok: false, json: () => Promise.resolve({}) }),
    )
    await userEvent.click(screen.getByRole('button', { name: '儲存' }))
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith('儲存失敗'))
    expect(screen.getByRole('button', { name: '儲存' })).toBeInTheDocument()
  })

  it('employee role does not see the edit button', async () => {
    mockAuth.user = { role: 'employee', is_superuser: false }
    mockFetchOnce(DETAIL)
    renderDetail()
    await screen.findByText('公司制度總覽')
    expect(screen.queryByRole('button', { name: /編輯/ })).not.toBeInTheDocument()
  })
})
