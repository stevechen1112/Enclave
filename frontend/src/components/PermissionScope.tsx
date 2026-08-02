/**
 * Visible scope summary — "誰能看什麼" (UIUX §9.7 / §9.8)
 */
import { Eye } from 'lucide-react'
import clsx from 'clsx'

type Props = {
  department?: string | null
  visibility?: string | null
  tags?: string[]
  className?: string
}

export default function PermissionScope({ department, visibility, tags, className }: Props) {
  const vis = visibility || '依部門與角色'
  return (
    <div className={clsx('rounded-lg border border-line bg-wash px-3 py-2.5 text-sm', className)}>
      <div className="flex items-center gap-1.5 font-medium text-ink">
        <Eye className="h-4 w-4 text-muted" aria-hidden />
        可見範圍
      </div>
      <dl className="mt-2 space-y-1 text-xs text-muted">
        <div className="flex gap-2">
          <dt className="w-14 shrink-0">部門</dt>
          <dd className="text-ink">{department || '未指定（核准前請設定）'}</dd>
        </div>
        <div className="flex gap-2">
          <dt className="w-14 shrink-0">範圍</dt>
          <dd className="text-ink">{vis}</dd>
        </div>
        {tags && tags.length > 0 && (
          <div className="flex gap-2">
            <dt className="w-14 shrink-0">標籤</dt>
            <dd className="text-ink">{tags.join('、')}</dd>
          </div>
        )}
      </dl>
    </div>
  )
}
