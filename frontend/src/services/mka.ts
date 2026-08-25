/**
 * MKA（製造業知識助理）API client。
 *
 * 對應後端 endpoints：voice / interaction / scene / forms / approvals / knowhow。
 * 所有金額與版本號欄位原樣傳遞，樂觀鎖（record_version）與冪等鍵
 * （idempotency_key）由呼叫端產生並帶入。
 */
import api from '../api'

// ─── Types ───

export interface TranscribeResponse {
  text: string
  is_draft: boolean
  language: string
  confidence: number
  duration_seconds: number
  segments: Array<Record<string, unknown>>
  session_id: string
  detected_fields: Record<string, string>
  detected_field_details: Array<{
    type: string
    value: string
    raw_span?: string
    needs_confirm: boolean
  }>
  term_corrected: boolean
  scene_context: Partial<SceneContext>
  needs_confirmation: boolean
}

export interface InteractionSessionInfo {
  session_id: string
  module_key: string | null
  channel: string
  state: string
  transcript: string | null
  transcript_confirmed_at: string | null
  detected_fields: Record<string, string>
  risk_level: string
  scene_context: Record<string, unknown>
}

export interface KnowledgeCaptureSessionInfo {
  id: string
  title: string
  equipment_id: string | null
  interviewee: string | null
  interviewer: string | null
  status: 'recording' | 'uploading' | 'queued' | 'transcribing' | 'ready_for_review' | 'failed' | 'aborted'
  received_chunks: number
  expected_chunks: number | null
  total_duration_ms: number
  error: Record<string, unknown>
  transcript?: string | null
  transcript_metadata?: Record<string, unknown>
  created_at: string | null
  completed_at: string | null
}

export interface KnowledgeCaptureTranscript {
  session_id: string
  status: string
  transcript: string | null
  segments: Array<{
    id: string
    speaker: string | null
    start_ms: number
    end_ms: number
    text: string
    raw_text: string
  }>
}

export interface SceneContext {
  site_id: string
  plant_id: string
  line_id: string
  equipment_id: string
  equipment_model: string
  work_order_id: string
  product_id: string
  part_number: string
  customer_id: string
  document_version_scope: string
  resolved_from: string
  resolved_at: string
}

export interface FormFieldSpec {
  name: string
  label?: string
  type?: string
  required?: boolean
  options?: string[]
  [key: string]: unknown
}

export interface FormDefinition {
  id: string
  form_key: string
  name: string
  schema_version: string
  json_schema: { fields?: FormFieldSpec[] } & Record<string, unknown>
  ui_schema: Record<string, unknown>
  status: string
  fields?: FormFieldSpec[]
}

export interface FormInstance {
  id: string
  form_key?: string | null
  form_version: string
  module_key: string | null
  status: string
  record_version: number
  values: Record<string, unknown>
  values_json?: Record<string, unknown>
  provenance: Record<string, string>
  provenance_json?: Record<string, string>
  calculation_snapshot: Record<string, unknown>
  validation_result: { valid?: boolean; errors?: string[] } & Record<string, unknown>
  scene_context?: Record<string, unknown>
  immutable_snapshot?: Record<string, unknown>
  approval_request_id: string | null
  created_at: string | null
  updated_at: string | null
}

export interface ApprovalItem {
  id: string
  object_type: string
  object_id: string
  current_step: number
  record_version: number
  status: string
  submitted_by: string
  reviewers: string[]
  decision_log: Array<Record<string, unknown>>
  immutable_snapshot: Record<string, unknown>
  created_at: string | null
}

export interface KnowhowCard {
  id: string
  card_id: string
  title: string
  summary: string
  status: string
  authority_level: number
  risk_level: string
  applicable_roles: string[]
  equipment_ids: string[]
  steps: string[]
  cautions: string[]
  recommended_actions: string[]
  source_quotes: string[]
  version: number
  reviewed_at: string | null
  retired_at: string | null
}

export interface ExportArtifact {
  format: string
  filename: string
  exported_by: string
  exported_at: string
  storage_key?: string
  status?: string
}

// ─── Voice / Interaction ───

