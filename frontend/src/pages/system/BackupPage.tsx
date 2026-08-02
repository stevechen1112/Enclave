/**
 * System backup / restore (UIUX §6.2)
 */
import { useCallback, useEffect, useState } from 'react'
import { Archive, HardDrive, RefreshCw } from 'lucide-react'
import toast from 'react-hot-toast'
import { kbApi, parseApiError, formatErrorWithTrace, type ApiErrorInfo } from '../../api'
import ConfirmDialog from '../../components/ConfirmDialog'
import AsyncState from '../../components/AsyncState'
import PageHeader from '../../components/PageHeader'

interface Backup {
  id: string
  backup_type: string
  status: string
  file_size_bytes: number | null
  document_count: number | null
  started_at: string | null
}

export default function BackupPage() {
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<ApiErrorInfo | null>(null)
  const [backups, setBackups] = useState<Backup[]>([])
  const [restoreId, setRestoreId] = useState<string | null>(null)
  const [restoring, setRestoring] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setBackups(await kbApi.listBackups(10))
    } catch (err) {
      setError(parseApiError(err, '無法載入備份資料'))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const handleBackup = async () => {
    try {
      await kbApi.createBackup('full')
      toast.success('備份已排程')
      setTimeout(load, 3000)
    } catch (err) {
      toast.error(formatErrorWithTrace(parseApiError(err, '備份排程失敗')))
    }
  }

  const confirmRestore = async () => {
    if (!restoreId) return
    setRestoring(true)
    try {
      await kbApi.restore(restoreId)
      toast.success('還原已排程')
      setRestoreId(null)
      setTimeout(load, 3000)
    } catch (err) {
      toast.error(formatErrorWithTrace(parseApiError(err, '還原失敗')))
    } finally {
      setRestoring(false)
    }
  }

  return (
    <div className="h-full overflow-y-auto p-4 md:p-6">
      <div className="mx-auto max-w-4xl space-y-6">
        <PageHeader
          variant="section"
          title="備份"
          subtitle="在維護窗口執行備份與還原；還原會覆蓋現有知識庫資料。"
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
                onClick={handleBackup}
                className="inline-flex min-h-11 items-center gap-1.5 rounded-lg bg-accent px-3 py-1.5 text-sm text-white hover:bg-accent-hover"
              >
                <HardDrive className="h-4 w-4" aria-hidden /> 立即備份
              </button>
            </div>
          )}
        />

        <AsyncState
          loading={loading}
          error={error}
          onRetry={load}
          empty={!loading && !error && backups.length === 0}
          emptyTitle="尚無備份記錄"
          emptyDescription="建議定期建立完整備份，以便於故障時還原。"
          emptyActionLabel="立即備份"
          onEmptyAction={handleBackup}
        >
          <div className="divide-y rounded-xl border border-line bg-surface">
            {backups.map(b => (
              <div key={b.id} className="flex items-center gap-3 p-4">
                <Archive className="h-5 w-5 text-muted" aria-hidden />
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium text-ink">
                    {b.backup_type === 'full' ? '完整備份' : '增量備份'}
                    <span className="ml-2 text-xs text-muted">{b.status}</span>
                  </p>
                  <p className="text-xs text-muted">
                    {b.started_at ? new Date(b.started_at).toLocaleString() : ''}
                    {b.document_count != null && ` · ${b.document_count} 文件`}
                  </p>
                </div>
                {b.status === 'completed' && (
                  <button
                    type="button"
                    onClick={() => setRestoreId(b.id)}
                    className="min-h-11 rounded-lg border border-line px-2.5 py-1 text-xs text-muted hover:text-ink"
                  >
                    還原
                  </button>
                )}
              </div>
            ))}
          </div>
        </AsyncState>
      </div>

      <ConfirmDialog
        open={!!restoreId}
        danger
        busy={restoring}
        title="還原此備份？"
        description="還原會覆蓋現有知識庫資料。請確認這是你要恢復的時間點；此操作應在維護窗口執行。"
        confirmLabel="確認還原"
        onCancel={() => !restoring && setRestoreId(null)}
        onConfirm={confirmRestore}
      />
    </div>
  )
}
