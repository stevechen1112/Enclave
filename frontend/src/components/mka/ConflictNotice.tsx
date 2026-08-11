/**
 * ConflictNotice — SOP 與 Know-how 衝突提示（§4.3、§7.5）。
 *
 * 當正式 SOP 與老師傅 know-how 衝突時，顯示差異並標示 SOP 優先。
 */
import { AlertTriangle, ArrowRight, ShieldCheck } from 'lucide-react'

export interface ConflictItem {
  conflict_type: string
  sop_field: string
  knowhow_field: string
  sop_value: string
  knowhow_value: string
  description: string
  resolved: boolean
  resolution: string
}

interface ConflictNoticeProps {
  conflicts: ConflictItem[]
}

const CONFLICT_LABELS: Record<string, string> = {
  step_mismatch: '步驟不一致',
  value_mismatch: '數值不一致',
  equipment_mismatch: '設備範圍不一致',
  mutual_exclusion: '注意事項互斥',
}

export default function ConflictNotice({ conflicts }: ConflictNoticeProps) {
  if (!conflicts || conflicts.length === 0) return null

  return (
    <div
      className="rounded-2xl border-2 border-amber-400 bg-amber-50 p-5"
      role="alert"
      aria-label="SOP 衝突提示"
    >
      <div className="mb-3 flex items-center gap-2">
        <AlertTriangle className="h-6 w-6 text-amber-600" aria-hidden />
        <h3 className="text-xl font-bold text-amber-900">
          與正式 SOP 有 {conflicts.length} 項差異
        </h3>
      </div>
      <p className="mb-4 text-base text-amber-800">
        以下內容與正式 SOP 不一致，已依公司規定以 SOP 為準。
        若認為 know-how 更適合目前情境，請聯繫文件 owner 更新 SOP。
      </p>

      <div className="flex flex-col gap-3">
        {conflicts.map((c, i) => (
          <div key={i} className="rounded-xl border-2 border-amber-300 bg-white p-4">
            <div className="mb-2 flex items-center gap-2">
              <span className="rounded-full bg-amber-100 px-2 py-0.5 text-sm font-bold text-amber-800">
                {CONFLICT_LABELS[c.conflict_type] || c.conflict_type}
              </span>
              {c.resolved && (
                <span className="rounded-full bg-green-100 px-2 py-0.5 text-sm font-bold text-green-800">
                  {c.resolution === 'sop_wins' ? 'SOP 優先' : c.resolution}
                </span>
              )}
            </div>
            <p className="text-sm text-muted">{c.description}</p>
            <div className="mt-2 flex items-start gap-3 rounded-lg bg-wash p-3">
              <div className="min-w-0 flex-1">
                <p className="text-xs font-bold text-muted">Know-how 內容</p>
                <p className="text-base text-ink line-through opacity-70">{c.knowhow_value}</p>
              </div>
              <ArrowRight className="mt-1 h-5 w-5 shrink-0 text-amber-500" aria-hidden />
              <div className="min-w-0 flex-1">
                <p className="flex items-center gap-1 text-xs font-bold text-green-700">
                  <ShieldCheck className="h-3.5 w-3.5" aria-hidden />
                  SOP 正式版本
                </p>
                <p className="text-base font-bold text-green-800">{c.sop_value}</p>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