export const voiceApi = {
  transcribe: (
    file: Blob,
    filename: string,
    opts?: { module_key?: string; channel?: string; scene_context?: SceneContext | null },
  ) => {
    const form = new FormData()
    form.append('file', file, filename)
    return api
      .post<TranscribeResponse>('/voice/transcribe', form, {
        headers: { 'Content-Type': 'multipart/form-data' },
        params: {
          module_key: opts?.module_key,
          channel: opts?.channel ?? 'pwa',
          scene_context_json: opts?.scene_context
            ? JSON.stringify(opts.scene_context)
            : undefined,
        },
        timeout: 60000,
      })
      .then(r => r.data)
  },
  confirmTranscript: (sessionId: string, confirmedText: string, confirmedFields?: Record<string, string>) =>
    api
      .post<InteractionSessionInfo>(`/voice/sessions/${sessionId}/confirm`, {
        confirmed_text: confirmedText,
        confirmed_fields: confirmedFields ?? {},
      })
      .then(r => r.data),
  synthesize: (text: string, opts?: { voice?: string; speed?: number }) =>
    api
      .post('/voice/synthesize', { text, voice: opts?.voice, speed: opts?.speed }, { responseType: 'blob', timeout: 30000 })
      .then(r => r.data as Blob),
}

export const knowledgeCaptureApi = {
  create: (body: {
    title: string
    equipment_id?: string
    interviewee?: string
    interviewer?: string
    consent: boolean
    consent_version?: string
  }) => api.post<KnowledgeCaptureSessionInfo>('/knowledge-captures', body).then(r => r.data),
  uploadChunk: (
    sessionId: string,
    input: { sequence: number; offsetMs: number; durationMs: number; sha256: string; blob: Blob },
  ) => {
    const form = new FormData()
    const extension = input.blob.type.includes('ogg') ? 'ogg' : input.blob.type.includes('mpeg') ? 'mp3' : input.blob.type.includes('mp4') ? 'm4a' : 'webm'
    form.append('file', input.blob, `interview-${input.sequence}.${extension}`)
    form.append('sequence', String(input.sequence))
    form.append('offset_ms', String(input.offsetMs))
    form.append('duration_ms', String(input.durationMs))
    form.append('sha256', input.sha256)
    return api.post<{ id: string; sequence: number; duplicate: boolean; received_chunks: number }>(
      `/knowledge-captures/${sessionId}/chunks`,
      form,
      { headers: { 'Content-Type': 'multipart/form-data' }, timeout: 120000 },
    ).then(r => r.data)
  },
  complete: (sessionId: string, finalSequence: number, totalDurationMs: number) =>
    api.post<KnowledgeCaptureSessionInfo & { queue_enqueued: boolean }>(`/knowledge-captures/${sessionId}/complete`, {
      final_sequence: finalSequence,
      total_duration_ms: totalDurationMs,
    }).then(r => r.data),
  retry: (sessionId: string) => api.post<KnowledgeCaptureSessionInfo>(`/knowledge-captures/${sessionId}/retry`).then(r => r.data),
  get: (sessionId: string) => api.get<KnowledgeCaptureSessionInfo>(`/knowledge-captures/${sessionId}`).then(r => r.data),
  transcript: (sessionId: string) => api.get<KnowledgeCaptureTranscript>(`/knowledge-captures/${sessionId}/transcript`).then(r => r.data),
  correctSegment: (sessionId: string, segmentId: string, correctedText: string) =>
    api.patch<{ id: string; text: string }>(`/knowledge-captures/${sessionId}/transcript/segments/${segmentId}`, {
      corrected_text: correctedText,
    }).then(r => r.data),
}

// ─── Scene ───

export const sceneApi = {
  resolve: (req: { qr_token?: string; barcode?: string }) =>
    api.post<SceneContext>('/scene/resolve', req).then(r => r.data),
}

// ─── Forms ───

