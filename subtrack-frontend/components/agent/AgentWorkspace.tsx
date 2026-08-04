'use client'

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type KeyboardEvent,
} from 'react'
import { useRouter } from 'next/navigation'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import {
  Archive,
  ArchiveRestore,
  ArrowDown,
  ArrowLeft,
  Check,
  ChevronLeft,
  History,
  LoaderCircle,
  Maximize2,
  Menu,
  MessageSquarePlus,
  Pencil,
  RotateCcw,
  Send,
  Square,
  Trash2,
  X,
} from 'lucide-react'
import { createClient } from '@/lib/supabase/client'
import {
  createAgentThread,
  deleteAgentThread,
  listAgentMessages,
  listAgentThreads,
  retryAgentMessage,
  sendAgentMessage,
  updateAgentThread,
} from '@/lib/agent/api'
import type {
  AgentMessage,
  AgentStreamEvent,
  AgentThread,
} from '@/lib/agent/types'
import { useStoredString } from '@/lib/hooks/useStoredState'
import { LogoMark } from '@/components/layout/Logo'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'


const ACTIVE_THREAD_KEY = 'subtrack:agent-active-thread'
const suggestions = [
  'What do my recurring payments cost each month?',
  'Which categories cost me the most?',
  'What payments are due next?',
]

interface AgentWorkspaceProps {
  variant: 'panel' | 'page'
  onClose?: () => void
  onOpenFullPage?: () => void
  tokenProvider?: () => Promise<string>
}

function temporaryMessage(
  id: string,
  threadId: string,
  role: 'user' | 'assistant',
  content: string,
  status: AgentMessage['status']
): AgentMessage {
  const now = new Date().toISOString()
  return {
    id,
    thread_id: threadId,
    role,
    sequence: Number.MAX_SAFE_INTEGER,
    content,
    status,
    reply_to_id: null,
    error_code: null,
    created_at: now,
    updated_at: now,
  }
}

function failureText(message: AgentMessage) {
  if (message.content) return message.content
  return {
    rate_limited: 'The assistant is busy right now. Please retry in a moment.',
    timed_out: 'The response took too long. Your message is safe—try it again.',
    provider_unavailable: 'The assistant could not be reached. Please retry.',
    stream_interrupted: 'The response was stopped before it finished.',
  }[message.error_code ?? ''] ?? 'The response failed, but your message was saved.'
}

function readableDate(value: string) {
  const date = new Date(value)
  const today = new Date()
  if (date.toDateString() === today.toDateString()) {
    return new Intl.DateTimeFormat(undefined, {
      hour: 'numeric',
      minute: '2-digit',
    }).format(date)
  }
  return new Intl.DateTimeFormat(undefined, {
    month: 'short',
    day: 'numeric',
  }).format(date)
}

async function accessToken() {
  const { data: { session } } = await createClient().auth.getSession()
  if (!session) throw new Error('Your session has expired. Please sign in again.')
  return session.access_token
}

