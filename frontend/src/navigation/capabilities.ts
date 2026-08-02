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
    'view_usage', 'admin_home',
  ],
  admin: [
    'ask', 'browse_knowledge', 'upload_documents', 'manage_sources',
    'review_queue', 'governance', 'system_ops', 'create_content',
    'view_usage', 'admin_home',
  ],
  hr: [
    'ask', 'browse_knowledge', 'upload_documents', 'create_content', 'view_usage',
  ],
  employee: [
    'ask', 'browse_knowledge', 'create_content', 'view_usage',
  ],
  viewer: [
    'ask', 'browse_knowledge', 'view_usage',
  ],
}

/** Admin primary nav (≤5) */
export const ADMIN_NAV: NavItem[] = [
  { to: '/overview', label: '總覽', capability: 'admin_home', end: true },
  { to: '/ask', label: '問答', capability: 'ask' },
  { to: '/knowledge', label: '知識', capability: 'browse_knowledge' },
  { to: '/governance', label: '治理', capability: 'governance' },
  { to: '/system', label: '系統', capability: 'system_ops' },
]

/** Employee / Viewer primary nav (≤2) */
export const EMPLOYEE_NAV: NavItem[] = [
  { to: '/ask', label: '問答', capability: 'ask', end: true },
  { to: '/knowledge/documents', label: '知識', capability: 'browse_knowledge' },
]

/** HR primary nav (§6.3)：問答｜知識｜我的用量 */
export const HR_NAV: NavItem[] = [
  { to: '/ask', label: '問答', capability: 'ask', end: true },
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
  const formal = normalizeRole(role)
  const items = caps.has('admin_home')
    ? ADMIN_NAV
    : formal === 'hr'
      ? HR_NAV
      : EMPLOYEE_NAV
  return items.filter(i => caps.has(i.capability))
}

export function defaultHomePath(role: string | undefined | null, isSuperuser?: boolean): string {
  return hasCapability(role, 'admin_home', isSuperuser) ? '/overview' : '/ask'
}

export const KNOWLEDGE_SUBNAV: { to: string; label: string; capability: Capability }[] = [
  { to: '/knowledge/documents', label: '文件', capability: 'browse_knowledge' },
  { to: '/knowledge/wiki', label: 'Wiki', capability: 'browse_knowledge' },
  { to: '/knowledge/sources', label: '來源', capability: 'manage_sources' },
  { to: '/knowledge/review', label: '審核', capability: 'review_queue' },
  { to: '/knowledge/quality', label: '品質', capability: 'governance' },
]

export const GOVERNANCE_SUBNAV: { to: string; label: string; capability: Capability }[] = [
  { to: '/governance/organization', label: '組織', capability: 'governance' },
  { to: '/governance/departments', label: '部門', capability: 'governance' },
  { to: '/governance/audit', label: '稽核', capability: 'governance' },
  { to: '/governance/insights', label: '問答品質', capability: 'governance' },
]

export const SYSTEM_SUBNAV: { to: string; label: string; capability: Capability }[] = [
  { to: '/system/modules', label: '能力包', capability: 'system_ops' },
  { to: '/system/health', label: '健康', capability: 'system_ops' },
  { to: '/system/backup', label: '備份', capability: 'system_ops' },
  { to: '/system/deploy', label: '部署', capability: 'system_ops' },
]

/** V1.1 create workspace — reachable via user menu, not primary nav */
export const CREATE_SUBNAV: { to: string; label: string; capability: Capability; end?: boolean }[] = [
  { to: '/create', label: '新建', capability: 'create_content', end: true },
  { to: '/create/reports', label: '報告', capability: 'create_content' },
]
