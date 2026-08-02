import { CheckCircle2, XCircle, AlertTriangle, MinusCircle } from 'lucide-react'
import clsx from 'clsx'

export type ModuleStatusKind = 'enabled' | 'disabled' | 'degraded' | 'unavailable'

type Props = {
  label: string
  status: ModuleStatusKind
  detail?: string
  code?: string
  className?: string
}

const META: Record<ModuleStatusKind, { text: string; icon: typeof CheckCircle2; tone: string }> = {
  enabled: { text: '已啟用', icon: CheckCircle2, tone: 'text-emerald-700' },
  disabled: { text: '未啟用', icon: XCircle, tone: 'text-muted' },
  degraded: { text: '降級', icon: AlertTriangle, tone: 'text-amber-700' },
  unavailable: { text: '不可用', icon: MinusCircle, tone: 'text-danger' },
}

export default function ModuleStatus({ label, status, detail, code, className }: Props) {
  const meta = META[status]
  const Icon = meta.icon
  return (
    <div
      className={clsx(
        'rounded-xl border bg-surface p-4',
        status === 'disabled' || status === 'unavailable' ? 'border-dashed border-line' : 'border-line',
        className,
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <p className="font-medium text-ink">{label}</p>
        <span className={clsx('inline-flex items-center gap-1 text-xs', meta.tone)}>
          <Icon className="h-3.5 w-3.5" aria-hidden />
          {meta.text}
        </span>
      </div>
      {code && <p className="mt-1 font-mono text-[11px] text-muted">{code}</p>}
      {detail && <p className="mt-2 text-xs text-muted">{detail}</p>}
    </div>
  )
}
