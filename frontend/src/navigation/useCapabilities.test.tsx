import { renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ExperienceBootstrap } from '../types'
import { useDefaultHomePath, usePrimaryNav } from './useCapabilities'

const authState: {
  user: { role: string; is_superuser: boolean }
  experience: Partial<ExperienceBootstrap> | null
} = {
  user: { role: 'employee', is_superuser: false },
  experience: null,
}

vi.mock('../auth', () => ({ useAuth: () => authState }))

describe('manifest-driven navigation', () => {
  beforeEach(() => {
    authState.experience = null
  })

  it('fails closed when bootstrap has no enabled UI module', () => {
    authState.experience = {
      capabilities: ['home', 'ask'],
      default_home: 'overview',
      primary_navigation: [
        { to: '/overview', label: '總覽', capability: 'home' },
        { to: '/ask', label: '問答', capability: 'ask' },
      ],
      ui_modules: [],
    }

    expect(renderHook(() => usePrimaryNav()).result.current.map(item => item.to)).not.toContain('/job')
    expect(renderHook(() => useDefaultHomePath()).result.current).toBe('/overview')
  })

  it('shows field navigation only when the manifest declares it', () => {
    authState.experience = {
      capabilities: ['ask', 'field_work'],
      default_home: 'job',
      primary_navigation: [
        { to: '/job', label: '現場作業', module: 'mka.workspace' },
        { to: '/ask', label: '問答', capability: 'ask' },
      ],
      ui_modules: [{
        pack_key: 'mka',
        ui_key: 'mka.workspace',
        version: '1.0.0',
        route_keys: ['workflow.job.home'],
        required_capabilities: [],
        navigation: [{ to: '/job', label: '現場作業' }],
      }],
    }

    expect(renderHook(() => usePrimaryNav()).result.current.map(item => item.to)).toContain('/job')
    expect(renderHook(() => useDefaultHomePath()).result.current).toBe('/job')
  })
})
