/**
 * Wiki 閱讀頁（唯讀 Beta）
 *
 * /knowledge/wiki/:id — Markdown 內容渲染、來源引用（citation_map → 文件詳情）、
 *                       backlinks。ACL 由後端把關，無權限一律 404。
 */

import { useState, useEffect } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { ArrowLeft, BookOpen, FileText, Link2, Pencil } from 'lucide-react'
import toast from 'react-hot-toast'
import { useAuth } from '../../auth'

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

export default function WikiDetailPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { user } = useAuth()
  const canEdit = !!user && (user.is_superuser || user.role === 'owner' || user.role === 'admin')
  const [page, setPage] = useState<WikiPageDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [editing, setEditing] = useState(false)
  const [editTitle, setEditTitle] = useState('')
  const [editContent, setEditContent] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    const fetchPage = async () => {
      setLoading(true)
      const token = localStorage.getItem('token')
      if (!token) return
      try {
        const res = await fetch(`/api/v1/wiki/pages/${id}`, {
          headers: { Authorization: `Bearer ${token}` },
        })
        if (!res.ok) throw new Error()
        setPage(await res.json())
      } catch {
        toast.error('Wiki 頁面不存在或無權限檢視')
        navigate('/knowledge/wiki')
      } finally {
        setLoading(false)
      }
    }
    fetchPage()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id])

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
      toast.success('已儲存（新增 revision）')
    } catch {
      toast.error('儲存失敗')
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <div className="flex justify-center items-center h-full">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-blue-600 border-t-transparent" />
      </div>
    )
  }

  if (!page) return null

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-4xl mx-auto px-4 py-6">
        <button
          onClick={() => navigate('/knowledge/wiki')}
          className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-700 transition mb-4"
        >
          <ArrowLeft className="w-4 h-4" /> 返回 Wiki 列表
        </button>

        <div className="bg-white border rounded-xl p-5 mb-4">
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2">
              <BookOpen className="w-5 h-5 text-blue-500" />
              <span className="text-xs font-medium px-2 py-0.5 rounded-full bg-blue-50 text-blue-600">
                {page.page_type}
              </span>
              <span className="text-[10px] font-medium px-2 py-0.5 rounded-full bg-amber-50 text-amber-600">
                Beta
              </span>
            </div>
            {canEdit && !editing && (
              <button
                onClick={startEdit}
                className="flex items-center gap-1.5 text-xs text-gray-500 hover:text-blue-600 border rounded-lg px-2.5 py-1.5 transition"
              >
                <Pencil className="w-3.5 h-3.5" /> 編輯
              </button>
            )}
          </div>
          {editing ? (
            <input
              value={editTitle}
              onChange={e => setEditTitle(e.target.value)}
              className="w-full text-lg font-bold text-gray-900 border border-gray-200 rounded-lg px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-300"
            />
          ) : (
            <>
              <h1 className="text-lg font-bold text-gray-900">{page.title}</h1>
              <p className="text-xs text-gray-400 mt-1">{page.slug}</p>
            </>
          )}
        </div>

        <div className="bg-white border rounded-xl p-5 mb-4">
          {editing ? (
            <div>
              <textarea
                value={editContent}
                onChange={e => setEditContent(e.target.value)}
                rows={18}
                className="w-full font-mono text-sm text-gray-800 border border-gray-200 rounded-lg p-3 focus:outline-none focus:ring-2 focus:ring-blue-300"
              />
              <p className="text-[11px] text-gray-400 mt-2">
                儲存會建立新 revision，不覆寫歷史；下次編譯會產生更新的 revision。
              </p>
              <div className="flex gap-2 mt-3">
                <button
                  onClick={handleSave}
                  disabled={saving}
                  className="px-4 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700 disabled:opacity-50"
                >
                  {saving ? '儲存中…' : '儲存'}
                </button>
                <button
                  onClick={() => setEditing(false)}
                  disabled={saving}
                  className="px-4 py-2 bg-gray-100 text-gray-700 text-sm rounded-lg hover:bg-gray-200"
                >
                  取消
                </button>
              </div>
            </div>
          ) : (
            <div className="prose prose-sm max-w-none text-gray-800">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {page.content}
              </ReactMarkdown>
            </div>
          )}
        </div>

        {page.citation_map && page.citation_map.length > 0 && (
          <div className="bg-white border rounded-xl p-5 mb-4">
            <h2 className="text-sm font-semibold text-gray-700 mb-3">來源引用</h2>
            <div className="space-y-2">
              {page.citation_map.map((c, i) => (
                <div key={i} className="flex items-start gap-2 text-sm">
                  <span className="flex-shrink-0 w-5 h-5 rounded-full bg-blue-100 text-blue-700 text-[10px] font-bold flex items-center justify-center">
                    {i + 1}
                  </span>
                  {c.document_id ? (
                    <Link
                      to={`/knowledge/documents/${c.document_id}`}
                      className="flex items-center gap-1.5 text-blue-600 hover:underline"
                    >
                      <FileText className="w-3.5 h-3.5" />
                      {c.title || c.filename || `文件 ${c.document_id.slice(0, 8)}…`}
                    </Link>
                  ) : (
                    <span className="text-gray-700">{c.title || c.filename || `來源 ${i + 1}`}</span>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {page.backlinks && page.backlinks.length > 0 && (
          <div className="bg-white border rounded-xl p-5">
            <h2 className="text-sm font-semibold text-gray-700 mb-3">反向連結</h2>
            <div className="flex flex-wrap gap-2">
              {page.backlinks.map((b, i) => (
                <span
                  key={i}
                  className="inline-flex items-center gap-1 text-xs bg-gray-50 text-gray-600 px-2 py-1 rounded-full"
                >
                  <Link2 className="w-3 h-3" /> {b}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
