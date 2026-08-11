/**
 * TranscriptEditor — 語音轉寫確認（§6.8：未確認不得進入高風險動作）。
 *
 * 現場設計：大字體顯示辨識結果、可直接修改、關鍵欄位（料號/客戶/數量）
 * 以 chip 凸顯要求逐項核對。
 */
import { useState } from 'react'
import { CheckCircle2, PencilLine, AlertTriangle } from 'lucide-react'
import clsx from 'clsx'

const FIELD_LABELS: Record<string, string> = {
  customer: '客戶',
  part_number: '料號',
  quantity: '數量',
  unit_price: '單價',
  equipment_id: '設備',
  work_order_id: '工單',
}

export default function TranscriptEditor({
  text,
  detectedFields,
  confidence,
  onConfirm,
  onCancel,
  confirming,
}: {
  text: string
  detectedFields: Record<string, string>
  confidence?: number
  onConfirm: (editedText: string) => void
  onCancel: () => void
  confirming?: boolean
}) {
  const [edited, setEdited] = useState(text)
  const fieldEntries = Object.entries(detectedFields || {}).filter(([, v]) => v)
  const lowConfidence = typeof confidence === 'number' && confidence < 0.7

  return (
    <div className="rounded-2xl border-2 border-accent bg-surface p-5 shadow-md">
      <div className="mb-3 flex items-center gap-2">
        <PencilLine className="h-6 w-6 text-accent" aria-hidden />
        <h3 className="text-xl font-bold text-ink">請確認聽到的內容</h3>
      </div>

      {lowConfidence && (
        <p className="mb-3 flex items-center gap-2 rounded-lg bg-amber-50 px-3 py-2 text-base font-medium text-amber-800">
          <AlertTriangle className="h-5 w-5 shrink-0" aria-hidden />
          這段錄音辨識信心較低，請特別核對數字與料號。
        </p>
      )}

      <label htmlFor="transcript-edit" className="mb-1 block text-base font-medium text-muted">
        內容有錯可直接修改：
      </label>
      <textarea
        id="transcript-edit"
        value={edited}
        onChange={e => setEdited(e.target.value)}
        rows={4}
        className="w-full rounded-xl border-2 border-line bg-wash p-4 text-xl leading-relaxed text-ink focus:border-accent focus:outline-none"
      />

      {fieldEntries.length > 0 && (
        <div className="mt-4">
          <p className="mb-2 text-base font-medium text-muted">系統辨識出的關鍵資料，請逐項核對：</p>
          <div className="flex flex-wrap gap-2">
            {fieldEntries.map(([key, value]) => (
              <span
                key={key}
                className="rounded-full border-2 border-accent/40 bg-accent/10 px-4 py-2 text-lg font-semibold text-ink"
              >
                {FIELD_LABELS[key] ?? key}：{value}
              </span>
            ))}
          </div>
        </div>
      )}

      <div className="mt-5 flex gap-3">
        <button
          type="button"
          onClick={() => onConfirm(edited)}
          disabled={confirming || !edited.trim()}
          className={clsx(
            'flex min-h-16 flex-1 items-center justify-center gap-2 rounded-xl text-xl font-bold text-white',
            'bg-accent hover:bg-accent-hover active:scale-[0.98] disabled:opacity-50',
          )}
        >
          <CheckCircle2 className="h-7 w-7" aria-hidden />
          {confirming ? '確認中…' : '內容正確，確認'}
        </button>
        <button
          type="button"
          onClick={onCancel}
          disabled={confirming}
          className="min-h-16 rounded-xl border-2 border-line px-6 text-xl font-bold text-muted hover:bg-wash active:scale-[0.98]"
        >
          重錄
        </button>
      </div>
    </div>
  )
}
