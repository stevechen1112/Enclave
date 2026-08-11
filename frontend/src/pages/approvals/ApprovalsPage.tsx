/**
 * ApprovalsPage — 主管審核收件匣。
 *
 * 設計對象：傳產主管（可能用手機在現場審單）。
 * 一張單一張卡片，展開看內容快照，三個大按鈕：核准 / 退回修改 / 駁回。
 * 核准是不可逆動作，需二次確認；退回與駁回必須填原因（審核軌跡）。
 */
import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  ArrowLeft,
  CheckCircle2,
  XCircle,
  MessageSquareWarning,
  ChevronDown,
  ChevronUp,
  Loader2,
  Inbox,
} from 'lucide-react'
import clsx from 'clsx'
import toast from 'react-hot-toast'
import { approvalsApi, type ApprovalItem } from '../../services/mka'

const OBJECT_TYPE_LABELS: Record<string, string> = {
  form: '表單',
  form_instance: '表單',
  knowhow: '師傅經驗卡',
}

const SNAPSHOT_FIELD_LABELS: Record<string, string> = {
  customer: '客戶',
  part_number: '料號',
  quantity: '數量',
  unit_price: '單價',
  tax_rate: '稅率%',
  valid_until: '有效期限',
  payment_terms: '付款條件',
  title: '標題',
  summary: '摘要',
  form_key: '表單種類',
}

function snapshotEntries(snapshot: Record<string, unknown>): Array<[string, string]> {
  const values = (snapshot.values as Record<string, unknown>) || snapshot
  return Object.entries(values)
    .filter(([, v]) => v !== null && v !== undefined && v !== '' && typeof v !== 'object')
    .map(([k, v]) => [SNAPSHOT_FIELD_LABELS[k] || k, String(v)])
}

