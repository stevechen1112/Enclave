/**
 * Bootstrap 驅動的能力 hook — 後端 /experience/bootstrap 是能力唯一來源。
 *
 * 本地 ROLE_CAPS（capabilities.ts）僅作 bootstrap 尚未載入時的
 * route-guard 最小安全 fallback；兩邊角色表必須保持一致。
 */
import { useAuth } from '../auth'
import {
  capabilitiesFor,
  defaultHomePathForCaps,
  primaryNavForCaps,
  type Capability,
  type NavItem,
} from './capabilities'

export function useCapabilities(): Set<Capability> {
  const { user, experience } = useAuth()
  const serverCaps = experience?.capabilities
  if (Array.isArray(serverCaps)) {
    return new Set(serverCaps as Capability[])
  }
  return capabilitiesFor(user?.role, user?.is_superuser)
}

export function useHasCapability(cap: Capability): boolean {
  return useCapabilities().has(cap)
}

export function usePrimaryNav(): NavItem[] {
  const { user } = useAuth()
  return primaryNavForCaps(useCapabilities(), user?.role)
}

export function useDefaultHomePath(): string {
  return defaultHomePathForCaps(useCapabilities())
}
