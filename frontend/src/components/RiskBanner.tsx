import { AlertTriangle } from 'lucide-react'
import clsx from 'clsx'

type Level = 'info' | 'warning' | 'danger'

type Props = {
  level?: Level
  title: string
  description?: string
  className?: string
}

const STYLES: Record<Level, string> = {
  info: 'border-accent/30 bg-accent/5 text-ink',
  warning: 'border-amber-300 bg-amber-50 text-amber-950',
  danger: 'border-danger/40 bg-danger/5 text-ink',
}

export default function RiskBanner({ level = 'warning', title, description, className }: Props) {
  return (
    <div
      role="status"
      className={clsx('flex gap-3 rounded-lg border px-3 py-2.5 text-sm', STYLES[level], className)}
    >
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
      <div>
        <p className="font-medium">{title}</p>
        {description && <p className="mt-0.5 text-xs opacity-90">{description}</p>}
      </div>
    </div>
  )
}
