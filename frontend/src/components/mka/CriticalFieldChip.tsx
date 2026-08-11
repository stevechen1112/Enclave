/**
 * CriticalFieldChip — 關鍵欄位醒目晶片。
 *
 * 用於語音辨識後標示需要人工確認的關鍵欄位（金額、料號、數量、客戶名等）。
 * 設計原則 §4.1：Voice-first 不是 Voice-only，重要欄位必須顯示與確認。
 */
import { AlertTriangle, Check, Pencil } from 'lucide-react'
import clsx from 'clsx'

export interface CriticalField {
  type: string        // amount | part_number | quantity | customer | date | equipment
  label: string
  value: string
  confirmed: boolean
  confidence?: number  // 0-1 STT confidence
}

interface CriticalFieldChipProps {
  field: CriticalField
  onConfirm: (type: string, value: string) => void
  onEdit: (type: string) => void
}

const FIELD_COLORS: Record<string, string> = {
  amount: 'border-amber-400 bg-amber-50 text-amber-900',
  part_number: 'border-blue-400 bg-blue-50 text-blue-900',
  quantity: 'border-amber-400 bg-amber-50 text-amber-900',
  customer: 'border-purple-400 bg-purple-50 text-purple-900',
  date: 'border-teal-400 bg-teal-50 text-teal-900',
  equipment: 'border-blue-400 bg-blue-50 text-blue-900',
}

export default function CriticalFieldChip({ field, onConfirm, onEdit }: CriticalFieldChipProps) {
  const colorClass = FIELD_COLORS[field.type] || 'border-line bg-surface text-ink'

  return (
    <div
      className={clsx(
        'flex items-center gap-3 rounded-xl border-2 px-4 py-3',
        field.confirmed ? 'border-green-400 bg-green-50' : colorClass,
      )}
      role="group"
      aria-label={`${field.label}：${field.value}${field.confirmed ? '（已確認）' : '（待確認）'}`}
    >
      {!field.confirmed && (
        <AlertTriangle className="h-6 w-6 shrink-0 text-amber-500" aria-hidden />
      )}
      {field.confirmed && (
        <Check className="h-6 w-6 shrink-0 text-green-600" aria-hidden />
      )}
      <div className="min-w-0 flex-1">
        <p className="text-sm font-bold text-muted">{field.label}</p>
        <p className="text-xl font-bold">{field.value || '（未辨識）'}</p>
        {field.confidence !== undefined && field.confidence < 0.7 && (
          <p className="text-sm text-amber-600">信心度偏低（{Math.round(field.confidence * 100)}%）</p>
        )}
      </div>
      {!field.confirmed && (
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => onConfirm(field.type, field.value)}
            className="rounded-lg bg-green-600 px-4 py-2 text-base font-bold text-white hover:bg-green-700 active:scale-95"
            aria-label={`確認${field.label}`}
          >
            正確
          </button>
          <button
            type="button"
            onClick={() => onEdit(field.type)}
            className="rounded-lg border-2 border-line bg-white px-3 py-2 text-base font-bold text-ink hover:bg-wash active:scale-95"
            aria-label={`修改${field.label}`}
          >
            <Pencil className="h-5 w-5" aria-hidden />
          </button>
        </div>
      )}
    </div>
  )
}
