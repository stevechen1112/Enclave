import { useState } from 'react'
import type { ChatSource } from '../../types'
import { ChevronDown, ChevronUp, Copy, Check } from 'lucide-react'
import EvidenceCard from '../EvidenceCard'
import toast from 'react-hot-toast'

interface Props {
  sources: ChatSource[]
  /** Prefer open by default for trust-first UX */
  defaultOpen?: boolean
}

export default function SourcePanel({ sources, defaultOpen = true }: Props) {
  const [expanded, setExpanded] = useState(defaultOpen)
  const [copiedIdx, setCopiedIdx] = useState<number | null>(null)

  if (!sources || sources.length === 0) return null

  const copyCite = async (source: ChatSource, index: number) => {
    const text = `「${source.title}」${source.snippet ? `：${source.snippet.slice(0, 200)}` : ''}`
    try {
      await navigator.clipboard.writeText(text)
      setCopiedIdx(index)
      toast.success('已複製引用')
      setTimeout(() => setCopiedIdx(null), 1500)
    } catch {
      toast.error('複製失敗')
    }
  }

  return (
    <div className="mt-3 border-t border-line pt-3">
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="flex min-h-11 w-full items-center justify-between gap-2 rounded-xl px-2 text-left text-sm font-semibold text-accent-ink transition-colors hover:bg-accent-soft/60"
        aria-expanded={expanded}
        aria-label={`證據 ${sources.length} 則，${expanded ? '收合' : '展開'}`}
      >
        <span className="chip-accent">證據 {sources.length} 則</span>
        {expanded
          ? <ChevronUp className="h-4 w-4 shrink-0" aria-hidden />
          : <ChevronDown className="h-4 w-4 shrink-0" aria-hidden />}
      </button>

      {expanded && (
        <div className="mt-2 animate-fade-in space-y-2" role="list">
          {sources.map((s, i) => (
            <div key={`${s.document_id || s.title}-${i}`} role="listitem" className="relative">
              <EvidenceCard source={s} index={i + 1} />
              <button
                type="button"
                onClick={() => copyCite(s, i)}
                className="absolute right-1 top-1 inline-flex min-h-11 min-w-11 items-center justify-center rounded-xl text-muted transition-colors hover:bg-wash hover:text-ink"
                aria-label={`複製引用 ${i + 1}`}
              >
                {copiedIdx === i
                  ? <Check className="h-4 w-4 text-success" aria-hidden />
                  : <Copy className="h-4 w-4" aria-hidden />}
              </button>
            </div>
          ))}
          <p className="text-xs text-muted">
            相似度僅供參考檢索相關度，不代表答案正確率。
          </p>
        </div>
      )}
    </div>
  )
}
