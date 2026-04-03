'use client'

import { useState } from 'react'
import { Expense } from '@/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Trash2, Pencil} from 'lucide-react'
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

interface Props {
  expense: Expense
  onDelete: (id: string) => Promise<void>
  onEdit: (expense: Expense) => void
}

export function ExpenseCard({ expense, onDelete, onEdit }: Props) {
  const [confirming, setConfirming] = useState(false)
  const [deleting, setDeleting]     = useState(false)
  const { baseCurrency } = useCurrency()

  async function handleDelete() {
    setDeleting(true)
    try {
      await onDelete(expense.id)
    } finally {
      setDeleting(false)
      setConfirming(false)
    }
  }

  return (
    <Card className="group border-0 shadow-[var(--shadow-sm)] hover:shadow-[var(--shadow-md)] transition-shadow duration-200">
      <CardContent className="p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-2">
              <p className="font-medium text-sm truncate">{expense.name}</p>
            </div>
            <div className="flex items-center gap-2 flex-wrap">
              <Badge
                variant="secondary"
                className={`text-xs font-medium border-0 rounded-full px-2.5 ${CATEGORY_STYLES[expense.category]}`}
              >
                {expense.category}
              </Badge>
              {expense.note && (
                <span className="text-xs text-muted-foreground truncate max-w-[200px]">
                  {expense.note}
                </span>
              )}
            </div>
          </div>

          <div className="shrink-0 text-right">
            <p className="font-semibold text-sm tabular-nums">
              {expense.currency} {expense.amount.toFixed(2)}
            </p>
            {expense.converted_amount != null && expense.currency !== baseCurrency && (
              <p className="text-xs text-muted-foreground mt-0.5">
                ≈ {baseCurrency} {expense.converted_amount.toFixed(2)}
                <span className="ml-1">at {expense.exchange_rate.toFixed(4)}</span>
              </p>
            )}

            <p className="text-xs text-muted-foreground mt-0.5">
              {new Date(expense.date).toLocaleDateString('en-AU')}
            </p>
            <div className="flex justify-end mt-2 h-7 gap-1">
              {!confirming ? (
                <>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-7 w-7 opacity-0 group-hover:opacity-100 transition-opacity text-muted-foreground hover:text-foreground hover:bg-muted"
                    onClick={() => onEdit(expense)}
                    aria-label="Edit expense"
                  >
                    <Pencil className="w-3.5 h-3.5" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-7 w-7 opacity-0 group-hover:opacity-100 transition-opacity text-muted-foreground hover:text-destructive hover:bg-destructive/10"
                    onClick={() => setConfirming(true)}
                    aria-label="Delete expense"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </Button>
                </>
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
        </div>
      </CardContent>
    </Card>
  )
}