export function AgentWorkspace({
  variant,
  onClose,
  onOpenFullPage,
  tokenProvider = accessToken,
}: AgentWorkspaceProps) {
  const router = useRouter()
  const [activeThreadId, setActiveThreadId, clearActiveThreadId] =
    useStoredString(ACTIVE_THREAD_KEY, '')
  const [threads, setThreads] = useState<AgentThread[]>([])
  const [messages, setMessages] = useState<AgentMessage[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [loadingHistory, setLoadingHistory] = useState(true)
  const [statusText, setStatusText] = useState('')
  const [loadError, setLoadError] = useState('')
  const [hasMore, setHasMore] = useState(false)
  const [nextBefore, setNextBefore] = useState<number | null>(null)
  const [showHistory, setShowHistory] = useState(false)
  const [showArchived, setShowArchived] = useState(false)
  const [renamingId, setRenamingId] = useState<string | null>(null)
  const [renameDraft, setRenameDraft] = useState('')
  const [deleteTarget, setDeleteTarget] = useState<AgentThread | null>(null)
  const abortRef = useRef<AbortController | null>(null)
  const skipNextMessageLoadRef = useRef<string | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const loadThreads = useCallback(async (preferredId?: string) => {
    try {
      const token = await tokenProvider()
      const result = await listAgentThreads(token, showArchived)
      setThreads(result)
      const wanted = preferredId ?? activeThreadId
      if (wanted && result.some(thread => thread.id === wanted)) return
      if (result[0]) setActiveThreadId(result[0].id)
      else clearActiveThreadId()
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : 'Could not load conversations.')
    }
  }, [activeThreadId, clearActiveThreadId, setActiveThreadId, showArchived, tokenProvider])

  const loadMessages = useCallback(async (
    threadId: string,
    before?: number | null,
    prepend = false,
    silent = false
  ) => {
    if (!threadId) {
      setMessages([])
      setLoadingHistory(false)
      return
    }
    if (!prepend && !silent) setLoadingHistory(true)
    try {
      const token = await tokenProvider()
      const page = await listAgentMessages(token, threadId, before)
      setMessages(current => prepend
        ? [...page.messages, ...current]
        : page.messages)
      setHasMore(page.has_more)
      setNextBefore(page.next_before)
      setLoadError('')
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : 'Could not load this conversation.')
    } finally {
      if (!silent) setLoadingHistory(false)
    }
  }, [tokenProvider])

  useEffect(() => {
    void loadThreads()
  }, [loadThreads])

  useEffect(() => {
    if (skipNextMessageLoadRef.current === activeThreadId) {
      skipNextMessageLoadRef.current = null
      return
    }
    void loadMessages(activeThreadId)
  }, [activeThreadId, loadMessages])

  useEffect(() => {
    const waitingForDetachedStream = !loading && messages.some(message =>
      message.status === 'streaming' && !message.id.startsWith('local-')
    )
    if (!activeThreadId || !waitingForDetachedStream) return
    const interval = window.setInterval(() => {
      void loadMessages(activeThreadId, null, false, true)
    }, 1_500)
    return () => window.clearInterval(interval)
  }, [activeThreadId, loading, loadMessages, messages])

  useEffect(() => {
    if (!loadingHistory) bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [loadingHistory, messages])

  async function newConversation(skipInitialMessageLoad = false) {
    if (loading) return null
    try {
      const token = await tokenProvider()
      const thread = await createAgentThread(token)
      if (skipInitialMessageLoad) skipNextMessageLoadRef.current = thread.id
      setShowArchived(false)
      setThreads(current => [thread, ...current.filter(item => item.id !== thread.id)])
      setActiveThreadId(thread.id)
      setMessages([])
      setShowHistory(false)
      setLoadError('')
      requestAnimationFrame(() => textareaRef.current?.focus())
      return thread
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : 'Could not start a conversation.')
      return null
    }
  }

  function handleStreamEvent(event: AgentStreamEvent, temporaryId: string) {
    if (event.type === 'status') {
      setStatusText(event.state === 'using_tool' ? 'Checking your data…' : 'Thinking…')
      return
    }
    if (event.type === 'delta') {
      setMessages(current => current.map(message =>
        message.id === temporaryId
          ? { ...message, content: message.content + event.text }
          : message
      ))
      return
    }
    if (event.type === 'error') {
      setMessages(current => current.map(message =>
        message.id === temporaryId
          ? {
              ...message,
              id: event.message_id,
              status: 'failed',
              error_code: event.code,
              content: event.message,
            }
          : message
      ))
      return
    }
    if (event.type === 'done') {
      setMessages(current => current.map(message =>
        message.id === temporaryId ? event.message : message
      ))
      setThreads(current => [
        event.thread,
        ...current.filter(thread => thread.id !== event.thread.id),
      ])
    }
  }

  async function send() {
    const text = input.trim()
    if (!text || loading) return

    let thread = threads.find(item => item.id === activeThreadId) ?? null
    if (!thread) thread = await newConversation(true)
    if (!thread) return

    const threadId = thread.id
    const userId = `local-user-${crypto.randomUUID()}`
    const assistantId = `local-assistant-${crypto.randomUUID()}`
    setInput('')
    setMessages(current => [
      ...current,
      temporaryMessage(userId, threadId, 'user', text, 'completed'),
      temporaryMessage(assistantId, threadId, 'assistant', '', 'streaming'),
    ])
    setLoading(true)
    setStatusText('Thinking…')
    setLoadError('')

    const controller = new AbortController()
    abortRef.current = controller
    try {
      const token = await tokenProvider()
      await sendAgentMessage(
        token,
        threadId,
        text,
        crypto.randomUUID(),
        event => handleStreamEvent(event, assistantId),
        controller.signal
      )
      await Promise.all([loadMessages(threadId), loadThreads(threadId)])
    } catch (error) {
      const stopped = error instanceof DOMException && error.name === 'AbortError'
      setMessages(current => current.map(message =>
        message.id === assistantId
          ? {
              ...message,
              status: 'failed',
              error_code: stopped ? 'stream_interrupted' : 'network_error',
              content: stopped
                ? 'The response was stopped before it finished.'
                : error instanceof Error ? error.message : 'The response failed.',
            }
          : message
      ))
    } finally {
      abortRef.current = null
      setLoading(false)
      setStatusText('')
    }
  }

  async function retry(message: AgentMessage) {
    if (loading || !activeThreadId) return
    const temporaryId = `local-retry-${crypto.randomUUID()}`
    setMessages(current => [
      ...current.filter(item => item.id !== message.id),
      temporaryMessage(temporaryId, activeThreadId, 'assistant', '', 'streaming'),
    ])
    setLoading(true)
    setStatusText('Trying again…')
    const controller = new AbortController()
    abortRef.current = controller
    try {
      const token = await tokenProvider()
      await retryAgentMessage(
        token,
        activeThreadId,
        message.id,
        event => handleStreamEvent(event, temporaryId),
        controller.signal
      )
      await Promise.all([loadMessages(activeThreadId), loadThreads(activeThreadId)])
    } catch (error) {
      setMessages(current => current.map(item =>
        item.id === temporaryId
          ? {
              ...item,
              status: 'failed',
              content: error instanceof Error ? error.message : 'The retry failed.',
            }
          : item
      ))
    } finally {
      abortRef.current = null
      setLoading(false)
      setStatusText('')
    }
  }

  async function saveRename(thread: AgentThread) {
    const title = renameDraft.trim()
    if (!title) return
    try {
      const token = await tokenProvider()
      const updated = await updateAgentThread(token, thread.id, { title })
      setThreads(current => current.map(item => item.id === updated.id ? updated : item))
      setRenamingId(null)
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : 'Could not rename the conversation.')
    }
  }

  async function archiveThread(thread: AgentThread) {
    try {
      const token = await tokenProvider()
      await updateAgentThread(token, thread.id, { archived: !thread.archived })
      if (thread.id === activeThreadId) clearActiveThreadId()
      await loadThreads()
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : 'Could not update the conversation.')
    }
  }

  async function confirmDelete() {
    if (!deleteTarget) return
    try {
      const token = await tokenProvider()
      await deleteAgentThread(token, deleteTarget.id)
      if (deleteTarget.id === activeThreadId) clearActiveThreadId()
      setDeleteTarget(null)
      await loadThreads()
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : 'Could not delete the conversation.')
    }
  }

  function handleComposerKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      void send()
    }
  }

  const activeThread = threads.find(thread => thread.id === activeThreadId)

  return (
    <div className="relative flex h-full min-h-0 flex-col overflow-hidden bg-card text-card-foreground">
      <header className="flex h-14 shrink-0 items-center gap-2 border-b border-border px-3">
        {variant === 'page' ? (
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={() => router.push('/dashboard')}
            aria-label="Back to dashboard"
          >
            <ArrowLeft />
          </Button>
        ) : null}
        <Button
          variant="ghost"
          size="icon-sm"
          onClick={() => setShowHistory(value => !value)}
          aria-label={showHistory ? 'Hide conversation history' : 'Show conversation history'}
          aria-expanded={showHistory}
        >
          {showHistory ? <ChevronLeft /> : <Menu />}
        </Button>
        <LogoMark className="h-7 w-7 shrink-0" />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold">
            {activeThread?.title ?? 'Subtrack assistant'}
          </p>
          <p className="truncate text-[11px] text-muted-foreground">
            {statusText || 'Your recurring payments, explained'}
          </p>
        </div>
        <Button
          variant="ghost"
          size="icon-sm"
          disabled={loading}
          onClick={() => void newConversation()}
          aria-label="New conversation"
        >
          <MessageSquarePlus />
        </Button>
        {variant === 'panel' && onOpenFullPage ? (
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={onOpenFullPage}
            aria-label="Open full-screen assistant"
          >
            <Maximize2 />
          </Button>
        ) : null}
        {variant === 'panel' && onClose ? (
          <Button variant="ghost" size="icon-sm" onClick={onClose} aria-label="Minimise assistant">
            <X />
          </Button>
        ) : null}
      </header>

      {showHistory ? (
        <aside className="absolute inset-y-14 left-0 z-20 flex w-[min(19rem,86%)] flex-col border-r border-border bg-card shadow-lg">
          <div className="flex items-center justify-between border-b border-border px-3 py-2">
            <div>
              <p className="text-xs font-semibold">Conversation history</p>
              <button
                type="button"
                disabled={loading}
                onClick={() => setShowArchived(value => !value)}
                className="mt-0.5 text-[11px] text-muted-foreground hover:text-foreground disabled:opacity-50"
              >
                {showArchived ? 'Show active conversations' : 'Show archived conversations'}
              </button>
            </div>
            <Button variant="ghost" size="icon-xs" onClick={() => setShowHistory(false)} aria-label="Close history">
              <X />
            </Button>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto p-2">
            {threads.length === 0 ? (
              <div className="px-3 py-10 text-center">
                <History className="mx-auto h-5 w-5 text-muted-foreground" />
                <p className="mt-2 text-xs text-muted-foreground">
                  {showArchived ? 'No archived conversations.' : 'No conversations yet.'}
                </p>
              </div>
            ) : (
              <ul className="space-y-1">
                {threads.map(thread => (
                  <li
                    key={thread.id}
                    className={`group rounded-lg ${thread.id === activeThreadId ? 'bg-primary/10' : 'hover:bg-muted'}`}
                  >
                    {renamingId === thread.id ? (
                      <form
                        className="flex items-center gap-1 p-1.5"
                        onSubmit={event => {
                          event.preventDefault()
                          void saveRename(thread)
                        }}
                      >
                        <input
                          autoFocus
                          value={renameDraft}
                          onChange={event => setRenameDraft(event.target.value)}
                          maxLength={120}
                          aria-label="Conversation title"
                          className="min-w-0 flex-1 rounded-md border border-border bg-background px-2 py-1 text-xs"
                        />
                        <Button size="icon-xs" type="submit" aria-label="Save title"><Check /></Button>
                      </form>
                    ) : (
                      <div className="flex items-center gap-1 p-1.5">
                        <button
                          type="button"
                          disabled={loading}
                          onClick={() => {
                            setActiveThreadId(thread.id)
                            if (variant === 'panel') setShowHistory(false)
                          }}
                          className="min-w-0 flex-1 rounded-md px-1.5 py-1 text-left disabled:opacity-50"
                        >
                          <span className="block truncate text-xs font-medium">{thread.title}</span>
                          <span className="mt-0.5 block text-[10px] text-muted-foreground">
                            {thread.message_count} messages · {readableDate(thread.updated_at)}
                          </span>
                        </button>
                        <Button
                          variant="ghost"
                          size="icon-xs"
                          disabled={loading}
                          onClick={() => {
                            setRenamingId(thread.id)
                            setRenameDraft(thread.title)
                          }}
                          aria-label={`Rename ${thread.title}`}
                        >
                          <Pencil />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon-xs"
                          disabled={loading}
                          onClick={() => void archiveThread(thread)}
                          aria-label={`${thread.archived ? 'Restore' : 'Archive'} ${thread.title}`}
                        >
                          {thread.archived ? <ArchiveRestore /> : <Archive />}
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon-xs"
                          disabled={loading}
                          className="text-destructive"
                          onClick={() => setDeleteTarget(thread)}
                          aria-label={`Delete ${thread.title}`}
                        >
                          <Trash2 />
                        </Button>
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div className="border-t border-border p-2">
            <Button className="w-full" variant="outline" disabled={loading} onClick={() => void newConversation()}>
              <MessageSquarePlus data-icon="inline-start" />
              New conversation
            </Button>
          </div>
        </aside>
      ) : null}

      <main
        className={`min-h-0 flex-1 overflow-y-auto px-4 py-5 ${variant === 'page' && showHistory ? 'md:pl-[20rem]' : ''}`}
        aria-live="polite"
        aria-busy={loading}
      >
        {hasMore ? (
          <div className="mb-5 text-center">
            <Button
              size="sm"
              variant="ghost"
              onClick={() => void loadMessages(activeThreadId, nextBefore, true)}
            >
              <ArrowDown className="rotate-180" data-icon="inline-start" />
              Load earlier messages
            </Button>
          </div>
        ) : null}

        {loadingHistory ? (
          <div className="flex h-full min-h-48 items-center justify-center text-muted-foreground">
            <LoaderCircle className="mr-2 h-4 w-4 animate-spin" />
            <span className="text-xs">Loading conversation…</span>
          </div>
        ) : messages.length === 0 ? (
          <div className="mx-auto flex min-h-full max-w-md flex-col items-center justify-center py-8 text-center">
            <LogoMark className="h-11 w-11" />
            <h1 className="mt-5 text-xl font-semibold tracking-tight">Talk to your recurring finances</h1>
            <p className="mt-2 max-w-sm text-sm leading-6 text-muted-foreground">
              Ask what changed, where your monthly commitments go, or which payments deserve a closer look.
            </p>
            <div className="mt-6 grid w-full gap-2">
              {suggestions.map(suggestion => (
                <button
                  type="button"
                  key={suggestion}
                  onClick={() => {
                    setInput(suggestion)
                    textareaRef.current?.focus()
                  }}
                  className="rounded-xl border border-border bg-background px-4 py-3 text-left text-xs leading-5 transition-colors hover:bg-muted"
                >
                  {suggestion}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="mx-auto flex max-w-2xl flex-col gap-4">
            {messages.map(message => message.role === 'user' ? (
              <div key={message.id} className="ml-auto max-w-[88%] rounded-2xl rounded-br-md bg-primary px-4 py-2.5 text-sm leading-6 text-primary-foreground">
                {message.content}
              </div>
            ) : message.status === 'failed' ? (
              <div key={message.id} className="max-w-[92%] rounded-xl border border-destructive/20 bg-destructive/5 p-3">
                <p className="text-sm text-foreground">{failureText(message)}</p>
                {!message.id.startsWith('local-') ? (
                  <Button className="mt-2" size="sm" variant="outline" onClick={() => void retry(message)} disabled={loading}>
                    <RotateCcw data-icon="inline-start" />
                    Retry response
                  </Button>
                ) : null}
              </div>
            ) : (
              <div key={message.id} className="max-w-[92%] text-sm leading-6 text-foreground">
                {message.content ? (
                  <div className="prose prose-sm max-w-none dark:prose-invert prose-p:my-2 prose-table:text-xs prose-td:py-1 prose-th:py-1">
                    <ReactMarkdown
                      remarkPlugins={[remarkGfm]}
                      components={{
                        a: ({ children, ...props }) => (
                          <a {...props} target="_blank" rel="noreferrer">{children}</a>
                        ),
                      }}
                    >
                      {message.content}
                    </ReactMarkdown>
                  </div>
                ) : null}
                {message.status === 'streaming' ? (
                  <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
                    <LoaderCircle className="h-3.5 w-3.5 animate-spin" />
                    {statusText || 'Thinking…'}
                  </span>
                ) : null}
              </div>
            ))}
            <div ref={bottomRef} />
          </div>
        )}
      </main>

      {loadError ? (
        <div role="alert" className="mx-3 mb-2 rounded-lg bg-destructive/10 px-3 py-2 text-xs text-destructive">
          {loadError}
        </div>
      ) : null}

      <footer className={`shrink-0 border-t border-border bg-card p-3 ${variant === 'page' && showHistory ? 'md:pl-[20rem]' : ''}`}>
        <div className="mx-auto flex max-w-2xl items-end gap-2 rounded-xl border border-border bg-background p-2 shadow-sm focus-within:ring-2 focus-within:ring-ring/30">
          <textarea
            ref={textareaRef}
            rows={1}
            value={input}
            onChange={event => setInput(event.target.value)}
            onKeyDown={handleComposerKeyDown}
            disabled={loading || showArchived}
            maxLength={8_000}
            placeholder={showArchived ? 'Restore or start a conversation to continue' : 'Ask about your recurring finances…'}
            aria-label="Message Subtrack assistant"
            className="max-h-32 min-h-9 min-w-0 flex-1 resize-none bg-transparent px-2 py-2 text-sm leading-5 outline-none placeholder:text-muted-foreground disabled:opacity-60"
          />
          {loading ? (
            <Button
              size="icon"
              variant="outline"
              onClick={() => abortRef.current?.abort()}
              aria-label="Stop response"
            >
              <Square className="fill-current" />
            </Button>
          ) : (
            <Button size="icon" onClick={() => void send()} disabled={!input.trim() || showArchived} aria-label="Send message">
              <Send />
            </Button>
          )}
        </div>
        <p className="mt-1.5 text-center text-[10px] text-muted-foreground">
          Subtrack can analyse your records but does not provide investment advice.
        </p>
      </footer>

      <Dialog open={deleteTarget !== null} onOpenChange={open => !open && setDeleteTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete conversation?</DialogTitle>
            <DialogDescription>
              “{deleteTarget?.title}” and its messages will be permanently removed. Your financial records are not affected.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <DialogClose asChild><Button variant="outline">Cancel</Button></DialogClose>
            <Button variant="destructive" disabled={loading} onClick={() => void confirmDelete()}>
              <Trash2 data-icon="inline-start" />
              Delete conversation
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
