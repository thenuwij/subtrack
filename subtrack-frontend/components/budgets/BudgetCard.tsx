'use client'

import { useState } from 'react'
import { Budget } from '@/types'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Trash2 } from 'lucide-react'

interface Props {
  budget: Budget
  spent: number
  onDelete: (id: string) => Promise<void>
}

export function BudgetCard({ budget, spent, onDelete }: Props) {
  const [confirming, setConfirming] = useState(false)
  const [deleting, setDeleting]     = useState(false)

  const pct     = Math.min((spent / budget.monthly_limit) * 100, 100)
  const overBudget = spent > budget.monthly_limit

  const barColor = overBudget ? 'bg-red-400' : pct >= 80 ? 'bg-yellow-400' : 'bg-green-400'

  async function handleDelete() {
    setDeleting(true)
    try {
      await onDelete(budget.id)
    } finally {
      setDeleting(false)
      setConfirming(false)
    }
  }

  return (
    <Card className="group">
      <CardContent className="p-4">
        <div className="flex items-start justify-between gap-3 mb-3">
          <div>
            <p className="font-medium text-sm capitalize">{budget.category}</p>
            <p className="text-xs text-muted-foreground mt-0.5">
              {budget.currency} {spent.toFixed(2)} of {budget.monthly_limit.toFixed(2)}
            </p>
          </div>
          <div className="shrink-0 text-right">
            <p className={`text-sm font-semibold tabular-nums ${overBudget ? 'text-destructive' : ''}`}>
              {pct.toFixed(0)}%
            </p>
            <div className="flex justify-end mt-1 h-7">
              {!confirming ? (
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-7 w-7 opacity-0 group-hover:opacity-100 transition-opacity
                             text-muted-foreground hover:text-destructive hover:bg-destructive/10"
                  onClick={() => setConfirming(true)}
                  aria-label="Delete budget"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </Button>
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

        <div className="w-full bg-muted rounded-full h-1.5">
          <div
            className={`h-1.5 rounded-full transition-all ${barColor}`}
            style={{ width: `${pct}%` }}
          />
        </div>

        {overBudget && (
          <p className="text-xs text-destructive mt-1.5">
            Over budget by {budget.currency} {(spent - budget.monthly_limit).toFixed(2)}
          </p>
        )}
      </CardContent>
    </Card>
  )
}