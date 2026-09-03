import clsx from 'clsx'
import { AlertCircle, CheckCircle, Clock, Loader2, ShieldOff } from 'lucide-react'

/** Unified document lifecycle labels (UIUX 2.0 §8.2) */
export type LifecycleState =
  | 'uploading'
  | 'pending_review'
  | 'processing'
  | 'searchable'
  | 'not_searchable'
  | 'failed'
  | 'revoked'
  | 'unknown'

const CONFIG: Record<
  LifecycleState,
  { label: string; className: string; Icon: typeof Loader2; spin?: boolean }
> = {
  uploading: {
    label: '上傳中',
    className: 'bg-amber-50 text-amber-800',
    Icon: Loader2,
    spin: true,
  },
  pending_review: {
    label: '等待人工確認',
    className: 'bg-orange-50 text-orange-800',
    Icon: Clock,
  },
  processing: {
    label: '處理中',
    className: 'bg-sky-50 text-sky-800',
    Icon: Loader2,
    spin: true,
  },
  searchable: {
    label: '已可問答',
    className: 'bg-emerald-50 text-emerald-800',
    Icon: CheckCircle,
  },
  not_searchable: {
    label: '尚不可問答',
    className: 'bg-amber-50 text-amber-800',
    Icon: AlertCircle,
  },
  failed: {
    label: '失敗',
    className: 'bg-red-50 text-red-800',
    Icon: AlertCircle,
  },
  revoked: {
    label: '已撤銷',
    className: 'bg-slate-100 text-slate-700',
    Icon: ShieldOff,
  },
  unknown: {
    label: '未知',
    className: 'bg-slate-50 text-slate-600',
    Icon: Clock,
  },
}

/** Map backend document.status (+ tombstone) to UI lifecycle */
// eslint-disable-next-line react-refresh/only-export-components
export function toLifecycle(
  status: string | null | undefined,
  tombstoned?: boolean | string | null,
  answerReady = false,
): LifecycleState {
  if (tombstoned) return 'revoked'
  const s = (status || '').toLowerCase()
  if (answerReady) return 'searchable'
  if (s === 'uploading') return 'uploading'
  if (s === 'pending_review' || s === 'pending' || s === 'review_required') return 'pending_review'
  if (s === 'awaiting_review') return 'pending_review'
  if (s === 'parsing' || s === 'embedding' || s === 'processing' || s === 'queued' || s === 'running') return 'processing'
  if (s === 'completed' || s === 'indexed' || s === 'searchable' || s === 'ready' || s === 'active' || s === 'draft') return 'not_searchable'
  if (s === 'failed' || s === 'needs_attention') return 'failed'
  if (s === 'revoked' || s === 'tombstoned') return 'revoked'
  return 'unknown'
}

export default function LifecycleBadge({
  status,
  tombstoned,
  answerReady,
}: {
  status?: string | null
  tombstoned?: boolean | string | null
  answerReady?: boolean
}) {
  const state = toLifecycle(status, tombstoned, answerReady)
  const { label, className, Icon, spin } = CONFIG[state]
  return (
    <span
      className={clsx(
        'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium',
        className,
      )}
    >
      <Icon className={clsx('h-3 w-3', spin && 'animate-spin')} aria-hidden />
      {label}
    </span>
  )
}
