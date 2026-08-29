import { render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import InputPilotPage from './InputPilotPage'

vi.mock('../../auth', () => ({
  useAuth: () => ({ user: { id: 'user-1' } }),
}))

const mocks = vi.hoisted(() => ({
  listInputPilots: vi.fn(),
  inputPilotGate: vi.fn(),
  inputPilotEvidence: vi.fn(),
}))

vi.mock('../../api', async importOriginal => {
  const actual = await importOriginal<typeof import('../../api')>()
  return {
    ...actual,
    operationsApi: {
      ...actual.operationsApi,
      listInputPilots: mocks.listInputPilots,
      inputPilotGate: mocks.inputPilotGate,
      inputPilotEvidence: mocks.inputPilotEvidence,
      createInputPilot: vi.fn(),
      startInputPilot: vi.fn(),
    },
  }
})

describe('InputPilotPage', () => {
  it('shows honest HOLD blockers instead of claiming the pilot passed', async () => {
    mocks.listInputPilots.mockResolvedValueOnce([{
      id: 'pilot-1',
      name: '第一租戶 Input 試行',
      status: 'running',
      evidence_mode: 'live',
      journeys: [{ key: 'nas_batch' }, { key: 'long_audio' }],
      created_at: '2026-08-29T00:00:00Z',
    }])
    mocks.inputPilotGate.mockResolvedValueOnce({
      status: 'HOLD',
      observation_days: 3,
      journeys: {},
      incident_count: 0,
      passed_audits: ['quality'],
      signed_acceptance: false,
      errors: [
        'pilot observation window is shorter than minimum days',
        'signed customer acceptance is missing',
      ],
    })
    mocks.inputPilotEvidence.mockResolvedValueOnce({
      metric_rows: 0,
      latest_metrics: [],
      incidents: [],
      audits: [],
      retrospective: null,
      acceptance: null,
    })

    render(<InputPilotPage />)

    expect(await screen.findByText('第一租戶 Input 試行')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText('HOLD')).toBeInTheDocument())
    expect(screen.getByText(/尚未累積連續 14 天資料/)).toBeInTheDocument()
    expect(screen.getByText(/尚未附上客戶簽署驗收文件/)).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Pilot 證據工作台' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /每日指標/ })).toBeEnabled()
  })
})
