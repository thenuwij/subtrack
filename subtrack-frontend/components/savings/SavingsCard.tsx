'use client'

import { useState } from 'react'
import { SavingsGoal } from '@/types'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Trash2, Pencil, CheckCircle2 } from 'lucide-react'
import { useCurrency } from '@/lib/context/currency'
import { formatCurrency } from '@/lib/utils/currency'

function getDaysUntil(dateStr: string): number | null {
  const today = new Date()
  const target = new Date(dateStr)
  const startOfToday = new Date(today.getFullYear(), today.getMonth(), today.getDate())
  const startOfTarget = new Date(target.getFullYear(), target.getMonth(), target.getDate())
  return Math.ceil((startOfTarget.getTime() - startOfToday.getTime()) / (1000 * 60 * 60 * 24))
}

interface Props {
  goal: SavingsGoal
  onDelete: (id: string) => Promise<void>
  onEdit: (goal: SavingsGoal) => void
  onComplete: (id: string) => Promise<void>
}

export function SavingsCard({ goal, onDelete, onEdit, onComplete }: Props) {
  const [confirming, setConfirming] = useState(false)
  const [deleting, setDeleting]     = useState(false)
  const [completing, setCompleting] = useState(false)

  const { baseCurrency, convertAmount } = useCurrency()
  const targetInBase  = convertAmount(goal.target_amount, goal.currency ?? baseCurrency)
  const currentInBase = convertAmount(goal.current_amount, goal.currency ?? baseCurrency)
  const pct           = targetInBase > 0 ? Math.min((currentInBase / targetInBase) * 100, 100) : 0
  const isCompleted   = !!goal.completed_at

  const barColor = isCompleted ? 'bg-green-500' : 'bg-primary'

  async function handleDelete() {
    setDeleting(true)
    try {
      await onDelete(goal.id)
    } finally {
      setDeleting(false)
      setConfirming(false)
    }
  }

  async function handleComplete() {
    setCompleting(true)
    try {
      await onComplete(goal.id)
    } finally {
      setCompleting(false)
    }
  }

  return (
    <Card className="group border-0 shadow-[var(--shadow-sm)] hover:shadow-[var(--shadow-md)] transition-shadow duration-200">
      <CardContent className="p-4">
        <div className="flex items-start justify-between gap-3 mb-3">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-0.5">
              <p className="font-medium text-sm truncate">{goal.name}</p>
              {isCompleted && (
                <span className="text-xs font-medium rounded-full px-2.5 py-0.5 bg-green-500/10 text-green-600 dark:text-green-400 shrink-0">
                  Completed
                </span>
              )}
            </div>
            <p className="text-xs text-muted-foreground">
              {formatCurrency(currentInBase, baseCurrency)} of {formatCurrency(targetInBase, baseCurrency)}
            </p>
          </div>

          <div className="shrink-0 text-right">
            <p className={`text-sm font-semibold tabular-nums ${isCompleted ? 'text-green-600 dark:text-green-400' : ''}`}>
              {pct.toFixed(0)}%
            </p>
            {goal.target_date && !isCompleted && (() => {
              const days = getDaysUntil(goal.target_date)
              if (days === null) return null
              return (
                <p className={`text-xs mt-0.5 ${days < 0 ? 'text-destructive' : 'text-muted-foreground'}`}>
                  {days < 0 ? 'Overdue' : days === 0 ? 'Due today' : `${days}d left`}
                </p>
              )
            })()}

            <div className="flex justify-end mt-1 h-7 gap-1">
              {!confirming ? (
                <>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-7 px-2 text-xs text-muted-foreground hover:bg-muted hover:text-foreground"
                    onClick={() => onEdit(goal)}
                    aria-label="Edit goal"
                  >
                    <Pencil className="mr-1 w-3.5 h-3.5" />
                    Edit
                  </Button>
                  {!isCompleted && (
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-7 w-7 text-muted-foreground hover:text-primary hover:bg-primary/10"
                      onClick={handleComplete}
                      disabled={completing}
                      aria-label="Mark as complete"
                    >
                      <CheckCircle2 className="w-3.5 h-3.5" />
                    </Button>
                  )}
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-7 w-7 text-muted-foreground hover:text-destructive hover:bg-destructive/10"
                    onClick={() => setConfirming(true)}
                    aria-label="Delete goal"
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

        <div className="w-full bg-muted rounded-full h-1.5">
          <div
            className={`h-1.5 rounded-full transition-all ${barColor}`}
            style={{ width: `${pct}%` }}
          />
        </div>

        {targetInBase - currentInBase > 0 && !isCompleted && (
          <p className="text-xs text-muted-foreground mt-1.5">
            {formatCurrency(targetInBase - currentInBase, baseCurrency)} remaining
          </p>
        )}
      </CardContent>
    </Card>
  )
}
