import type {
  AgentMessagePage,
  AgentPageContext,
  AgentStreamEvent,
  AgentThread,
} from '@/lib/agent/types'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

function headers(token: string) {
  return {
    'Content-Type': 'application/json',
    Authorization: `Bearer ${token}`,
  }
}

async function detailFrom(response: Response) {
  const body = await response.json().catch(() => null)
  return typeof body?.detail === 'string'
    ? body.detail
    : `The Subtrack server returned ${response.status}.`
}

async function jsonRequest<T>(
  path: string,
  token: string,
  init: RequestInit = {}
): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: { ...headers(token), ...(init.headers ?? {}) },
  })
  if (!response.ok) throw new Error(await detailFrom(response))
  if (response.status === 204) return undefined as T
  return response.json()
}

export function listAgentThreads(token: string, archived = false) {
  return jsonRequest<AgentThread[]>(`/agent/threads?archived=${archived}`, token)
}

export function createAgentThread(token: string) {
  return jsonRequest<AgentThread>('/agent/threads', token, {
    method: 'POST',
    body: JSON.stringify({}),
  })
}

export function updateAgentThread(
  token: string,
  id: string,
  update: { title?: string; archived?: boolean }
) {
  return jsonRequest<AgentThread>(`/agent/threads/${id}`, token, {
    method: 'PATCH',
    body: JSON.stringify(update),
  })
}

export function deleteAgentThread(token: string, id: string) {
  return jsonRequest<void>(`/agent/threads/${id}`, token, { method: 'DELETE' })
}

export function listAgentMessages(
  token: string,
  threadId: string,
  before?: number | null
) {
  const query = before ? `?before=${encodeURIComponent(before)}` : ''
  return jsonRequest<AgentMessagePage>(
    `/agent/threads/${threadId}/messages${query}`,
    token
  )
}

interface StreamOptions {
  token: string
  path: string
  body?: unknown
  signal?: AbortSignal
  onEvent: (event: AgentStreamEvent) => void
}

async function streamEvents({ token, path, body, signal, onEvent }: StreamOptions) {
  const response = await fetch(`${API_URL}${path}`, {
    method: 'POST',
    headers: headers(token),
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
  })
  if (!response.ok) throw new Error(await detailFrom(response))
  if (!response.body) throw new Error('The assistant returned an empty response.')

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  function consume(block: string) {
    let eventName = ''
    const data: string[] = []
    for (const line of block.split('\n')) {
      if (line.startsWith('event:')) eventName = line.slice(6).trim()
      if (line.startsWith('data:')) data.push(line.slice(5).trimStart())
    }
    if (!eventName || data.length === 0) return
    const payload = JSON.parse(data.join('\n'))
    onEvent({ type: eventName, ...payload } as AgentStreamEvent)
  }

  while (true) {
    const { value, done } = await reader.read()
    buffer += decoder.decode(value, { stream: !done }).replaceAll('\r\n', '\n')
    let boundary = buffer.indexOf('\n\n')
    while (boundary >= 0) {
      consume(buffer.slice(0, boundary))
      buffer = buffer.slice(boundary + 2)
      boundary = buffer.indexOf('\n\n')
    }
    if (done) break
  }
  if (buffer.trim()) consume(buffer)
}

export function sendAgentMessage(
  token: string,
  threadId: string,
  message: string,
  clientMessageId: string,
  pageContext: AgentPageContext,
  onEvent: (event: AgentStreamEvent) => void,
  signal?: AbortSignal
) {
  return streamEvents({
    token,
    path: `/agent/threads/${threadId}/messages`,
    body: {
      message,
      client_message_id: clientMessageId,
      page_context: pageContext,
    },
    signal,
    onEvent,
  })
}

export function retryAgentMessage(
  token: string,
  threadId: string,
  messageId: string,
  onEvent: (event: AgentStreamEvent) => void,
  signal?: AbortSignal
) {
  return streamEvents({
    token,
    path: `/agent/threads/${threadId}/messages/${messageId}/retry`,
    signal,
    onEvent,
  })
}
