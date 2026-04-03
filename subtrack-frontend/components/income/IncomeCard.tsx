'use client'

import { useState } from 'react'
import { Income } from '@/types'
import { Button } from '@/components/ui/button'
import { Trash2, Pencil } from 'lucide-react'
import { useCurrency } from '@/lib/context/currency'
import { formatCurrency } from '@/lib/utils/currency'

const FREQUENCY_DOT: Record<string, string> = {
  weekly:      'bg-green-500',
  fortnightly: 'bg-blue-500',
  monthly:     'bg-primary',
  irregular:   'bg-muted-foreground',
}

interface Props {
  income: Income
  onDelete: (id: string) => Promise<void>
  onEdit: (income: Income) => void
}

export function IncomeCard({ income, onDelete, onEdit }: Props) {
  const [confirming, setConfirming] = useState(false)
  const [deleting, setDeleting]     = useState(false)
  const { baseCurrency } = useCurrency()

  async function handleDelete() {
    setDeleting(true)
    try {
      await onDelete(income.id)
    } finally {
      setDeleting(false)
      setConfirming(false)
    }
  }

  const dotClass = FREQUENCY_DOT[income.frequency] ?? 'bg-muted-foreground'
  const dateLabel = new Date(income.date).toLocaleDateString('en-AU', { day: 'numeric', month: 'short' })

  return (
    <div className="flex items-center justify-between gap-4 px-4 py-3 hover:bg-muted/40 transition-colors group">

      {/* Left — dot + source + subtitle */}
      <div className="flex items-center gap-3 flex-1 min-w-0">
        <span className={`w-2 h-2 rounded-full shrink-0 ${dotClass}`} />
        <div className="min-w-0">
          <p className="font-medium text-sm truncate leading-tight">{income.source || 'Income'}</p>
          <p className="text-xs text-muted-foreground mt-0.5 truncate">
            {income.frequency}
            {income.note && <span className="ml-1.5">· {income.note}</span>}
          </p>
        </div>
      </div>

      {/* Right — amount + actions */}
      <div className="shrink-0 flex items-center gap-3">
        <div className="text-right">
          <p className="font-semibold text-sm tabular-nums leading-tight">
            {formatCurrency(income.amount, income.currency)}
          </p>
          {income.converted_amount != null && income.currency !== baseCurrency ? (
            <p className="text-xs text-muted-foreground mt-0.5">
              ≈ {formatCurrency(income.converted_amount, baseCurrency)}
            </p>
          ) : (
            <p className="text-xs text-muted-foreground mt-0.5">{dateLabel}</p>
          )}
        </div>

        {!confirming ? (
          <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7 text-muted-foreground hover:text-foreground hover:bg-muted"
              onClick={() => onEdit(income)}
              aria-label="Edit income"
            >
              <Pencil className="w-3.5 h-3.5" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7 text-muted-foreground hover:text-destructive hover:bg-destructive/10"
              onClick={() => setConfirming(true)}
              aria-label="Delete income"
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
