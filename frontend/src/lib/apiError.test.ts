import axios from 'axios'
import { afterEach, describe, expect, it } from 'vitest'

import { parseApiError } from './apiError'

function failure(status: number | undefined, data: unknown, code?: string) {
  return new axios.AxiosError('failed', code, undefined, undefined, status ? {
    status,
    statusText: 'error',
    headers: { 'x-request-id': 'req-7' },
    config: { headers: new axios.AxiosHeaders() },
    data,
  } : undefined)
}

describe('parseApiError', () => {
  afterEach(() => Object.defineProperty(window.navigator, 'onLine', { configurable: true, value: true }))

  it('maps offline, timeout, quota and provider-disabled states to actionable messages', () => {
    Object.defineProperty(window.navigator, 'onLine', { configurable: true, value: false })
    expect(parseApiError(failure(undefined, null, 'ERR_NETWORK')).message).toContain('離線')
    Object.defineProperty(window.navigator, 'onLine', { configurable: true, value: true })
    expect(parseApiError(failure(408, null)).message).toContain('逾時')
    expect(parseApiError(failure(429, { detail: 'quota limit reached' })).message).toContain('額度')
    expect(parseApiError(failure(503, { detail: 'provider disabled' })).message).toContain('未啟用')
  })

  it('preserves request IDs and marks non-retryable client errors', () => {
    expect(parseApiError(failure(403, { detail: '權限不足' }))).toEqual({
      message: '權限不足', status: 403, requestId: 'req-7', retryable: false,
    })
  })
})
