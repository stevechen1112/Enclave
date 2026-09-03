import { useCallback, useEffect, useState } from 'react'
import { RefreshCw, ShieldAlert } from 'lucide-react'
import AsyncState from '../../components/AsyncState'
import PageHeader from '../../components/PageHeader'
import { knowledgeDecisionApi, parseApiError } from '../../api'
import type { ApiErrorInfo, KnowledgeDecisionDiff } from '../../api'

const stateLabel: Record<string, string> = {
  complete: '完整', partial: '部分', absent: '指定範圍無依據',
  conflict: '來源衝突', insufficient_context: '缺少必要條件',
}

export default function KnowledgeDecisionDiffPage() {
  const [items, setItems] = useState<KnowledgeDecisionDiff[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<ApiErrorInfo | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const result = await knowledgeDecisionApi.listDiffs()
      setItems(result.items)
    } catch (err) {
      setError(parseApiError(err, '無法載入回答決策差異'))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void load() }, [load])

  return (
    <div className="h-full overflow-y-auto p-4 md:p-6">
      <div className="mx-auto max-w-5xl space-y-5">
        <PageHeader
          variant="section"
          title="回答決策差異"
          subtitle="唯讀檢視 legacy 與新版 Evidence Decision；來源會在每次開啟時重新授權。"
          actions={<button type="button" onClick={() => void load()} className="btn-outline inline-flex min-h-11 items-center gap-2"><RefreshCw className="h-4 w-4" aria-hidden />重新整理</button>}
        />
        <AsyncState loading={loading} error={error} onRetry={load} empty={!items.length} emptyTitle="尚無有效 Shadow 量測" emptyDescription="只有成功寫入加密 telemetry 的案例才會顯示。">
          <div className="space-y-3">
            {items.map(item => (
              <article key={item.record_id} className="rounded-xl border border-line bg-surface p-4" aria-label={`決策差異 ${item.transition}`}>
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <div className="font-medium text-ink">{item.legacy_decision} → {stateLabel[item.new_evidence_state] || item.new_evidence_state}</div>
                    <div className="mt-1 text-xs text-muted">{new Date(item.captured_at).toLocaleString('zh-TW')} · {item.new_response_action} · {item.execution_status}</div>
                  </div>
                  {(item.false_accept_candidate || item.false_reject_candidate) && <span className="inline-flex items-center gap-1 rounded-full bg-warning-soft px-2.5 py-1 text-xs font-medium text-warning"><ShieldAlert className="h-4 w-4" aria-hidden />需人工複核</span>}
                </div>
                <dl className="mt-3 grid gap-2 text-sm sm:grid-cols-2">
                  <div><dt className="text-muted">原因</dt><dd className="break-words text-ink">{item.reason_codes.join('、') || '—'}</dd></div>
                  <div><dt className="text-muted">Decision hash</dt><dd className="break-all font-mono text-xs text-ink">{item.decision_hash}</dd></div>
                  <div><dt className="text-muted">目前可見來源</dt><dd className="text-ink">{item.source_refs.length} 筆</dd></div>
                </dl>
              </article>
            ))}
          </div>
        </AsyncState>
      </div>
    </div>
  )
}
