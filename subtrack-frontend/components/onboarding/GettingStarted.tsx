'use client'

import Link from 'next/link'
import { Check, X } from 'lucide-react'
import { listAgentThreads } from '@/lib/agent/api'
import type { AgentThread } from '@/lib/agent/types'
import { apiKeys, useApi } from '@/lib/hooks/useApi'
import { useStoredString } from '@/lib/hooks/useStoredState'

const HIDDEN_KEY = 'subtrack:getting-started-hidden'
const ASSISTANT_PROMPT = 'What do my recurring payments cost each month?'

interface GettingStartedProps {
  gmailConnected: boolean
  hasPayments: boolean
  hasIncome: boolean
}

export function GettingStarted({ gmailConnected, hasPayments, hasIncome }: GettingStartedProps) {
  const [hidden, setHidden] = useStoredString(HIDDEN_KEY, '')
  const threads = useApi<AgentThread[]>(apiKeys.agentThreads, token => listAgentThreads(token))
  const askedAssistant = (threads.data ?? []).some(thread => thread.message_count > 0)

  const items = [
    {
      done: gmailConnected,
      label: 'Connect Gmail',
      detail: 'Subtrack finds recurring payments in your receipts.',
      href: '/account#inbox',
    },
    {
      done: hasPayments,
      label: 'Approve or add your first payment',
      detail: gmailConnected ? 'Review what Subtrack found in your inbox.' : 'Or add one by hand.',
      href: gmailConnected ? '/review' : '/subscriptions',
    },
    {
      done: hasIncome,
      label: 'Add your monthly income',
      detail: 'See your payments as a share of what you earn.',
      href: '/account',
    },
    {
      done: askedAssistant,
      label: 'Ask the assistant a question',
      detail: 'Try asking what your payments cost each month.',
      onClick: () => {
        window.dispatchEvent(new CustomEvent('subtrack:ask-agent', {
          detail: { prompt: ASSISTANT_PROMPT },
        }))
      },
    },
  ]
  const completed = items.filter(item => item.done).length

  if (hidden || completed === items.length || threads.isLoading) return null

  return (
    <section className="rounded-2xl bg-card p-5 text-left shadow-sm" aria-labelledby="getting-started-heading">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 id="getting-started-heading" className="text-sm font-semibold text-foreground">Getting started</h2>
          <p className="mt-0.5 text-xs text-muted-foreground tabular-nums">
            {completed} of {items.length} done
          </p>
        </div>
        <button
          type="button"
          onClick={() => setHidden('1')}
          aria-label="Hide getting started checklist"
          className="flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-muted">
        <div
          className="h-full rounded-full bg-primary transition-all"
          style={{ width: `${(completed / items.length) * 100}%` }}
        />
      </div>

      <ul className="mt-4 space-y-1">
        {items.map(item => {
          const content = (
            <>
              <span
                className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border ${
                  item.done
                    ? 'border-primary bg-primary text-primary-foreground'
                    : 'border-border'
                }`}
              >
                {item.done ? <Check className="h-3 w-3" /> : null}
              </span>
              <span className="min-w-0">
                <span className={`block text-sm font-medium ${item.done ? 'text-muted-foreground line-through' : 'text-foreground'}`}>
                  {item.label}
                </span>
                {!item.done ? (
                  <span className="mt-0.5 block text-xs text-muted-foreground">{item.detail}</span>
                ) : null}
              </span>
            </>
          )
          const className = 'flex w-full items-start gap-3 rounded-lg px-2 py-2 text-left transition-colors hover:bg-muted'
          return (
            <li key={item.label}>
              {item.done ? (
                <div className="flex items-start gap-3 px-2 py-2">{content}</div>
              ) : item.href ? (
                <Link href={item.href} className={className}>{content}</Link>
              ) : (
                <button type="button" onClick={item.onClick} className={className}>{content}</button>
              )}
            </li>
          )
        })}
      </ul>
    </section>
  )
}
