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
    <div className={clsx('border-b border-line/80 bg-surface/90 backdrop-blur-sm px-4 py-5 md:px-8', className)}>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          <h1 className="font-display text-2xl font-semibold tracking-tight text-ink md:text-[1.65rem]">
            {title}
          </h1>
          {subtitle && (
            <p className="mt-1 max-w-2xl text-sm leading-relaxed text-muted">{subtitle}</p>
          )}
        </div>
        {actions}
      </div>
    </div>
  )
}
