/**
 * ApprovalTimeline — 審核流程時間軸（§6.4）。
 *
 * 顯示審核步驟、審核者、決策與時間。
 */
import { Check, X, Clock, MessageSquare } from 'lucide-react'
import clsx from 'clsx'

export interface ApprovalStep {
  step: number
  name: string
  roles: string[]
  status: 'pending' | 'approved' | 'rejected' | 'changes_requested' | 'waiting'
  reviewer?: string
  reason?: string
  decided_at?: string
}

interface ApprovalTimelineProps {
  steps: ApprovalStep[]
  currentStep: number
}

const STEP_ICONS: Record<string, typeof Check> = {
  approved: Check,
  rejected: X,
  changes_requested: MessageSquare,
  waiting: Clock,
  pending: Clock,
}

const STEP_COLORS: Record<string, string> = {
  approved: 'bg-green-500 text-white',
  rejected: 'bg-red-500 text-white',
  changes_requested: 'bg-amber-500 text-white',
  waiting: 'bg-gray-300 text-gray-600',
  pending: 'bg-gray-300 text-gray-600',
}

export default function ApprovalTimeline({ steps, currentStep }: ApprovalTimelineProps) {
  return (
    <div className="flex flex-col gap-0" role="list" aria-label="審核流程">
      {steps.map((step, i) => {
        const Icon = STEP_ICONS[step.status] || Clock
        const isActive = i === currentStep
        const isPast = i < currentStep

        return (
          <div key={i} className="flex gap-3" role="listitem">
            {/* 左側：圓點 + 連線 */}
            <div className="flex flex-col items-center">
              <div
                className={clsx(
                  'flex h-10 w-10 items-center justify-center rounded-full border-2',
                  isActive ? 'border-accent bg-accent text-white' : STEP_COLORS[step.status],
                  isPast && step.status === 'approved' && 'border-green-500',
                )}
                aria-hidden
              >
                <Icon className="h-5 w-5" />
              </div>
              {i < steps.length - 1 && (
                <div
                  className={clsx(
                    'w-0.5 flex-1 min-h-[24px]',
                    isPast && step.status === 'approved' ? 'bg-green-300' : 'bg-line',
                  )}
                  aria-hidden
                />
              )}
            </div>

            {/* 右側：內容 */}
            <div className={clsx('pb-4 min-w-0 flex-1', i === steps.length - 1 && 'pb-0')}>
              <p className={clsx('text-lg font-bold', isActive ? 'text-accent' : 'text-ink')}>
                {step.name}
              </p>
              <p className="text-base text-muted">
                {step.roles.join('、')}
                {step.reviewer && ` — ${step.reviewer}`}
              </p>
              {step.reason && (
                <p className="mt-1 rounded-lg bg-wash px-3 py-1.5 text-base text-ink">
                  {step.reason}
                </p>
              )}
              {step.decided_at && (
                <p className="mt-0.5 text-sm text-muted">{step.decided_at}</p>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}
