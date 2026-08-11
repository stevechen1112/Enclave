/**
 * Cross-page async UI — loading / empty / error with retry + request ID (UIUX §10)
 */
import { Loader2, RefreshCw, Inbox, CloudOff } from 'lucide-react'
import clsx from 'clsx'
import type { ApiErrorInfo } from '../lib/apiError'

type Props = {
  loading?: boolean
  error?: ApiErrorInfo | string | null
  empty?: boolean
  emptyTitle?: string
  emptyDescription?: string
  emptyActionLabel?: string
  onEmptyAction?: () => void
  onRetry?: () => void
  skeleton?: React.ReactNode
  className?: string
  children: React.ReactNode
}

export default function AsyncState({
  loading,
  error,
  empty,
  emptyTitle = '尚無資料',
  emptyDescription,
  emptyActionLabel,
  onEmptyAction,
  onRetry,
  skeleton,
  className,
  children,
}: Props) {
  if (loading) {
    return (
      <div className={clsx('flex h-full min-h-[12rem] flex-col', className)} role="status" aria-label="載入中">
        {skeleton || (
          <div className="flex flex-1 flex-col items-center justify-center gap-3">
            <Loader2 className="h-8 w-8 animate-spin text-accent" aria-hidden />
            <p className="text-sm text-muted">載入中…</p>
          </div>
        )}
      </div>
    )
  }

  if (error) {
    const info = typeof error === 'string'
      ? { message: error, retryable: true as const }
      : error
    return (
      <div className={clsx('flex h-full min-h-[12rem] flex-col items-center justify-center gap-4 px-4 text-center', className)}>
        <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-danger-soft">
          <CloudOff className="h-7 w-7 text-danger" aria-hidden />
        </div>
        <div>
          <p className="text-[15px] font-semibold text-ink">載入失敗</p>
          <p className="mt-1 text-sm text-muted">{info.message}</p>
          {info.requestId && (
            <p className="mt-1 font-mono text-xs text-muted">追蹤：{info.requestId}</p>
          )}
        </div>
        {onRetry && info.retryable !== false && (
          <button type="button" onClick={onRetry} className="btn-outline">
            <RefreshCw className="h-4 w-4" aria-hidden />
            重試
          </button>
        )}
      </div>
    )
  }

  if (empty) {
    return (
      <div className={clsx('flex h-full min-h-[12rem] flex-col items-center justify-center gap-4 px-4 text-center', className)}>
        <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-accent-soft">
          <Inbox className="h-7 w-7 text-accent" aria-hidden />
        </div>
        <div>
          <p className="text-[15px] font-semibold text-ink">{emptyTitle}</p>
          {emptyDescription && <p className="mt-1 text-sm text-muted">{emptyDescription}</p>}
        </div>
        {emptyActionLabel && onEmptyAction && (
          <button type="button" onClick={onEmptyAction} className="btn-primary">
            {emptyActionLabel}
          </button>
        )}
      </div>
    )
  }

  return <>{children}</>
}
