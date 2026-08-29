import api from '../../api'

export interface CapturePolicy {
  consent_version: string
  max_duration_seconds: number
  chunk_max_seconds: number
  chunk_max_bytes: number
  max_chunks: number
  audio_retention_days: number
  transcript_retention_days: number
  save_audio: boolean
  save_transcript: boolean
  encrypt_at_rest: boolean
  terminology_count: number
  terminology_sha256: string
  default_metadata: {
    data_classification: string
    source_module: string
    purpose: string
  }
  device_limitations: string[]
}

export interface CaptureSessionInfo {
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
  source_asset_id: string | null
  capture_metadata: Record<string, unknown>
  policy: Record<string, unknown>
  transcript?: string | null
  transcript_metadata?: Record<string, unknown>
  created_at: string | null
  completed_at: string | null
}

export interface CaptureTranscript {
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

export interface CreateCaptureInput {
  title: string
  equipment_id?: string
  interviewee?: string
  interviewer?: string
  consent: boolean
  consent_version?: string
  source_module?: string
  purpose?: string
  department_id?: string
  data_classification?: string
  context_metadata?: Record<string, string | string[]>
}

export const captureApi = {
  policy: () => api.get<CapturePolicy>('/knowledge/captures/policy').then(response => response.data),
  create: (body: CreateCaptureInput) => api.post<CaptureSessionInfo>('/knowledge/captures', body).then(response => response.data),
  uploadChunk: (
    sessionId: string,
    input: { sequence: number; offsetMs: number; durationMs: number; sha256: string; blob: Blob },
  ) => {
    const form = new FormData()
    const extension = input.blob.type.includes('ogg') ? 'ogg' : input.blob.type.includes('mpeg') ? 'mp3' : input.blob.type.includes('mp4') ? 'm4a' : 'webm'
    form.append('file', input.blob, `capture-${input.sequence}.${extension}`)
    form.append('sequence', String(input.sequence))
    form.append('offset_ms', String(input.offsetMs))
    form.append('duration_ms', String(input.durationMs))
    form.append('sha256', input.sha256)
    return api.post<{ id: string; sequence: number; duplicate: boolean; received_chunks: number }>(
      `/knowledge/captures/${sessionId}/chunks`,
      form,
      { headers: { 'Content-Type': 'multipart/form-data' }, timeout: 120000 },
    ).then(response => response.data)
  },
  complete: (sessionId: string, finalSequence: number, totalDurationMs: number) =>
    api.post<CaptureSessionInfo & { queue_enqueued: boolean }>(`/knowledge/captures/${sessionId}/complete`, {
      final_sequence: finalSequence,
      total_duration_ms: totalDurationMs,
    }).then(response => response.data),
  retry: (sessionId: string) => api.post<CaptureSessionInfo>(`/knowledge/captures/${sessionId}/retry`).then(response => response.data),
  get: (sessionId: string) => api.get<CaptureSessionInfo>(`/knowledge/captures/${sessionId}`).then(response => response.data),
  transcript: (sessionId: string) => api.get<CaptureTranscript>(`/knowledge/captures/${sessionId}/transcript`).then(response => response.data),
  correctSegment: (sessionId: string, segmentId: string, correctedText: string) =>
    api.patch<{ id: string; text: string }>(`/knowledge/captures/${sessionId}/transcript/segments/${segmentId}`, {
      corrected_text: correctedText,
    }).then(response => response.data),
}
