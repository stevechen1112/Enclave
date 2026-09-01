import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import HealthPage from './HealthPage'

const auth = vi.hoisted(() => ({ experience: { demo_mode: false } }))

vi.mock('../../auth', () => ({
  useAuth: () => auth,
}))

const mocks = vi.hoisted(() => ({
  listIntegrityReports: vi.fn(),
  providerHealth: vi.fn(),
  probeProviderHealth: vi.fn(),
}))

vi.mock('../../api', async importOriginal => {
  const actual = await importOriginal<typeof import('../../api')>()
  return {
    ...actual,
    kbApi: {
      ...actual.kbApi,
      listIntegrityReports: mocks.listIntegrityReports,
      triggerIntegrityCheck: vi.fn(),
    },
    companyApi: {
      ...actual.companyApi,
      providerHealth: mocks.providerHealth,
      probeProviderHealth: mocks.probeProviderHealth,
    },
  }
})

describe('HealthPage provider gate', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    auth.experience.demo_mode = false
    mocks.listIntegrityReports.mockResolvedValue([])
    mocks.providerHealth.mockResolvedValue({
      providers: [{
        role: 'main_llm',
        label: 'AI 問答',
        provider: 'openai',
        model: 'gpt-test',
        enabled: true,
        credential_configured: true,
      }],
    })
    mocks.probeProviderHealth.mockResolvedValue({
      status: 'pass',
      passed: 1,
      total: 1,
      results: [{
        role: 'main_llm',
        label: 'AI 問答',
        provider: 'openai',
        model: 'gpt-test',
        status: 'pass',
        elapsed_ms: 125,
        detail: '實際呼叫成功',
      }],
    })
  })

  it('does not make paid probe calls on page load and probes only after confirmation click', async () => {
    render(<HealthPage />)

    expect(await screen.findByText('AI 問答')).toBeInTheDocument()
    expect(mocks.probeProviderHealth).not.toHaveBeenCalled()

    fireEvent.click(screen.getByRole('button', { name: '實際檢查 Provider' }))

    await waitFor(() => expect(mocks.probeProviderHealth).toHaveBeenCalledTimes(1))
    expect(await screen.findByText('實測通過')).toBeInTheDocument()
  })

  it('keeps public demo sessions from calling paid external services', async () => {
    auth.experience.demo_mode = true
    render(<HealthPage />)

    const button = await screen.findByRole('button', { name: 'Demo 不執行外部實測' })
    expect(button).toBeDisabled()
    fireEvent.click(button)
    expect(mocks.probeProviderHealth).not.toHaveBeenCalled()
  })
})
