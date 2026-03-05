/**
 * Phase 11-2 — 我的報告列表頁
 *
 * /reports — 顯示使用者的生成報告清單
 * 功能：搜尋、模板篩選、釘選/取消釘選、刪除、分頁、跳轉詳情頁
 */

import { useState, useEffect, useCallback } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import {
  FileText, Search, Pin, PinOff, Trash2, ChevronLeft, ChevronRight,
  Wand2, Plus, Filter
} from 'lucide-react'
import toast from 'react-hot-toast'

const TEMPLATES = [
  { id: 'draft_response', label: '函件草稿', icon: '✉️' },
  { id: 'case_summary', label: '案件摘要', icon: '📋' },
  { id: 'meeting_minutes', label: '會議記錄', icon: '📝' },
  { id: 'analysis_report', label: '分析報告', icon: '📊' },
  { id: 'faq_draft', label: 'FAQ 問答集', icon: '❓' },
]

interface ReportSummary {
  id: string
  title: string
  template: string
  prompt: string
  word_count: number | null
  is_pinned: boolean
  created_at: string
}

interface ReportListResponse {
  reports: ReportSummary[]
  total: number
  page: number
  page_size: number
}

export default function ReportsPage() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()

  const [reports, setReports] = useState<ReportSummary[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(parseInt(searchParams.get('page') || '1'))
  const [pageSize] = useState(15)
  const [search, setSearch] = useState(searchParams.get('q') || '')
  const [searchInput, setSearchInput] = useState(searchParams.get('q') || '')
  const [templateFilter, setTemplateFilter] = useState(searchParams.get('template') || '')
  const [loading, setLoading] = useState(true)

  const totalPages = Math.ceil(total / pageSize)

  const fetchReports = useCallback(async () => {
    setLoading(true)
    const token = localStorage.getItem('token')
    if (!token) return

    const params = new URLSearchParams()
    params.set('page', String(page))
    params.set('page_size', String(pageSize))
    if (search) params.set('search', search)
    if (templateFilter) params.set('template', templateFilter)

    try {
      const res = await fetch(`/api/v1/generate/reports?${params}`, {
        headers: { Authorization: `Bearer ${token}` },
      })
      if (!res.ok) throw new Error()
      const data: ReportListResponse = await res.json()
      setReports(data.reports)
      setTotal(data.total)
    } catch {
      toast.error('載入報告清單失敗')
    } finally {
      setLoading(false)
    }
  }, [page, pageSize, search, templateFilter])

  useEffect(() => {
    fetchReports()
  }, [fetchReports])

  // Sync URL params
  useEffect(() => {
    const p = new URLSearchParams()
    if (page > 1) p.set('page', String(page))
    if (search) p.set('q', search)
    if (templateFilter) p.set('template', templateFilter)
    setSearchParams(p, { replace: true })
  }, [page, search, templateFilter, setSearchParams])

  const handleSearch = () => {
    setSearch(searchInput)
    setPage(1)
  }

  const handleTogglePin = async (report: ReportSummary) => {
    const token = localStorage.getItem('token')
    if (!token) return
    try {
      const res = await fetch(`/api/v1/generate/reports/${report.id}`, {
        method: 'PATCH',
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ is_pinned: !report.is_pinned }),
      })
      if (!res.ok) throw new Error()
      toast.success(report.is_pinned ? '已取消釘選' : '已釘選')
      fetchReports()
    } catch {
      toast.error('操作失敗')
    }
  }

  const handleDelete = async (report: ReportSummary) => {
    if (!confirm(`確定要刪除「${report.title}」？此操作無法復原。`)) return
    const token = localStorage.getItem('token')
    if (!token) return
    try {
      const res = await fetch(`/api/v1/generate/reports/${report.id}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${token}` },
      })
      if (!res.ok) throw new Error()
      toast.success('已刪除報告')
      fetchReports()
    } catch {
      toast.error('刪除失敗')
    }
  }

  const getTemplateMeta = (id: string) => TEMPLATES.find(t => t.id === id)

  const formatDate = (iso: string) => {
    if (!iso) return ''
    const d = new Date(iso)
    return d.toLocaleDateString('zh-TW', { year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
  }

  // ── Date grouping helper ────────────────────────────────
  type DateGroup = { label: string; reports: ReportSummary[] }

  function groupByDate(items: ReportSummary[]): { pinned: ReportSummary[]; groups: DateGroup[] } {
    const pinned = items.filter(r => r.is_pinned)
    const unpinned = items.filter(r => !r.is_pinned)

    const now = new Date()
    const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
    const yesterdayStart = todayStart - 86400000
    const weekStart = todayStart - (now.getDay() * 86400000)
    const monthStart = new Date(now.getFullYear(), now.getMonth(), 1).getTime()

    const buckets: Record<string, ReportSummary[]> = {
      '今天': [],
      '昨天': [],
      '本週': [],
      '本月': [],
      '更早': [],
    }

    for (const r of unpinned) {
      const ts = new Date(r.created_at).getTime()
      if (ts >= todayStart) buckets['今天'].push(r)
      else if (ts >= yesterdayStart) buckets['昨天'].push(r)
      else if (ts >= weekStart) buckets['本週'].push(r)
      else if (ts >= monthStart) buckets['本月'].push(r)
      else buckets['更早'].push(r)
    }

    const groups: DateGroup[] = []
    for (const label of ['今天', '昨天', '本週', '本月', '更早']) {
      if (buckets[label].length > 0) {
        groups.push({ label, reports: buckets[label] })
      }
    }
    return { pinned, groups }
  }

  const { pinned: pinnedReports, groups: dateGroups } = groupByDate(reports)

  // ── Report row component ────────────────────────────────
  const ReportRow = ({ report }: { report: ReportSummary }) => {
    const tpl = getTemplateMeta(report.template)
    return (
      <div
        onClick={() => navigate(`/reports/${report.id}`)}
        className="flex items-center gap-4 bg-white border rounded-xl px-4 py-3 hover:border-blue-200 hover:shadow-sm transition cursor-pointer group"
      >
        <span className="text-xl flex-shrink-0">{tpl?.icon ?? '📄'}</span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            {report.is_pinned && <Pin className="w-3.5 h-3.5 text-amber-500 flex-shrink-0" />}
            <h3 className="text-sm font-medium text-gray-900 truncate">{report.title}</h3>
          </div>
          <p className="text-xs text-gray-400 truncate mt-0.5">{report.prompt}</p>
        </div>
        <div className="flex-shrink-0 text-right">
          <span className="inline-block px-2 py-0.5 text-[10px] font-medium rounded-full bg-gray-100 text-gray-500 mb-1">
            {tpl?.label ?? report.template}
          </span>
          <div className="text-[11px] text-gray-400">
            {report.word_count ? `${report.word_count} 字` : ''}
            {' · '}
            {formatDate(report.created_at)}
          </div>
        </div>
        <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0">
          <button
            onClick={e => { e.stopPropagation(); handleTogglePin(report) }}
            className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-400 hover:text-amber-500"
            title={report.is_pinned ? '取消釘選' : '釘選'}
          >
            {report.is_pinned ? <PinOff className="w-4 h-4" /> : <Pin className="w-4 h-4" />}
          </button>
          <button
            onClick={e => { e.stopPropagation(); handleDelete(report) }}
            className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-400 hover:text-red-500"
            title="刪除"
          >
            <Trash2 className="w-4 h-4" />
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-5xl mx-auto px-4 py-6">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-3">
            <FileText className="w-6 h-6 text-blue-600" />
            <h1 className="text-xl font-bold text-gray-900">我的報告</h1>
            <span className="text-sm text-gray-400">{total} 份</span>
          </div>
          <button
            onClick={() => navigate('/generate')}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700 transition"
          >
            <Plus className="w-4 h-4" /> 新增生成
          </button>
        </div>

        {/* Template quick stats */}
        {!search && !templateFilter && reports.length > 0 && (
          <div className="flex gap-2 mb-5 overflow-x-auto pb-1">
            {TEMPLATES.map(t => {
              const count = reports.filter(r => r.template === t.id).length
              return (
                <button
                  key={t.id}
                  onClick={() => { setTemplateFilter(t.id); setPage(1) }}
                  className="flex items-center gap-1.5 px-3 py-1.5 bg-white border rounded-lg text-xs hover:border-blue-200 hover:shadow-sm transition whitespace-nowrap"
                >
                  <span>{t.icon}</span>
                  <span className="text-gray-700">{t.label}</span>
                  {count > 0 && <span className="text-[10px] bg-gray-100 text-gray-500 px-1.5 py-0.5 rounded-full">{count}</span>}
                </button>
              )
            })}
          </div>
        )}

        {/* Active filter indicator */}
        {(search || templateFilter) && (
          <div className="flex items-center gap-2 mb-4">
            <span className="text-xs text-gray-500">篩選中：</span>
            {search && (
              <span className="inline-flex items-center gap-1 text-xs bg-blue-50 text-blue-600 px-2 py-1 rounded-full">
                「{search}」
                <button onClick={() => { setSearch(''); setSearchInput(''); setPage(1) }} className="hover:text-blue-800">&times;</button>
              </span>
            )}
            {templateFilter && (
              <span className="inline-flex items-center gap-1 text-xs bg-purple-50 text-purple-600 px-2 py-1 rounded-full">
                {getTemplateMeta(templateFilter)?.icon} {getTemplateMeta(templateFilter)?.label}
                <button onClick={() => { setTemplateFilter(''); setPage(1) }} className="hover:text-purple-800">&times;</button>
              </span>
            )}
            <button onClick={() => { setSearch(''); setSearchInput(''); setTemplateFilter(''); setPage(1) }} className="text-xs text-gray-400 hover:text-gray-600 ml-2">
              清除全部
            </button>
          </div>
        )}

        {/* Search + Filter bar */}
        <div className="flex gap-3 mb-5">
          <div className="flex-1 relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
            <input
              type="text"
              value={searchInput}
              onChange={e => setSearchInput(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleSearch()}
              placeholder="搜尋報告標題、提示詞或內容..."
              className="w-full pl-9 pr-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-300"
            />
          </div>
          <div className="relative">
            <Filter className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
            <select
              value={templateFilter}
              onChange={e => { setTemplateFilter(e.target.value); setPage(1) }}
              className="pl-9 pr-8 py-2 border border-gray-200 rounded-lg text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-300 appearance-none"
            >
              <option value="">全部模板</option>
              {TEMPLATES.map(t => (
                <option key={t.id} value={t.id}>{t.icon} {t.label}</option>
              ))}
            </select>
          </div>
          <button
            onClick={handleSearch}
            className="px-4 py-2 bg-gray-100 text-gray-700 text-sm rounded-lg hover:bg-gray-200"
          >
            搜尋
          </button>
        </div>

        {/* Reports list */}
        {loading ? (
          <div className="flex justify-center py-20">
            <div className="h-8 w-8 animate-spin rounded-full border-4 border-blue-600 border-t-transparent" />
          </div>
        ) : reports.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20 text-gray-400">
            <Wand2 className="w-12 h-12 mb-3 opacity-30" />
            <p className="text-sm">
              {search || templateFilter ? '沒有符合條件的報告' : '尚未有任何生成報告'}
            </p>
            {!search && !templateFilter && (
              <button
                onClick={() => navigate('/generate')}
                className="mt-3 text-sm text-blue-600 hover:underline"
              >
                前往「內容生成」建立第一份報告
              </button>
            )}
          </div>
        ) : (
          <div className="space-y-6">
            {/* Pinned section */}
            {pinnedReports.length > 0 && (
              <div>
                <div className="flex items-center gap-2 mb-2 px-1">
                  <Pin className="w-3.5 h-3.5 text-amber-500" />
                  <span className="text-xs font-semibold text-amber-600 uppercase tracking-wider">已釘選</span>
                  <span className="text-[10px] text-amber-400">{pinnedReports.length}</span>
                </div>
                <div className="space-y-2">
                  {pinnedReports.map(report => (
                    <ReportRow key={report.id} report={report} />
                  ))}
                </div>
              </div>
            )}

            {/* Date-grouped sections */}
            {dateGroups.map(group => (
              <div key={group.label}>
                <div className="flex items-center gap-2 mb-2 px-1">
                  <span className="text-xs font-semibold text-gray-500 uppercase tracking-wider">{group.label}</span>
                  <div className="flex-1 border-t border-gray-100" />
                  <span className="text-[10px] text-gray-400">{group.reports.length} 份</span>
                </div>
                <div className="space-y-2">
                  {group.reports.map(report => (
                    <ReportRow key={report.id} report={report} />
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Pagination */}
        {totalPages > 1 && (
          <div className="flex items-center justify-center gap-3 mt-6">
            <button
              disabled={page <= 1}
              onClick={() => setPage(p => p - 1)}
              className="flex items-center gap-1 px-3 py-1.5 text-sm border rounded-lg hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              <ChevronLeft className="w-4 h-4" /> 上一頁
            </button>
            <span className="text-sm text-gray-500">
              {page} / {totalPages}
            </span>
            <button
              disabled={page >= totalPages}
              onClick={() => setPage(p => p + 1)}
              className="flex items-center gap-1 px-3 py-1.5 text-sm border rounded-lg hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              下一頁 <ChevronRight className="w-4 h-4" />
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
