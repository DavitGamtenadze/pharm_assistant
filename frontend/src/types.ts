export type HealthStatus = {
  status: 'ok' | 'degraded'
  openai_configured: boolean
  langfuse_enabled: boolean
  store_ready: boolean
  document_count: number
  embedding_model: string
  generation_model: string
}

export type DocumentSummary = {
  id: string
  filename: string
  page_count: number
  chunk_count: number
  size_bytes: number
  created_at: string
}

export type Citation = {
  id: string
  type: 'document' | 'literature'
  label: string
  excerpt: string
  score: number | null
  document_id: string | null
  filename: string | null
  page: number | null
  external_id: string | null
  source: string | null
  title: string | null
  url: string | null
}

export type QuestionRequest = {
  question: string
  document_ids: string[]
  top_k: number
  include_literature: boolean
}

export type QuestionResponse = {
  answer: string
  citations: Citation[]
  request_id: string
  latency_ms: number
}

export type ChatTurn = {
  id: string
  question: string
  documentIds: string[]
  includeLiterature: boolean
  answer: string
  citations: Citation[]
  requestId: string | null
  latencyMs: number | null
  status: 'loading' | 'success' | 'error'
  error: string | null
}

export type AsyncState = 'idle' | 'loading' | 'success' | 'error'
