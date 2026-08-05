'use client'

import { useState } from 'react'
import { Subscription } from '@/types'
import { Button } from '@/components/ui/button'
import { Bell, Clock3, Trash2, Pencil, Sparkles } from 'lucide-react'
import { useCurrency } from '@/lib/context/currency'
import { formatCurrency } from '@/lib/utils/currency'
import { categoryColor, formatCategory } from '@/lib/utils/categories'
import { isActiveTrial } from '@/lib/utils/trials'

const CYCLE_LABEL: Record<string, string> = {
  weekly:  '/wk',
  monthly: '/mo',
  yearly:  '/yr',
}

// Just the date it next goes out. Subtrack isn't tracking whether payments landed,
// so anything framed as overdue/due-soon would be claiming knowledge it doesn't have.
function formatNextDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString('en-AU', { day: 'numeric', month: 'short' })
}

interface Props {
  subscription: Subscription
  onDelete: (id: string) => Promise<void>
  onEdit: (subscription: Subscription) => void
  onReminders: (subscription: Subscription) => void
  onAskAssistant?: (subscription: Subscription) => void
}

export function SubscriptionCard({
  subscription,
  onDelete,
  onEdit,
  onReminders,
  onAskAssistant,
}: Props) {
  const [confirming, setConfirming] = useState(false)
  const [deleting, setDeleting]     = useState(false)
  const { baseCurrency, convertAmount } = useCurrency()

  const nextDate = subscription.next_due ? formatNextDate(subscription.next_due) : null
  const trialEnd = subscription.trial_ends_at
    ? formatNextDate(subscription.trial_ends_at)
    : null
  const trialActive = isActiveTrial(subscription)

  async function handleDelete() {
    setDeleting(true)
    try {
      await onDelete(subscription.id)
    } finally {
      setDeleting(false)
      setConfirming(false)
    }
  }

  return (
    <div className="flex flex-col gap-3 px-4 py-3 transition-colors hover:bg-muted/40 sm:flex-row sm:items-center sm:justify-between sm:gap-4">

      {/* Left — dot + name + subtitle */}
      <div className="flex items-center gap-3 flex-1 min-w-0">
        <span
          className="w-2 h-2 rounded-full shrink-0"
          style={{ backgroundColor: categoryColor(subscription.category) }}
          aria-hidden="true"
        />
        <div className="min-w-0">
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <p className="truncate text-sm font-medium leading-tight">{subscription.name}</p>
            {trialActive ? (
              <span className="inline-flex items-center gap-1 rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-semibold text-primary">
                <Clock3 className="h-3 w-3" />
                Free trial
              </span>
            ) : null}
          </div>
          <p className="text-xs text-muted-foreground mt-0.5">
            {formatCategory(subscription.category)}
            {trialActive && trialEnd
              ? <span className="ml-1.5">· trial ends {trialEnd}</span>
              : nextDate && <span className="ml-1.5">· next {nextDate}</span>}
            {subscription.full_amount != null && (
              <span className="ml-1.5">
                · your share of{' '}
                {formatCurrency(subscription.full_amount, subscription.currency)}
              </span>
            )}
          </p>
        </div>
      </div>

      {/* Right — amount + actions */}
      <div className="flex shrink-0 items-center justify-between gap-3 pl-5 sm:justify-start sm:pl-0">
        <div className="text-right">
          <p className="font-semibold text-sm tabular-nums leading-tight">
            {formatCurrency(subscription.amount, subscription.currency)}
            <span className="text-xs font-normal text-muted-foreground ml-0.5">
              {CYCLE_LABEL[subscription.cycle]}
            </span>
          </p>
          {trialActive ? (
            <p className="mt-0.5 text-[10px] font-medium text-primary">after trial</p>
          ) : null}
          {subscription.currency !== baseCurrency && (
            <p className="text-xs text-muted-foreground mt-0.5">
              ≈ {formatCurrency(convertAmount(subscription.amount, subscription.currency), baseCurrency)}
            </p>
          )}
        </div>

        {!confirming ? (
          <div className="flex gap-1">
            {onAskAssistant ? (
              <Button
                variant="ghost"
                size="icon"
                className="h-7 w-7 text-muted-foreground hover:bg-primary/10 hover:text-primary"
                onClick={() => onAskAssistant(subscription)}
                aria-label={`Ask the assistant about cheaper alternatives to ${subscription.name}`}
                title="Compare current alternatives"
              >
                <Sparkles className="h-3.5 w-3.5" />
              </Button>
            ) : null}
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7 text-muted-foreground hover:bg-primary/10 hover:text-primary"
              onClick={() => onReminders(subscription)}
              aria-label={`Manage reminders for ${subscription.name}`}
            >
              <Bell className="h-3.5 w-3.5" />
            </Button>
            <Button
              variant="ghost"
              size="sm"
              className="h-7 px-2 text-xs text-muted-foreground hover:bg-muted hover:text-foreground"
              onClick={() => onEdit(subscription)}
              aria-label="Edit recurring payment"
            >
              <Pencil className="mr-1 h-3.5 w-3.5" />
              Edit
            </Button>
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7 text-muted-foreground hover:text-destructive hover:bg-destructive/10"
              onClick={() => setConfirming(true)}
              aria-label="Delete recurring payment"
            >
              <Trash2 className="w-3.5 h-3.5" />
            </Button>
          </div>
        ) : (
          <div className="flex items-center gap-1">
            <Button variant="destructive" size="sm" className="h-7 text-xs px-2" onClick={handleDelete} disabled={deleting}>
              {deleting ? 'Deleting…' : 'Delete'}
            </Button>
            <Button variant="ghost" size="sm" className="h-7 text-xs px-2" onClick={() => setConfirming(false)} disabled={deleting}>
              Cancel
            </Button>
          </div>
        )}
      </div>

    </div>
  )
}
