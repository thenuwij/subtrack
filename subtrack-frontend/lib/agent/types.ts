import type { Category } from '@/types'

export interface AgentThread {
  id: string
  title: string
  archived: boolean
  message_count: number
  created_at: string
  updated_at: string
}

export type AgentPage =
  | 'dashboard'
  | 'subscriptions'
  | 'review'
  | 'account'
  | 'assistant'
  | 'unknown'

export interface AgentPageFilters {
  search?: string
  category?: Category
  due_period?: 'all' | 'day' | 'week' | 'month'
  from_date?: string
  to_date?: string
  sort_order?: 'asc' | 'desc'
  group_by_category?: boolean
  review_status?: 'pending' | 'dismissed'
  record_scope?: 'current' | 'paused' | 'history' | 'all'
}

export interface AgentPageContext {
  page: AgentPage
  route: string
  source_page?: Exclude<AgentPage, 'assistant'>
  source_route?: string
  selected_subscription_ids: string[]
  visible_subscription_ids: string[]
  visible_detection_ids: string[]
  visible_reminder_ids: string[]
  filters?: AgentPageFilters
}

export type AgentMessageStatus =
  | 'completed'
  | 'streaming'
  | 'failed'
  | 'superseded'

export type AgentActionStatus =
  | 'pending'
  | 'completed'
  | 'rejected'
  | 'failed'
  | 'expired'

export interface AgentAction {
  id: string
  thread_id: string
  assistant_message_id: string
  action_type: string
  summary: string
  description: string
  status: AgentActionStatus
  result: Record<string, unknown> | null
  error_code: string | null
  error_message: string | null
  expires_at: string
  created_at: string
  resolved_at: string | null
}

export interface AgentMessage {
  id: string
  thread_id: string
  role: 'user' | 'assistant'
  sequence: number
  content: string
  status: AgentMessageStatus
  reply_to_id: string | null
  error_code: string | null
  actions: AgentAction[]
  page_context?: AgentPageContext | null
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
