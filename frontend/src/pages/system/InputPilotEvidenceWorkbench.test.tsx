import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import InputPilotEvidenceWorkbench from './InputPilotEvidenceWorkbench'

const mocks = vi.hoisted(() => ({
  inputPilotEvidence: vi.fn(),
  recordInputPilotMetric: vi.fn(),
}))

vi.mock('../../api', async importOriginal => {
  const actual = await importOriginal<typeof import('../../api')>()
  return {
    ...actual,
    operationsApi: {
      ...actual.operationsApi,
      inputPilotEvidence: mocks.inputPilotEvidence,
      recordInputPilotMetric: mocks.recordInputPilotMetric,
    },
  }
})

const emptyEvidence = {
  metric_rows: 0,
  latest_metrics: [],
  incidents: [],
  audits: [],
  retrospective: null,
  acceptance: null,
}

describe('InputPilotEvidenceWorkbench', () => {
  it('records a configured journey metric with numeric fields and evidence hash', async () => {
    mocks.inputPilotEvidence.mockResolvedValue(emptyEvidence)
    mocks.recordInputPilotMetric.mockResolvedValue({ id: 'metric-1' })
    const onChanged = vi.fn()
    render(
      <InputPilotEvidenceWorkbench
        pilot={{
          id: 'pilot-1', name: 'Pilot', status: 'running', evidence_mode: 'live',
          journeys: [{ key: 'nas_batch' }, { key: 'long_audio' }], created_at: '2026-08-29T00:00:00Z',
        }}
        gate={null}
        onChanged={onChanged}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: /每日指標/ }))
    fireEvent.change(screen.getByLabelText('來源證據 SHA-256'), { target: { value: 'a'.repeat(64) } })
    fireEvent.click(screen.getByRole('button', { name: '封存證據' }))

    await waitFor(() => expect(mocks.recordInputPilotMetric).toHaveBeenCalledWith(
      'pilot-1',
      expect.objectContaining({
        journey_key: 'nas_batch',
        total_attempts: 1,
        successful_attempts: 1,
        source_evidence_sha256: 'a'.repeat(64),
      }),
    ))
    await waitFor(() => expect(onChanged).toHaveBeenCalled())
  })
})
