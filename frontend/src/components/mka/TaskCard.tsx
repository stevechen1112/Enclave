/**
 * TaskCard — 職務首頁的工作任務卡片。
 *
 * 設計對象：現場人員從首頁一鍵進入工作流程。
 * - 大觸控目標（≥48px）
 * - 圖示 + 標題 + 簡述
 * - 支援 disabled 狀態（模組未啟用）
 */
import { type LucideIcon, ChevronRight } from 'lucide-react'
import clsx from 'clsx'

export interface TaskCardProps {
  icon: LucideIcon
  title: string
  description: string
  onClick: () => void
  disabled?: boolean
  disabledReason?: string
  badge?: string
}

export default function TaskCard({
  icon: Icon,
  title,
  description,
  onClick,
  disabled,
  disabledReason,
  badge,
}: TaskCardProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={clsx(
        'flex w-full items-center gap-4 rounded-2xl border-2 p-5 text-left transition-all',
        'active:scale-[0.98] min-h-[72px]',
        disabled
          ? 'cursor-not-allowed border-line bg-wash opacity-60'
          : 'border-line bg-surface hover:border-accent/40 hover:shadow-md',
      )}
      aria-label={disabled ? `${title}（${disabledReason || '未啟用'}）` : title}
    >
      <div
        className={clsx(
          'flex h-14 w-14 shrink-0 items-center justify-center rounded-xl',
          disabled ? 'bg-muted/20' : 'bg-accent/10',
        )}
      >
        <Icon className={clsx('h-7 w-7', disabled ? 'text-muted' : 'text-accent')} aria-hidden />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <p className="text-xl font-bold text-ink">{title}</p>
          {badge && (
            <span className="rounded-full bg-accent/15 px-2 py-0.5 text-sm font-bold text-accent">
              {badge}
            </span>
          )}
        </div>
        <p className="mt-0.5 text-base text-muted">{disabled ? disabledReason || '尚未啟用' : description}</p>
      </div>
      <ChevronRight className="h-6 w-6 shrink-0 text-muted" aria-hidden />
    </button>
  )
}
