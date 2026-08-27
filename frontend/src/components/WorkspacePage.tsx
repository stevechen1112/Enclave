import type { ReactNode } from 'react'
import { ArrowLeft } from 'lucide-react'
import { Link } from 'react-router-dom'
import clsx from 'clsx'
import PageHeader from './PageHeader'

type WorkspacePageProps = {
  title: string
  subtitle?: string
  actions?: ReactNode
  backTo?: string
  backLabel?: string
  width?: 'wide' | 'reading'
  children: ReactNode
  className?: string
}

/** Standard scroll, spacing and heading contract for task-oriented pages. */
export function WorkspacePage({
  title,
  subtitle,
  actions,
  backTo,
  backLabel = '返回',
  width = 'wide',
  children,
  className,
}: WorkspacePageProps) {
  return (
    <div className="h-full overflow-y-auto px-4 py-5 md:px-8">
      <div className={clsx('mx-auto w-full', width === 'reading' ? 'max-w-4xl' : 'max-w-[96rem]', className)}>
        {backTo && (
          <Link to={backTo} className="mb-4 inline-flex min-h-11 items-center gap-2 rounded-lg pr-3 text-sm font-medium text-accent hover:bg-accent-soft/50">
            <ArrowLeft className="h-4 w-4" aria-hidden />
            {backLabel}
          </Link>
        )}
        <PageHeader variant="section" title={title} subtitle={subtitle} actions={actions} />
        {children}
      </div>
    </div>
  )
}

type SectionPanelProps = {
  title?: string
  description?: string
  actions?: ReactNode
  children: ReactNode
  className?: string
  bodyClassName?: string
  labelledBy?: string
}

/** Shared visual hierarchy for a single workspace concern. */
export function SectionPanel({
  title,
  description,
  actions,
  children,
  className,
  bodyClassName,
  labelledBy,
}: SectionPanelProps) {
  const generatedId = labelledBy || (title ? `panel-${title.replace(/\s+/g, '-').toLowerCase()}` : undefined)
  return (
    <section className={clsx('panel', className)} aria-labelledby={title ? generatedId : undefined}>
      {(title || description || actions) && (
        <div className="flex flex-wrap items-start justify-between gap-3 border-b border-line/70 px-5 py-4">
          <div className="min-w-0">
            {title && <h3 id={generatedId} className="font-semibold text-ink">{title}</h3>}
            {description && <p className="mt-1 text-sm leading-relaxed text-muted">{description}</p>}
          </div>
          {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
        </div>
      )}
      <div className={clsx('p-5', bodyClassName)}>{children}</div>
    </section>
  )
}

export type MetadataItem = {
  label: string
  value: ReactNode
  mono?: boolean
}

export function MetadataList({ items, className }: { items: MetadataItem[]; className?: string }) {
  return (
    <dl className={clsx('divide-y divide-line/70', className)}>
      {items.map(item => (
        <div key={item.label} className="grid gap-1 py-3 first:pt-0 last:pb-0 sm:grid-cols-[8rem_minmax(0,1fr)] sm:gap-4">
          <dt className="text-sm text-muted">{item.label}</dt>
          <dd className={clsx('min-w-0 break-words text-sm text-ink', item.mono && 'font-mono text-xs')}>{item.value || '—'}</dd>
        </div>
      ))}
    </dl>
  )
}
