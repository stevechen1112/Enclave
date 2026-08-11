import { Lightbulb } from 'lucide-react'

interface Props {
  suggestions: string[]
  onSelect: (question: string) => void
}

/**
 * T7-6: 跟進建議問題
 * 顯示 AI 推薦的後續問題，點擊自動帶入輸入
 */
export default function FollowUpSuggestions({ suggestions, onSelect }: Props) {
  if (!suggestions || suggestions.length === 0) return null

  return (
    <div className="mt-3 animate-fade-in">
      <p className="flex items-center gap-1.5 text-xs font-semibold text-muted">
        <Lightbulb className="h-3.5 w-3.5 text-highlight" aria-hidden /> 你可能想問
      </p>
      <div className="mt-2 flex flex-wrap gap-2">
        {suggestions.map((s, i) => (
          <button
            key={i}
            type="button"
            onClick={() => onSelect(s)}
            className="inline-flex min-h-11 items-center rounded-full border border-accent/30 bg-accent-soft px-4 text-sm font-medium text-accent-ink transition-colors hover:border-accent/60 hover:bg-accent-soft/70"
          >
            {s}
          </button>
        ))}
      </div>
    </div>
  )
}
