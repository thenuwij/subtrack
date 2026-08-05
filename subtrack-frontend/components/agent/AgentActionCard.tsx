'use client'

import { AlertTriangle, Check, CheckCircle2, Clock3, LoaderCircle, X } from 'lucide-react'
import type { AgentAction } from '@/lib/agent/types'
import { Button } from '@/components/ui/button'


function completedCopy(action: AgentAction) {
  if (action.action_type === 'remove_recurring_payment') {
    return 'Removed from Subtrack. The merchant subscription was not cancelled.'
  }
  return 'Completed successfully.'
}

interface AgentActionCardProps {
  action: AgentAction
  busy: 'confirm' | 'reject' | null
  onConfirm: (action: AgentAction) => Promise<void>
  onReject: (action: AgentAction) => Promise<void>
}

export function AgentActionCard({
  action,
  busy,
  onConfirm,
  onReject,
}: AgentActionCardProps) {
  const pending = action.status === 'pending'

  return (
    <section
      className="mt-3 overflow-hidden rounded-xl border border-primary/20 bg-primary/[0.04]"
      aria-label={`Assistant action: ${action.summary}`}
    >
      <div className="p-3">
        <div className="flex items-start gap-2.5">
          <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
            {action.status === 'completed' ? (
              <CheckCircle2 className="h-4 w-4" />
            ) : action.status === 'failed' || action.status === 'expired' ? (
              <AlertTriangle className="h-4 w-4" />
            ) : (
              <Clock3 className="h-4 w-4" />
            )}
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <p className="text-sm font-semibold text-foreground">{action.summary}</p>
              <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${
                pending
                  ? 'bg-amber-500/10 text-amber-700 dark:text-amber-300'
                  : action.status === 'completed'
                    ? 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-300'
                    : 'bg-muted text-muted-foreground'
              }`}>
                {pending ? 'Needs confirmation' : action.status}
              </span>
            </div>
            <p className="mt-1 text-xs leading-5 text-muted-foreground">
              {action.description}
            </p>
            {action.status === 'completed' ? (
              <p className="mt-1.5 text-xs font-medium text-emerald-700 dark:text-emerald-300">
                {completedCopy(action)}
              </p>
            ) : action.status === 'rejected' ? (
              <p className="mt-1.5 text-xs text-muted-foreground">Not applied.</p>
            ) : action.status === 'expired' ? (
              <p className="mt-1.5 text-xs text-muted-foreground">
                This confirmation expired. Ask the assistant to prepare it again.
              </p>
            ) : action.status === 'failed' ? (
              <p role="alert" className="mt-1.5 text-xs text-destructive">
                {action.error_message ?? 'The action could not be completed. No change was applied.'}
              </p>
            ) : null}
          </div>
        </div>
      </div>

      {pending ? (
        <div className="flex flex-wrap justify-end gap-2 border-t border-primary/15 bg-background/60 px-3 py-2.5">
          <Button
            size="sm"
            variant="ghost"
            disabled={busy !== null}
            onClick={() => void onReject(action)}
          >
            {busy === 'reject' ? <LoaderCircle className="animate-spin" /> : <X />}
            Don&apos;t do this
          </Button>
          <Button
            size="sm"
            disabled={busy !== null}
            onClick={() => void onConfirm(action)}
          >
            {busy === 'confirm' ? <LoaderCircle className="animate-spin" /> : <Check />}
            {busy === 'confirm' ? 'Applying…' : 'Confirm'}
          </Button>
        </div>
      ) : null}
    </section>
  )
}
