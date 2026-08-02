import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import {
  ArrowLeft, FileText, Loader2, ShieldOff, Upload, AlertCircle,
} from 'lucide-react'
import toast from 'react-hot-toast'
import { docApi, kbApi, parseApiError, formatErrorWithTrace } from '../../api'
import type { Document } from '../../types'
import LifecycleBadge, { toLifecycle } from '../../components/LifecycleBadge'
import ConfirmDialog from '../../components/ConfirmDialog'
import { useAuth } from '../../auth'
import { hasCapability } from '../../navigation/capabilities'
import clsx from 'clsx'

type TimelineStep = {
  key: string
  label: string
  done: boolean
  current: boolean
  detail?: string
}

function buildTimeline(doc: Document): TimelineStep[] {
  const life = toLifecycle(doc.status, doc.tombstoned_at)
  const order = ['uploading', 'pending_review', 'processing', 'searchable', 'revoked'] as const
  const labels: Record<string, string> = {
    uploading: '上傳／發現',
    pending_review: '待審核',
    processing: '處理中',
    searchable: '可搜尋',
    revoked: '已撤銷',
  }

  if (life === 'failed') {
    return [
      { key: 'uploading', label: '上傳／發現', done: true, current: false },
      {
        key: 'failed',
        label: '處理失敗',
        done: false,
        current: true,
        detail: doc.error_message || '請查看錯誤後重試或重新上傳',
      },
    ]
  }

  const currentIdx = order.indexOf(life === 'unknown' ? 'processing' : life)
  return order.map((key, i) => ({
    key,
    label: labels[key],
    done: life === 'revoked' ? key !== 'revoked' || true : i < currentIdx,
    current: i === currentIdx || (life === 'revoked' && key === 'revoked'),
    detail:
      key === 'pending_review' && life === 'pending_review'
        ? '審核前暫不可被問到'
        : key === 'searchable' && life === 'searchable'
          ? `可被問答引用${doc.chunk_count != null ? ` · ${doc.chunk_count} 個處理片段` : ''}`
          : key === 'revoked' && life === 'revoked'
            ? '問答已立即拒絕存取；投影可能稍後收斂'
            : undefined,
  })).map(s => {
    if (life === 'revoked' && s.key !== 'revoked') {
      return { ...s, done: true, current: false }
    }
    if (life === 'revoked' && s.key === 'revoked') {
      return { ...s, done: false, current: true }
    }
    return s
  })
}

