import { describe, expect, it } from 'vitest'
import { FORM_STATUS_LABELS, FORM_TYPE_LABELS, presentableEntries } from './formPresentation'

describe('formPresentation', () => {
  it('將系統代碼轉成一般使用者看得懂的名稱', () => {
    expect(FORM_TYPE_LABELS.quote).toBe('報價單')
    expect(FORM_STATUS_LABELS.approved).toBe('已核准')
  })

  it('只顯示白名單業務欄位，隱藏識別碼與巢狀系統資料', () => {
    const rows = presentableEntries({
      customer: '合成示範客戶',
      quantity: 200,
      tenant_id: 'internal-tenant-id',
      provenance: { task_run_id: 'internal-task-id' },
    })

    expect(rows).toEqual([
      ['客戶', '合成示範客戶'],
      ['數量', '200'],
    ])
  })

  it('把步驟與風險轉成可讀內容', () => {
    expect(presentableEntries({ steps: ['停機上鎖', '確認接頭'], risk_level: 'medium' }))
      .toEqual([
        ['做法步驟', '1. 停機上鎖\n2. 確認接頭'],
        ['作業風險', '中風險'],
      ])
  })
})
