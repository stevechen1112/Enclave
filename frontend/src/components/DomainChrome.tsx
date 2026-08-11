import type { ReactNode } from 'react'
import clsx from 'clsx'

type Props = {
  title: string
  subtitle?: string
  actions?: ReactNode
  className?: string
}

/** Shared domain header for Knowledge / Governance / System shells */
export default function DomainChrome({ title, subtitle, actions, className }: Props) {
  return (
    <div className={clsx('border-b border-line/60 bg-surface/70 px-4 py-6 backdrop-blur-sm md:px-8', className)}>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          <h1 className="font-display text-[1.75rem] font-semibold tracking-tight text-ink md:text-4xl">
            {title}
          </h1>
          {subtitle && (
            <p className="mt-2 max-w-2xl text-[15px] leading-relaxed text-muted">{subtitle}</p>
          )}
        </div>
        {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
      </div>
    </div>
  )
}
