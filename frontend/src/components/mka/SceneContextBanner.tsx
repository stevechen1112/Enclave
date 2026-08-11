/**
 * SceneContextBanner — 顯示目前作業場景（掃 QR 後的設備/產線/工單上下文）。
 *
 * 現場人員需要一眼確認「我現在操作的對象是誰」，避免張冠李戴。
 */
import { MapPin, X } from 'lucide-react'
import type { SceneContext } from '../../services/mka'

const SCENE_LABELS: Array<[keyof SceneContext, string]> = [
  ['site_id', '廠區'],
  ['plant_id', '廠房'],
  ['line_id', '產線'],
  ['equipment_id', '設備'],
  ['equipment_model', '機型'],
  ['work_order_id', '工單'],
  ['product_id', '產品'],
  ['part_number', '料號'],
  ['customer_id', '客戶'],
]

export default function SceneContextBanner({
  scene,
  onClear,
}: {
  scene: SceneContext
  onClear?: () => void
}) {
  const entries = SCENE_LABELS.filter(([key]) => scene[key])
  if (entries.length === 0) return null

  return (
    <div
      className="flex items-start gap-3 rounded-xl border-2 border-accent/50 bg-accent/10 px-4 py-3"
      role="status"
      aria-label="目前作業場景"
    >
      <MapPin className="mt-1 h-6 w-6 shrink-0 text-accent" aria-hidden />
      <div className="min-w-0 flex-1">
        <p className="text-base font-bold text-accent">目前作業場景（掃碼帶入）</p>
        <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1">
          {entries.map(([key, label]) => (
            <span key={key} className="text-lg text-ink">
              <span className="text-muted">{label}</span>{' '}
              <strong className="font-semibold">{scene[key]}</strong>
            </span>
          ))}
        </div>
      </div>
      {onClear && (
        <button
          type="button"
          onClick={onClear}
          aria-label="清除場景"
          className="rounded-lg p-2 text-muted hover:bg-accent/20 hover:text-ink"
        >
          <X className="h-6 w-6" aria-hidden />
        </button>
      )}
    </div>
  )
}
