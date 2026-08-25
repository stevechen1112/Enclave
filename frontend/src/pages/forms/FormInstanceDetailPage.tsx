/**
 * 單一表單實例詳情：預覽、下載、版本／來源／審核軌跡。
 */
import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { Loader2 } from 'lucide-react'
import toast from 'react-hot-toast'
import PageHeader from '../../components/PageHeader'
import { formsApi, type FormInstance } from '../../services/mka'
import { FORM_STATUS_LABELS, FORM_TYPE_LABELS, presentableEntries } from './formPresentation'

export default function FormInstanceDetailPage() {
  const { instanceId = '' } = useParams()
  const [row, setRow] = useState<FormInstance | null>(null)
  const [loading, setLoading] = useState(true)
  const [exporting, setExporting] = useState(false)

  useEffect(() => {
    if (!instanceId) return
    setLoading(true)
    formsApi
      .getInstance(instanceId)
      .then(setRow)
      .catch(() => {
        toast.error('載入失敗')
        setRow(null)
      })
      .finally(() => setLoading(false))
  }, [instanceId])

  const handleExport = async (format: 'pdf' | 'docx' | 'xlsx') => {
    if (!row) return
    setExporting(true)
    try {
      const { blob, filename } = await formsApi.exportSync(row.id, format)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      a.click()
      URL.revokeObjectURL(url)
    } catch {
      toast.error('匯出失敗（可能尚未核准或缺公司版型轉檔）')
    } finally {
      setExporting(false)
    }
  }

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="h-7 w-7 animate-spin text-muted" />
      </div>
    )
  }
  if (!row) {
    return <div className="p-6 text-muted">找不到這張單。</div>
  }

  const values = (row.values_json || row.values || {}) as Record<string, unknown>
  const provenance = (row.provenance_json || row.provenance || {}) as Record<string, unknown>
  const approved = ['approved', 'finalized'].includes(row.status)
  const entries = presentableEntries(values)
  const formTitle = FORM_TYPE_LABELS[row.form_key || ''] || '表單詳情'
  const statusLabel = FORM_STATUS_LABELS[row.status] || '處理中'

  return (
    <div className="h-full overflow-y-auto p-4 md:p-6">
      <div className="mx-auto max-w-3xl space-y-4">
        <PageHeader
          variant="section"
          title={formTitle}
          subtitle={`${statusLabel} · 第 ${row.record_version} 版`}
        />
        <div className="flex flex-wrap gap-2">
          <Link to={`/forms/${row.form_key}`} className="rounded-lg border border-line px-3 py-2 text-sm">
            開新單
          </Link>
          {approved && (
            <>
              <button type="button" disabled={exporting} onClick={() => handleExport('docx')} className="rounded-lg bg-accent px-3 py-2 text-sm text-white">
                下載 Word
              </button>
              <button type="button" disabled={exporting} onClick={() => handleExport('xlsx')} className="rounded-lg bg-accent px-3 py-2 text-sm text-white">
                下載 Excel
              </button>
              <button type="button" disabled={exporting} onClick={() => handleExport('pdf')} className="rounded-lg border border-line px-3 py-2 text-sm">
                下載 PDF
              </button>
            </>
          )}
        </div>
        <section className="rounded-xl border border-line bg-surface p-4">
          <h2 className="mb-2 font-semibold">欄位</h2>
          <dl className="grid gap-2 sm:grid-cols-2">
            {entries.map(([label, value]) => (
              <div key={label}>
                <dt className="text-sm text-muted">{label}</dt>
                <dd className="whitespace-pre-line font-medium text-ink">{value}</dd>
              </div>
            ))}
          </dl>
        </section>
        {Object.keys(provenance).length > 0 && (
          <p className="rounded-xl border border-line bg-wash p-4 text-sm text-muted">
            系統已保留這張單的資料來源與核准紀錄，供公司管理者日後稽核。
          </p>
        )}
      </div>
    </div>
  )
}
