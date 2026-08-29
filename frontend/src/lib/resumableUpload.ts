import { uploadSessionApi, type UploadSessionState } from '../api'
import type { KnowledgeAsset } from '../types'

export interface ResumableUploadInput {
  file: File
  idempotencyKey: string
  sessionId?: string
  partSize?: number
  title?: string
  departmentId?: string
  dataClassification?: string
  contextMetadata?: Record<string, string | string[]>
}

export interface ResumableUploadOptions {
  signal?: AbortSignal
  concurrency?: number
  maxRetries?: number
  onSession?: (session: UploadSessionState) => void
  onProgress?: (percentage: number, acknowledgedBytes: number) => void
}

function abortError() {
  return new DOMException('Upload paused', 'AbortError')
}

function throwIfAborted(signal?: AbortSignal) {
  if (signal?.aborted) throw abortError()
}

async function sha256(blob: Blob): Promise<string> {
  const bytes = await blob.arrayBuffer()
  const digest = await crypto.subtle.digest('SHA-256', bytes)
  return Array.from(new Uint8Array(digest), value => value.toString(16).padStart(2, '0')).join('')
}

async function retry<T>(operation: () => Promise<T>, options: ResumableUploadOptions): Promise<T> {
  const attempts = Math.max(1, options.maxRetries ?? 4)
  let lastError: unknown
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    throwIfAborted(options.signal)
    try {
      return await operation()
    } catch (error) {
      if (options.signal?.aborted) throw abortError()
      lastError = error
      const status = typeof error === 'object' && error !== null && 'response' in error
        ? Number((error as { response?: { status?: number } }).response?.status || 0)
        : 0
      const retryable = status === 0 || status === 408 || status === 429 || status >= 500
      if (!retryable || attempt + 1 >= attempts) break
      const delay = Math.min(4000, 300 * 2 ** attempt) + Math.floor(Math.random() * 150)
      await new Promise<void>((resolve, reject) => {
        let settled = false
        const finish = () => {
          if (settled) return
          settled = true
          window.clearTimeout(timer)
          window.removeEventListener('online', finish)
          resolve()
        }
        const timer = window.setTimeout(finish, delay)
        if (typeof navigator !== 'undefined' && !navigator.onLine) {
          window.addEventListener('online', finish, { once: true })
        }
        options.signal?.addEventListener('abort', () => {
          if (settled) return
          settled = true
          window.clearTimeout(timer)
          window.removeEventListener('online', finish)
          reject(abortError())
        }, { once: true })
      })
    }
  }
  throw lastError
}

async function restoreOrCreate(input: ResumableUploadInput, options: ResumableUploadOptions) {
  if (input.sessionId) {
    try {
      return await uploadSessionApi.get(input.sessionId)
    } catch {
      throwIfAborted(options.signal)
      // The idempotent create call recovers a session whose local identifier
      // was stale without ever creating duplicate canonical assets.
    }
  }
  return uploadSessionApi.create({
    filename: input.file.name,
    mediaType: input.file.type || 'application/octet-stream',
    byteSize: input.file.size,
    partSize: input.partSize,
    idempotencyKey: input.idempotencyKey,
    title: input.title,
    departmentId: input.departmentId,
    dataClassification: input.dataClassification,
    contextMetadata: input.contextMetadata,
  })
}

export async function uploadFileResumable(
  input: ResumableUploadInput,
  options: ResumableUploadOptions = {},
): Promise<KnowledgeAsset> {
  const session = await retry(() => restoreOrCreate(input, options), options)
  options.onSession?.(session)
  if (session.status === 'committed' && session.asset_id) {
    return uploadSessionApi.commit(session.id)
  }
  if (['aborted', 'expired'].includes(session.status)) throw new Error('上傳工作已過期或中止，請重新加入檔案。')

  const acknowledged = new Map(session.acknowledged_parts.map(part => [part.part_number, part.byte_size]))
  let acknowledgedBytes = Array.from(acknowledged.values()).reduce((sum, value) => sum + value, 0)
  const report = () => options.onProgress?.(Math.min(99, Math.round(acknowledgedBytes * 100 / input.file.size)), acknowledgedBytes)
  report()
  const missing = Array.from({ length: session.total_parts }, (_, index) => index + 1).filter(number => !acknowledged.has(number))
  let cursor = 0
  const worker = async () => {
    while (cursor < missing.length) {
      const index = cursor
      cursor += 1
      const partNumber = missing[index]
      const start = (partNumber - 1) * session.part_size
      const part = input.file.slice(start, Math.min(input.file.size, start + session.part_size))
      const digest = await sha256(part)
      await retry(() => uploadSessionApi.putPart(session.id, partNumber, part, digest, { signal: options.signal }), options)
      acknowledgedBytes += part.size
      report()
    }
  }
  await Promise.all(Array.from({ length: Math.min(options.concurrency ?? 3, missing.length || 1) }, worker))
  throwIfAborted(options.signal)
  const asset = await retry(() => uploadSessionApi.commit(session.id), options)
  options.onProgress?.(100, input.file.size)
  return asset
}
