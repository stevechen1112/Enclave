import axios from 'axios'
import type {
  User, Document, ChatRequest, ChatResponse,
  Conversation, Message, UsageSummary, UsageByAction,
  UsageRecord, AuditLog,
  SSEEvent, FeedbackCreate, FeedbackResponse, SearchResult,
} from './types'

const api = axios.create({ baseURL: '/api/v1' })

// ─── Request interceptor: attach JWT ───
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// ─── Response interceptor: auto-logout on 401 ───
api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401) {
      localStorage.removeItem('token')
      window.location.href = '/login'
    }
    return Promise.reject(err)
  },
)

// ─── Auth ───
export const authApi = {
  login: async (email: string, password: string) => {
    const params = new URLSearchParams()
    params.append('username', email)
    params.append('password', password)
    const { data } = await api.post<{ access_token: string }>('/auth/login/access-token', params, {
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    })
    return data
  },
  me: () => api.get<User>('/users/me').then(r => r.data),
}

// ─── Documents ───
// Cache with TTL — re-fetches every 10 minutes so hot-deployed format changes are picked up
let _supportedFormatsCache: { promise: Promise<Set<string>>; ts: number } | null = null
const FORMATS_CACHE_TTL = 10 * 60 * 1000  // 10 minutes

export const docApi = {
  /**
   * Fetches the backend's authoritative list of supported upload extensions.
   * Result is cached with a 10-minute TTL.
   * Falls back to an empty Set on network error (caller should handle gracefully).
   */
  getSupportedFormats: (): Promise<Set<string>> => {
    const now = Date.now()
    if (_supportedFormatsCache && (now - _supportedFormatsCache.ts) < FORMATS_CACHE_TTL) {
      return _supportedFormatsCache.promise
    }
    const promise = api
      .get<{ extensions: string[] }>('/documents/supported-formats')
      .then(r => new Set<string>(r.data.extensions))
      .catch(() => {
        _supportedFormatsCache = null   // allow retry next time
        return new Set<string>()
      })
    _supportedFormatsCache = { promise, ts: now }
    return promise
  },

  list: (params?: { department_id?: string }) => api.get<Document[]>('/documents/', { params }).then(r => r.data),
  get: (id: string) => api.get<Document>(`/documents/${id}`).then(r => r.data),
  upload: (file: File, onProgress?: (pct: number) => void) => {
    const form = new FormData()
    // Strip webkitRelativePath prefix — only send the basename
    const basename = file.name.includes('/') ? file.name.split('/').pop()! : file.name
    form.append('file', file, basename)
    return api.post<Document>('/documents/upload', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
      onUploadProgress: (e) => {
        if (e.total && onProgress) onProgress(Math.round((e.loaded * 100) / e.total))
      },
    }).then(r => r.data)
  },
  delete: (id: string) => api.delete(`/documents/${id}`).then(r => r.data),
}

// ─── Chat ───
export const chatApi = {
  send: (req: ChatRequest) => api.post<ChatResponse>('/chat/chat', req).then(r => r.data),
  conversations: () => api.get<Conversation[]>('/chat/conversations').then(r => r.data),
  messages: (convId: string) => api.get<Message[]>(`/chat/conversations/${convId}/messages`).then(r => r.data),
  deleteConversation: (convId: string) => api.delete(`/chat/conversations/${convId}`).then(r => r.data),

  /** T7-1: SSE streaming chat */
  stream: (req: ChatRequest, onEvent: (event: SSEEvent) => void, signal?: AbortSignal): Promise<void> => {
    const token = localStorage.getItem('token')
    return fetch('/api/v1/chat/chat/stream', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify(req),
      signal,
    }).then(async (response) => {
      if (!response.ok) {
        const body = await response.json().catch(() => ({}))
        throw new Error(body.detail || `HTTP ${response.status}`)
      }
      const reader = response.body?.getReader()
      if (!reader) throw new Error('ReadableStream not supported')

      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })

        // 解析 SSE data: lines
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          const trimmed = line.trim()
          if (!trimmed.startsWith('data: ')) continue
          try {
            const raw = JSON.parse(trimmed.slice(6))
            // Map backend source fields to frontend ChatSource interface
            if (raw.type === 'sources' && Array.isArray(raw.sources)) {
              raw.sources = raw.sources.map((s: Record<string, unknown>) => ({
                ...s,
                title: s.title || s.filename || '',
                snippet: s.snippet || s.content || '',
              }))
            }
            const event: SSEEvent = raw
            onEvent(event)
          } catch {
            // skip malformed
          }
        }
      }
    })
  },

  /** T7-5: Feedback */
  submitFeedback: (data: FeedbackCreate) =>
    api.post<FeedbackResponse>('/chat/feedback', data).then(r => r.data),

  /** T7-11: Export conversation */
  exportConversation: (convId: string) =>
    api.get(`/chat/conversations/${convId}/export`, { responseType: 'blob' }).then(r => r.data),

  /** T7-13: Search conversations */
  searchConversations: (q: string) =>
    api.get<SearchResult[]>('/chat/conversations/search', { params: { q } }).then(r => r.data),

  /** T7-12: RAG quality dashboard */
  ragDashboard: (days = 30) =>
    api.get('/chat/dashboard/rag', { params: { days } }).then(r => r.data),
}