export default function ApprovalsPage() {
  const navigate = useNavigate()
  const [items, setItems] = useState<ApprovalItem[] | null>(null)
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [reason, setReason] = useState('')
  const [acting, setActing] = useState<string | null>(null)
  const [confirmApproveId, setConfirmApproveId] = useState<string | null>(null)

  const load = useCallback(() => {
    approvalsApi
      .inbox()
      .then(setItems)
      .catch(() => {
        setItems([])
        toast.error('審核清單載入失敗，請稍後再試')
      })
  }, [])

  useEffect(load, [load])

  const act = async (item: ApprovalItem, action: 'approve' | 'reject' | 'request-changes') => {
    if ((action === 'reject' || action === 'request-changes') && !reason.trim()) {
      toast.error('請填寫原因，讓送單的人知道要改什麼')
      return
    }
    setActing(item.id)
    try {
      await approvalsApi.decide(item.id, action, item.record_version, reason.trim())
      toast.success(
        action === 'approve' ? '已核准' : action === 'reject' ? '已駁回' : '已退回修改',
      )
      setReason('')
      setConfirmApproveId(null)
      setExpandedId(null)
      load()
    } catch (err) {
      const status = (err as { response?: { status?: number } })?.response?.status
      if (status === 409) {
        toast.error('這張單已被其他人處理或內容已更新，清單已重新整理')
        load()
      } else {
        toast.error('操作失敗，請再試一次')
      }
    } finally {
      setActing(null)
    }
  }

  return (
    <div className="mx-auto flex h-full max-w-2xl flex-col gap-4 overflow-y-auto p-4 pb-8">
      <header className="flex items-center gap-3">
        <button
          type="button"
          onClick={() => navigate('/job')}
          aria-label="回上一頁"
          className="rounded-xl border-2 border-line p-3 text-muted hover:bg-wash"
        >
          <ArrowLeft className="h-6 w-6" aria-hidden />
        </button>
        <div>
          <h1 className="text-2xl font-bold text-ink">待審核</h1>
          <p className="text-base text-muted">核准前請展開確認內容；核准後就會產生正式文件。</p>
        </div>
      </header>

      {items === null && (
        <div className="flex flex-1 items-center justify-center" role="status">
          <Loader2 className="h-10 w-10 animate-spin text-accent" aria-label="載入中" />
        </div>
      )}

      {items !== null && items.length === 0 && (
        <div className="flex flex-1 flex-col items-center justify-center gap-3 text-center">
          <Inbox className="h-16 w-16 text-line" aria-hidden />
          <p className="text-xl font-bold text-ink">目前沒有待審核的單據</p>
          <p className="text-lg text-muted">有人送單時會出現在這裡。</p>
        </div>
      )}

      {items?.map(item => {
        const expanded = expandedId === item.id
        const entries = snapshotEntries(item.immutable_snapshot || {})
        const busy = acting === item.id
        return (
          <article
            key={item.id}
            className="rounded-2xl border-2 border-line bg-surface shadow-sm"
          >
            <button
              type="button"
              onClick={() => {
                setExpandedId(expanded ? null : item.id)
                setReason('')
                setConfirmApproveId(null)
              }}
              aria-expanded={expanded}
              className="flex min-h-20 w-full items-center justify-between gap-3 px-5 text-left"
            >
              <div>
                <p className="text-xl font-bold text-ink">
                  {OBJECT_TYPE_LABELS[item.object_type] || item.object_type}
                  <span className="ml-2 font-mono text-base font-normal text-muted">
                    #{item.id.slice(0, 8)}
                  </span>
                </p>
                <p className="text-base text-muted">
                  {item.created_at ? new Date(item.created_at).toLocaleString('zh-TW') : ''}
                </p>
              </div>
              {expanded ? (
                <ChevronUp className="h-7 w-7 shrink-0 text-muted" aria-hidden />
              ) : (
                <ChevronDown className="h-7 w-7 shrink-0 text-muted" aria-hidden />
              )}
            </button>

            {expanded && (
              <div className="flex flex-col gap-4 border-t-2 border-line px-5 py-4">
                {entries.length > 0 ? (
                  <dl className="grid grid-cols-1 gap-2">
                    {entries.map(([label, value]) => (
                      <div key={label} className="flex justify-between gap-4 text-lg">
                        <dt className="shrink-0 text-muted">{label}</dt>
                        <dd className="break-all text-right font-semibold text-ink">{value}</dd>
                      </div>
                    ))}
                  </dl>
                ) : (
                  <p className="text-lg text-muted">（此單據無明細快照）</p>
                )}

                <label htmlFor={`reason-${item.id}`} className="text-base font-medium text-muted">
                  審核意見（退回或駁回時必填）：
                </label>
                <textarea
                  id={`reason-${item.id}`}
                  value={reason}
                  onChange={e => setReason(e.target.value)}
                  rows={2}
                  placeholder="例如：單價低於底價，請重新確認"
                  className="w-full rounded-xl border-2 border-line bg-wash p-3 text-lg text-ink focus:border-accent focus:outline-none"
                />

                {confirmApproveId === item.id ? (
                  <div className="rounded-xl border-2 border-amber-400 bg-amber-50 p-4">
                    <p className="mb-3 text-lg font-bold text-amber-900">
                      確定核准？核准後就不能再修改內容。
                    </p>
                    <div className="flex gap-3">
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => void act(item, 'approve')}
                        className="flex min-h-14 flex-1 items-center justify-center gap-2 rounded-xl bg-accent text-lg font-bold text-white disabled:opacity-50"
                      >
                        {busy ? <Loader2 className="h-6 w-6 animate-spin" aria-hidden /> : null}
                        確定核准
                      </button>
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => setConfirmApproveId(null)}
                        className="min-h-14 rounded-xl border-2 border-line px-5 text-lg font-bold text-muted"
                      >
                        再想想
                      </button>
                    </div>
                  </div>
                ) : (
                  <div className="grid grid-cols-1 gap-3">
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => setConfirmApproveId(item.id)}
                      className={clsx(
                        'flex min-h-16 items-center justify-center gap-2 rounded-xl text-xl font-bold text-white',
                        'bg-accent hover:bg-accent-hover active:scale-[0.98] disabled:opacity-50',
                      )}
                    >
                      <CheckCircle2 className="h-7 w-7" aria-hidden />
                      核准
                    </button>
                    <div className="grid grid-cols-2 gap-3">
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => void act(item, 'request-changes')}
                        className="flex min-h-14 items-center justify-center gap-2 rounded-xl border-2 border-amber-500 text-lg font-bold text-amber-700 hover:bg-amber-50 disabled:opacity-50"
                      >
                        <MessageSquareWarning className="h-6 w-6" aria-hidden />
                        退回修改
                      </button>
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => void act(item, 'reject')}
                        className="flex min-h-14 items-center justify-center gap-2 rounded-xl border-2 border-danger text-lg font-bold text-danger hover:bg-red-50 disabled:opacity-50"
                      >
                        <XCircle className="h-6 w-6" aria-hidden />
                        駁回
                      </button>
                    </div>
                  </div>
                )}
              </div>
            )}
          </article>
        )
      })}
    </div>
  )
}
