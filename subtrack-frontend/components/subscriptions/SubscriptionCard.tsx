'use client'

import { useState } from 'react'
import { Subscription } from '@/types'
import { Button } from '@/components/ui/button'
import { Trash2, Pencil } from 'lucide-react'
import { useCurrency } from '@/lib/context/currency'
import { formatCurrency } from '@/lib/utils/currency'

const CATEGORY_DOT: Record<string, string> = {
  streaming:  'bg-purple-500',
  software:   'bg-blue-500',
  cloud:      'bg-sky-500',
  utilities:  'bg-yellow-500',
  fitness:    'bg-green-500',
  food:       'bg-orange-500',
  transport:  'bg-red-500',
  other:      'bg-muted-foreground',
}

const CYCLE_LABEL: Record<string, string> = {
  weekly:  '/wk',
  monthly: '/mo',
  yearly:  '/yr',
}

function formatDueDate(dateStr: string): { label: string; urgency: 'overdue' | 'soon' | 'normal' } {
  const due = new Date(dateStr)
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  due.setHours(0, 0, 0, 0)
  const diff = Math.round((due.getTime() - today.getTime()) / (1000 * 60 * 60 * 24))

  if (diff < 0)   return { label: 'Overdue',   urgency: 'overdue' }
  if (diff === 0) return { label: 'Due today', urgency: 'soon'    }
  if (diff <= 7)  return { label: `${diff}d`,  urgency: 'soon'    }

  return {
    label: due.toLocaleDateString('en-AU', { day: 'numeric', month: 'short' }),
    urgency: 'normal',
  }
}

interface Props {
  subscription: Subscription
  onDelete: (id: string) => Promise<void>
  onEdit: (subscription: Subscription) => void
}

export function SubscriptionCard({ subscription, onDelete, onEdit }: Props) {
  const [confirming, setConfirming] = useState(false)
  const [deleting, setDeleting]     = useState(false)
  const { baseCurrency, convertAmount } = useCurrency()

  const due = subscription.next_due ? formatDueDate(subscription.next_due) : null

  const urgencyClass =
    due?.urgency === 'overdue' ? 'text-destructive' :
    due?.urgency === 'soon'    ? 'text-amber-500'   :
                                 'text-muted-foreground'

  async function handleDelete() {
    setDeleting(true)
    try {
      await onDelete(subscription.id)
    } finally {
      setDeleting(false)
      setConfirming(false)
    }
  }

  const dotClass = CATEGORY_DOT[subscription.category] ?? 'bg-muted-foreground'

  return (
    <div className="flex items-center justify-between gap-4 px-4 py-3 hover:bg-muted/40 transition-colors group">

      {/* Left — dot + name + subtitle */}
      <div className="flex items-center gap-3 flex-1 min-w-0">
        <span className={`w-2 h-2 rounded-full shrink-0 ${dotClass}`} />
        <div className="min-w-0">
          <p className="font-medium text-sm truncate leading-tight">{subscription.name}</p>
          <p className="text-xs text-muted-foreground mt-0.5">
            {subscription.category}
            {due && (
              <span className={`ml-1.5 ${urgencyClass}`}>· {due.label}</span>
            )}
          </p>
        </div>
      </div>

      {/* Right — amount + actions */}
      <div className="shrink-0 flex items-center gap-3">
        <div className="text-right">
          <p className="font-semibold text-sm tabular-nums leading-tight">
            {formatCurrency(subscription.amount, subscription.currency)}
            <span className="text-xs font-normal text-muted-foreground ml-0.5">
              {CYCLE_LABEL[subscription.cycle]}
            </span>
          </p>
          {subscription.currency !== baseCurrency && (
            <p className="text-xs text-muted-foreground mt-0.5">
              ≈ {formatCurrency(convertAmount(subscription.amount, subscription.currency), baseCurrency)}
            </p>
          )}
        </div>

        {!confirming ? (
          <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7 text-muted-foreground hover:text-foreground hover:bg-muted"
              onClick={() => onEdit(subscription)}
              aria-label="Edit subscription"
            >
              <Pencil className="w-3.5 h-3.5" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7 text-muted-foreground hover:text-destructive hover:bg-destructive/10"
              onClick={() => setConfirming(true)}
              aria-label="Delete subscription"
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
