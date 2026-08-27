import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import ModulesPage from './ModulesPage'

const refreshExperience = vi.fn(async () => undefined)
vi.mock('../../auth', () => ({
  useAuth: () => ({
    experienceStatus: 'ready',
    refreshExperience,
    experience: {
      capability_catalog: [
        { key: 'enclave_base', kind: 'platform_capability', deployment_status: 'deployed', entitlement_status: 'included', runtime_status: 'healthy', user_permission_status: 'not_applicable' },
        { key: 'quality_8d', pack_key: 'mka', kind: 'domain_module', deployment_status: 'deployed', entitlement_status: 'enabled', runtime_status: 'degraded', user_permission_status: 'denied' },
      ],
    },
  }),
}))

describe('ModulesPage', () => {
  it('keeps deployment, entitlement, runtime and user permission as separate states', () => {
    render(<ModulesPage />)
    expect(screen.getByRole('table', { name: '平台能力及應用包的四維狀態' })).toBeInTheDocument()
    for (const heading of ['部署', '租戶授權', '執行狀態', '我的權限']) expect(screen.getByRole('columnheader', { name: heading })).toBeInTheDocument()
    expect(screen.getByRole('rowheader', { name: /quality_8d/ })).toBeInTheDocument()
    expect(screen.getByText('降級')).toBeInTheDocument()
    expect(screen.getByText('未授權')).toBeInTheDocument()
  })
})
