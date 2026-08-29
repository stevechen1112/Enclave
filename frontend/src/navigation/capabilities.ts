/** Server-composed capability and navigation contracts. */

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
  | 'home'
  | 'field_work'

export type NavItem = {
  to: string
  label: string
  capability?: Capability
  module?: string
  end?: boolean
}

export const ROLE_LABELS: Record<string, string> = {
  owner: '擁有者', admin: '管理員', hr: '內容負責人', employee: '員工', viewer: '唯讀',
}

export function isSafeAppPath(value: unknown): value is string {
  return typeof value === 'string' && !value.startsWith('//') && /^\/[a-z0-9/_-]*$/i.test(value)
}

export function serverNavigation(
  items: NavItem[] | undefined,
  capabilities: Set<Capability>,
): NavItem[] {
  const seen = new Set<string>()
  return (items || []).filter(item => {
    if (!isSafeAppPath(item.to) || !item.label?.trim() || seen.has(item.to)) return false
    if (item.capability && !capabilities.has(item.capability)) return false
    seen.add(item.to)
    return true
  })
}

export function serverDefaultHome(value: unknown, navigation: NavItem[]): string {
  const normalized = typeof value === 'string' && !value.startsWith('/') ? `/${value}` : value
  if (!isSafeAppPath(normalized)) return '/ask'
  if (normalized === '/ask') return normalized
  const reachable = navigation.some(item => item.to === normalized || normalized.startsWith(`${item.to}/`))
  return reachable ? normalized : '/ask'
}

export const KNOWLEDGE_SUBNAV: { to: string; label: string; capability: Capability }[] = [
  { to: '/knowledge/assets', label: '所有資產', capability: 'browse_knowledge' },
  { to: '/knowledge/wiki', label: '已發布知識', capability: 'browse_knowledge' },
  { to: '/knowledge/sources', label: '來源與整合', capability: 'manage_sources' },
  { to: '/knowledge/review', label: '待審核', capability: 'review_queue' },
  { to: '/knowledge/quality', label: '品質與版本', capability: 'governance' },
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
  { to: '/system/input-pilot', label: 'Input 試行', capability: 'system_ops' },
  { to: '/system/backup', label: '備份', capability: 'system_ops' },
  { to: '/system/deploy', label: '版本更新', capability: 'system_ops' },
]

export const CREATE_SUBNAV: { to: string; label: string; capability: Capability; end?: boolean }[] = [
  { to: '/create', label: '新建', capability: 'create_content', end: true },
  { to: '/create/reports', label: '報告', capability: 'create_content' },
]
