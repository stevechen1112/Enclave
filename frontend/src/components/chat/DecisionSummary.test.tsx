import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { KnowledgeDecision } from '../../types'
import DecisionSummary from './DecisionSummary'

const base: KnowledgeDecision = {
  decision_id: 'decision-1',
  evidence_state: 'partial',
  execution_status: 'ok',
  answer_type: 'partial_gap',
  direct_conclusion: '目前可確認 A',
  applicability_scope: { tenant_id: 'tenant-1', document_revision: '7' },
  answered_items: ['item-a'],
  missing_items: [{ requirement_id: 'item-b', label: '項目 B' }],
  conflicts: [],
  source_versions: [{ document_id: 'doc-1', document_revision: '7' }],
}

describe('DecisionSummary', () => {
  it('shows partial answers, scope and named gaps without hover', () => {
    render(<DecisionSummary decision={base} />)
    expect(screen.getByRole('region', { name: '答案證據狀態' })).toBeInTheDocument()
    expect(screen.getByText('部分證據')).toBeInTheDocument()
    expect(screen.getByText(/tenant_id=tenant-1/)).toBeInTheDocument()
    expect(screen.getByText(/缺少：項目 B/)).toBeInTheDocument()
  })

  it('never presents execution failure as missing company data', () => {
    render(
      <DecisionSummary
        decision={{ ...base, evidence_state: 'absent', execution_status: 'timeout' }}
      />,
    )
    expect(screen.getByText('系統未完成本次判斷')).toBeInTheDocument()
    expect(screen.getByText(/不代表公司沒有資料/)).toBeInTheDocument()
    expect(screen.queryByText('指定範圍無依據')).not.toBeInTheDocument()
  })
})
