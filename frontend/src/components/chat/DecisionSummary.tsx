import type { KnowledgeDecision } from '../../types'
import RiskBanner from '../RiskBanner'

const STATE_LABEL: Record<KnowledgeDecision['evidence_state'], string> = {
  complete: '完整證據',
  partial: '部分證據',
  insufficient_context: '需要補充條件',
  absent: '指定範圍無依據',
  conflict: '來源衝突',
}

export default function DecisionSummary({ decision }: { decision: KnowledgeDecision }) {
  if (decision.execution_status !== 'ok') {
    return (
      <RiskBanner
        level="danger"
        title="系統未完成本次判斷"
        description="這是執行失敗，不代表公司沒有資料。請重試；若持續發生，請使用追蹤碼聯絡管理員。"
        className="mb-4"
      />
    )
  }

  const scope = Object.entries(decision.applicability_scope || {})
    .filter(([, value]) => value != null && value !== '' && (!Array.isArray(value) || value.length > 0))
  return (
    <section className="mb-4 rounded-2xl border border-line bg-surface p-4" aria-label="答案證據狀態">
      <div className="flex flex-wrap items-center gap-2">
        <span className={decision.evidence_state === 'complete' ? 'chip-success' : 'chip-accent'}>
          {STATE_LABEL[decision.evidence_state]}
        </span>
        <span className="chip-neutral">{decision.answer_type}</span>
      </div>
      {scope.length > 0 && (
        <p className="mt-3 text-xs text-muted">
          適用範圍：{scope.map(([key, value]) => `${key}=${Array.isArray(value) ? value.join('、') : String(value)}`).join('；')}
        </p>
      )}
      {decision.answered_items.length > 0 && (
        <p className="mt-2 text-xs text-muted">已回答：{decision.answered_items.join('、')}</p>
      )}
      {decision.missing_items.length > 0 && (
        <div className="mt-3 rounded-xl bg-highlight-soft px-3 py-2 text-sm text-highlight">
          缺少：{decision.missing_items.map(item => item.label || item.requirement_id || '必要項目').join('、')}
        </div>
      )}
      {decision.conflicts.length > 0 && (
        <div className="mt-3 rounded-xl bg-danger-soft px-3 py-2 text-sm text-danger">
          衝突：{decision.conflicts.map(item => item.conflict_key || item.requirement_id || '來源差異').join('、')}
        </div>
      )}
    </section>
  )
}
