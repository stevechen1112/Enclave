/**
 * 知識頁列表（唯讀，試用中）
 *
 * /knowledge/wiki — 列出目前角色可見的知識頁。
 * 可見性由後端嚴格交集 ACL 決定（所有來源文件可讀才可見）。
 */

import { useState, useEffect, useCallback } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { BookOpen, Search } from 'lucide-react'
import toast from 'react-hot-toast'
import AsyncState from '../../components/AsyncState'
import PageHeader from '../../components/PageHeader'

interface WikiPageSummary {
  id: string
  slug: string
  title: string
  page_type: string
  status: string
  active_revision: number
}

const PAGE_TYPE_LABELS: Record<string, string> = {
  summary: '摘要',
  faq: '常見問答',
  guide: '指南',
}

const STATUS_LABELS: Record<string, { label: string; chip: string }> = {
  published: { label: '已發布', chip: 'chip-success' },
  draft: { label: '草稿', chip: 'chip-neutral' },
}

export default function WikiListPage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const [pages, setPages] = useState<WikiPageSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [searchInput, setSearchInput] = useState(searchParams.get('q') ?? '')
  const [search, setSearch] = useState(searchParams.get('q') ?? '')

  const fetchPages = useCallback(async () => {
    setLoading(true)
    setError(null)
    const token = localStorage.getItem('token')
    if (!token) {
      setLoading(false)
      setError('尚未登入，請先登入後再試。')
      return
    }
    const params = new URLSearchParams()
    if (search) params.set('q', search)
    try {
      const res = await fetch(`/api/v1/wiki/pages?${params}`, {
        headers: { Authorization: `Bearer ${token}` },
      })
      if (!res.ok) throw new Error()
      setPages(await res.json())
    } catch {
      setError('載入知識頁失敗')
      toast.error('載入知識頁失敗')
    } finally {
      setLoading(false)
    }
  }, [search])

  useEffect(() => {
    fetchPages()
  }, [fetchPages])

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-5xl px-4 py-6 md:px-8">
        <PageHeader
          variant="section"
          title="知識頁"
          subtitle={`由知識編譯器從已審核文件自動整理產生 · ${pages.length} 頁`}
          actions={<span className="chip-highlight">試用中</span>}
          className="mb-6"
        />

        <div className="mb-5 flex gap-2">
          <div className="relative flex-1">
            <Search className="absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" aria-hidden />
            <input
              type="text"
              value={searchInput}
              onChange={e => setSearchInput(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && setSearch(searchInput)}
              placeholder="搜尋知識頁標題…"
              className="input pl-10"
              aria-label="搜尋知識頁標題"
            />
          </div>
          <button
            type="button"
            onClick={() => setSearch(searchInput)}
            className="btn-outline"
          >
            搜尋
          </button>
        </div>

        <AsyncState
          loading={loading}
          error={error}
          onRetry={fetchPages}
          empty={!error && pages.length === 0}
          emptyTitle={search ? '沒有符合條件的知識頁' : '尚未有知識頁'}
          emptyDescription="知識頁由知識編譯器從已審核文件自動編譯產生"
        >
          <div className="space-y-3">
            {pages.map(p => {
              const st = STATUS_LABELS[p.status] ?? { label: p.status, chip: 'chip-neutral' }
              return (
                <button
                  key={p.id}
                  type="button"
                  onClick={() => navigate(`/knowledge/wiki/${p.id}`)}
                  className="card-interactive flex w-full items-center gap-4 px-4 py-4 text-left animate-rise-in"
                >
                  <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-accent-soft">
                    <BookOpen className="h-5 w-5 text-accent" aria-hidden />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-base font-semibold text-ink">{p.title}</span>
                    <span className="mt-1 block text-sm text-muted">版本 {p.active_revision}</span>
                  </span>
                  <span className="flex shrink-0 flex-wrap items-center justify-end gap-1.5">
                    <span className="chip-accent">{PAGE_TYPE_LABELS[p.page_type] ?? p.page_type}</span>
                    <span className={st.chip}>{st.label}</span>
                  </span>
                </button>
              )
            })}
          </div>
        </AsyncState>
      </div>
    </div>
  )
}
