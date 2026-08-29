import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../api', () => ({
  uploadSessionApi: {
    create: vi.fn(),
    get: vi.fn(),
    putPart: vi.fn(),
    commit: vi.fn(),
  },
}))

import { uploadSessionApi } from '../api'
import { uploadFileResumable } from './resumableUpload'

const create = vi.mocked(uploadSessionApi.create)
const get = vi.mocked(uploadSessionApi.get)
const putPart = vi.mocked(uploadSessionApi.putPart)
const commit = vi.mocked(uploadSessionApi.commit)

function session(overrides: Record<string, unknown> = {}) {
  return {
    id: 'session-1', status: 'uploading', filename: 'manual.txt', media_type: 'text/plain',
    byte_size: 10, part_size: 4, total_parts: 3, received_bytes: 0, received_parts: 0,
    acknowledged_parts: [], expires_at: new Date(Date.now() + 60_000).toISOString(),
    ...overrides,
  }
}

describe('uploadFileResumable', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    create.mockResolvedValue(session())
    putPart.mockImplementation(async (_id, number) => session({ received_parts: number }))
    commit.mockResolvedValue({ id: 'asset-1', title: 'manual.txt' } as never)
  })

  it('uploads bounded parts and commits only after all acknowledgements', async () => {
    const progress: number[] = []
    const file = new File(['abcdefghij'], 'manual.txt', { type: 'text/plain' })
    const asset = await uploadFileResumable(
      { file, idempotencyKey: 'upload-1', partSize: 4 },
      { concurrency: 2, onProgress: value => progress.push(value) },
    )

    expect(asset.id).toBe('asset-1')
    expect(putPart).toHaveBeenCalledTimes(3)
    expect(putPart.mock.calls.map(call => call[1]).sort()).toEqual([1, 2, 3])
    expect(putPart.mock.calls.map(call => call[2].size).sort()).toEqual([2, 4, 4])
    expect(commit.mock.invocationCallOrder[0]).toBeGreaterThan(Math.max(...putPart.mock.invocationCallOrder))
    expect(progress.at(-1)).toBe(100)
  })

  it('resumes by skipping server-acknowledged parts', async () => {
    get.mockResolvedValue(session({
      received_bytes: 4,
      received_parts: 1,
      acknowledged_parts: [{ part_number: 1, byte_size: 4, sha256: 'a'.repeat(64) }],
    }))
    const file = new File(['abcdefghij'], 'manual.txt', { type: 'text/plain' })
    await uploadFileResumable({ file, idempotencyKey: 'upload-1', sessionId: 'session-1' })

    expect(create).not.toHaveBeenCalled()
    expect(putPart.mock.calls.map(call => call[1]).sort()).toEqual([2, 3])
  })

  it('pauses without committing when its abort signal fires', async () => {
    const controller = new AbortController()
    putPart.mockImplementation(async () => {
      controller.abort()
      return session()
    })
    const file = new File(['abcdefghij'], 'manual.txt', { type: 'text/plain' })

    await expect(uploadFileResumable(
      { file, idempotencyKey: 'upload-1' },
      { signal: controller.signal, concurrency: 1 },
    )).rejects.toMatchObject({ name: 'AbortError' })
    expect(commit).not.toHaveBeenCalled()
  })

  it('does not retry deterministic 4xx checksum failures', async () => {
    putPart.mockRejectedValue({ response: { status: 422 } })
    const file = new File(['abcd'], 'manual.txt', { type: 'text/plain' })
    create.mockResolvedValue(session({ byte_size: 4, total_parts: 1 }))

    await expect(uploadFileResumable(
      { file, idempotencyKey: 'upload-1' },
      { maxRetries: 4 },
    )).rejects.toMatchObject({ response: { status: 422 } })
    expect(putPart).toHaveBeenCalledTimes(1)
    expect(commit).not.toHaveBeenCalled()
  })

  it('retries a transient network failure without re-creating the session', async () => {
    putPart.mockRejectedValueOnce(new Error('connection reset')).mockResolvedValue(session())
    const file = new File(['abcd'], 'manual.txt', { type: 'text/plain' })
    create.mockResolvedValue(session({ byte_size: 4, total_parts: 1 }))

    await uploadFileResumable(
      { file, idempotencyKey: 'upload-1' },
      { maxRetries: 2 },
    )
    expect(create).toHaveBeenCalledTimes(1)
    expect(putPart).toHaveBeenCalledTimes(2)
    expect(commit).toHaveBeenCalledTimes(1)
  })
})
