'use client'

import { useEffect, useState } from 'react'
import { createClient } from '@/lib/supabase/client'
import { getExpenses, createExpense, deleteExpense } from '@/lib/api'
import { Expense } from '@/types'
import { ExpenseCard }       from '@/components/expenses/ExpenseCard'
import { AddExpenseModal }   from '@/components/expenses/AddExpenseModal'
import { Button }            from '@/components/ui/button'
import { Skeleton }          from '@/components/ui/skeleton'
import { Plus, Receipt }     from 'lucide-react'

export default function ExpensesPage() {
  const supabase = createClient()

  const [expenses, setExpenses]   = useState<Expense[]>([])
  const [loading, setLoading]     = useState(true)
  const [error, setError]         = useState<string | null>(null)
  const [modalOpen, setModalOpen] = useState(false)

  async function fetchExpenses() {
    const { data: { session } } = await supabase.auth.getSession()
    if (!session) return
    try {
      const data = await getExpenses(session.access_token)
      setExpenses(data)
    } catch (e: any) {
      setError(e?.message ?? 'Failed to load expenses.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchExpenses() }, []) // eslint-disable-line

  async function handleAdd(formData: Omit<Expense, 'id' | 'user_id' | 'created_at'>) {
    const { data: { session } } = await supabase.auth.getSession()
    if (!session) throw new Error('Not authenticated')
    const created = await createExpense(session.access_token, formData)
    setExpenses(prev => [created, ...prev])
  }

  async function handleDelete(id: string) {
    const { data: { session } } = await supabase.auth.getSession()
    if (!session) throw new Error('Not authenticated')
    await deleteExpense(session.access_token, id)
    setExpenses(prev => prev.filter(e => e.id !== id))
  }

  const thisMonth = new Date()
  const monthlyTotal = expenses
    .filter(e => {
      const d = new Date(e.date)
      return d.getMonth() === thisMonth.getMonth() &&
        d.getFullYear() === thisMonth.getFullYear()
    })
    .reduce((sum, e) => sum + e.amount, 0)

  return (
    <div className="max-w-2xl mx-auto px-4 py-8 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Expenses</h1>
          {!loading && expenses.length > 0 && (
            <p className="text-sm text-muted-foreground mt-0.5">
              {expenses[0]?.currency ?? 'AUD'} {monthlyTotal.toFixed(2)} this month
            </p>
          )}
        </div>
        <Button onClick={() => setModalOpen(true)} size="sm">
          <Plus className="w-4 h-4 mr-1.5" />
          Add
        </Button>
      </div>

      {error && (
        <div className="rounded-md border border-destructive/40 bg-destructive/5 px-4 py-3">
          <p className="text-sm text-destructive">{error}</p>
          <button
            className="text-xs text-destructive underline underline-offset-2 mt-1"
            onClick={() => { setError(null); setLoading(true); fetchExpenses() }}
          >
            Try again
          </button>
        </div>
      )}

      {loading && (
        <div className="space-y-3">
          {[...Array(4)].map((_, i) => (
            <Skeleton key={i} className="h-[76px] w-full rounded-lg" />
          ))}
        </div>
      )}

      {!loading && !error && expenses.length === 0 && (
        <div className="flex flex-col items-center justify-center py-20 text-center">
          <div className="rounded-full bg-muted p-4 mb-4">
            <Receipt className="w-6 h-6 text-muted-foreground" />
          </div>
          <p className="font-medium text-sm">No expenses yet</p>
          <p className="text-sm text-muted-foreground mt-1 mb-4">
            Log your first expense to start tracking.
          </p>
          <Button size="sm" onClick={() => setModalOpen(true)}>
            <Plus className="w-4 h-4 mr-1.5" />
            Log expense
          </Button>
        </div>
      )}

      {!loading && expenses.length > 0 && (
        <div className="space-y-2.5">
          {expenses.map(exp => (
            <ExpenseCard
              key={exp.id}
              expense={exp}
              onDelete={handleDelete}
            />
          ))}
        </div>
      )}

      <AddExpenseModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        onSubmit={handleAdd}
      />
    </div>
  )
}