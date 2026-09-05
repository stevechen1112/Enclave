import axios from 'axios'
import type {
  User, Document, ChatRequest, ChatResponse,
  Conversation, Message, UsageSummary, UsageByAction,
  UsageRecord, AuditLog, ExperienceBootstrap,
  SSEEvent, FeedbackCreate, FeedbackResponse, SearchResult,
  VideoAsset, VideoAssetDetail,
  KnowledgeAsset, KnowledgeAssetEvent,
  InputCapabilityContract,
  KnowledgeReviewInbox,
} from './types'
import { parseApiError } from './lib/apiError'

const api = axios.create({ baseURL: '/api/v1' })

export type DemoPersona = 'sales' | 'field' | 'master' | 'newcomer' | 'viewer' | 'admin'

export interface ReleaseMetadata {
  schema_version: number
  release_id: string
  source_commit: string
  source_dirty: string
  build_time: string
  deployment_manifest_id: string
  schema_head: string
  route_contract_hash: string
  identifiable?: boolean
  database_schema_heads?: string[]
  schema_matches?: boolean
  canonical_routes?: string[]
}

export interface InputPilotSummary {
  id: string
  name: string
  status: 'draft' | 'ready' | 'running' | 'hold' | 'accepted' | 'rejected'
  evidence_mode: 'live' | 'synthetic'
  journeys: Array<{ key: string; [key: string]: unknown }>
  started_at?: string | null
  planned_end_at?: string | null
  created_at: string
}

export interface InputPilotGate {
  status: 'PASS' | 'HOLD'
  observation_days: number
  journeys: Record<string, Record<string, number | null>>
  incident_count: number
  passed_audits: string[]
  signed_acceptance: boolean
  errors: string[]
}

export interface InputPilotEvidence {
  metric_rows: number
  latest_metrics: Array<{
    id: string
    metric_date: string
    journey_key: string
    total_attempts: number
    successful_attempts: number
    retry_count: number
    manual_correction_count: number
    processing_p95_ms: number
    retrieval_checks: number
    cited_retrievals: number
    friction_count: number
    source_evidence_sha256: string
  }>
  incidents: Array<{
    id: string
    severity: 'low' | 'medium' | 'high' | 'critical'
    category: string
    near_miss: boolean
    status: 'open' | 'mitigated' | 'resolved'
    data_loss: boolean
    unauthorized_access: boolean
    false_completion: boolean
    summary: string
    occurred_at: string
    resolved_at?: string | null
  }>
  audits: Array<{
    id: string
    audit_type: 'quality' | 'security' | 'permission'
    status: 'pending' | 'pass' | 'fail'
    sample_size: number
    findings: Array<Record<string, unknown>>
    evidence_sha256: string
    audited_at: string
  }>
  retrospective: { ref: string; sha256: string } | null
  acceptance: {
    decision: 'accepted' | 'rejected'
    signer_name: string
    signer_role: string
    signed_document_ref: string
    signed_document_sha256: string
    signed_at: string
  } | null
}

// ─── Request interceptor: attach JWT ───
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// ─── Response interceptor: 401 logout + attach normalized ApiErrorInfo ───
api.interceptors.response.use(
  (res) => res,
  (err) => {
    const isLoginRequest = String(err.config?.url || '').startsWith('/auth/login/')
    if (err.response?.status === 401 && !isLoginRequest) {
      localStorage.removeItem('token')
      window.location.href = '/login'
    }
    err.apiError = parseApiError(err)
    return Promise.reject(err)
  },
)

export { parseApiError, formatErrorWithTrace } from './lib/apiError'
export type { ApiErrorInfo } from './lib/apiError'

