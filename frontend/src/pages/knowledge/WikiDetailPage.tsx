/**
 * 知識頁閱讀頁（試用中）
 *
 * /knowledge/wiki/:id — Markdown 內容渲染、來源引用（citation_map → 文件詳情）、
 *                       反向連結。ACL 由後端把關，無權限一律 404。
 */

import { useState, useEffect, useCallback } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { ArrowLeft, BookOpen, FileText, Link2, Pencil } from 'lucide-react'
import toast from 'react-hot-toast'
import { useAuth } from '../../auth'
import AsyncState from '../../components/AsyncState'

interface Citation {
  document_id?: string
  revision?: number
  title?: string
  filename?: string
}

interface WikiPageDetail {
  id: string
  slug: string
  title: string
  page_type: string
  status: string
  content: string
  citation_map: Citation[]
  source_document_ids: string[]
  backlinks: string[]
}

const PAGE_TYPE_LABELS: Record<string, string> = {
  summary: '摘要',
  faq: '常見問答',
  guide: '指南',
}

export default function WikiDetailPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { user } = useAuth()
  const canEdit = !!user && (user.is_superuser || user.role === 'owner' || user.role === 'admin')
  const [page, setPage] = useState<WikiPageDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [editing, setEditing] = useState(false)
  const [editTitle, setEditTitle] = useState('')
  const [editContent, setEditContent] = useState('')
  const [saving, setSaving] = useState(false)

  const fetchPage = useCallback(async () => {
    setLoading(true)
    setError(null)
    const token = localStorage.getItem('token')
    if (!token) {
      setLoading(false)
      setError('尚未登入，請先登入後再試。')
      return
    }
    try {
      const res = await fetch(`/api/v1/wiki/pages/${id}`, {
        headers: { Authorization: `Bearer ${token}` },
      })
      if (!res.ok) throw new Error()
      setPage(await res.json())
    } catch {
      setError('知識頁不存在或無權限檢視')
      toast.error('知識頁不存在或無權限檢視')
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => {
    fetchPage()
  }, [fetchPage])

  const startEdit = () => {
    if (!page) return
    setEditTitle(page.title)
    setEditContent(page.content)
    setEditing(true)
  }

  const handleSave = async () => {
    if (!page) return
    setSaving(true)
    const token = localStorage.getItem('token')
    try {
      const res = await fetch(`/api/v1/wiki/pages/${page.id}`, {
        method: 'PATCH',
        headers: {
          Authorization: `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ title: editTitle, content: editContent }),
      })
      if (!res.ok) throw new Error()
      setPage({ ...page, title: editTitle, content: editContent })
      setEditing(false)
      toast.success('已儲存（新增版本）')
    } catch {
      toast.error('儲存失敗')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="h-full overflow-y-auto">
      <AsyncState loading={loading} error={error} onRetry={fetchPage} empty={false}>
        {page && (
          <div className="mx-auto max-w-4xl px-4 py-6 md:px-8">
            <button
              type="button"
              onClick={() => navigate('/knowledge/wiki')}
              className="btn-ghost mb-4 -ml-3"
            >
              <ArrowLeft className="h-4 w-4" aria-hidden /> 返回知識頁列表
            </button>

            <div className="card mb-4 p-5 animate-fade-in">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex flex-wrap items-center gap-2">
                  <BookOpen className="h-5 w-5 text-accent" aria-hidden />
                  <span className="chip-accent">{PAGE_TYPE_LABELS[page.page_type] ?? page.page_type}</span>
                  <span className="chip-highlight">試用中</span>
                </div>
                {canEdit && !editing && (
                  <button
                    type="button"
                    onClick={startEdit}
                    className="btn-outline"
                  >
                    <Pencil className="h-4 w-4" aria-hidden /> 編輯
                  </button>
                )}
              </div>
              {editing ? (
                <input
                  value={editTitle}
                  onChange={e => setEditTitle(e.target.value)}
                  className="input mt-3 font-semibold"
                  aria-label="知識頁標題"
                />
              ) : (
                <h1 className="mt-3 font-display text-xl font-semibold text-ink md:text-2xl">{page.title}</h1>
              )}
            </div>

            <div className="card mb-4 p-5">
              {editing ? (
                <div>
                  <textarea
                    value={editContent}
                    onChange={e => setEditContent(e.target.value)}
                    rows={18}
                    className="input min-h-0 w-full p-3 font-mono text-sm"
                    aria-label="知識頁內容"
                  />
                  <p className="mt-2 text-sm text-muted">
                    儲存會建立新版本，不覆寫歷史；下次編譯會產生更新的版本。
                  </p>
                  <div className="mt-3 flex gap-2">
                    <button
                      type="button"
                      onClick={handleSave}
                      disabled={saving}
                      className="btn-primary"
                    >
                      {saving ? '儲存中…' : '儲存'}
                    </button>
                    <button
                      type="button"
                      onClick={() => setEditing(false)}
                      disabled={saving}
                      className="btn-outline"
                    >
                      取消
                    </button>
                  </div>
                </div>
              ) : (
                <div className="prose prose-sm max-w-none text-ink">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {page.content}
                  </ReactMarkdown>
                </div>
              )}
            </div>

            {page.citation_map && page.citation_map.length > 0 && (
              <div className="card mb-4 p-5">
                <h2 className="mb-3 text-sm font-semibold text-ink">來源引用</h2>
                <div className="space-y-2">
                  {page.citation_map.map((c, i) => (
                    <div key={i} className="flex items-start gap-2 text-sm">
                      <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-accent-soft text-xs font-bold text-accent-ink">
                        {i + 1}
                      </span>
                      {c.document_id ? (
                        <Link
                          to={`/knowledge/documents/${c.document_id}`}
                          className="flex min-h-11 items-center gap-1.5 text-accent hover:underline"
                        >
                          <FileText className="h-4 w-4" aria-hidden />
                          {c.title || c.filename || '來源文件'}
                        </Link>
                      ) : (
                        <span className="flex min-h-11 items-center text-ink">{c.title || c.filename || `來源 ${i + 1}`}</span>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {page.backlinks && page.backlinks.length > 0 && (
              <div className="card p-5">
                <h2 className="mb-1 text-sm font-semibold text-ink">提到此頁的其他知識頁</h2>
                <p className="mb-3 text-sm text-muted">點擊可在列表中搜尋該頁</p>
                <div className="flex flex-wrap gap-2">
                  {page.backlinks.map((b, i) => (
                    <Link
                      key={i}
                      to={`/knowledge/wiki?q=${encodeURIComponent(b)}`}
                      className="chip-neutral min-h-11 hover:bg-accent-soft hover:text-accent-ink"
                    >
                      <Link2 className="h-3.5 w-3.5" aria-hidden /> {b}
                    </Link>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </AsyncState>
    </div>
  )
}
