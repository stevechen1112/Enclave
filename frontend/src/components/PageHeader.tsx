import clsx from 'clsx'

type Props = {
  title: string
  subtitle?: string
  actions?: React.ReactNode
  className?: string
  /** section = under DomainChrome (no competing display h1) */
  variant?: 'page' | 'section'
}

export default function PageHeader({
  title,
  subtitle,
  actions,
  className,
  variant = 'page',
}: Props) {
  const isSection = variant === 'section'
  return (
    <div className={clsx('flex flex-wrap items-end justify-between gap-3', className)}>
      <div className="min-w-0">
        {isSection ? (
          <h2 className="text-base font-semibold tracking-tight text-ink md:text-lg">{title}</h2>
        ) : (
          <h1 className="font-display text-xl font-semibold tracking-tight text-ink md:text-2xl">{title}</h1>
        )}
        {subtitle && (
          <p className={clsx('max-w-2xl text-sm leading-relaxed text-muted', isSection ? 'mt-0.5' : 'mt-1')}>
            {subtitle}
          </p>
        )}
      </div>
      {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}
