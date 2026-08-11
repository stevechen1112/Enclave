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
    <div className={clsx('flex flex-wrap items-end justify-between gap-4', className)}>
      <div className="min-w-0">
        {isSection ? (
          <h2 className="text-lg font-bold tracking-tight text-ink md:text-xl">{title}</h2>
        ) : (
          <h1 className="font-display text-2xl font-semibold tracking-tight text-ink md:text-3xl">{title}</h1>
        )}
        {subtitle && (
          <p className={clsx('max-w-2xl text-[15px] leading-relaxed text-muted', isSection ? 'mt-1' : 'mt-1.5')}>
            {subtitle}
          </p>
        )}
      </div>
      {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}