// ─── Auth ───
export const authApi = {
  loginOptions: () => api.get<{ password_enabled: boolean; demo_enabled: boolean }>('/auth/login/options').then(r => r.data),
  login: async (email: string, password: string) => {
    const params = new URLSearchParams()
    params.append('username', email)
    params.append('password', password)
    const { data } = await api.post<{ access_token: string }>('/auth/login/access-token', params, {
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    })
    return data
  },
  demoLogin: async (persona: DemoPersona) => {
    const { data } = await api.post<{
      access_token: string
      token_type: string
      persona: DemoPersona
      read_only: boolean
      expires_in: number
    }>('/auth/login/demo', { persona })
    return data
  },
  me: () => api.get<User>('/users/me').then(r => r.data),
  experience: () => api.get<ExperienceBootstrap>('/experience/bootstrap').then(r => r.data),
  changePassword: (currentPassword: string, newPassword: string) =>
    api.post('/auth/change-password', {
      current_password: currentPassword,
      new_password: newPassword,
    }),
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

  list: (params?: { department_id?: string; skip?: number; limit?: number }) =>
    api.get<Document[]>('/documents/', { params }).then(r => r.data),
  /** Paginate past default limit=100 so list UIs see full tenant corpus. */
  listAll: async (params?: { department_id?: string; pageSize?: number; maxPages?: number }) => {
    const pageSize = params?.pageSize ?? 200
    const maxPages = params?.maxPages ?? 50
    const all: Document[] = []
    for (let page = 0; page < maxPages; page += 1) {
      const batch = await api.get<Document[]>('/documents/', {
        params: {
          department_id: params?.department_id,
          skip: page * pageSize,
          limit: pageSize,
        },
      }).then(r => r.data)
      all.push(...batch)
      if (batch.length < pageSize) break
    }
    return all
  },
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

// ─── Video knowledge sources ───
export const videoApi = {
  list: () => api.get<VideoAsset[]>('/media/videos').then(r => r.data),
  get: (assetId: string) =>
    api.get<VideoAssetDetail>(`/media/videos/${assetId}`).then(r => r.data),
  upload: (
    file: File,
    metadata?: { title?: string; equipmentIds?: string; applicableRoles?: string },
    onProgress?: (pct: number) => void,
  ) => {
    const form = new FormData()
    form.append('file', file, file.name.split(/[\\/]/).pop() || file.name)
    if (metadata?.title?.trim()) form.append('title', metadata.title.trim())
    if (metadata?.equipmentIds?.trim()) form.append('equipment_ids', metadata.equipmentIds.trim())
    if (metadata?.applicableRoles?.trim()) form.append('applicable_roles', metadata.applicableRoles.trim())
    return api.post<VideoAsset>('/media/videos', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
      onUploadProgress: (event) => {
        if (event.total && onProgress) {
          onProgress(Math.round((event.loaded * 100) / event.total))
        }
      },
    }).then(r => r.data)
  },
  review: (
    artifactId: string,
    decision: 'approved' | 'rejected',
    notes?: string,
    governance?: { conflictResolutions?: Record<string, string>; acknowledgeHighRisk?: boolean },
  ) => api.post(`/media/video-artifacts/${artifactId}/review`, {
    decision,
    notes,
    conflict_resolutions: governance?.conflictResolutions || {},
    acknowledge_high_risk: governance?.acknowledgeHighRisk || false,
  }).then(r => r.data),
}

// ─── Unified knowledge intake and Asset Library ───
export const knowledgeAssetApi = {
  capabilities: () =>
    api.get<InputCapabilityContract>('/knowledge/input-capabilities').then(r => r.data),
  departments: () =>
    api.get<Array<{ id: string; name: string }>>('/departments/options').then(r => r.data),
  list: (params?: { kind?: string; source_system?: string; processing_status?: string; data_classification?: string; department_id?: string; updated_after?: string; publication_status?: string }) =>
    api.get<KnowledgeAsset[]>('/knowledge/assets', { params }).then(r => r.data),
  get: (assetId: string) =>
    api.get<KnowledgeAsset>(`/knowledge/assets/${assetId}`).then(r => r.data),
  events: (assetId: string) =>
    api.get<KnowledgeAssetEvent[]>(`/knowledge/assets/${assetId}/events`).then(r => r.data),
  create: (
    input: {
      file?: File
      title?: string
      sourceUrl?: string
      sourceSystem?: string
      sourceRecordId?: string
      dataClassification?: string
      departmentId?: string
      idempotencyKey?: string
      contextMetadata?: Record<string, string | string[]>
    },
    options?: { onProgress?: (pct: number) => void; signal?: AbortSignal },
  ) => {
    const form = new FormData()
    if (input.file) form.append('file', input.file, input.file.name.split(/[\\/]/).pop() || input.file.name)
    if (input.title?.trim()) form.append('title', input.title.trim())
    if (input.sourceUrl?.trim()) form.append('source_url', input.sourceUrl.trim())
    if (input.sourceSystem?.trim()) form.append('source_system', input.sourceSystem.trim())
    if (input.sourceRecordId?.trim()) form.append('source_record_id', input.sourceRecordId.trim())
    if (input.departmentId) form.append('department_id', input.departmentId)
    if (input.idempotencyKey) form.append('idempotency_key', input.idempotencyKey)
    if (input.contextMetadata && Object.keys(input.contextMetadata).length) {
      form.append('context_metadata', JSON.stringify(input.contextMetadata))
    }
    form.append('data_classification', input.dataClassification || 'internal')
    return api.post<KnowledgeAsset>('/knowledge/assets', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
      signal: options?.signal,
      onUploadProgress: event => {
        if (event.total && options?.onProgress) options.onProgress(Math.round((event.loaded * 100) / event.total))
      },
    }).then(r => r.data)
  },
  retry: (assetId: string) => api.post(`/knowledge/assets/${assetId}/retry`).then(r => r.data),
  tombstone: (assetId: string) => api.delete(`/knowledge/assets/${assetId}`).then(r => r.data),
}

