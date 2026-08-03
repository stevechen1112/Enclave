/**
 * Wiki 列表頁（唯讀 Beta）
 *
 * /knowledge/wiki — 列出目前角色可見的 Auto-Wiki 頁面。
 * 可見性由後端嚴格交集 ACL 決定（所有來源文件可讀才可見）。
 */

import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { BookOpen, Search } from 'lucide-react'
import toast from 'react-hot-toast'

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
  faq: 'FAQ',
  guide: '指南',
}

const STATUS_LABELS: Record<string, { label: string; cls: string }> = {
  published: { label: '已發布', cls: 'bg-green-50 text-green-600' },
  draft: { label: '草稿', cls: 'bg-gray-100 text-gray-500' },
}

export default function WikiListPage() {
  const navigate = useNavigate()
  const [pages, setPages] = useState<WikiPageSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [searchInput, setSearchInput] = useState('')
  const [search, setSearch] = useState('')

  const fetchPages = useCallback(async () => {
    setLoading(true)
    const token = localStorage.getItem('token')
    if (!token) return
    const params = new URLSearchParams()
    if (search) params.set('q', search)
    try {
      const res = await fetch(`/api/v1/wiki/pages?${params}`, {
        headers: { Authorization: `Bearer ${token}` },
      })
      if (!res.ok) throw new Error()
      setPages(await res.json())
    } catch {
      toast.error('載入 Wiki 頁面失敗')
    } finally {
      setLoading(false)
    }
  }, [search])

  useEffect(() => {
    fetchPages()
  }, [fetchPages])

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-5xl mx-auto px-4 py-6">
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-3">
            <BookOpen className="w-6 h-6 text-blue-600" />
            <h1 className="text-xl font-bold text-gray-900">Wiki</h1>
            <span className="text-sm text-gray-400">{pages.length} 頁</span>
            <span className="text-[10px] font-medium px-2 py-0.5 rounded-full bg-amber-50 text-amber-600">
              Beta
            </span>
          </div>
        </div>

        <div className="flex gap-3 mb-5">
          <div className="flex-1 relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
            <input
              type="text"
              value={searchInput}
              onChange={e => setSearchInput(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && setSearch(searchInput)}
              placeholder="搜尋 Wiki 標題..."
              className="w-full pl-9 pr-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-300"
            />
          </div>
          <button
            onClick={() => setSearch(searchInput)}
            className="px-4 py-2 bg-gray-100 text-gray-700 text-sm rounded-lg hover:bg-gray-200"
          >
            搜尋
          </button>
        </div>

        {loading ? (
          <div className="flex justify-center py-20">
            <div className="h-8 w-8 animate-spin rounded-full border-4 border-blue-600 border-t-transparent" />
          </div>
        ) : pages.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20 text-gray-400">
            <BookOpen className="w-12 h-12 mb-3 opacity-30" />
            <p className="text-sm">
              {search ? '沒有符合條件的 Wiki 頁面' : '尚未有 Wiki 頁面'}
            </p>
            <p className="text-xs text-gray-300 mt-2">
              Wiki 頁由知識編譯器從已審核文件自動編譯產生
            </p>
          </div>
        ) : (
          <div className="space-y-2">
            {pages.map(p => {
              const st = STATUS_LABELS[p.status] ?? { label: p.status, cls: 'bg-gray-100 text-gray-500' }
              return (
                <div
                  key={p.id}
                  onClick={() => navigate(`/knowledge/wiki/${p.id}`)}
                  className="flex items-center gap-4 bg-white border rounded-xl px-4 py-3 hover:border-blue-200 hover:shadow-sm transition cursor-pointer"
                >
                  <BookOpen className="w-5 h-5 text-blue-500 flex-shrink-0" />
                  <div className="flex-1 min-w-0">
                    <h3 className="text-sm font-medium text-gray-900 truncate">{p.title}</h3>
                    <p className="text-xs text-gray-400 truncate mt-0.5">{p.slug}</p>
                  </div>
                  <div className="flex-shrink-0 flex items-center gap-2">
                    <span className="inline-block px-2 py-0.5 text-[10px] font-medium rounded-full bg-blue-50 text-blue-600">
                      {PAGE_TYPE_LABELS[p.page_type] ?? p.page_type}
                    </span>
                    <span className={`inline-block px-2 py-0.5 text-[10px] font-medium rounded-full ${st.cls}`}>
                      {st.label}
                    </span>
                    <span className="text-[11px] text-gray-400">rev {p.active_revision}</span>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
