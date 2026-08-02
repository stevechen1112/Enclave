/**
 * Admin overview task inbox (UIUX §9.3)
 */
import { Link } from 'react-router-dom'
import { ArrowRight } from 'lucide-react'
import clsx from 'clsx'

export type TaskItem = {
  id: string
  title: string
  description: string
  count?: number
  to: string
  actionLabel: string
  tone?: 'default' | 'warning' | 'danger'
}

type Props = {
  tasks: TaskItem[]
  emptyMessage?: string
  className?: string
}

export default function TaskInbox({
  tasks,
  emptyMessage = '知識系統正常 — 目前沒有需要立刻處理的事項。',
  className,
}: Props) {
  if (tasks.length === 0) {
    return (
      <div className={clsx('rounded-xl border border-line bg-surface px-4 py-6 text-sm text-muted', className)}>
        {emptyMessage}
      </div>
    )
  }

  return (
    <ul className={clsx('space-y-2', className)} aria-label="待辦事項">
      {tasks.map(task => (
        <li
          key={task.id}
          className={clsx(
            'flex flex-wrap items-center justify-between gap-3 rounded-xl border bg-surface px-4 py-3',
            task.tone === 'danger' && 'border-danger/30',
            task.tone === 'warning' && 'border-amber-300',
            (!task.tone || task.tone === 'default') && 'border-line',
          )}
        >
          <div className="min-w-0">
            <p className="font-medium text-ink">
              {task.title}
              {typeof task.count === 'number' && (
                <span className="ml-2 rounded-full bg-wash px-2 py-0.5 text-xs text-muted">{task.count}</span>
              )}
            </p>
            <p className="mt-0.5 text-sm text-muted">{task.description}</p>
          </div>
          <Link
            to={task.to}
            className="inline-flex min-h-11 items-center gap-1 rounded-lg bg-accent px-3 py-2 text-sm text-white hover:bg-accent-hover"
          >
            {task.actionLabel}
            <ArrowRight className="h-4 w-4" aria-hidden />
          </Link>
        </li>
      ))}
    </ul>
  )
}
