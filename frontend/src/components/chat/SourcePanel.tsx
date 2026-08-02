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
        className="flex w-full min-h-11 items-center justify-between gap-2 text-left text-xs font-medium text-accent hover:text-accent-hover"
        aria-expanded={expanded}
        aria-label={`證據 ${sources.length} 則，${expanded ? '收合' : '展開'}`}
      >
        <span>證據（{sources.length}）</span>
        {expanded ? <ChevronUp className="h-3.5 w-3.5" aria-hidden /> : <ChevronDown className="h-3.5 w-3.5" aria-hidden />}
      </button>

      {expanded && (
        <div className="mt-2 space-y-2 animate-fade-in" role="list">
          {sources.map((s, i) => (
            <div key={`${s.document_id || s.title}-${i}`} role="listitem" className="relative">
              <EvidenceCard source={s} index={i + 1} />
              <button
                type="button"
                onClick={() => copyCite(s, i)}
                className="absolute right-2 top-2 rounded p-1.5 text-muted hover:bg-wash hover:text-ink"
                aria-label={`複製引用 ${i + 1}`}
              >
                {copiedIdx === i
                  ? <Check className="h-3.5 w-3.5 text-emerald-600" aria-hidden />
                  : <Copy className="h-3.5 w-3.5" aria-hidden />}
              </button>
            </div>
          ))}
          <p className="text-[11px] text-muted">
            相似度僅供參考檢索相關度，不代表答案正確率。
          </p>
        </div>
      )}
    </div>
  )
}
