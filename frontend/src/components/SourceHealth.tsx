/**
 * Source sync health card (UIUX §9.6 / §13)
 */
import { Activity, AlertCircle, CheckCircle2, Clock } from 'lucide-react'
import clsx from 'clsx'

export type SourceHealthData = {
  name: string
  status: string
  lastSuccessAt?: string | null
  documentCount?: number | null
  lagLabel?: string | null
  failureReason?: string | null
  packDisabled?: boolean
}

type Props = {
  data: SourceHealthData
  actions?: React.ReactNode
  className?: string
}

function statusTone(status: string, packDisabled?: boolean) {
  if (packDisabled) return 'text-muted'
  const s = status.toLowerCase()
  if (s.includes('fail') || s.includes('error')) return 'text-danger'
  if (s.includes('sync') || s.includes('run') || s.includes('active') || s.includes('ok') || s.includes('idle')) {
    return 'text-emerald-700'
  }
  return 'text-amber-700'
}

export default function SourceHealth({ data, actions, className }: Props) {
  const tone = statusTone(data.status, data.packDisabled)
  return (
    <div className={clsx('rounded-xl border border-line bg-surface p-4', className)}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="font-medium text-ink">{data.name}</p>
          <p className={clsx('mt-1 inline-flex items-center gap-1 text-xs', tone)}>
            {data.packDisabled ? (
              <AlertCircle className="h-3.5 w-3.5" aria-hidden />
            ) : data.failureReason ? (
              <AlertCircle className="h-3.5 w-3.5" aria-hidden />
            ) : (
              <CheckCircle2 className="h-3.5 w-3.5" aria-hidden />
            )}
            {data.packDisabled ? '能力包未啟用' : data.status}
          </p>
        </div>
        {actions}
      </div>
      <dl className="mt-3 grid gap-2 text-xs text-muted sm:grid-cols-2">
        <div className="inline-flex items-center gap-1.5">
          <Clock className="h-3.5 w-3.5" aria-hidden />
          上次成功：{data.lastSuccessAt ? new Date(data.lastSuccessAt).toLocaleString() : '尚無'}
        </div>
        <div className="inline-flex items-center gap-1.5">
          <Activity className="h-3.5 w-3.5" aria-hidden />
          文件數：{data.documentCount != null ? data.documentCount : '—'}
        </div>
        {data.lagLabel && (
          <div className="sm:col-span-2">延遲：{data.lagLabel}</div>
        )}
        {data.failureReason && (
          <div className="sm:col-span-2 text-danger">失敗原因：{data.failureReason}</div>
        )}
      </dl>
    </div>
  )
}