export const formsApi = {
  list: () =>
    api
      .get<{ forms: string[]; definitions: FormDefinition[] }>('/forms')
      .then(r => r.data),
  schema: (formKey: string) =>
    api.get<FormDefinition>(`/forms/${formKey}/schema`).then(r => r.data),
  createInstance: (
    formKey: string,
    values: Record<string, unknown>,
    provenance?: Record<string, string>,
    moduleKey?: string,
    sceneContext?: SceneContext | null,
  ) =>
    api
      .post<FormInstance>(`/forms/${formKey}/instances`, {
        values,
        provenance: provenance ?? {},
        module_key: moduleKey ?? null,
        scene_context: sceneContext ?? {},
      })
      .then(r => r.data),
  listInstances: (status?: string) =>
    api
      .get<FormInstance[]>('/forms/instances', { params: status ? { status } : undefined })
      .then(r => r.data),
  getInstance: (instanceId: string) =>
    api.get<FormInstance>(`/forms/instances/${instanceId}`).then(r => r.data),
  patchInstance: (instanceId: string, recordVersion: number, values: Record<string, unknown>, provenance?: Record<string, string>) =>
    api
      .patch<FormInstance>(`/forms/instances/${instanceId}`, {
        record_version: recordVersion,
        values,
        provenance: provenance ?? {},
      })
      .then(r => r.data),
  calculate: (instanceId: string, recordVersion: number) =>
    api
      .post<FormInstance>(`/forms/instances/${instanceId}/calculate`, { record_version: recordVersion })
      .then(r => r.data),
  validate: (instanceId: string, recordVersion: number) =>
    api
      .post<FormInstance>(`/forms/instances/${instanceId}/validate`, { record_version: recordVersion })
      .then(r => r.data),
  submit: (instanceId: string, recordVersion: number, idempotencyKey: string) =>
    api
      .post<{ form: FormInstance; approval: ApprovalItem }>(`/forms/instances/${instanceId}/submit`, {
        record_version: recordVersion,
        idempotency_key: idempotencyKey,
      })
      .then(r => r.data),
  exportSync: async (instanceId: string, format: 'pdf' | 'docx' | 'xlsx' | 'md') => {
    const res = await api.post<Blob>(
      `/forms/instances/${instanceId}/export`,
      { format },
      { responseType: 'blob', timeout: 120000 },
    )
    const disposition = (res.headers?.['content-disposition'] as string) || ''
    const match = disposition.match(/filename="?([^";]+)"?/)
    return { blob: res.data, filename: match?.[1] ?? `export.${format}` }
  },
  exportAsync: (instanceId: string, format: 'pdf' | 'docx' | 'xlsx' | 'md') =>
    api
      .post<{ status: string; task_id: string; format: string }>(
        `/forms/instances/${instanceId}/export`,
        { format, async_export: true },
      )
      .then(r => r.data),
  listExports: (instanceId: string) =>
    api.get<{ exports: ExportArtifact[] }>(`/forms/instances/${instanceId}/exports`).then(r => r.data),
  listTemplates: (formKey?: string) =>
    api
      .get<Array<Record<string, unknown>>>('/forms/templates', {
        params: formKey ? { form_key: formKey } : undefined,
      })
      .then(r => r.data),
  downloadExport: (instanceId: string, artifactIndex: number) =>
    api
      .get<Blob>(`/forms/instances/${instanceId}/exports/${artifactIndex}/download`, { responseType: 'blob' })
      .then(r => r.data),
}

// ─── Approvals ───

export const approvalsApi = {
  inbox: (status = 'pending') =>
    api.get<ApprovalItem[]>('/approvals/inbox', { params: { status } }).then(r => r.data),
  get: (approvalId: string) =>
    api.get<ApprovalItem>(`/approvals/${approvalId}`).then(r => r.data),
  decide: (approvalId: string, action: 'approve' | 'reject' | 'request-changes', recordVersion: number, reason = '') =>
    api
      .post<ApprovalItem>(`/approvals/${approvalId}/${action}`, {
        record_version: recordVersion,
        idempotency_key: `${action}-${approvalId}-${Date.now()}`,
        reason,
      })
      .then(r => r.data),
}

// ─── Know-how ───

export const knowhowApi = {
  list: (status?: string) =>
    api.get<KnowhowCard[]>('/knowhow', { params: status ? { status } : {} }).then(r => r.data),
  get: (id: string) => api.get<KnowhowCard>(`/knowhow/${id}`).then(r => r.data),
  create: (data: { title: string; summary?: string; steps?: string[]; risk_level?: string }) =>
    api.post<KnowhowCard>('/knowhow', data).then(r => r.data),
  update: (id: string, version: number, values: Record<string, unknown>) =>
    api.patch<KnowhowCard>(`/knowhow/${id}`, { version, values }).then(r => r.data),
  submit: (id: string, version: number) =>
    api
      .post(`/knowhow/${id}/submit`, {
        version,
        idempotency_key: `knowhow-submit-${id}-${Date.now()}`,
      })
      .then(r => r.data),
  retire: (id: string) =>
    api.post(`/knowhow/${id}/retire`).then(r => r.data),
}

// ─── Helpers ───

/** 觸發瀏覽器下載（同步匯出 blob）。 */
export function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}
