/**
 * Phase 11-2 — 報告詳情頁
 *
 * /reports/:id — 完整 Markdown 渲染、來源引用、重新匯出、重新命名、
 *                以此為基礎重新生成、釘選
 */

import { useState, useEffect, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import {
  ArrowLeft, Download, Copy, Check, Pin, PinOff,
  Pencil, Wand2, Trash2
} from 'lucide-react'
import toast from 'react-hot-toast'

const TEMPLATE_LABELS: Record<string, string> = {
  draft_response: '函件草稿',
  case_summary: '案件摘要',
  meeting_minutes: '會議記錄',
  analysis_report: '分析報告',
  faq_draft: 'FAQ 草稿',
}

const TEMPLATE_ICONS: Record<string, string> = {
  draft_response: '✉️',
  case_summary: '📋',
  meeting_minutes: '📝',
  analysis_report: '📊',
  faq_draft: '❓',
}

interface ReportDetail {
  id: string
  title: string
  template: string
  prompt: string
  context_query: string | null
  content: string
  word_count: number | null
  sources: any[] | null
  document_ids: string[] | null
  is_pinned: boolean
  created_at: string
  updated_at: string | null
}

export default function ReportDetailPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()

  const [report, setReport] = useState<ReportDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [justCopied, setJustCopied] = useState(false)
  const [editingTitle, setEditingTitle] = useState(false)
  const [titleDraft, setTitleDraft] = useState('')
  const titleInputRef = useRef<HTMLInputElement>(null)

  const token = localStorage.getItem('token') || ''

  useEffect(() => {
    fetchReport()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id])

  const fetchReport = async () => {
    setLoading(true)
    try {
      const res = await fetch(`/api/v1/generate/reports/${id}`, {
        headers: { Authorization: `Bearer ${token}` },
      })
      if (!res.ok) throw new Error()
      const data: ReportDetail = await res.json()
      setReport(data)
      setTitleDraft(data.title)
    } catch {
      toast.error('載入報告失敗')
      navigate('/reports')
    } finally {
      setLoading(false)
    }
  }

  const handleCopy = async () => {
    if (!report) return
    try {
      await navigator.clipboard.writeText(report.content)
      setJustCopied(true)
      toast.success('已複製到剪貼簿')
      setTimeout(() => setJustCopied(false), 2000)
    } catch {
      toast.error('複製失敗')
    }
  }

  const handleExport = async (format: 'docx' | 'pdf') => {
    if (!report) return
    try {
      const res = await fetch(`/api/v1/generate/export/${format}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          content: report.content,
          title: report.title,
          sources: report.sources || [],
          template: report.template,
        }),
      })
      if (!res.ok) throw new Error()
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${report.title}.${format}`
      a.click()
      URL.revokeObjectURL(url)
      toast.success(`已下載 ${format.toUpperCase()} 檔案`)
    } catch {
      toast.error(`${format.toUpperCase()} 匯出失敗`)
    }
  }

  const handleTogglePin = async () => {
    if (!report) return
    try {
      const res = await fetch(`/api/v1/generate/reports/${report.id}`, {
        method: 'PATCH',
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ is_pinned: !report.is_pinned }),
      })
      if (!res.ok) throw new Error()
      const updated = await res.json()
      setReport(updated)
      toast.success(report.is_pinned ? '已取消釘選' : '已釘選')
    } catch {
      toast.error('操作失敗')
    }
  }

  const handleSaveTitle = async () => {
    if (!report || !titleDraft.trim()) return
    try {
      const res = await fetch(`/api/v1/generate/reports/${report.id}`, {
        method: 'PATCH',
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: titleDraft.trim() }),
      })
      if (!res.ok) throw new Error()
      const updated = await res.json()
      setReport(updated)
      setEditingTitle(false)
      toast.success('標題已更新')
    } catch {
      toast.error('更新標題失敗')
    }
  }

  const handleRegenerate = () => {
    if (!report) return
    navigate(`/generate?from=${report.id}`)
  }

  const handleDelete = async () => {
    if (!report) return
    if (!confirm(`確定要刪除「${report.title}」？此操作無法復原。`)) return
    try {
      const res = await fetch(`/api/v1/generate/reports/${report.id}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${token}` },
      })
      if (!res.ok) throw new Error()
      toast.success('已刪除報告')
      navigate('/reports')
    } catch {
      toast.error('刪除失敗')
    }
  }

  const formatDate = (iso: string) => {
    if (!iso) return ''
    return new Date(iso).toLocaleDateString('zh-TW', {
      year: 'numeric', month: 'long', day: 'numeric',
      hour: '2-digit', minute: '2-digit',
    })
  }

  if (loading) {
    return (
      <div className="flex justify-center items-center h-full">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-blue-600 border-t-transparent" />
      </div>
    )
  }

  if (!report) return null

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-4xl mx-auto px-4 py-6">
        {/* Back button + toolbar */}
        <div className="flex items-center justify-between mb-4">
          <button
            onClick={() => navigate('/reports')}
            className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-700 transition"
          >
            <ArrowLeft className="w-4 h-4" /> 返回報告列表
          </button>

          <div className="flex items-center gap-2">
            <button
              onClick={handleCopy}
              className="flex items-center gap-1 px-3 py-1.5 text-xs border rounded-lg hover:bg-gray-50 text-gray-600"
            >
              {justCopied ? <Check className="w-3.5 h-3.5 text-green-500" /> : <Copy className="w-3.5 h-3.5" />}
              {justCopied ? '已複製' : '複製'}
            </button>
            <button
              onClick={() => handleExport('docx')}
              className="flex items-center gap-1 px-3 py-1.5 text-xs border rounded-lg hover:bg-gray-50 text-gray-600"
            >
              <Download className="w-3.5 h-3.5" /> Word
            </button>
            <button
              onClick={() => handleExport('pdf')}
              className="flex items-center gap-1 px-3 py-1.5 text-xs border rounded-lg hover:bg-gray-50 text-gray-600"
            >
              <Download className="w-3.5 h-3.5" /> PDF
            </button>
            <button
              onClick={handleTogglePin}
              className={`flex items-center gap-1 px-3 py-1.5 text-xs border rounded-lg hover:bg-gray-50 ${report.is_pinned ? 'text-amber-500' : 'text-gray-600'}`}
            >
              {report.is_pinned ? <PinOff className="w-3.5 h-3.5" /> : <Pin className="w-3.5 h-3.5" />}
              {report.is_pinned ? '取消釘選' : '釘選'}
            </button>
            <button
              onClick={handleRegenerate}
              className="flex items-center gap-1 px-3 py-1.5 text-xs border rounded-lg hover:bg-gray-50 text-blue-600"
            >
              <Wand2 className="w-3.5 h-3.5" /> 重新生成
            </button>
            <button
              onClick={handleDelete}
              className="flex items-center gap-1 px-3 py-1.5 text-xs border rounded-lg hover:bg-gray-50 text-red-500"
            >
              <Trash2 className="w-3.5 h-3.5" /> 刪除
            </button>
          </div>
        </div>

        {/* Report header */}
        <div className="bg-white border rounded-xl p-5 mb-4">
          <div className="flex items-center gap-2 mb-2">
            <span className="text-xl">{TEMPLATE_ICONS[report.template] || '📄'}</span>
            <span className="text-xs font-medium px-2 py-0.5 rounded-full bg-blue-50 text-blue-600">
              {TEMPLATE_LABELS[report.template] || report.template}
            </span>
            {report.is_pinned && <Pin className="w-3.5 h-3.5 text-amber-500" />}
          </div>

          {/* Editable title */}
          {editingTitle ? (
            <div className="flex items-center gap-2 mb-2">
              <input
                ref={titleInputRef}
                value={titleDraft}
                onChange={e => setTitleDraft(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter') handleSaveTitle(); if (e.key === 'Escape') setEditingTitle(false) }}
                className="flex-1 text-lg font-bold border-b-2 border-blue-400 focus:outline-none py-1"
                autoFocus
              />
              <button onClick={handleSaveTitle} className="text-xs px-3 py-1 bg-blue-600 text-white rounded-lg">儲存</button>
              <button onClick={() => { setEditingTitle(false); setTitleDraft(report.title) }} className="text-xs px-3 py-1 bg-gray-100 rounded-lg">取消</button>
            </div>
          ) : (
            <h1
              onClick={() => setEditingTitle(true)}
              className="text-lg font-bold text-gray-900 cursor-pointer hover:text-blue-700 flex items-center gap-2 mb-2 group"
            >
              {report.title}
              <Pencil className="w-3.5 h-3.5 text-gray-300 group-hover:text-blue-500 transition" />
            </h1>
          )}

          <div className="flex items-center gap-4 text-xs text-gray-400">
            <span>{formatDate(report.created_at)}</span>
            {report.word_count && <span>{report.word_count} 字</span>}
            {report.updated_at && <span>更新於 {formatDate(report.updated_at)}</span>}
          </div>

          {/* Original prompt */}
          <div className="mt-3 p-3 bg-gray-50 rounded-lg">
            <div className="text-[10px] uppercase tracking-wider text-gray-400 mb-1">原始需求</div>
            <p className="text-sm text-gray-600">{report.prompt}</p>
            {report.context_query && (
              <p className="text-xs text-gray-400 mt-1">搜尋關鍵字：{report.context_query}</p>
            )}
          </div>
        </div>

        {/* Main content */}
        <div className="bg-white border rounded-xl p-5 mb-4">
          <div className="prose prose-sm max-w-none text-gray-800">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {report.content}
            </ReactMarkdown>
          </div>
        </div>

        {/* Sources */}
        {report.sources && report.sources.length > 0 && (
          <div className="bg-white border rounded-xl p-5">
            <h2 className="text-sm font-semibold text-gray-700 mb-3">參考來源</h2>
            <div className="space-y-2">
              {report.sources.map((src, i) => (
                <div key={i} className="flex items-start gap-2 text-sm">
                  <span className="flex-shrink-0 w-5 h-5 rounded-full bg-blue-100 text-blue-700 text-[10px] font-bold flex items-center justify-center">
                    {i + 1}
                  </span>
                  <div>
                    <span className="font-medium text-gray-700">{src.filename || src.title || `來源 ${i + 1}`}</span>
                    {src.score != null && (
                      <span className="text-xs text-gray-400 ml-2">相似度 {(src.score).toFixed(2)}</span>
                    )}
                    {src.chunk_text && (
                      <p className="text-xs text-gray-400 mt-0.5 line-clamp-2">{src.chunk_text}</p>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
