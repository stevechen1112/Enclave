/**
 * System health — integrity checks (UIUX §6.2)
 */
import { useCallback, useEffect, useState } from 'react'
import { RefreshCw, ShieldCheck } from 'lucide-react'
import toast from 'react-hot-toast'
import { kbApi, parseApiError, formatErrorWithTrace } from '../../api'
import AsyncState from '../../components/AsyncState'
import PageHeader from '../../components/PageHeader'
import type { ApiErrorInfo } from '../../api'

interface IntegrityReport {
  id: string
  status: string
  total_documents: number
  total_chunks: number
  orphan_chunks: number
  missing_embeddings: number
  failed_documents: number
  stale_documents: number
  started_at: string | null
}

export default function HealthPage() {
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<ApiErrorInfo | null>(null)
  const [reports, setReports] = useState<IntegrityReport[]>([])

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setReports(await kbApi.listIntegrityReports(5))
    } catch (err) {
      setError(parseApiError(err, '無法載入健康資料'))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const handleIntegrity = async () => {
    try {
      await kbApi.triggerIntegrityCheck()
      toast.success('完整性檢查已排程')
      setTimeout(load, 3000)
    } catch (err) {
      toast.error(formatErrorWithTrace(parseApiError(err, '排程失敗')))
    }
  }

  return (
    <div className="h-full overflow-y-auto p-4 md:p-6">
      <div className="mx-auto max-w-4xl space-y-6">
        <PageHeader
          variant="section"
          title="健康"
          subtitle="確認文件與可搜尋索引是否一致；異常時先修復，再擴充來源。"
          actions={(
            <div className="flex gap-2">
              <button
                type="button"
                onClick={load}
                className="inline-flex min-h-11 items-center gap-1.5 rounded-lg border border-line px-3 py-1.5 text-sm text-muted hover:text-ink"
                aria-label="重新整理"
              >
                <RefreshCw className="h-4 w-4" aria-hidden /> 重新整理
              </button>
              <button
                type="button"
                onClick={handleIntegrity}
                className="inline-flex min-h-11 items-center gap-1.5 rounded-lg bg-accent px-3 py-1.5 text-sm text-white hover:bg-accent-hover"
              >
                <ShieldCheck className="h-4 w-4" aria-hidden /> 立即檢查
              </button>
            </div>
          )}
        />

        <AsyncState loading={loading} error={error} onRetry={load} empty={!loading && !error && reports.length === 0} emptyTitle="尚無掃描報告" emptyDescription="執行檢查可確認文件與可搜尋索引是否一致。" emptyActionLabel="立即檢查" onEmptyAction={handleIntegrity}>
          <div className="space-y-2">
            {reports.map(r => (
              <div key={r.id} className="rounded-xl border border-line bg-surface p-4 text-sm">
                <div className="flex justify-between text-xs text-muted">
                  <span>{r.status === 'completed' ? '完成' : r.status}</span>
                  <span>{r.started_at ? new Date(r.started_at).toLocaleString() : ''}</span>
                </div>
                <div className="mt-2 grid grid-cols-2 gap-2 md:grid-cols-4">
                  <div>文件 <strong>{r.total_documents}</strong></div>
                  <div>處理片段 <strong>{r.total_chunks}</strong></div>
                  <div className={r.orphan_chunks > 0 ? 'text-danger' : ''} title="索引中有片段但找不到對應文件">
                    無主片段 <strong>{r.orphan_chunks}</strong>
                  </div>
                  <div className={r.missing_embeddings > 0 ? 'text-danger' : ''} title="文件尚未完成可搜尋索引">
                    未完成索引 <strong>{r.missing_embeddings}</strong>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </AsyncState>
      </div>
    </div>
  )
}
