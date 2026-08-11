/**
 * EvidenceCard — 來源文件卡片（漸進揭露 §6.6）。
 *
 * 層級：答案 → 版本/權威標籤 → 來源文件卡 → 展開原文/頁碼
 */
import { FileText, ChevronDown, ChevronUp, ExternalLink } from 'lucide-react'
import { useState } from 'react'
import AuthorityBadge from './AuthorityBadge'

export interface Evidence {
  document_id: string
  document_title: string
  page?: number
  chunk_text?: string
  authority_level?: number
  authority_label?: string
}

interface EvidenceCardProps {
  evidence: Evidence
  defaultExpanded?: boolean
}

export default function EvidenceCard({ evidence, defaultExpanded = false }: EvidenceCardProps) {
  const [expanded, setExpanded] = useState(defaultExpanded)

  return (
    <div className="rounded-xl border-2 border-line bg-surface">
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-wash/50"
        aria-expanded={expanded}
        aria-label={`來源：${evidence.document_title}`}
      >
        <FileText className="h-5 w-5 shrink-0 text-accent" aria-hidden />
        <div className="min-w-0 flex-1">
          <p className="text-base font-bold text-ink truncate">{evidence.document_title}</p>
          {evidence.page && (
            <p className="text-sm text-muted">第 {evidence.page} 頁</p>
          )}
        </div>
        <div className="flex items-center gap-2">
          {evidence.authority_level !== undefined && (
            <AuthorityBadge level={evidence.authority_level} label={evidence.authority_label} />
          )}
          {expanded ? (
            <ChevronUp className="h-5 w-5 text-muted" aria-hidden />
          ) : (
            <ChevronDown className="h-5 w-5 text-muted" aria-hidden />
          )}
        </div>
      </button>
      {expanded && evidence.chunk_text && (
        <div className="border-t-2 border-line px-4 py-3">
          <blockquote className="text-base leading-relaxed text-ink whitespace-pre-wrap">
            {evidence.chunk_text}
          </blockquote>
          <a
            href={`/knowledge/documents/${evidence.document_id}`}
            target="_blank"
            rel="noopener noreferrer"
            className="mt-2 inline-flex items-center gap-1 text-sm font-bold text-accent hover:underline"
          >
            <ExternalLink className="h-4 w-4" aria-hidden />
            開啟完整文件
          </a>
        </div>
      )}
    </div>
  )
}
