export interface AgentThread {
  id: string
  title: string
  archived: boolean
  message_count: number
  created_at: string
  updated_at: string
}

export type AgentMessageStatus =
  | 'completed'
  | 'streaming'
  | 'failed'
  | 'superseded'

export interface AgentMessage {
  id: string
  thread_id: string
  role: 'user' | 'assistant'
  sequence: number
  content: string
  status: AgentMessageStatus
  reply_to_id: string | null
  error_code: string | null
  created_at: string
  updated_at: string
}

export interface AgentMessagePage {
  messages: AgentMessage[]
  has_more: boolean
  next_before: number | null
}

export type AgentStreamEvent =
  | { type: 'status'; state: 'thinking' | 'using_tool'; tool?: string }
  | { type: 'delta'; text: string }
  | { type: 'done'; message: AgentMessage; thread: AgentThread; replayed?: boolean }
  | { type: 'error'; message_id: string; code: string; message: string }
