import type {
  DocumentSummary,
  HealthStatus,
  QuestionRequest,
  QuestionResponse,
} from '../types'

const configuredBaseUrl = import.meta.env.VITE_API_BASE_URL?.trim()
const API_BASE_URL = (configuredBaseUrl || 'http://localhost:8000').replace(
  /\/+$/,
  '',
)
const API_KEY = import.meta.env.VITE_API_KEY?.trim()

export class ApiError extends Error {
  status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

function getErrorMessage(payload: unknown, fallback: string) {
  if (typeof payload === 'object' && payload !== null) {
    const detail = 'detail' in payload ? payload.detail : undefined
    const message = 'message' in payload ? payload.message : undefined

    if (typeof detail === 'string') return detail
    if (typeof message === 'string') return message
  }

  return fallback
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)

  if (API_KEY) headers.set('X-API-Key', API_KEY)
  if (init.body && !(init.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }

  let response: Response

  try {
    response = await fetch(`${API_BASE_URL}${path}`, { ...init, headers })
  } catch {
    throw new ApiError(
      'Unable to reach the research service. Confirm the API is running and try again.',
      0,
    )
  }

  if (response.status === 204) return undefined as T

  const responseText = await response.text()
  let payload: unknown = null

  if (responseText) {
    try {
      payload = JSON.parse(responseText)
    } catch {
      payload = responseText
    }
  }

  if (!response.ok) {
    if (response.status === 429) {
      throw new ApiError(
        'Too many requests. Wait a moment and try again.',
        429,
      )
    }
    throw new ApiError(
      getErrorMessage(payload, `Request failed with status ${response.status}.`),
      response.status,
    )
  }

  return payload as T
}

export function getHealth() {
  return request<HealthStatus>('/health')
}

export async function getDocuments() {
  const response = await request<{ documents: DocumentSummary[] }>(
    '/api/v1/documents',
  )
  return response.documents
}

export function uploadDocument(file: File) {
  const body = new FormData()
  body.append('file', file)

  return request<DocumentSummary>('/api/v1/documents', {
    method: 'POST',
    body,
  })
}

export function deleteDocument(documentId: string) {
  return request<void>(`/api/v1/documents/${encodeURIComponent(documentId)}`, {
    method: 'DELETE',
  })
}

export function getDocumentFileUrl(
  documentId: string,
  page?: number | null,
) {
  const url = `${API_BASE_URL}/api/v1/documents/${encodeURIComponent(documentId)}/file`
  return page ? `${url}#page=${page}` : url
}

export async function getDocumentPageImageUrl(
  documentId: string,
  page: number,
) {
  const headers = new Headers()
  if (API_KEY) headers.set('X-API-Key', API_KEY)
  const response = await fetch(
    `${API_BASE_URL}/api/v1/documents/${encodeURIComponent(documentId)}/pages/${page}`,
    { headers },
  )
  if (!response.ok) {
    throw new ApiError('The cited page preview could not be loaded.', response.status)
  }
  return URL.createObjectURL(await response.blob())
}

export function openDocumentPage(documentId: string, page?: number | null) {
  window.open(getDocumentFileUrl(documentId, page), '_blank', 'noopener,noreferrer')
}

export function askQuestion(payload: QuestionRequest) {
  return request<QuestionResponse>('/api/v1/questions', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

type StreamEvent =
  | { type: 'token'; text: string }
  | (QuestionResponse & { type: 'done' })
  | { type: 'error'; detail: string }

export async function askQuestionStream(
  payload: QuestionRequest,
  onToken: (text: string) => void,
): Promise<QuestionResponse> {
  const headers = new Headers({ 'Content-Type': 'application/json' })
  if (API_KEY) headers.set('X-API-Key', API_KEY)

  let response: Response
  try {
    response = await fetch(`${API_BASE_URL}/api/v1/questions/stream`, {
      method: 'POST',
      headers,
      body: JSON.stringify(payload),
    })
  } catch {
    throw new ApiError(
      'Unable to reach the research service. Confirm the API is running and try again.',
      0,
    )
  }

  if (!response.ok) {
    const responseText = await response.text()
    let payloadJson: unknown = null
    if (responseText) {
      try {
        payloadJson = JSON.parse(responseText)
      } catch {
        payloadJson = responseText
      }
    }
    if (response.status === 429) {
      throw new ApiError('Too many requests. Wait a moment and try again.', 429)
    }
    throw new ApiError(
      getErrorMessage(payloadJson, `Request failed with status ${response.status}.`),
      response.status,
    )
  }

  if (!response.body) {
    throw new ApiError('The answer stream could not be opened.', response.status)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let finalResponse: QuestionResponse | null = null

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const blocks = buffer.split('\n\n')
    buffer = blocks.pop() ?? ''

    for (const block of blocks) {
      const line = block
        .split('\n')
        .find((entry) => entry.startsWith('data: '))
      if (!line) continue
      const event = JSON.parse(line.slice(6)) as StreamEvent
      if (event.type === 'token') {
        onToken(event.text)
      } else if (event.type === 'done') {
        const { type: _type, ...completed } = event
        finalResponse = completed
      } else if (event.type === 'error') {
        throw new ApiError(event.detail, 503)
      }
    }
  }

  if (!finalResponse) {
    throw new ApiError('The answer stream ended before a complete response.', 503)
  }
  return finalResponse
}