// ─── Audit ───
export const auditApi = {
  logs: (params?: Record<string, string>) => api.get<AuditLog[]>('/audit/logs', { params }).then(r => r.data),
  usageSummary: (params?: Record<string, string>) => api.get<UsageSummary>('/audit/usage/summary', { params }).then(r => r.data),
  usageByAction: (params?: Record<string, string>) => api.get<UsageByAction[]>('/audit/usage/by-action', { params }).then(r => r.data),
  usageRecords: (params?: Record<string, string>) => api.get<UsageRecord[]>('/audit/usage/records', { params }).then(r => r.data),
  exportLogs: (format: 'csv' | 'pdf', params?: Record<string, string>) =>
    api.get('/audit/logs/export', { params: { format, ...params }, responseType: 'blob' }).then(r => r.data),
  exportUsage: (format: 'csv' | 'pdf', params?: Record<string, string>) =>
    api.get('/audit/usage/export', { params: { format, ...params }, responseType: 'blob' }).then(r => r.data),
}

// ─── Admin / Organization Management ───
// P9-1/P9-2: Removed branding/subscription/quota-plan from companyApi
// Routes map to backend /admin/* prefix
export const companyApi = {
  dashboard: () => api.get('/admin/dashboard').then(r => r.data),
  users: (params?: Record<string, string>) => api.get('/admin/users', { params }).then(r => r.data),
  inviteUser: (data: { email: string; full_name?: string; role: string; password: string }) =>
    api.post('/admin/users/invite', data).then(r => r.data),
  updateUser: (id: string, data: Record<string, unknown>) =>
    api.put(`/admin/users/${id}`, data).then(r => r.data),
  deactivateUser: (id: string) => api.delete(`/admin/users/${id}`).then(r => r.data),
  systemHealth: () => api.get('/admin/system/health').then(r => r.data),
  usageSummary: () => api.get('/audit/usage/summary').then(r => r.data),
  usageByUser: () => api.get('/audit/usage/by-action').then(r => r.data),
}

// ─── Phase 13: KB Maintenance ───
export const kbApi = {
  // P13-3: Health dashboard
  health: (staleDays?: number) =>
    api.get('/kb-maintenance/kb/health', { params: staleDays ? { stale_days: staleDays } : {} }).then(r => r.data),

  // P13-1: Document versions
  listVersions: (docId: string) =>
    api.get(`/kb-maintenance/documents/${docId}/versions`).then(r => r.data),
  reupload: (docId: string, file: File, changeNote?: string) => {
    const form = new FormData()
    form.append('file', file)
    return api.post(`/kb-maintenance/documents/${docId}/reupload`, form, {
      params: changeNote ? { change_note: changeNote } : {},
      headers: { 'Content-Type': 'multipart/form-data' },
    }).then(r => r.data)
  },

  // P13-2: Version diff
  diff: (docId: string, oldVer: number, newVer: number) =>
    api.get(`/kb-maintenance/documents/${docId}/diff`, { params: { old_version: oldVer, new_version: newVer } }).then(r => r.data),

  // P13-4: Knowledge gaps
  listGaps: (status?: string) =>
    api.get('/kb-maintenance/kb/gaps', { params: status ? { status } : {} }).then(r => r.data),
  resolveGap: (gapId: string, data: { document_id?: string; resolve_note?: string }) =>
    api.post(`/kb-maintenance/kb/gaps/${gapId}/resolve`, data).then(r => r.data),
  scanGaps: (days?: number) =>
    api.post('/kb-maintenance/kb/gaps/scan', null, { params: days ? { days } : {} }).then(r => r.data),

  // P13-5: Taxonomy
  listCategories: (includeInactive?: boolean) =>
    api.get('/kb-maintenance/kb/categories', { params: includeInactive ? { include_inactive: true } : {} }).then(r => r.data),
  createCategory: (data: { name: string; description?: string; parent_id?: string; sort_order?: number }) =>
    api.post('/kb-maintenance/kb/categories', data).then(r => r.data),
  updateCategory: (catId: string, data: Record<string, unknown>) =>
    api.put(`/kb-maintenance/kb/categories/${catId}`, data).then(r => r.data),
  deleteCategory: (catId: string) =>
    api.delete(`/kb-maintenance/kb/categories/${catId}`).then(r => r.data),
  categoryRevisions: (catId: string) =>
    api.get(`/kb-maintenance/kb/categories/${catId}/revisions`).then(r => r.data),
  rollbackCategory: (catId: string, revision: number) =>
    api.post(`/kb-maintenance/kb/categories/${catId}/rollback/${revision}`).then(r => r.data),

  // P13-6: Integrity check
  triggerIntegrityCheck: () =>
    api.post('/kb-maintenance/kb/integrity/scan').then(r => r.data),
  listIntegrityReports: (limit?: number) =>
    api.get('/kb-maintenance/kb/integrity/reports', { params: limit ? { limit } : {} }).then(r => r.data),

  // P13-7: Backup & restore
  createBackup: (backupType?: string) =>
    api.post('/kb-maintenance/kb/backups', { backup_type: backupType || 'full' }).then(r => r.data),
  listBackups: (limit?: number) =>
    api.get('/kb-maintenance/kb/backups', { params: limit ? { limit } : {} }).then(r => r.data),
  restore: (backupId: string) =>
    api.post('/kb-maintenance/kb/backups/restore', { backup_id: backupId }).then(r => r.data),

  // P13-8: Usage report
  usageReport: (days?: number) =>
    api.get('/kb-maintenance/kb/usage-report', { params: days ? { days } : {} }).then(r => r.data),
}

// ─── Phase 10: Agent ───
export const agentApi = {
  scanPreview: (subfolders: Array<{ path: string; name: string; files: string[]; content_samples?: string[] }>) =>
    api.post<{
      subfolders: Array<{ path: string; name: string; file_count: number; summary: string; has_content_samples: boolean }>
    }>('/agent/scan-preview', { subfolders }).then(r => r.data),
}

export default api
