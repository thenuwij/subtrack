'use client'

import { useState } from 'react'
import { Subscription } from '@/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Trash2, Calendar, Pencil } from 'lucide-react'
import { useCurrency } from '@/lib/context/currency'

const CATEGORY_STYLES: Record<string, string> = {
  streaming:  'bg-purple-500/10 text-purple-600 dark:text-purple-400',
  software:   'bg-blue-500/10   text-blue-600   dark:text-blue-400',
  cloud:      'bg-sky-500/10    text-sky-600    dark:text-sky-400',
  utilities:  'bg-yellow-500/10 text-yellow-600 dark:text-yellow-400',
  fitness:    'bg-green-500/10  text-green-600  dark:text-green-400',
  food:       'bg-orange-500/10 text-orange-600 dark:text-orange-400',
  transport:  'bg-red-500/10    text-red-600    dark:text-red-400',
  other:      'bg-muted text-muted-foreground',
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

  if (diff < 0)  return { label: 'Overdue',   urgency: 'overdue' }
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
  const { baseCurrency } = useCurrency()

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

  return (
    <Card className="group border-0 shadow-[var(--shadow-sm)] hover:shadow-[var(--shadow-md)] transition-shadow duration-200">
      <CardContent className="p-4">
        <div className="flex items-start justify-between gap-3">

          {/* Left — name, badges */}
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-2">
              <p className="font-medium text-sm truncate">{subscription.name}</p>
              {!subscription.is_active && (
                <Badge variant="outline" className="text-xs shrink-0 text-muted-foreground">
                  Inactive
                </Badge>
              )}
            </div>
            <div className="flex items-center gap-2 flex-wrap">
              <Badge
                variant="secondary"
                className={`text-xs font-medium border-0 rounded-full px-2.5 ${CATEGORY_STYLES[subscription.category]}`}
              >
                {subscription.category}
              </Badge>
              {due && (
                <span className={`text-xs flex items-center gap-1 ${urgencyClass}`}>
                  <Calendar className="w-3 h-3" />
                  {due.label}
                </span>
              )}
            </div>
          </div>

          {/* Right — amount, delete */}
          <div className="shrink-0 text-right">
            <p className="font-semibold text-sm tabular-nums">
              {subscription.currency}{' '}
              {subscription.amount.toFixed(2)}
              <span className="text-xs font-normal text-muted-foreground ml-0.5">
                {CYCLE_LABEL[subscription.cycle]}
              </span>
            </p>
            {subscription.converted_amount != null && subscription.currency !== baseCurrency && (
              <p className='text-xs text-muted-foreground mt-0.5'>
                ≈ {baseCurrency} {subscription.converted_amount.toFixed(2)}
                <span className="ml-1">at {subscription.exchange_rate.toFixed(4)}</span>
              </p>
            )}

            <div className="flex justify-end mt-2 h-7 gap-1">
              {!confirming ? (
                <>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-7 w-7 opacity-0 group-hover:opacity-100 transition-opacity text-muted-foreground hover:text-foreground hover:bg-muted"
                    onClick={() => onEdit(subscription)}
                    aria-label="Edit subscription"
                  >
                    <Pencil className="w-3.5 h-3.5" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-7 w-7 opacity-0 group-hover:opacity-100 transition-opacity text-muted-foreground hover:text-destructive hover:bg-destructive/10"
                    onClick={() => setConfirming(true)}
                    aria-label="Delete subscription"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </Button>
                </>
              ) : (
                <div className="flex items-center gap-1">
                  <Button
                    variant="destructive"
                    size="sm"
                    className="h-7 text-xs px-2"
                    onClick={handleDelete}
                    disabled={deleting}
                  >
                    {deleting ? 'Deleting…' : 'Delete'}
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-7 text-xs px-2"
                    onClick={() => setConfirming(false)}
                    disabled={deleting}
                  >
                    Cancel
                  </Button>
                </div>
              )}
            </div>
          </div>

        </div>
      </CardContent>
    </Card>
  )
}