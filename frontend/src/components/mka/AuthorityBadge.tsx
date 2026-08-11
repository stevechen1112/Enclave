/**
 * AuthorityBadge — 權威層級標籤（§7.3）。
 *
 * 100 formal_policy / 90 approved_sop / 80 approved_spec / 70 approved_case
 * 60 approved_knowhow / 20 external_reference / 0 draft
 */
import { Shield, ShieldCheck, ShieldAlert, BookOpen, Users, Globe } from 'lucide-react'
import clsx from 'clsx'

const AUTHORITY_CONFIG: Record<number, { label: string; icon: typeof Shield; color: string }> = {
  100: { label: '正式政策', icon: ShieldCheck, color: 'bg-red-100 text-red-800 border-red-300' },
  90: { label: '已核准 SOP', icon: ShieldCheck, color: 'bg-amber-100 text-amber-800 border-amber-300' },
  80: { label: '正式規格/合約', icon: BookOpen, color: 'bg-blue-100 text-blue-800 border-blue-300' },
  70: { label: '已核准案例', icon: Users, color: 'bg-teal-100 text-teal-800 border-teal-300' },
  60: { label: '已審 Know-how', icon: Users, color: 'bg-green-100 text-green-800 border-green-300' },
  20: { label: '外部參考', icon: Globe, color: 'bg-gray-100 text-gray-600 border-gray-300' },
  0: { label: '草稿', icon: ShieldAlert, color: 'bg-gray-100 text-gray-400 border-gray-200' },
}

interface AuthorityBadgeProps {
  level: number
  label?: string
}

export default function AuthorityBadge({ level, label }: AuthorityBadgeProps) {
  const config = AUTHORITY_CONFIG[level] || AUTHORITY_CONFIG[20]
  const Icon = config.icon

  return (
    <span
      className={clsx(
        'inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-bold',
        config.color,
      )}
      title={`權威層級：${label || config.label}（${level}）`}
    >
      <Icon className="h-3.5 w-3.5" aria-hidden />
      {label || config.label}
    </span>
  )
}