export interface UploadSessionState {
  id: string
  status: string
  filename: string
  media_type: string
  byte_size: number
  part_size: number
  total_parts: number
  received_bytes: number
  received_parts: number
  acknowledged_parts: Array<{ part_number: number; byte_size: number; sha256: string }>
  expires_at: string
  asset_id?: string | null
  content_sha256?: string | null
}

export const uploadSessionApi = {
  create: (input: {
    filename: string
    mediaType: string
    byteSize: number
    partSize?: number
    idempotencyKey: string
    title?: string
    departmentId?: string
    dataClassification?: string
    contextMetadata?: Record<string, string | string[]>
  }) => api.post<UploadSessionState>('/knowledge/upload-sessions', {
    filename: input.filename.split(/[\\/]/).pop() || input.filename,
    media_type: input.mediaType || 'application/octet-stream',
    byte_size: input.byteSize,
    part_size: input.partSize,
    idempotency_key: input.idempotencyKey,
    title: input.title?.trim() || undefined,
    department_id: input.departmentId,
    data_classification: input.dataClassification || 'internal',
    context_metadata: input.contextMetadata || {},
  }).then(response => response.data),
  get: (sessionId: string) =>
    api.get<UploadSessionState>(`/knowledge/upload-sessions/${encodeURIComponent(sessionId)}`).then(response => response.data),
  putPart: (
    sessionId: string,
    partNumber: number,
    part: Blob,
    sha256: string,
    options?: { signal?: AbortSignal },
  ) => api.put<UploadSessionState>(`/knowledge/upload-sessions/${encodeURIComponent(sessionId)}/parts/${partNumber}`, part, {
    headers: { 'Content-Type': 'application/octet-stream', 'X-Part-SHA256': sha256 },
    signal: options?.signal,
  }).then(response => response.data),
  commit: (sessionId: string) =>
    api.post<KnowledgeAsset>(`/knowledge/upload-sessions/${encodeURIComponent(sessionId)}/commit`, {}).then(response => response.data),
  abort: (sessionId: string) =>
    api.delete<UploadSessionState>(`/knowledge/upload-sessions/${encodeURIComponent(sessionId)}`).then(response => response.data),
}

export const knowledgeReviewApi = {
  list: (params?: { risk_level?: string; confidence_max?: number; overdue?: boolean; source_type?: string; department_id?: string; policy_key?: string; assignee?: string }) =>
    api.get<KnowledgeReviewInbox>('/knowledge/review-items', { params }).then(r => r.data),
  decide: (itemId: string, input: {
    decision: 'approved' | 'rejected'
    notes?: string
    acknowledgeHighRisk?: boolean
    acknowledgeLowConfidence?: boolean
    conflictResolutions?: Record<string, string>
    idempotencyKey?: string
  }) => api.post(`/knowledge/review-items/${encodeURIComponent(itemId)}/decision`, {
    decision: input.decision,
    notes: input.notes,
    acknowledge_high_risk: input.acknowledgeHighRisk || false,
    acknowledge_low_confidence: input.acknowledgeLowConfidence || false,
    conflict_resolutions: input.conflictResolutions || {},
    idempotency_key: input.idempotencyKey || crypto.randomUUID(),
  }).then(r => r.data),
  batchApprove: (itemIds: string[], notes?: string) =>
    api.post('/knowledge/review-items/batch/approve', { item_ids: itemIds, notes }).then(r => r.data),
  decideSource: (sourceAssetId: string, input: {
    decision?: 'approved' | 'rejected'
    notes?: string
    acknowledgeLowConfidence?: boolean
    idempotencyKey?: string
  }) => api.post(`/knowledge/review-items/source/${encodeURIComponent(sourceAssetId)}/decision`, {
    decision: input.decision || 'approved',
    notes: input.notes,
    acknowledge_low_confidence: input.acknowledgeLowConfidence || false,
    idempotency_key: input.idempotencyKey || crypto.randomUUID(),
  }).then(r => r.data),
}

