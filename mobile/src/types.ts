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

// ─── Document ───
export interface Document {
  id: string
  filename: string
  file_type: string | null
  status: 'uploading' | 'parsing' | 'embedding' | 'completed' | 'failed'
  tenant_id: string
  uploaded_by: string | null
  department_id: string | null
  file_size: number | null
  chunk_count: number | null
  error_message: string | null
  created_at: string | null
  updated_at: string | null
  is_new: boolean
}

// ─── Chat ───
export interface ChatRequest {
  question: string
  conversation_id?: string | null
  top_k?: number
}

export interface Conversation {
  id: string
  user_id: string
  tenant_id: string
  title: string | null
  created_at: string
  updated_at: string | null
}

export interface Message {
  id: string
  conversation_id: string
  role: 'user' | 'assistant'
  content: string
  created_at: string
}

export interface ChatSource {
  document_id: string
  filename: string
  content: string        // chunk text from backend
  score: number
  chunk_index?: number
}

// ─── SSE event types (matches backend chat.py SSE format) ───
export type SSEEvent =
  | { type: 'status';         content: string }
  | { type: 'token';          content: string }
  | { type: 'sources';        sources: ChatSource[] }
  | { type: 'suggestions';    items: string[] }
  | { type: 'done';           message_id: string; conversation_id: string }
  | { type: 'error';          content: string }
