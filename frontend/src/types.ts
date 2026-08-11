// ─── User ───
export interface User {
  id: string
  email: string
  full_name: string | null
  tenant_id: string
  role: string
  status: string | null
  is_superuser?: boolean
}

// ─── Tenant ───
export interface Tenant {
  id: string
  name: string
  plan: string | null
  status: string | null
  created_at: string | null
  updated_at: string | null
}

// ─── Document ───
export interface Document {
  id: string
  filename: string
  file_type: string | null
  status: string // uploading | parsing | embedding | completed | failed | pending_review
  tenant_id: string
  uploaded_by: string | null
  department_id: string | null
  file_size: number | null
  chunk_count: number | null
  error_message: string | null
  source_type?: string | null
  source_system?: string | null
  version?: number | null
  external_version?: string | null
  tombstoned_at?: string | null
  created_at: string | null
  updated_at: string | null
  /** P10-3: true 若文件於 7 天內新增或重新索引 */
  is_new: boolean
}

export interface ExperienceBootstrap {
  product: {
    name: string
    version_label: string
    maturity: string
    maturity_label: string
  }
  user: {
    id: string
    email: string
    full_name: string | null
    role: string
    tenant_id: string | null
    is_superuser: boolean
  }
  capabilities: string[]
  default_home: string
  packs: Record<string, {
    enabled?: boolean
    state?: string
    label?: string
    items?: string[]
    not_certified?: string[]
  }>
  inference: {
    mode: string
    main_provider: string
    data_stays_on_prem_for_inference: boolean
    message: string
  }
  features: Record<string, boolean>
  job_modules?: Array<Record<string, unknown>>
  workspace_entries?: Array<{
    module_key?: string
    key?: string
    label?: string
    path?: string
    description?: string
  }>
  job_role_assignments?: Array<{
    id: string
    job_role_id?: string
    role_key?: string | null
    name?: string | null
    is_primary?: boolean
    default_module_keys?: string[]
  }>
  active_job_role?: Record<string, unknown> | null
  default_job_home?: string
  interaction_capabilities?: Record<string, boolean>
}

// ─── Chat ───
export interface ChatRequest {
  question: string
  conversation_id?: string | null
  top_k?: number
  module_key?: string | null
  scene_context?: Record<string, string>
}

export interface ChatResponse {
  request_id: string
  question: string
  answer: string
  conversation_id: string
  message_id: string
  company_policy: Record<string, unknown> | null
  labor_law: Record<string, unknown> | null
}

export interface Conversation {
  id: string
  user_id: string
  tenant_id: string
  title: string | null
  created_at: string
}

export interface Message {
  id: string
  conversation_id: string
  role: 'user' | 'assistant'
  content: string
  created_at: string
  /** T7-5: 當前用戶對此訊息的回饋 */
  feedback?: 'up' | 'down' | null
  /** T7-4: 來源引用 */
  sources?: ChatSource[]
}

// ─── T7-1 SSE Streaming ───
export type SSEEventType = 'status' | 'sources' | 'token' | 'suggestions' | 'done' | 'error' | 'retrieval'

export interface SSEEvent {
  type: SSEEventType
  content?: string
  sources?: ChatSource[]
  retrieval?: RetrievalInfo
  items?: string[]
  message_id?: string
  conversation_id?: string
}

// ─── T7-4 Source reference ───
export interface ChatSource {
  type?: 'policy' | 'law'
  title: string          // display — mapped from backend `filename`
  snippet: string        // display — mapped from backend `content`
  document_id?: string
  document_revision?: string | number | null
  provider?: string | null
  updated_at?: string | null
  score?: number
  chunk_index?: number
  page?: number | null
  accessible?: boolean
}

export interface RetrievalInfo {
  mode: string
  degraded: boolean
  request_id?: string
  label?: string
}

// ─── T7-5 Feedback ───
export interface FeedbackCreate {
  message_id: string
  rating: 1 | 2            // 1=👎  2=👍
  category?: string | null
  comment?: string | null
}

export interface FeedbackResponse {
  id: string
  message_id: string
  rating: number
  created_at: string
}

// ─── T7-13 Search ───
export interface SearchResult {
  conversation_id: string
  conversation_title: string | null
  message_id: string
  role: string
  snippet: string
  created_at: string
}

// ─── Audit ───
export interface AuditLog {
  id: string
  tenant_id: string
  actor_user_id: string | null
  action: string
  resource_type: string | null
  resource_id: string | null
  details: Record<string, unknown> | null
  ip_address: string | null
  created_at: string
}

export interface UsageSummary {
  tenant_id: string
  total_input_tokens: number
  total_output_tokens: number
  total_pinecone_queries: number
  total_embedding_calls: number
  total_cost: number
  total_actions: number
}

export interface UsageByAction {
  action_type: string
  count: number
  total_input_tokens: number
  total_output_tokens: number
  total_cost: number
}

export interface UsageRecord {
  id: string
  tenant_id: string
  user_id: string | null
  action_type: string
  input_tokens: number
  output_tokens: number
  pinecone_queries: number
  embedding_calls: number
  estimated_cost_usd: number
  created_at: string
}