// ─── Chat ───
export const chatApi = {
  send: (req: ChatRequest) => api.post<ChatResponse>('/chat/chat', req).then(r => r.data),
  conversations: () => api.get<Conversation[]>('/chat/conversations').then(r => r.data),
  messages: (convId: string) =>
    api.get<Message[]>(`/chat/conversations/${convId}/messages`).then(r =>
      r.data.map(m => ({
        ...m,
        sources: Array.isArray(m.sources)
          ? m.sources.map((s) => ({
              ...s,
              title: s.title || (s as { filename?: string }).filename || '',
              snippet: s.snippet || (s as { content?: string }).content || '',
            }))
          : m.sources,
      })),
    ),
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

// ─── Tenant organization management ───
// These routes deliberately use /company, not platform-only /admin.  Tenant
// Owners and Admins must be able to manage their own workspace without access
// to cross-tenant platform administration.
export const companyApi = {
  dashboard: () => api.get('/company/dashboard').then(r => r.data),
  users: (params?: Record<string, string>) => api.get('/company/users', { params }).then(r => r.data),
  inviteUser: (data: { email: string; full_name?: string; role: string; password: string }) =>
    api.post('/company/users/invite', data).then(r => r.data),
  updateUser: (id: string, data: Record<string, unknown>) =>
    api.put(`/company/users/${id}`, data).then(r => r.data),
  deactivateUser: (id: string) => api.delete(`/company/users/${id}`).then(r => r.data),
  systemHealth: () => api.get('/admin/system/health').then(r => r.data),
  providerHealth: () => api.get('/company/system/provider-health').then(r => r.data),
  probeProviderHealth: () => api.post('/company/system/provider-health/probe').then(r => r.data),
  usageSummary: () => api.get('/audit/usage/summary').then(r => r.data),
  usageByUser: () => api.get('/audit/usage/by-action').then(r => r.data),
  getDeploymentMode: () => api.get('/company/deployment-mode').then(r => r.data),
  setDeploymentMode: (mode: 'gpu' | 'nogpu') => api.put('/company/deployment-mode', { mode }).then(r => r.data),
}

export const operationsApi = {
  release: () => api.get<ReleaseMetadata>('/operations/release').then(r => r.data),
  frontendRelease: () => fetch('/release.json', { cache: 'no-store' }).then(async response => {
    if (!response.ok) throw new Error(`release metadata unavailable: ${response.status}`)
    return response.json() as Promise<ReleaseMetadata>
  }),
  listInputPilots: () => api.get<InputPilotSummary[]>('/operations/input/pilots').then(r => r.data),
  createInputPilot: (data: Record<string, unknown>) =>
    api.post<{ id: string; status: string }>('/operations/input/pilots', data).then(r => r.data),
  startInputPilot: (pilotId: string) =>
    api.post(`/operations/input/pilots/${pilotId}/start`).then(r => r.data),
  inputPilotGate: (pilotId: string) =>
    api.get<InputPilotGate>(`/operations/input/pilots/${pilotId}/gate`).then(r => r.data),
  inputPilotEvidence: (pilotId: string) =>
    api.get<InputPilotEvidence>(`/operations/input/pilots/${pilotId}/evidence`).then(r => r.data),
  recordInputPilotMetric: (pilotId: string, data: Record<string, unknown>) =>
    api.post(`/operations/input/pilots/${pilotId}/daily-metrics`, data).then(r => r.data),
  recordInputPilotIncident: (pilotId: string, data: Record<string, unknown>) =>
    api.post(`/operations/input/pilots/${pilotId}/incidents`, data).then(r => r.data),
  resolveInputPilotIncident: (pilotId: string, incidentId: string, data: Record<string, unknown>) =>
    api.post(`/operations/input/pilots/${pilotId}/incidents/${incidentId}/resolve`, data).then(r => r.data),
  recordInputPilotAudit: (pilotId: string, data: Record<string, unknown>) =>
    api.post(`/operations/input/pilots/${pilotId}/audits`, data).then(r => r.data),
  recordInputPilotRetrospective: (pilotId: string, data: Record<string, unknown>) =>
    api.post(`/operations/input/pilots/${pilotId}/retrospective`, data).then(r => r.data),
  recordInputPilotAcceptance: (pilotId: string, data: Record<string, unknown>) =>
    api.post<InputPilotGate>(`/operations/input/pilots/${pilotId}/acceptance`, data).then(r => r.data),
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

export interface KnowledgeControlOverview {
  readiness: { ready: number; partial: number; needs_attention: number }
  profiled_documents: number
  knowledge_bases: Array<{
    id: string
    name: string
    active_revision: number
    revisions: Array<{ id: string; revision: number; status: string; manifest_hash: string | null
      passed_gates: string[]; required_gate_count: number; promotion_ready: boolean }>
  }>
}

export const knowledgeControlApi = {
  overview: () => api.get<KnowledgeControlOverview>('/knowledge-control/overview').then(r => r.data),
  documents: () => api.get<Array<{
    document_id: string; revision: number; format: string; support_level: string
    profile_answer_ready: boolean; answer_ready: boolean; published_revision: number | null
    readiness_reasons: string[]; capabilities: Record<string, boolean>; warnings: Array<{ code: string; action: string }>
  }>>('/knowledge-control/documents').then(r => r.data),
  createCandidate: () => api.post('/knowledge-control/revisions/candidate', { versions: {} }).then(r => r.data),
  transition: (id: string, target: 'shadow' | 'rejected') =>
    api.post(`/knowledge-control/revisions/${id}/transition`, { target }).then(r => r.data),
  promote: (id: string, expectedManifestHash: string) => api.post(`/knowledge-control/revisions/${id}/promote`, {
    expected_manifest_hash: expectedManifestHash,
  }).then(r => r.data),
  rollback: (id: string) => api.post(`/knowledge-control/revisions/${id}/rollback`).then(r => r.data),
  feedback: (status?: string) => api.get<Array<{
    id: string; message_id: string; rating: number; category: string | null; comment: string | null
    status: string; owner_id: string; processing_history: Array<Record<string, string>>; created_at: string
  }>>('/knowledge-control/feedback', { params: status ? { status } : {} }).then(r => r.data),
  processFeedback: (id: string, status: 'open' | 'acknowledged' | 'resolved', note: string) =>
    api.patch(`/knowledge-control/feedback/${id}`, { status, note }).then(r => r.data),
  freshness: () => api.get<Array<{
    id: string; document_id: string; state: string; reasons: string[]; owner_id: string | null
    review_due_at: string | null; last_reviewed_at: string | null; upstream_sync_at: string | null
  }>>('/knowledge-control/freshness').then(r => r.data),
  scanFreshness: () => api.post('/knowledge-control/freshness/scan').then(r => r.data),
}

export interface KnowledgeDecisionDiff {
  record_id: string
  captured_at: string
  legacy_decision: string
  new_evidence_state: string
  new_response_action: string
  execution_status: string
  decision_hash: string
  transition: string
  false_accept_candidate: boolean
  false_reject_candidate: boolean
  reason_codes: string[]
  source_refs: Array<{ document_id: string; document_revision?: string; unit_id?: string }>
}

export const knowledgeDecisionApi = {
  listDiffs: (limit = 100) => api.get<{
    schema_version: string
    read_only: boolean
    tenant_id: string
    items: KnowledgeDecisionDiff[]
  }>('/knowledge/decision-diffs', { params: { limit } }).then(r => r.data),
}

// ─── Phase 10: Agent ───
export const agentApi = {
  scanPreview: (subfolders: Array<{ path: string; name: string; files: string[]; content_samples?: string[] }>) =>
    api.post<{
      subfolders: Array<{ path: string; name: string; file_count: number; summary: string; has_content_samples: boolean }>
    }>('/agent/scan-preview', { subfolders }).then(r => r.data),
}

export default api
