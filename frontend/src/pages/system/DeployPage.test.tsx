import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import DeployPage from './DeployPage'

const backendRelease = {
  schema_version: 1,
  release_id: 'release-42',
  source_commit: 'abc123',
  source_dirty: 'false',
  build_time: '2026-08-27T10:00:00Z',
  deployment_manifest_id: 'manifest-1',
  schema_head: 'phase-p0',
  route_contract_hash: 'route-hash',
  identifiable: true,
  database_schema_heads: ['phase-p0'],
  schema_matches: true,
}

const frontendRelease = {
  ...backendRelease,
  canonical_routes: ['/overview', '/knowledge/assets'],
}

const getDeploymentMode = vi.fn()
const release = vi.fn()
const getFrontendRelease = vi.fn()

vi.mock('../../api', () => ({
  companyApi: {
    getDeploymentMode: () => getDeploymentMode(),
    setDeploymentMode: vi.fn(),
  },
  operationsApi: {
    release: () => release(),
    frontendRelease: () => getFrontendRelease(),
  },
  parseApiError: (error: unknown) => error,
  formatErrorWithTrace: () => 'error',
}))

describe('DeployPage release identity', () => {
  beforeEach(() => {
    getDeploymentMode.mockResolvedValue({ mode: 'nogpu' })
    release.mockResolvedValue(backendRelease)
    getFrontendRelease.mockResolvedValue(frontendRelease)
  })

  it('shows a positive parity decision only when backend and frontend identity match', async () => {
    render(<DeployPage />)

    expect(await screen.findByText('前後端版本一致')).toBeInTheDocument()
    expect(screen.getByText('release-42')).toBeInTheDocument()
    expect(screen.getByText('abc123')).toBeInTheDocument()
  })

  it('fails closed when frontend and backend route contracts differ', async () => {
    getFrontendRelease.mockResolvedValue({ ...frontendRelease, route_contract_hash: 'different' })
    render(<DeployPage />)

    await waitFor(() => expect(screen.getByText('版本識別待確認')).toBeInTheDocument())
  })
})
