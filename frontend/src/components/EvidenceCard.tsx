/**
 * Citation / evidence card (UIUX §9.4)
 */
import { Link } from 'react-router-dom'
import { ExternalLink, FileText } from 'lucide-react'
import type { ChatSource } from '../types'
import clsx from 'clsx'

type Props = {
  source: ChatSource
  index?: number
  className?: string
}

export default function EvidenceCard({ source, index, className }: Props) {
  const title = source.title || '未命名文件'
  const accessible = source.accessible !== false
  const transcriptTime = source.transcript_start_ms != null
    ? `${Math.floor(source.transcript_start_ms / 60000)}:${String(Math.floor((source.transcript_start_ms % 60000) / 1000)).padStart(2, '0')}`
    : null
  return (
    <article
      className={clsx(
        'rounded-lg border border-line bg-surface p-3 text-sm',
        !accessible && 'opacity-70',
        className,
      )}
    >
      <div className="flex items-start gap-2">
        <FileText className="mt-0.5 h-4 w-4 shrink-0 text-muted" aria-hidden />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
            {typeof index === 'number' && (
              <span className="font-mono text-xs text-muted">#{index}</span>
            )}
            <h3 className="font-medium text-ink">{title}</h3>
            {!accessible && (
              <span className="rounded bg-wash px-1.5 py-0.5 text-[11px] text-muted">目前不可存取</span>
            )}
          </div>
          <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 font-mono text-[11px] text-muted">
            {source.document_revision != null && source.document_revision !== '' && (
              <span>版本 {String(source.document_revision)}</span>
            )}
            {source.page != null && <span>第 {source.page} 頁</span>}
            {source.section && <span>章節：{source.section}</span>}
            {source.worksheet && <span>工作表：{source.worksheet}</span>}
            {source.row_number != null && <span>第 {source.row_number} 列</span>}
            {source.field_name && <span>欄位：{source.field_name}</span>}
            {transcriptTime && <span>逐字稿 {transcriptTime}</span>}
            {source.chunk_index != null && <span>片段 {source.chunk_index}</span>}
            {source.provider && <span>{source.provider}</span>}
            {source.updated_at && (
              <span>更新 {new Date(source.updated_at).toLocaleDateString()}</span>
            )}
            {source.effective_at && (
              <span>生效 {new Date(source.effective_at).toLocaleDateString()}</span>
            )}
            {source.score != null && <span>相關 {(source.score * 100).toFixed(0)}%</span>}
          </div>
          {source.applicable_scope && (
            <p className="mt-1 text-xs text-muted">適用範圍：{source.applicable_scope}</p>
          )}
          {source.snippet && (
            <p className="mt-2 line-clamp-3 text-xs leading-relaxed text-muted">{source.snippet}</p>
          )}
          {source.document_id && accessible && (
            <Link
              to={`/knowledge/documents/${source.document_id}`}
              className="mt-2 inline-flex items-center gap-1 text-xs text-accent hover:underline"
            >
              在文件中開啟
              <ExternalLink className="h-3 w-3" aria-hidden />
            </Link>
          )}
        </div>
      </div>
    </article>
  )
}
