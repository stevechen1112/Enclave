/**
 * Unified API error mapping — scope, retry, request ID (UIUX §12.4)
 */
import axios from 'axios'

export type ApiErrorInfo = {
  message: string
  status?: number
  requestId?: string
  retryable: boolean
}

function pickRequestId(data: unknown, headers?: Record<string, unknown>): string | undefined {
  if (data && typeof data === 'object') {
    const d = data as Record<string, unknown>
    const id =
      d.request_id ||
      d.requestId ||
      (d.detail && typeof d.detail === 'object'
        ? (d.detail as Record<string, unknown>).request_id
        : undefined)
    if (typeof id === 'string' && id.trim()) return id.trim()
    if (typeof d.detail === 'string' && /request[_-]?id/i.test(d.detail)) {
      const m = d.detail.match(/request[_-]?id[=:\s]+([a-zA-Z0-9-]+)/i)
      if (m) return m[1]
    }
  }
  const h = headers || {}
  const hdr =
    (h['x-request-id'] as string | undefined) ||
    (h['X-Request-Id'] as string | undefined) ||
    (h['x-correlation-id'] as string | undefined)
  return hdr || undefined
}

function detailMessage(data: unknown): string | undefined {
  if (!data) return undefined
  if (typeof data === 'string') return data
  if (typeof data === 'object') {
    const d = data as Record<string, unknown>
    if (typeof d.detail === 'string') return d.detail
    if (Array.isArray(d.detail)) {
      return d.detail
        .map(item => (typeof item === 'object' && item && 'msg' in item
          ? String((item as { msg: unknown }).msg)
          : String(item)))
        .join('；')
    }
    if (typeof d.message === 'string') return d.message
    if (typeof d.error === 'string') return d.error
  }
  return undefined
}

export function parseApiError(err: unknown, fallback = '操作失敗，請稍後重試'): ApiErrorInfo {
  if (axios.isAxiosError(err)) {
    const status = err.response?.status
    const data = err.response?.data
    const requestId = pickRequestId(data, err.response?.headers as Record<string, unknown> | undefined)
    const message = detailMessage(data) || err.message || fallback
    const retryable =
      !status ||
      status === 408 ||
      status === 429 ||
      status >= 500 ||
      err.code === 'ECONNABORTED' ||
      err.code === 'ERR_NETWORK'
    return { message, status, requestId, retryable }
  }
  if (err instanceof Error) {
    return { message: err.message || fallback, retryable: true }
  }
  return { message: fallback, retryable: true }
}

export function formatErrorWithTrace(info: ApiErrorInfo): string {
  return info.requestId ? `${info.message}（追蹤：${info.requestId}）` : info.message
}
