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
  category?: 'streaming' | 'software' | 'cloud' | 'utilities' | 'fitness' | 'food' | 'transport' | 'other'
  due_period?: 'all' | 'day' | 'week' | 'month'
  from_date?: string
  to_date?: string
  sort_order?: 'asc' | 'desc'
  group_by_category?: boolean
  review_status?: 'pending' | 'dismissed'
}

export interface AgentPageContext {
  page: AgentPage
  route: string
  source_page?: Exclude<AgentPage, 'assistant'>
  source_route?: string
  selected_subscription_ids: string[]
  visible_subscription_ids: string[]
  visible_detection_ids: string[]
  filters?: AgentPageFilters
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
