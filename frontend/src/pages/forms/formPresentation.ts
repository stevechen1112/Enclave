export const FORM_TYPE_LABELS: Record<string, string> = {
  quote: '報價單',
  purchase_order: '採購單',
  incident_report: '異常回報',
  shift_handover: '交接班紀錄',
  meeting_visit: '會議／拜訪紀錄',
  equipment_repair: '設備維修紀錄',
  payment_request: '請款單',
  quality_8d: '品質 8D',
  capa: '改善追蹤',
  training_checklist: '訓練檢核',
  daily_report: '工作日報',
}

export const FORM_STATUS_LABELS: Record<string, string> = {
  draft: '草稿',
  changes_requested: '退回修改',
  rejected: '已駁回',
  pending_review: '待審核',
  pending_approval: '待審核',
  approved: '已核准',
  finalized: '已完成',
}

export const FORM_FIELD_LABELS: Record<string, string> = {
  customer: '客戶', part_number: '料號', quantity: '數量', unit_price: '單價',
  tax_rate: '稅率%', valid_until: '有效期限', payment_terms: '付款條件',
  subtotal: '小計', tax: '稅額', total: '含稅總計', supplier: '供應商',
  expected_date: '預計交貨日', equipment_id: '設備編號', location: '發生位置／產線',
  occurred_at: '發生時間', category: '異常類別', severity: '嚴重程度', description: '說明',
  immediate_action: '已採取的緊急處置', reporter: '回報人', shift_date: '班次日期',
  shift: '班次', line: '產線／區域', outgoing: '交班人', incoming: '接班人',
  production_summary: '本班生產狀況', pending_issues: '未完成事項／待追蹤',
  equipment_notes: '設備注意事項', customer_id: '客戶／客訴來源', visit_date: '日期',
  attendees: '與會者', purpose: '目的', next_actions: '後續行動', equipment_model: '機型',
  fault_symptom: '故障現象', root_cause: '原因分析／根因', repair_action: '維修處置',
  parts_used: '更換零件', technician: '維修人員', completed_at: '完成日',
  invoice_no: '發票／對帳單號', amount: '請款金額', due_date: '期限', problem: '問題描述',
  containment: '圍堵措施（D3）', corrective_action: '矯正措施（D5）', owner: '責任人',
  related_8d: '關聯 8D 編號', action: '改善行動', status_note: '進度說明',
  effectiveness: '有效性驗證', trainee: '受訓人', job_role: '職務', required_docs: '必讀文件',
  quiz_score: '情境測驗分數', common_mistakes: '常見錯誤複習', mentor: '指導人',
  report_date: '日期', work_summary: '今日工作內容', issues: '異常／待追蹤',
  tomorrow_plan: '明日計畫', title: '標題', summary: '摘要', form_key: '表單種類',
  risk_level: '作業風險', equipment_ids: '適用設備', applicable_roles: '適用職務',
  steps: '做法步驟', cautions: '注意事項', recommended_actions: '建議處置',
  prerequisites: '作業前確認', risks: '風險說明', prohibited_actions: '禁止事項',
  product_ids: '適用產品', customer_ids: '適用客戶', problem_context: '問題情境',
  source_quotes: '師傅原話',
}

const RISK_LEVEL_LABELS: Record<string, string> = {
  low: '低風險', medium: '中風險', high: '高風險',
}

/** Fail closed: backend metadata and newly introduced keys stay hidden until labelled. */
export function presentableEntries(values: Record<string, unknown>): Array<[string, string]> {
  return Object.entries(values).flatMap(([key, value]) => {
    const label = FORM_FIELD_LABELS[key]
    if (!label || value === null || value === undefined || value === '') return []
    if (typeof value === 'object' && !Array.isArray(value)) return []
    if (Array.isArray(value) && value.length === 0) return []
    let displayValue = Array.isArray(value)
      ? key === 'steps'
        ? value.map((item, index) => `${index + 1}. ${String(item)}`).join('\n')
        : value.map(String).join('；')
      : String(value)
    if (key === 'risk_level') displayValue = RISK_LEVEL_LABELS[displayValue] || displayValue
    return [[label, displayValue]]
  })
}
