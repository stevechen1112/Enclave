/**
 * 導覽／能力結構快照測試（Phase 0 基線凍結）。
 *
 * 目的：重構職能工作台時，若誤刪可用能力或改變角色—能力對應，
 * 此測試會立即失敗。ROLE_CAPS 是 bootstrap 未載入時的 fallback，
 * 其內容與後端 experience._ROLE_CAPS 的 parity 由
 * tests/test_capability_parity.py 把關。
 */
import { describe, expect, it } from 'vitest'
import {
  ADMIN_NAV,
  EMPLOYEE_NAV,
  HR_NAV,
  capabilitiesFor,
  defaultHomePath,
  defaultHomePathForCaps,
  primaryNavFor,
  primaryNavForCaps,
  type Capability,
} from './capabilities'

const ALL_CAPS: Capability[] = [
  'ask', 'browse_knowledge', 'upload_documents', 'manage_sources',
  'review_queue', 'governance', 'system_ops', 'create_content',
  'view_usage', 'admin_home', 'field_work',
]

describe('capability baseline snapshot', () => {
  it('每個正式角色的能力集合不漂移', () => {
    expect([...capabilitiesFor('owner')].sort()).toEqual([...ALL_CAPS].sort())
    expect([...capabilitiesFor('admin')].sort()).toEqual([...ALL_CAPS].sort())
    expect([...capabilitiesFor('hr')].sort()).toEqual([
      'ask', 'browse_knowledge', 'upload_documents', 'create_content',
      'view_usage', 'field_work',
    ].sort())
    expect([...capabilitiesFor('employee')].sort()).toEqual([
      'ask', 'browse_knowledge', 'create_content', 'view_usage', 'field_work',
    ].sort())
    expect([...capabilitiesFor('viewer')].sort()).toEqual([
      'ask', 'browse_knowledge', 'view_usage', 'field_work',
    ].sort())
  })

  it('superuser 會提升 system/governance/admin 能力', () => {
    const caps = capabilitiesFor('viewer', true)
    expect(caps.has('system_ops')).toBe(true)
    expect(caps.has('governance')).toBe(true)
    expect(caps.has('admin_home')).toBe(true)
  })

  it('未知角色降級為 employee（最小權限）', () => {
    expect([...capabilitiesFor('manager')].sort()).toEqual(
      [...capabilitiesFor('employee')].sort(),
    )
  })

  it('主導覽結構快照', () => {
    expect(ADMIN_NAV.map(i => i.to)).toEqual([
      '/overview', '/job', '/ask', '/knowledge', '/governance', '/system',
    ])
    expect(EMPLOYEE_NAV.map(i => i.to)).toEqual(['/job', '/ask', '/knowledge/documents'])
    expect(HR_NAV.map(i => i.to)).toEqual([
      '/job', '/ask', '/knowledge/documents', '/me/usage',
    ])
  })

  it('primaryNavFor 依能力過濾', () => {
    expect(primaryNavFor('viewer').map(i => i.to)).toEqual([
      '/job', '/ask', '/knowledge/documents',
    ])
    expect(primaryNavFor('admin').map(i => i.to)).toEqual(ADMIN_NAV.map(i => i.to))
  })

  it('預設首頁：admin→overview、現場→job、其他→ask', () => {
    expect(defaultHomePath('admin')).toBe('/overview')
    expect(defaultHomePath('employee')).toBe('/job')
    expect(defaultHomePathForCaps(new Set<Capability>(['ask']))).toBe('/ask')
  })

  it('caps 驅動變體與角色驅動結果一致', () => {
    for (const role of ['owner', 'admin', 'hr', 'employee', 'viewer'] as const) {
      expect(primaryNavForCaps(capabilitiesFor(role), role).map(i => i.to)).toEqual(
        primaryNavFor(role).map(i => i.to),
      )
      expect(defaultHomePathForCaps(capabilitiesFor(role))).toBe(defaultHomePath(role))
    }
  })
})
