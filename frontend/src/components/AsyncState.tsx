/**
 * Cross-page async UI — loading / empty / error with retry + request ID (UIUX §10)
 */
import { Loader2, RefreshCw, Inbox } from 'lucide-react'
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
          <div className="flex flex-1 items-center justify-center">
            <Loader2 className="h-7 w-7 animate-spin text-muted" aria-hidden />
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
      <div className={clsx('flex h-full min-h-[12rem] flex-col items-center justify-center gap-3 px-4 text-center', className)}>
        <p className="text-sm text-ink">{info.message}</p>
        {info.requestId && (
          <p className="font-mono text-xs text-muted">追蹤：{info.requestId}</p>
        )}
        {onRetry && info.retryable !== false && (
          <button
            type="button"
            onClick={onRetry}
            className="inline-flex min-h-11 items-center gap-2 rounded-lg border border-line bg-surface px-4 py-2 text-sm text-ink hover:bg-wash focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
          >
            <RefreshCw className="h-4 w-4" aria-hidden />
            重試
          </button>
        )}
      </div>
    )
  }

  if (empty) {
    return (
      <div className={clsx('flex h-full min-h-[12rem] flex-col items-center justify-center gap-3 px-4 text-center', className)}>
        <Inbox className="h-10 w-10 text-muted/50" aria-hidden />
        <div>
          <p className="text-sm font-medium text-ink">{emptyTitle}</p>
          {emptyDescription && <p className="mt-1 text-sm text-muted">{emptyDescription}</p>}
        </div>
        {emptyActionLabel && onEmptyAction && (
          <button
            type="button"
            onClick={onEmptyAction}
            className="inline-flex min-h-11 items-center rounded-lg bg-accent px-4 py-2 text-sm text-white hover:bg-accent-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
          >
            {emptyActionLabel}
          </button>
        )}
      </div>
    )
  }

  return <>{children}</>
}
