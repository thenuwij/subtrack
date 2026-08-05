import type {
  AgentMessagePage,
  AgentAction,
  AgentPageContext,
  AgentStreamEvent,
  AgentThread,
} from '@/lib/agent/types'
import { API_URL } from '@/lib/config'
import { handleExpiredSession, SessionExpiredError } from '@/lib/api'

const JSON_TIMEOUT_MS = 15_000
// Anthropic requests are bounded server-side, but an interrupted proxy can
// otherwise leave a browser reader pending forever. This is an inactivity
// limit, reset whenever an SSE chunk arrives (including tool/status events).
const STREAM_IDLE_TIMEOUT_MS = 110_000

function headers(token: string) {
  return {
    'Content-Type': 'application/json',
    Authorization: `Bearer ${token}`,
  }
}

async function detailFrom(response: Response) {
  const body = await response.json().catch(() => null)
  if (typeof body?.detail === 'string') return body.detail
  if (Array.isArray(body?.detail)) {
    const messages = body.detail
      .map((item: unknown) => item && typeof item === 'object' && 'msg' in item
        ? String((item as { msg: unknown }).msg) : '')
      .filter(Boolean)
      .slice(0, 3)
    if (messages.length) return messages.join(' ')
  }
  return `The Subtrack server returned ${response.status}.`
}

async function jsonRequest<T>(
  path: string,
  token: string,
  init: RequestInit = {}
): Promise<T> {
  const controller = new AbortController()
  const timeout = window.setTimeout(() => controller.abort(), JSON_TIMEOUT_MS)
  let response: Response
  try {
    response = await fetch(`${API_URL}${path}`, {
      ...init,
      signal: controller.signal,
      headers: { ...headers(token), ...(init.headers ?? {}) },
    })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new Error('The Subtrack server took too long to respond.')
    }
    throw new Error('Could not reach the Subtrack server.')
  } finally {
    window.clearTimeout(timeout)
  }
  if (response.status === 401) {
    await handleExpiredSession()
    throw new SessionExpiredError()
  }
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

export function confirmAgentAction(token: string, id: string) {
  return jsonRequest<AgentAction>(`/agent/actions/${id}/confirm`, token, {
    method: 'POST',
  })
}

export function rejectAgentAction(token: string, id: string) {
  return jsonRequest<AgentAction>(`/agent/actions/${id}/reject`, token, {
    method: 'POST',
  })
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
  const controller = new AbortController()
  let timedOut = false
  let idleTimeout = 0
  const callerAbort = () => controller.abort()
  const resetIdleTimeout = () => {
    window.clearTimeout(idleTimeout)
    idleTimeout = window.setTimeout(() => {
      timedOut = true
      controller.abort()
    }, STREAM_IDLE_TIMEOUT_MS)
  }

  if (signal?.aborted) throw new DOMException('The request was stopped.', 'AbortError')
  signal?.addEventListener('abort', callerAbort, { once: true })
  resetIdleTimeout()

  try {
    const response = await fetch(`${API_URL}${path}`, {
      method: 'POST',
      headers: headers(token),
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
    })
    resetIdleTimeout()
    if (response.status === 401) {
      await handleExpiredSession()
      throw new SessionExpiredError()
    }
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
      resetIdleTimeout()
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
  } catch (error) {
    if (timedOut) {
      throw new Error('The assistant took too long to respond. Please retry your message.')
    }
    if (signal?.aborted) {
      throw new DOMException('The request was stopped.', 'AbortError')
    }
    if (error instanceof TypeError) {
      throw new Error('The connection to the assistant was interrupted. Please retry.')
    }
    throw error
  } finally {
    window.clearTimeout(idleTimeout)
    signal?.removeEventListener('abort', callerAbort)
  }
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
