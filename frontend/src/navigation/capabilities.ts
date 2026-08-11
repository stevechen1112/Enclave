/**
 * Enclave 2.0 — capability / navigation registry
 * Single source of truth for nav visibility and route guards.
 * Formal roles: owner | admin | hr | employee | viewer (+ is_superuser)
 * Note: `manager` is NOT a formal UserRole; do not grant review via manager.
 */

export type FormalRole = 'owner' | 'admin' | 'hr' | 'employee' | 'viewer'

export type Capability =
  | 'ask'
  | 'browse_knowledge'
  | 'upload_documents'
  | 'manage_sources'
  | 'review_queue'
  | 'governance'
  | 'system_ops'
  | 'create_content'
  | 'view_usage'
  | 'admin_home'
  | 'field_work'

export type NavItem = {
  to: string
  label: string
  capability: Capability
  end?: boolean
}

const ROLE_CAPS: Record<FormalRole, Capability[]> = {
  owner: [
    'ask', 'browse_knowledge', 'upload_documents', 'manage_sources',
    'review_queue', 'governance', 'system_ops', 'create_content',
    'view_usage', 'admin_home', 'field_work',
  ],
  admin: [
    'ask', 'browse_knowledge', 'upload_documents', 'manage_sources',
    'review_queue', 'governance', 'system_ops', 'create_content',
    'view_usage', 'admin_home', 'field_work',
  ],
  hr: [
    'ask', 'browse_knowledge', 'upload_documents', 'create_content', 'view_usage',
    'field_work',
  ],
  employee: [
    'ask', 'browse_knowledge', 'create_content', 'view_usage', 'field_work',
  ],
  viewer: [
    'ask', 'browse_knowledge', 'view_usage', 'field_work',
  ],
}

/** Admin primary nav (≤6) */
export const ADMIN_NAV: NavItem[] = [
  { to: '/overview', label: '總覽', capability: 'admin_home', end: true },
  { to: '/job', label: '現場作業', capability: 'field_work' },
  { to: '/ask', label: '問答', capability: 'ask' },
  { to: '/knowledge', label: '知識', capability: 'browse_knowledge' },
  { to: '/governance', label: '管理', capability: 'governance' },
  { to: '/system', label: '系統', capability: 'system_ops' },
]

/** Employee / Viewer primary nav：現場作業為主入口（製造業現場人員） */
export const EMPLOYEE_NAV: NavItem[] = [
  { to: '/job', label: '現場作業', capability: 'field_work', end: true },
  { to: '/ask', label: '問答', capability: 'ask' },
  { to: '/knowledge/documents', label: '知識', capability: 'browse_knowledge' },
]

/** HR primary nav (§6.3)：現場作業｜問答｜知識｜我的用量 */
export const HR_NAV: NavItem[] = [
  { to: '/job', label: '現場作業', capability: 'field_work', end: true },
  { to: '/ask', label: '問答', capability: 'ask' },
  { to: '/knowledge/documents', label: '知識', capability: 'browse_knowledge' },
  { to: '/me/usage', label: '我的用量', capability: 'view_usage' },
]

export const ROLE_LABELS: Record<string, string> = {
  owner: '擁有者',
  admin: '管理員',
  hr: '內容負責人',
  employee: '員工',
  viewer: '唯讀',
}

export function normalizeRole(role: string | undefined | null): FormalRole {
  const r = (role || 'employee').toLowerCase()
  if (r === 'owner' || r === 'admin' || r === 'hr' || r === 'employee' || r === 'viewer') {
    return r
  }
  return 'employee'
}

export function capabilitiesFor(role: string | undefined | null, isSuperuser?: boolean): Set<Capability> {
  const caps = new Set(ROLE_CAPS[normalizeRole(role)])
  if (isSuperuser) {
    caps.add('system_ops')
    caps.add('governance')
    caps.add('admin_home')
  }
  return caps
}

export function hasCapability(
  role: string | undefined | null,
  cap: Capability,
  isSuperuser?: boolean,
): boolean {
  return capabilitiesFor(role, isSuperuser).has(cap)
}

export function primaryNavFor(role: string | undefined | null, isSuperuser?: boolean): NavItem[] {
  const caps = capabilitiesFor(role, isSuperuser)
  return primaryNavForCaps(caps, role)
}

/** 以能力集合計算主導覽（bootstrap 驅動時使用） */
export function primaryNavForCaps(caps: Set<Capability>, role?: string | undefined | null): NavItem[] {
  const formal = normalizeRole(role)
  const items = caps.has('admin_home')
    ? ADMIN_NAV
    : formal === 'hr'
      ? HR_NAV
      : EMPLOYEE_NAV
  return items.filter(i => caps.has(i.capability))
}

export function defaultHomePath(role: string | undefined | null, isSuperuser?: boolean): string {
  return defaultHomePathForCaps(capabilitiesFor(role, isSuperuser))
}

/** 以能力集合計算預設首頁（bootstrap 驅動時使用） */
export function defaultHomePathForCaps(caps: Set<Capability>): string {
  if (caps.has('admin_home')) return '/overview'
  // 製造業現場人員登入後直接進職務入口（語音/掃碼/常用工作）
  if (caps.has('field_work')) return '/job'
  return '/ask'
}

export const KNOWLEDGE_SUBNAV: { to: string; label: string; capability: Capability }[] = [
  { to: '/knowledge/documents', label: '文件', capability: 'browse_knowledge' },
  { to: '/knowledge/wiki', label: '知識頁', capability: 'browse_knowledge' },
  { to: '/knowledge/sources', label: '來源', capability: 'manage_sources' },
  { to: '/knowledge/review', label: '審核', capability: 'review_queue' },
  { to: '/knowledge/quality', label: '品質', capability: 'governance' },
]

export const GOVERNANCE_SUBNAV: { to: string; label: string; capability: Capability }[] = [
  { to: '/governance/organization', label: '公司與帳號', capability: 'governance' },
  { to: '/governance/departments', label: '部門權限', capability: 'governance' },
  { to: '/governance/audit', label: '操作紀錄', capability: 'governance' },
  { to: '/governance/insights', label: '問答品質', capability: 'governance' },
]

export const SYSTEM_SUBNAV: { to: string; label: string; capability: Capability }[] = [
  { to: '/system/modules', label: '功能開關', capability: 'system_ops' },
  { to: '/system/tenant-admin', label: '租戶設定', capability: 'admin_home' },
  { to: '/system/health', label: '資料健檢', capability: 'system_ops' },
  { to: '/system/backup', label: '備份', capability: 'system_ops' },
  { to: '/system/deploy', label: '版本更新', capability: 'system_ops' },
]

/** V1.1 create workspace — reachable via user menu, not primary nav */
export const CREATE_SUBNAV: { to: string; label: string; capability: Capability; end?: boolean }[] = [
  { to: '/create', label: '新建', capability: 'create_content', end: true },
  { to: '/create/reports', label: '報告', capability: 'create_content' },
]
