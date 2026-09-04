import type { Capability } from './navigation/capabilities'

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

export interface UIModuleManifest {
  pack_key: string
  ui_key: string
  version: string
  module_key?: string | null
  route_keys: string[]
  required_capabilities: string[]
  navigation: Array<{ to: string; label: string }>
  bundle_key?: string | null
  default_home?: string | null
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
  answer_ready: boolean
  published_revision: number | null
  published_chunk_count: number
  readiness_reasons: string[]
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
  organization?: {
    id: string | null
    name: string
    department_id: string | null
    department_name: string | null
    environment: 'production' | 'demo'
    environment_label: string
  }
  capabilities: string[]
  default_home: string
  primary_navigation?: Array<{
    to: string
    label: string
    capability?: Capability
    module?: string
    end?: boolean
  }>
  packs: Record<string, {
    enabled?: boolean
    available?: boolean
    state?: string
    label?: string
    message?: string
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
  demo_mode?: boolean
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
  ui_modules?: UIModuleManifest[]
  pack_permissions?: string[]
  capability_catalog?: Array<{
    key: string
    pack_key?: string
    kind: 'platform_capability' | 'domain_module'
    deployment_status: string
    entitlement_status: string
    runtime_status: string
    user_permission_status: string
  }>
}

// ─── Video knowledge sources ───
export interface VideoIngestionJob {
  id: string
  status: string
  phase: string | null
  quality_state: string | null
  readiness: Record<string, unknown>
  error: Record<string, unknown>
}

export interface VideoEvidenceSpan {
  id: string
  locator_kind: string
  start_ms: number | null
  end_ms: number | null
  frame_index: number | null
  speaker: string | null
  deep_link: string
}

export interface VideoArtifactReview {
  decision: 'approved' | 'rejected'
  notes: string | null
  reviewer_id: string
  created_at: string
  resolution?: Record<string, unknown>
}

export interface VideoArtifact {
  id: string
  kind: 'audio_event' | 'transcript_segment' | 'keyframe' | 'ocr_region' | 'procedure_candidate' | string
  quality_state: string
  confidence: number | null
  content: string | Record<string, unknown> | null
  metadata: Record<string, unknown>
  content_url: string | null
  evidence: VideoEvidenceSpan[]
  review: VideoArtifactReview | null
}

export interface VideoAsset {
  id: string
  title: string
  status: string
  created_at: string
  revision_id: string
  duration_ms: number | null
  media_type: string
  probe: Record<string, unknown>
  job: VideoIngestionJob | null
  dispatched?: boolean
}

export interface VideoAssetDetail extends VideoAsset {
  content_url: string
  proxy_url: string | null
  artifacts: VideoArtifact[]
  media_analysis?: MediaAnalysisSnapshot
}

export interface MediaAnalysisRunSummary {
  id: string
  status: string
  profile: string
  pipeline_version: string
  provider_manifest: Record<string, unknown>
  checkpoint: Record<string, unknown>
  quality_metrics: Record<string, unknown>
  cost_metrics: Record<string, unknown>
  failure: Record<string, unknown>
  created_at: string
  completed_at: string | null
}

export interface MediaAnalysisArtifact {
  id: string
  kind: string
  quality_state: string
  confidence: number | null
  content: string | Record<string, unknown> | null
  metadata: Record<string, unknown>
  evidence: Array<{ id: string; kind: string; start_ms: number | null; end_ms: number | null; speaker?: string | null; frame_index?: number | null }>
}

export interface MediaAnalysisSnapshot {
  schema_version: string
  runs: MediaAnalysisRunSummary[]
  artifacts: MediaAnalysisArtifact[]
  entity_links: Array<{ id: string; entity_id: string; link_kind: string; status: string; confidence: number | null; evidence: Record<string, unknown>[] }>
  partial_use_allowed: boolean
  unavailable_reason?: string
}

// ─── Unified Knowledge Assets ───
export interface KnowledgeAssetRevision {
  id: string
  revision: number
  media_type: string
  content_hash: string
  byte_size: number | null
  duration_ms: number | null
  ingestion_status: string
  created_at: string
}

export type InputCapabilityStatus = 'available' | 'degraded' | 'not_applicable' | 'failed'

export interface InputCapabilityResult {
  status: InputCapabilityStatus
  reason_code: string | null
  artifact_count: number
  provider: {
    name: string | null
    version: string | null
    model: string | null
    confidence_provider_supplied: boolean | null
    calibration_version: string | null
  } | null
  details: Record<string, unknown>
}

export interface InputJobReadiness extends Record<string, unknown> {
  capability_results_schema?: string
  capability_results?: Record<string, InputCapabilityResult>
  runtime_identity?: Record<string, unknown>
}

export interface KnowledgeAssetJob {
  id: string
  status: string
  phase: string
  quality_state: string
  adapter_key: string
  adapter_version: string
  requested_capabilities: string[]
  readiness: InputJobReadiness
  error: Record<string, unknown>
  correlation_id?: string
  attempt: number
  created_at: string
  completed_at: string | null
}

export interface KnowledgeAsset {
  id: string
  asset_kind: string
  title: string
  source_system: string
  data_classification: string
  status: string
  current_revision: number
  created_at: string
  updated_at: string | null
  tombstoned_at: string | null
  metadata: Record<string, unknown>
  revision: KnowledgeAssetRevision | null
  revisions?: KnowledgeAssetRevision[]
  job: KnowledgeAssetJob | null
  /** Canonical, serving-mode-aware status exposed by the asset API. */
  answer_ready?: boolean
  lifecycle_status?: 'received' | 'processing' | 'awaiting_review' | 'answer_ready' | 'needs_attention'
  pending_review_count?: number
  readiness_reasons?: string[]
  preview_url?: string | null
  media_analysis?: MediaAnalysisSnapshot
  deduplicated?: boolean
}

export interface KnowledgeAssetEvent {
  id: string
  job_id: string
  sequence: number
  from_status: string | null
  to_status: string
  phase: string
  details: Record<string, unknown>
  created_at: string
}

export interface InputFormatCapability {
  extension: string
  media_type: string
  parser_kind: string
  asset_kind: string
  capabilities: string[]
  evidence_state: 'internally_verified' | 'environment_validation_pending' | 'transitional' | 'not_implemented'
  ui_default: boolean
  quality_gate?: {
    key: string
    min_content_accuracy: number
    min_locator_coverage: number
    min_parse_success: number
    review_below_confidence: number
    sample_rate: number
    max_provider_regression: number
  }
  max_bytes: number
  max_duration_seconds: number | null
  processing_status: 'configured' | 'disabled' | 'degraded'
  degradation_reasons: string[]
}

export interface InputCapabilityContract {
  contract_version: string
  registry_sha256: string
  tenant_id: string
  policy: {
    accepted_modes: string[]
    data_classifications: string[]
    core_capture: boolean
    capture_modes: string[]
    capture_policy_path: string
    generic_resumable_upload: boolean
    resumable_part_size: number
    resumable_min_part_size: number
    resumable_max_part_size: number
    resumable_max_parts: number
    resumable_session_ttl_hours: number
    video_allowed_codecs: string[]
  }
  formats: InputFormatCapability[]
  providers: Array<{ key: string; status: string; runtime_verified: boolean; detail: string }>
  quota: {
    max_documents: number | null
    current_documents: number
    remaining_documents: number | null
    max_storage_bytes: number | null
    current_storage_bytes: number
    remaining_storage_bytes: number | null
    warnings: string[]
  } | null
}

export interface ReviewEvidenceLocator {
  id: string
  kind: 'document' | 'table' | 'image' | 'audio' | 'video' | 'external_record'
  page?: number | null
  section?: string | null
  paragraph_index?: number | null
  slide_number?: number | null
  bbox?: number[] | Record<string, number> | null
  coordinate_space?: string | null
  locator_fallback?: boolean
  worksheet?: string | null
  table_name?: string | null
  row_number?: number | null
  column_name?: string | null
  cell_range?: string | null
  start_ms?: number | null
  end_ms?: number | null
  speaker?: string | null
  frame_index?: number | null
  source_system?: string | null
  source_record_id?: string | null
  field_path?: string | null
  deep_link: string
}

export interface KnowledgeReviewItem {
  id: string
  source_group_key?: string
  source_asset_id?: string | null
  provider: string
  source_type: string
  asset_kind: string
  title: string
  subtitle: string
  status: string
  risk_level: 'low' | 'medium' | 'high'
  confidence: number | null
  created_at: string
  due_at: string | null
  department_ids: string[]
  policy_key: string
  policy_version: string | number
  assignee: string | null
  batch_eligible: boolean
  blocked_reasons: string[]
  proposal: Record<string, unknown>
  evidence: ReviewEvidenceLocator[]
  publication: {
    unit_key: string | null
    next_revision: number
    effective_from: string
    acl: Record<string, unknown>
    rollback: string
    sop_precedence: boolean
  }
}

export interface KnowledgeReviewSourceGroup {
  key: string
  source_asset_id: string | null
  title: string
  asset_kind: string
  item_count: number
  high_risk_count: number
  low_confidence_count: number
  blocked_reasons: string[]
  item_ids: string[]
  source_confirmable_count: number
  exception_count: number
  source_approval_ready: boolean
}

export interface KnowledgeReviewInbox {
  items: KnowledgeReviewItem[]
  groups?: KnowledgeReviewSourceGroup[]
  source_total?: number
  total: number
  limit: number
  offset: number
  facets: {
    source_types: string[]
    policy_keys: string[]
    assignees: string[]
  }
}

// ─── Chat ───
export interface ChatRequest {
  question: string
  conversation_id?: string | null
  top_k?: number
  knowledge_mode?: 'spec_sop' | null
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
  decision?: KnowledgeDecision
}

// ─── T7-1 SSE Streaming ───
export type SSEEventType = 'status' | 'sources' | 'decision' | 'token' | 'suggestions' | 'done' | 'error' | 'retrieval'

export interface SSEEvent {
  type: SSEEventType
  content?: string
  sources?: ChatSource[]
  retrieval?: RetrievalInfo
  decision?: KnowledgeDecision
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
  citation_id?: string | null
  canonical_resource_type?: string | null
  canonical_resource_id?: string | null
  source_asset_id?: string | null
  evidence_url?: string | null
  document_revision?: string | number | null
  provider?: string | null
  updated_at?: string | null
  score?: number
  chunk_index?: number
  page?: number | null
  section?: string | null
  worksheet?: string | null
  row_number?: number | null
  field_name?: string | null
  table_name?: string | null
  cell_range?: string | null
  transcript_start_ms?: number | null
  transcript_end_ms?: number | null
  speaker?: string | null
  frame_index?: number | null
  keyframe?: number | null
  bbox?: { x: number; y: number; w: number; h: number } | number[] | null
  section_path?: string[] | null
  applicable_scope?: string | null
  effective_at?: string | null
  accessible?: boolean
}

export interface KnowledgeDecision {
  decision_id: string
  evidence_state: 'complete' | 'partial' | 'insufficient_context' | 'absent' | 'conflict'
  execution_status: string
  answer_type: string
  direct_conclusion: string
  applicability_scope: Record<string, unknown>
  answered_items: string[]
  missing_items: Array<{ requirement_id?: string; label?: string; reason_codes?: string[] }>
  conflicts: Array<{ requirement_id?: string; conflict_key?: string; evidence_ids?: string[] }>
  source_versions: Array<{ document_id?: string; document_revision?: string; locator?: Record<string, unknown> }>
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
