import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import {
  ArrowLeft, FileText, ShieldOff, Upload,
} from 'lucide-react'
import toast from 'react-hot-toast'
import { docApi, kbApi, parseApiError, formatErrorWithTrace, type ApiErrorInfo } from '../../api'
import type { Document } from '../../types'
import LifecycleBadge, { toLifecycle } from '../../components/LifecycleBadge'
import ConfirmDialog from '../../components/ConfirmDialog'
import AsyncState from '../../components/AsyncState'
import { useHasCapability } from '../../navigation/useCapabilities'
import clsx from 'clsx'
import EvidenceLocatorBanner from '../../components/EvidenceLocatorBanner'

type TimelineStep = {
  key: string
  label: string
  done: boolean
  current: boolean
  detail?: string
}

function buildTimeline(doc: Document): TimelineStep[] {
  const life = toLifecycle(doc.status, doc.tombstoned_at, doc.answer_ready)
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

  if (life === 'not_searchable') {
    return [
      { key: 'uploading', label: '上傳／發現', done: true, current: false },
      { key: 'processing', label: '內容處理', done: true, current: false },
      {
        key: 'not_searchable',
        label: '尚不可查',
        done: false,
        current: true,
        detail: '文件尚未同時通過品質檢查、建立搜尋分段並進入正式知識版本。',
      },
    ]
  }

  const currentIdx = order.indexOf(life === 'unknown' ? 'processing' : life)
  return order.map((key, i) => ({
    key,
    label: labels[key],
    done: life === 'revoked' ? true : i < currentIdx,
    current: i === currentIdx || (life === 'revoked' && key === 'revoked'),
    detail:
      key === 'pending_review' && life === 'pending_review'
        ? '審核前暫不可被問到'
        : key === 'searchable' && life === 'searchable'
            ? `可被問答引用 · 正式版本 ${doc.published_revision ?? '—'} · ${doc.published_chunk_count} 段可搜尋內容`
          : key === 'revoked' && life === 'revoked'
            ? '問答已立即拒絕引用此文件'
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
  const canManage = useHasCapability('upload_documents')

  const [doc, setDoc] = useState<Document | null>(null)
  const [versions, setVersions] = useState<Array<{ version_number: number; change_note: string | null; created_at: string }>>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<ApiErrorInfo | null>(null)
  const [revokeOpen, setRevokeOpen] = useState(false)
  const [revoking, setRevoking] = useState(false)

  const load = useCallback(async () => {
    if (!id) return
    setLoading(true)
    setError(null)
    try {
      const [d, v] = await Promise.all([
        docApi.get(id),
        kbApi.listVersions(id).catch(() => []),
      ])
      setDoc(d)
      setVersions(Array.isArray(v) ? v : (v.versions ?? []))
    } catch (err) {
      const info = parseApiError(err, '無法載入文件詳情')
      if (info.status === 404 || info.status === 403) {
        setError({ ...info, message: '找不到此文件，或你沒有存取權限。', retryable: false })
      } else {
        setError(info)
      }
      setDoc(null)
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => { load() }, [load])

  useEffect(() => {
    if (!doc) return
    const life = toLifecycle(doc.status, doc.tombstoned_at, doc.answer_ready)
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

  const timeline = doc ? buildTimeline(doc) : []
  const life = doc ? toLifecycle(doc.status, doc.tombstoned_at, doc.answer_ready) : 'unknown'

  return (
    <div className="h-full overflow-y-auto">
      <AsyncState
        loading={loading}
        error={error}
        onRetry={load}
        empty={false}
      >
        {doc && (
          <div className="mx-auto max-w-3xl space-y-6 p-4 md:p-8">
            <EvidenceLocatorBanner />
            <div className="flex items-start gap-2">
              <button
                type="button"
                onClick={() => navigate('/knowledge/documents')}
                className="icon-btn mt-1 shrink-0"
                aria-label="返回文件列表"
              >
                <ArrowLeft className="h-5 w-5" aria-hidden />
              </button>
              <div className="min-w-0 flex-1 animate-fade-in">
                <div className="flex flex-wrap items-center gap-2">
                  <FileText className="h-5 w-5 text-accent" aria-hidden />
                  <h1 className="truncate font-display text-xl font-semibold text-ink">{doc.filename}</h1>
                  <LifecycleBadge status={doc.status} tombstoned={doc.tombstoned_at} answerReady={doc.answer_ready} />
                </div>
                <p className="mt-1 text-sm text-muted">
                  {doc.file_type || '檔案'}
                  {doc.created_at && ` · 建立 ${new Date(doc.created_at).toLocaleString()}`}
                  {doc.updated_at && ` · 更新 ${new Date(doc.updated_at).toLocaleString()}`}
                </p>
              </div>
            </div>

            <section className="card animate-rise-in p-5">
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
                        step.done && !step.current && 'border-accent bg-accent-soft',
                        !step.done && !step.current && 'border-line bg-surface',
                      )}
                      aria-hidden
                    />
                    <div>
                      <p className={clsx('text-sm font-medium', step.current ? 'text-accent' : 'text-ink')}>
                        {step.label}
                      </p>
                      {step.detail && <p className="mt-0.5 text-sm text-muted">{step.detail}</p>}
                    </div>
                  </li>
                ))}
              </ol>
            </section>

            <section className="grid gap-4 sm:grid-cols-2">
              <div className="card p-4 text-sm">
                <p className="text-sm text-muted">搜尋分段</p>
                <p className="mt-1 text-lg font-semibold text-ink">
                  {doc.answer_ready ? `${doc.published_chunk_count} 段正式可查內容` : '尚無正式可查內容'}
                </p>
              </div>
              <div className="card p-4 text-sm">
                <p className="text-sm text-muted">目前能否被問到</p>
                <p className="mt-1 text-lg font-semibold text-ink">
                  {doc.answer_ready ? '可以' : life === 'revoked' ? '已撤銷' : '尚不可'}
                </p>
              </div>
            </section>

            {doc.error_message && (
              <div className="rounded-2xl border border-danger/30 bg-danger-soft p-4 text-sm text-danger">
                {doc.error_message}
              </div>
            )}

            {versions.length > 0 && (
              <section className="card p-5">
                <h2 className="text-sm font-semibold text-ink">版本</h2>
                <ul className="mt-3 space-y-2">
                  {versions.map((v, i) => (
                    <li key={v.version_number} className="rounded-xl border border-line px-3 py-2 text-sm">
                      <span className="font-medium">版本 {v.version_number}</span>
                      {i === 0 && <span className="chip-accent ml-2">目前版本</span>}
                      {v.change_note && <p className="text-sm text-muted">{v.change_note}</p>}
                      <p className="text-xs text-muted">
                        {v.created_at ? new Date(v.created_at).toLocaleString() : ''}
                      </p>
                    </li>
                  ))}
                </ul>
              </section>
            )}

            <div className="flex flex-wrap gap-2">
              {doc.answer_ready && (
                <Link
                  to={`/ask?q=${encodeURIComponent(`請根據「${doc.filename}」說明重點`)}`}
                  className="btn-primary"
                >
                  測試提問
                </Link>
              )}
              {life === 'pending_review' && canManage && (
                <Link to="/knowledge/review" className="btn-primary">
                  前往審核
                </Link>
              )}
              {canManage && life !== 'revoked' && (
                <button
                  type="button"
                  onClick={() => setRevokeOpen(true)}
                  className="btn-outline text-danger hover:border-danger/40 hover:bg-danger-soft"
                >
                  <ShieldOff className="h-4 w-4" aria-hidden /> 撤銷知識
                </button>
              )}
              {canManage && (
                <Link to="/knowledge/documents" className="btn-outline">
                  <Upload className="h-4 w-4" aria-hidden /> 返回列表上傳新版本
                </Link>
              )}
            </div>
          </div>
        )}
      </AsyncState>

      <ConfirmDialog
        open={revokeOpen}
        danger
        busy={revoking}
        title="撤銷此知識？"
        description={doc ? `「${doc.filename}」將立即停止出現在問答與搜尋中，且無法復原。` : ''}
        confirmLabel="確認撤銷"
        onCancel={() => !revoking && setRevokeOpen(false)}
        onConfirm={handleRevoke}
      />
    </div>
  )
}
