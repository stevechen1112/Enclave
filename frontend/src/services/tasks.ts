/**
 * Task API client — 職能任務平台（TaskDefinition / TaskRun）。
 */
import api from '../api'

export type TaskDefinition = {
  id: string
  task_key: string
  name: string
  description?: string | null
  version: string
  status: string
  handler_key: string
  module_key?: string | null
  applicable_job_role_keys: string[]
  input_schema: Record<string, unknown>
  required_capabilities: string[]
  output_bindings: Array<{ kind: string; form_key?: string }>
  risk_level: string
}

export type FieldSource = {
  source?: 'voice' | 'text' | 'knowledge' | 'tool' | 'rule' | 'user' | 'default'
  ref?: string | null
  confidence?: number | null
}

export type TaskRun = {
  id: string
  task_key: string
  task_version: string
  status: string
  module_key?: string | null
  job_role_id?: string | null
  input_snapshot: { values?: Record<string, unknown>; [k: string]: unknown }
  field_sources: Record<string, FieldSource>
  provenance: {
    missing_fields?: string[]
    manual_edits?: string[]
    [k: string]: unknown
  }
  error?: { code: string; message: string; retryable: boolean } | null
  output_refs: Record<string, unknown>
  created_at?: string | null
  updated_at?: string | null
  created?: boolean
}

export type RealtimeQuoteToolResult = {
  run_id: string
  status: string
  values: Record<string, unknown>
  missing_fields: string[]
  ready_for_user_review: boolean
  next_action: string
  updated_fields?: string[]
  idempotent?: boolean
}

export const tasksApi = {
  list: async (): Promise<TaskDefinition[]> => {
    const res = await api.get('/tasks')
    return res.data
  },

  listRuns: async (params: { task_key?: string; status?: string }): Promise<TaskRun[]> => {
    const res = await api.get('/tasks/runs', { params })
    return res.data
  },

  startRun: async (
    taskKey: string,
    body: { idempotency_key: string; inputs?: Record<string, unknown>; scene_context?: Record<string, unknown> },
  ): Promise<TaskRun> => {
    const res = await api.post(`/tasks/${taskKey}/runs`, body)
    return res.data
  },

  getRun: async (runId: string): Promise<TaskRun> => {
    const res = await api.get(`/tasks/runs/${runId}`)
    return res.data
  },

  patchInputs: async (
    runId: string,
    body: {
      values?: Record<string, unknown>
      sources?: Record<string, FieldSource>
      edited_fields?: string[]
    },
  ): Promise<TaskRun> => {
    const res = await api.patch(`/tasks/runs/${runId}/inputs`, body)
    return res.data
  },

  parseText: async (
    runId: string,
    text: string,
    opts?: { source?: 'text' | 'voice'; source_ref?: string; confidence?: number },
  ): Promise<{ run: TaskRun; detected_fields: Record<string, unknown> }> => {
    const res = await api.post(`/tasks/runs/${runId}/parse-text`, { text, ...opts })
    return res.data
  },

  execute: async (runId: string): Promise<TaskRun> => {
    const res = await api.post(`/tasks/runs/${runId}/execute`)
    return res.data
  },

  transition: async (runId: string, toStatus: string): Promise<TaskRun> => {
    const res = await api.post(`/tasks/runs/${runId}/transition`, { to_status: toStatus })
    return res.data
  },

  createQuoteRealtimeSession: async (runId: string, sdp: string): Promise<string> => {
    const res = await api.post(`/voice/realtime/quote/session?run_id=${encodeURIComponent(runId)}`, sdp, {
      headers: { 'Content-Type': 'application/sdp' },
      responseType: 'text',
    })
    return res.data
  },

  callQuoteRealtimeTool: async (body: {
    run_id: string
    call_id: string
    name: string
    arguments: Record<string, unknown>
  }): Promise<RealtimeQuoteToolResult> => {
    const res = await api.post('/voice/realtime/quote/tools', body)
    return res.data
  },
}
