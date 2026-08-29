import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('./captureApi', () => ({
  captureApi: {
    policy: vi.fn(),
    create: vi.fn(),
    get: vi.fn(),
    uploadChunk: vi.fn(),
    complete: vi.fn(),
  },
}))

import CoreAudioRecorder from './CoreAudioRecorder'
import { captureApi } from './captureApi'

const policy = {
  consent_version: 'core-capture-v1',
  max_duration_seconds: 2700,
  chunk_max_seconds: 30,
  chunk_max_bytes: 8_388_608,
  max_chunks: 240,
  audio_retention_days: 30,
  transcript_retention_days: 365,
  save_audio: true,
  save_transcript: true,
  encrypt_at_rest: true,
  terminology_count: 42,
  terminology_sha256: 'a'.repeat(64),
  default_metadata: { data_classification: 'confidential', source_module: 'core', purpose: 'knowledge_capture' },
  device_limitations: ['lock_screen_or_app_switch_may_interrupt_browser_capture'],
}

class FakeMediaRecorder {
  static isTypeSupported() { return true }
  state = 'inactive'
  stop() {}
  start() { this.state = 'recording' }
  requestData() { requestDataSpy() }
}

const requestDataSpy = vi.fn()

describe('CoreAudioRecorder', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.mocked(captureApi.policy).mockReset()
    vi.mocked(captureApi.policy).mockResolvedValue(policy)
    vi.mocked(captureApi.create).mockReset()
    requestDataSpy.mockReset()
    vi.stubGlobal('MediaRecorder', FakeMediaRecorder)
  })

  it('shows tenant policy, terminology and an explicit device storage warning', async () => {
    render(<CoreAudioRecorder title="交接" onQueued={vi.fn()} />)
    expect(await screen.findByText(/術語表：42 筆/)).toBeInTheDocument()
    expect(screen.getByText(/音訊保留 30 天/)).toBeInTheDocument()
    expect(screen.getByText(/鎖屏或切換 App 可能會中斷/)).toBeInTheDocument()
    expect(screen.getByText('45:00')).toBeInTheDocument()
  })

  it('fails clearly when microphone permission is denied and never creates a session', async () => {
    const denied = Object.assign(new Error('denied'), { name: 'NotAllowedError' })
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { getUserMedia: vi.fn().mockRejectedValue(denied) },
    })
    render(<CoreAudioRecorder title="交接" onQueued={vi.fn()} />)
    await screen.findByText(/術語表：42 筆/)
    await userEvent.click(screen.getByRole('button', { name: '開始訪談' }))
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('沒有取得麥克風權限'))
    expect(captureApi.create).not.toHaveBeenCalled()
  })

  it('flushes the active recorder and warns when the page becomes hidden', async () => {
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { getUserMedia: vi.fn().mockResolvedValue({ getTracks: () => [{ stop: vi.fn() }] }) },
    })
    vi.mocked(captureApi.create).mockResolvedValue({
      id: 'capture-1', title: '交接', equipment_id: null, interviewee: null, interviewer: null,
      status: 'recording', received_chunks: 0, expected_chunks: null, total_duration_ms: 0,
      error: {}, source_asset_id: 'asset-1', capture_metadata: {}, policy: {},
      created_at: new Date().toISOString(), completed_at: null,
    })
    render(<CoreAudioRecorder title="交接" onQueued={vi.fn()} />)
    await screen.findByText(/術語表：42 筆/)
    await userEvent.click(screen.getByRole('button', { name: '開始訪談' }))
    await screen.findByRole('button', { name: '結束訪談' })
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' })
    act(() => document.dispatchEvent(new Event('visibilitychange')))
    expect(requestDataSpy).toHaveBeenCalledTimes(1)
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('鎖屏或切換 App'))
  })
})
