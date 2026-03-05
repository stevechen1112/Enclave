/**
 * API client for Enclave Mobile
 *
 * Mirrors web frontend/src/api.ts, adapted for React Native:
 * - Uses expo-secure-store instead of localStorage
 * - SSE streaming uses native fetch with ReadableStream (RN 0.74 / Hermes)
 * - Base URL is configurable via src/config.ts
 */
import axios from 'axios'
import type { AxiosError, InternalAxiosRequestConfig } from 'axios'
import * as SecureStore from 'expo-secure-store'
import { API_BASE_URL } from './config'
import { injectDeviceHeaders, verifyCertFingerprint, CERT_PINS } from './security'
import type { User, Document, Conversation, Message, ChatRequest, SSEEvent } from './types'

// ─── Axios instance ───
const api = axios.create({ baseURL: API_BASE_URL })

/** P12-2: 是否正在 refresh token，避免重複 refresh */
let isRefreshing = false
let failedQueue: Array<{
  resolve: (token: string) => void
  reject: (error: unknown) => void
}> = []

function processQueue(error: unknown, token: string | null) {
  failedQueue.forEach(({ resolve, reject }) => {
    if (error) reject(error)
    else resolve(token!)
  })
  failedQueue = []
}

api.interceptors.request.use(async (config) => {
  const token = await SecureStore.getItemAsync('token')
  if (token) config.headers.Authorization = `Bearer ${token}`

  // P12-11: 裝置綁定 — 注入 X-Device-ID / X-Platform / X-App-Version
  const extra = await injectDeviceHeaders({})
  Object.assign(config.headers, extra)

  return config
})

api.interceptors.response.use(
  (res) => res,
  async (err: AxiosError) => {
    const originalRequest = err.config as InternalAxiosRequestConfig & { _retry?: boolean }
    const status = err.response?.status

    // P12-2: 401 時嘗試 token refresh（僅一次）
    if (status === 401 && originalRequest && !originalRequest._retry) {
      if (isRefreshing) {
        // 排入佇列等待 refresh 完成
        return new Promise((resolve, reject) => {
          failedQueue.push({
            resolve: (newToken: string) => {
              originalRequest.headers.Authorization = `Bearer ${newToken}`
              resolve(api(originalRequest))
            },
            reject,
          })
        })
      }

      originalRequest._retry = true
      isRefreshing = true

      try {
        const { data } = await axios.post<{ access_token: string }>(
          `${API_BASE_URL}/mobile/auth/refresh-token`,
          {},
          {
            headers: {
              Authorization: originalRequest.headers.Authorization as string,
            },
          },
        )
        const newToken = data.access_token
        await SecureStore.setItemAsync('token', newToken)
        originalRequest.headers.Authorization = `Bearer ${newToken}`
        processQueue(null, newToken)
        return api(originalRequest)
      } catch (refreshErr) {
        processQueue(refreshErr, null)
        await SecureStore.deleteItemAsync('token')
        return Promise.reject(refreshErr)
      } finally {
        isRefreshing = false
      }
    }

    return Promise.reject(err)
  },
)

/**
 * P12-11: 啟動時驗證 SSL 憑證指紋（一次性檢查）
 * 在 App 初始化時呼叫此函式。
 */
export async function performCertPinningCheck(): Promise<boolean> {
  return verifyCertFingerprint(async () => {
    const { data } = await axios.get<{ fingerprint: string }>(
      `${API_BASE_URL}/mobile/security/cert-fingerprint`,
    )
    return data
  })
}

export default api

// ──────────────────────────────────────────────
// Auth
// ──────────────────────────────────────────────
export const authApi = {
  /** POST /auth/login/access-token — x-www-form-urlencoded */
  login: async (email: string, password: string): Promise<{ access_token: string }> => {
    const params = new URLSearchParams()
    params.append('username', email)
    params.append('password', password)
    const { data } = await api.post<{ access_token: string }>(
      '/auth/login/access-token',
      params.toString(),
      { headers: { 'Content-Type': 'application/x-www-form-urlencoded' } },
    )
    return data
  },
  me: (): Promise<User> => api.get<User>('/users/me').then(r => r.data),
}

// ──────────────────────────────────────────────
// Documents
// ──────────────────────────────────────────────
export const docApi = {
  list: (): Promise<Document[]> =>
    api.get<Document[]>('/documents/').then(r => r.data),

  /**
   * Upload a file using expo-document-picker result.
   * `uri`  — local file URI from DocumentPicker
   * `name` — original filename
   * `mimeType` — e.g. "application/pdf"
   */
  /**
   * P12-6 上傳模式：
   *   'immediate' → 立即入庫（預設）
   *   'review'    → 待審核佇列（將 queue_for_review=true 傳給後端）
   */
  upload: async (
    uri: string,
    name: string,
    mimeType: string,
    onProgress?: (pct: number) => void,
    uploadMode: 'immediate' | 'review' = 'immediate',
  ): Promise<Document> => {
    const token = await SecureStore.getItemAsync('token')
    const form = new FormData()
    // React Native FormData accepts object literals as file blobs
    form.append('file', { uri, name, type: mimeType } as unknown as Blob)
    const endpoint = uploadMode === 'review'
      ? '/documents/upload?queue_for_review=true'
      : '/documents/upload'
    const { data } = await api.post<Document>(endpoint, form, {
      headers: {
        'Content-Type': 'multipart/form-data',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      onUploadProgress: (e) => {
        if (e.total && onProgress) onProgress(Math.round((e.loaded * 100) / e.total))
      },
    })
    return data
  },

  delete: (id: string): Promise<void> =>
    api.delete(`/documents/${id}`).then(() => undefined),
}

// ──────────────────────────────────────────────
// Chat
// ──────────────────────────────────────────────
export const chatApi = {
  conversations: (): Promise<Conversation[]> =>
    api.get<Conversation[]>('/chat/conversations').then(r => r.data),

  messages: (convId: string): Promise<Message[]> =>
    api.get<Message[]>(`/chat/conversations/${convId}/messages`).then(r => r.data),

  deleteConversation: (convId: string): Promise<void> =>
    api.delete(`/chat/conversations/${convId}`).then(() => undefined),

  /**
   * SSE streaming chat — mirrors web chatApi.stream()
   * Uses native fetch with ReadableStream (Hermes / RN 0.74+)
   */
  stream: async (
    req: ChatRequest,
    onEvent: (event: SSEEvent) => void,
    signal?: AbortSignal,
  ): Promise<void> => {
    const token = await SecureStore.getItemAsync('token')
    const response = await fetch(`${API_BASE_URL}/chat/chat/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify(req),
      signal,
      // @ts-ignore — React Native fetch supports this in RN 0.74+
      reactNative: { textStreaming: true },
    })

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`)
    }
    if (!response.body) throw new Error('No response body')

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() ?? ''
      for (const line of lines) {
        if (line.startsWith('data: ')) {
          const raw = line.slice(6).trim()
          if (!raw || raw === '[DONE]') continue
          try {
            const event = JSON.parse(raw) as SSEEvent
            onEvent(event)
          } catch {
            // ignore malformed chunk
          }
        }
      }
    }
  },
}
