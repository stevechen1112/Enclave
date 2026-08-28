import { Crosshair } from 'lucide-react'
import { useSearchParams } from 'react-router-dom'

function clock(ms: number) {
  const seconds = Math.floor(Math.max(0, ms) / 1000)
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
}

export default function EvidenceLocatorBanner() {
  const [params] = useSearchParams()
  const labels: string[] = []
  const page = params.get('page')
  const section = params.get('section')
  const start = params.get('t')
  const end = params.get('end')
  const frame = params.get('frame')
  const region = params.get('region') || params.get('bbox')
  if (page && /^[1-9]\d*$/.test(page)) labels.push(`第 ${page} 頁`)
  if (section) labels.push(`段落：${section.slice(0, 160)}`)
  if (start && /^\d+$/.test(start)) {
    const range = end && /^\d+$/.test(end) ? `–${clock(Number(end))}` : ''
    labels.push(`時間 ${clock(Number(start))}${range}`)
  }
  if (frame) labels.push(`畫面 ${frame.slice(0, 80)}`)
  if (region) labels.push('已指定影像標記區域')
  if (!labels.length) return null
  return (
    <div
      id="evidence-locator"
      role="status"
      aria-live="polite"
      className="mb-5 flex scroll-mt-4 items-start gap-3 rounded-xl border border-accent/30 bg-accent-soft p-4 text-sm text-accent-ink"
    >
      <Crosshair className="mt-0.5 h-5 w-5 shrink-0" aria-hidden />
      <span>
        <strong className="block font-semibold">已開啟引用證據位置</strong>
        <span className="mt-1 block">{labels.join(' · ')}</span>
      </span>
    </div>
  )
}