export default function DocumentDetailPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { user } = useAuth()
  const canManage = hasCapability(user?.role, 'upload_documents', user?.is_superuser)

  const [doc, setDoc] = useState<Document | null>(null)
  const [versions, setVersions] = useState<Array<{ version_number: number; change_note: string | null; created_at: string }>>([])
  const [loading, setLoading] = useState(true)
  const [revokeOpen, setRevokeOpen] = useState(false)
  const [revoking, setRevoking] = useState(false)

  const load = useCallback(async () => {
    if (!id) return
    setLoading(true)
    try {
      const [d, v] = await Promise.all([
        docApi.get(id),
        kbApi.listVersions(id).catch(() => []),
      ])
      setDoc(d)
      setVersions(Array.isArray(v) ? v : (v.versions ?? []))
    } catch {
      toast.error('無法載入文件詳情')
      setDoc(null)
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => { load() }, [load])

  useEffect(() => {
    if (!doc) return
    const life = toLifecycle(doc.status, doc.tombstoned_at)
    if (!['uploading', 'processing', 'pending_review'].includes(life)) return
    const t = setInterval(load, 3000)
    return () => clearInterval(t)
  }, [doc, load])

  const handleRevoke = async () => {
    if (!doc) return
    setRevoking(true)
    try {
      await docApi.delete(doc.id)
      toast.success(`知識已撤銷：問答立即不可見（追蹤：${doc.id.slice(0, 8)}…）`)
      setRevokeOpen(false)
      navigate('/knowledge/documents')
    } catch (err) {
      toast.error(formatErrorWithTrace(parseApiError(err, '撤銷失敗')))
    } finally {
      setRevoking(false)
    }
  }

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="h-7 w-7 animate-spin text-muted" />
      </div>
    )
  }

  if (!doc) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 p-8 text-muted">
        <AlertCircle className="h-10 w-10" />
        <p>找不到此文件，或你沒有存取權限。</p>
        <Link to="/knowledge/documents" className="text-accent underline">返回文件列表</Link>
      </div>
    )
  }

  const timeline = buildTimeline(doc)
  const life = toLifecycle(doc.status, doc.tombstoned_at)

  return (
    <div className="h-full overflow-y-auto bg-wash">
      <div className="mx-auto max-w-3xl space-y-6 p-4 md:p-8">
        <div className="flex items-start gap-3">
          <button
            type="button"
            onClick={() => navigate('/knowledge/documents')}
            className="mt-1 rounded-lg p-1.5 text-muted hover:bg-surface hover:text-ink"
            aria-label="返回"
          >
            <ArrowLeft className="h-5 w-5" />
          </button>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <FileText className="h-5 w-5 text-accent" />
              <h1 className="truncate font-display text-xl font-semibold text-ink">{doc.filename}</h1>
              <LifecycleBadge status={doc.status} tombstoned={doc.tombstoned_at} />
            </div>
            <p className="mt-1 text-sm text-muted">
              {doc.file_type?.toUpperCase() || '檔案'}
              {doc.created_at && ` · 建立 ${new Date(doc.created_at).toLocaleString()}`}
              {doc.updated_at && ` · 更新 ${new Date(doc.updated_at).toLocaleString()}`}
            </p>
          </div>
        </div>

        <section className="rounded-xl border border-line bg-surface p-5">
          <h2 className="text-sm font-semibold text-ink">生命週期</h2>
          <ol className="mt-4 space-y-0">
            {timeline.map((step, i) => (
              <li key={step.key} className="relative flex gap-3 pb-6 last:pb-0">
                {i < timeline.length - 1 && (
                  <span
                    className={clsx(
                      'absolute left-[9px] top-5 h-[calc(100%-12px)] w-0.5',
                      step.done ? 'bg-accent' : 'bg-line',
                    )}
                    aria-hidden
                  />
                )}
                <span
                  className={clsx(
                    'relative z-10 mt-0.5 h-[18px] w-[18px] shrink-0 rounded-full border-2',
                    step.current && 'border-accent bg-accent',
                    step.done && !step.current && 'border-accent bg-accent/20',
                    !step.done && !step.current && 'border-line bg-surface',
                  )}
                />
                <div>
                  <p className={clsx('text-sm font-medium', step.current ? 'text-accent' : 'text-ink')}>
                    {step.label}
                  </p>
                  {step.detail && <p className="mt-0.5 text-xs text-muted">{step.detail}</p>}
                </div>
              </li>
            ))}
          </ol>
        </section>

        <section className="grid gap-4 sm:grid-cols-2">
          <div className="rounded-xl border border-line bg-surface p-4 text-sm">
            <p className="text-xs text-muted">處理片段</p>
            <p className="mt-1 text-lg font-semibold text-ink">{doc.chunk_count ?? '—'}</p>
          </div>
          <div className="rounded-xl border border-line bg-surface p-4 text-sm">
            <p className="text-xs text-muted">目前能否被問到</p>
            <p className="mt-1 text-lg font-semibold text-ink">
              {life === 'searchable' ? '可以' : life === 'revoked' ? '已撤銷' : '尚不可'}
            </p>
          </div>
        </section>

        {doc.error_message && (
          <div className="rounded-xl border border-danger/30 bg-danger/5 p-4 text-sm text-danger">
            {doc.error_message}
          </div>
        )}

        {versions.length > 0 && (
          <section className="rounded-xl border border-line bg-surface p-5">
            <h2 className="text-sm font-semibold text-ink">版本</h2>
            <ul className="mt-3 space-y-2">
              {versions.map((v, i) => (
                <li key={v.version_number} className="rounded-lg border border-line px-3 py-2 text-sm">
                  <span className="font-medium">v{v.version_number}</span>
                  {i === 0 && <span className="ml-2 text-xs text-accent">當前</span>}
                  {v.change_note && <p className="text-xs text-muted">{v.change_note}</p>}
                  <p className="text-xs text-muted">
                    {v.created_at ? new Date(v.created_at).toLocaleString() : ''}
                  </p>
                </li>
              ))}
            </ul>
          </section>
        )}

        <div className="flex flex-wrap gap-2">
          {life === 'searchable' && (
            <Link
              to={`/ask?q=${encodeURIComponent(`請根據「${doc.filename}」說明重點`)}`}
              className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-hover"
            >
              測試提問
            </Link>
          )}
          {life === 'pending_review' && canManage && (
            <Link
              to="/knowledge/review"
              className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-hover"
            >
              前往審核
            </Link>
          )}
          {canManage && life !== 'revoked' && (
            <button
              type="button"
              onClick={() => setRevokeOpen(true)}
              className="inline-flex items-center gap-1.5 rounded-lg border border-danger/40 px-4 py-2 text-sm text-danger hover:bg-danger/5"
            >
              <ShieldOff className="h-4 w-4" /> 撤銷知識
            </button>
          )}
          {canManage && (
            <Link
              to="/knowledge/documents"
              className="inline-flex items-center gap-1.5 rounded-lg border border-line px-4 py-2 text-sm text-muted hover:text-ink"
            >
              <Upload className="h-4 w-4" /> 返回列表上傳新版本
            </Link>
          )}
        </div>
      </div>

      <ConfirmDialog
        open={revokeOpen}
        danger
        busy={revoking}
        title="撤銷此知識？"
        description={`「${doc.filename}」將立即停止出現在問答與搜尋。後端投影可能稍後收斂。`}
        confirmLabel="確認撤銷"
        onCancel={() => !revoking && setRevokeOpen(false)}
        onConfirm={handleRevoke}
      />
    </div>
  )
}
