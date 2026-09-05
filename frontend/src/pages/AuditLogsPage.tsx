import { useState, useEffect, useCallback } from 'react'
import { auditApi } from '../api'
import type { AuditLog } from '../types'
import { Shield, Loader2, FileSpreadsheet, FileText, RefreshCw } from 'lucide-react'

const ACTION_LABELS: Record<string, string> = {
  login: '登入', logout: '登出', chat: 'AI 問答', upload_document: '上傳文件',
  upload_doc: '上傳文件', delete_document: '刪除文件', document_uploaded: '上傳文件',
  document_deleted: '刪除文件', knowledge_approved: '核准知識', knowledge_rejected: '駁回知識',
  legacy_surface_used: '舊版相容性紀錄',
}

const RESOURCE_LABELS: Record<string, string> = {
  document: '文件', source_asset: '來源', knowledge: '知識', user: '成員',
  legacy_surface: '系統相容性', conversation: '對話',
}

function actionLabel(value: string) {
  return ACTION_LABELS[value] || '其他工作區操作'
}

function resourceLabel(value: string | null) {
  return value ? (RESOURCE_LABELS[value] || '其他資料') : '—'
}

function maskIp(value: string | null) {
  if (!value) return '—'
  const ipv4 = value.split('.')
  return ipv4.length === 4 ? `${ipv4[0]}.${ipv4[1]}.*.*` : '已隱藏'
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

export default function AuditLogsPage() {
  const [logs, setLogs] = useState<AuditLog[]>([])
  const [loading, setLoading] = useState(true)
  const [exporting, setExporting] = useState<'csv' | 'pdf' | null>(null)
  const [actionFilter, setActionFilter] = useState('')
  const [includeSystemEvents, setIncludeSystemEvents] = useState(false)
  const [offset, setOffset] = useState(0)
  const [hasMore, setHasMore] = useState(false)
  const pageSize = 50

  const load = useCallback((nextOffset = 0, append = false) => {
    setLoading(true)
    const params: Record<string, string> = { limit: String(pageSize), skip: String(nextOffset) }
    if (actionFilter) params.action = actionFilter
    if (includeSystemEvents) params.include_system_events = 'true'
    auditApi.logs(params)
      .then(rows => { setLogs(current => append ? [...current, ...rows] : rows); setOffset(nextOffset); setHasMore(rows.length === pageSize) })
      .catch(() => setLogs([]))
      .finally(() => setLoading(false))
  }, [actionFilter, includeSystemEvents])

  useEffect(() => { load() }, [load])

  const handleExport = async (format: 'csv' | 'pdf') => {
    setExporting(format)
    try {
    const params: Record<string, string> = { include_system_events: String(includeSystemEvents) }
      if (actionFilter) params.action = actionFilter
      const blob = await auditApi.exportLogs(format, params)
      const ext = format === 'csv' ? 'csv' : 'pdf'
      downloadBlob(blob, `audit_logs_${new Date().toISOString().slice(0, 10)}.${ext}`)
    } catch {
      alert('匯出失敗，請稍後再試')
    } finally {
      setExporting(null)
    }
  }

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-gray-400" />
      </div>
    )
  }

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Header */}
      <div className="border-b border-gray-200 bg-white px-6 py-4">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-base font-semibold tracking-tight text-ink md:text-lg">操作紀錄</h2>
            <p className="text-sm text-muted">誰在什麼時候動過什麼資料，都記在這裡</p>
          </div>
          <div className="flex items-center gap-2">
            <button onClick={() => load()} className="inline-flex items-center gap-1.5 rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"><RefreshCw className="h-4 w-4" />重新整理</button>
            <button
              onClick={() => handleExport('csv')}
              disabled={!!exporting}
              className="inline-flex items-center gap-1.5 rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50 transition-colors"
            >
              {exporting === 'csv' ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileSpreadsheet className="h-4 w-4" />}
              匯出 CSV
            </button>
            <button
              onClick={() => handleExport('pdf')}
              disabled={!!exporting}
              className="inline-flex items-center gap-1.5 rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50 transition-colors"
            >
              {exporting === 'pdf' ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileText className="h-4 w-4" />}
              匯出 PDF
            </button>
          </div>
        </div>
        {/* Filter */}
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <input
            type="text"
            placeholder="依操作代碼篩選（進階）"
            value={actionFilter}
            onChange={e => { setActionFilter(e.target.value); setLoading(true) }}
            className="w-full max-w-sm rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          />
          <label className="flex items-center gap-2 text-sm text-gray-600"><input type="checkbox" checked={includeSystemEvents} onChange={event => setIncludeSystemEvents(event.target.checked)} />顯示系統技術事件</label>
        </div>
        <p className="mt-2 text-xs text-muted">預設只顯示公司成員的重要操作；相容性與診斷事件會保留，但不干擾日常追溯。</p>
      </div>

      <div className="flex-1 overflow-y-auto">
        {logs.length === 0 ? (
          <div className="flex flex-col items-center py-16 text-gray-400">
            <Shield className="mb-3 h-10 w-10" />
            <p className="text-sm">尚無稽核日誌</p>
          </div>
        ) : (
          <table className="w-full">
            <thead className="sticky top-0 z-10 bg-gray-50">
              <tr className="border-b border-gray-100 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                <th className="px-6 py-3">時間</th>
                <th className="px-6 py-3">操作</th>
                <th className="px-6 py-3">資料類型</th>
                <th className="px-6 py-3">資料識別</th>
                <th className="px-6 py-3">來源網路</th>
                <th className="px-6 py-3">執行者</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 bg-white">
              {logs.map(log => (
                <tr key={log.id} className="hover:bg-gray-50 transition-colors">
                  <td className="whitespace-nowrap px-6 py-3 text-sm text-gray-500">
                    {new Date(log.created_at).toLocaleString('zh-TW')}
                  </td>
                  <td className="px-6 py-3">
                    <span className="inline-flex items-center rounded-full bg-blue-50 px-2.5 py-0.5 text-xs font-medium text-blue-700">
                      {actionLabel(log.action)}
                    </span>
                  </td>
                  <td className="px-6 py-3 text-sm text-gray-600">{resourceLabel(log.resource_type)}</td>
                  <td className="px-6 py-3 text-sm text-gray-500 font-mono text-xs">{log.resource_id ? log.resource_id.slice(0, 8) + '...' : '—'}</td>
                  <td className="px-6 py-3 text-sm text-gray-500">{maskIp(log.ip_address)}</td>
                  <td className="px-6 py-3 text-sm text-gray-500">{log.actor_display || (log.actor_user_id ? '已登入使用者' : '系統')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {hasMore && <div className="p-4 text-center"><button type="button" className="rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50" onClick={() => load(offset + pageSize, true)} disabled={loading}>載入更多</button></div>}
      </div>
    </div>
  )
}
