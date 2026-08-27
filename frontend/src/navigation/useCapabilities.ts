/** Hooks backed exclusively by the authenticated experience bootstrap. */
import { useAuth } from '../auth'
import {
  serverDefaultHome,
  serverNavigation,
  type Capability,
  type NavItem,
} from './capabilities'

export function useCapabilities(): Set<Capability> {
  const { experience } = useAuth()
  return new Set((experience?.capabilities || []) as Capability[])
}

export function useHasCapability(capability: Capability): boolean {
  return useCapabilities().has(capability)
}

export function usePrimaryNav(): NavItem[] {
  const { experience } = useAuth()
  return serverNavigation(experience?.primary_navigation, useCapabilities())
}

export function useDefaultHomePath(): string {
  const { experience } = useAuth()
  return serverDefaultHome(experience?.default_home, usePrimaryNav())
}
