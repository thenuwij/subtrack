'use client'

import { useEffect, useState } from 'react'
import { createClient } from '@/lib/supabase/client'
import { getBudgets, createBudget, deleteBudget, getExpenses } from '@/lib/api'
import { Budget, Expense, Category } from '@/types'
import { BudgetCard }       from '@/components/budgets/BudgetCard'
import { AddBudgetModal }   from '@/components/budgets/AddBudgetModal'
import { Button }           from '@/components/ui/button'
import { Skeleton }         from '@/components/ui/skeleton'
import { Plus, PieChart }   from 'lucide-react'
import { toast } from 'sonner'

export default function BudgetsPage() {
  const supabase = createClient()

  const [budgets, setBudgets]   = useState<Budget[]>([])
  const [expenses, setExpenses] = useState<Expense[]>([])
  const [loading, setLoading]   = useState(true)
  const [error, setError]       = useState<string | null>(null)
  const [modalOpen, setModalOpen] = useState(false)

  async function fetchData() {
    const { data: { session } } = await supabase.auth.getSession()
    if (!session) return
    try {
      const [buds, exps] = await Promise.all([
        getBudgets(session.access_token),
        getExpenses(session.access_token),
      ])
      setBudgets(buds)
      setExpenses(exps)
    } catch (e: any) {
      setError(e?.message ?? 'Failed to load budgets.')
      toast.error('Something went wrong')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchData() }, []) // eslint-disable-line

  async function handleAdd(formData: Omit<Budget, 'id' | 'user_id' | 'created_at'>) {
    const { data: { session } } = await supabase.auth.getSession()
    if (!session) throw new Error('Not authenticated')
    const created = await createBudget(session.access_token, formData)
    setBudgets(prev => [...prev, created])
    toast.success('Budget saved')
  }

  async function handleDelete(id: string) {
    const { data: { session } } = await supabase.auth.getSession()
    if (!session) throw new Error('Not authenticated')
    await deleteBudget(session.access_token, id)
    setBudgets(prev => prev.filter(b => b.id !== id))
    toast.success('Budget deleted')
  }

  const thisMonth = new Date()
  const monthlyExpenses = expenses.filter(e => {
    const d = new Date(e.date)
    return d.getMonth() === thisMonth.getMonth() &&
      d.getFullYear() === thisMonth.getFullYear()
  })

  function spentForCategory(category: string) {
    return monthlyExpenses
      .filter(e => e.category === category)
      .reduce((sum, e) => sum + (e.converted_amount ?? e.amount), 0)
  }

  const existingCategories = budgets.map(b => b.category as Category)

  return (
    <div className="max-w-2xl mx-auto px-4 py-8 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Budgets</h1>
          {!loading && budgets.length > 0 && (
            <p className="text-sm text-muted-foreground mt-0.5">
              {budgets.length} {budgets.length === 1 ? 'category' : 'categories'} tracked
            </p>
          )}
        </div>
        <Button
          onClick={() => setModalOpen(true)}
          size="sm"
          disabled={existingCategories.length === 8}
        >
          <Plus className="w-4 h-4 mr-1.5" />
          Add
        </Button>
      </div>

      {error && (
        <div className="rounded-md border border-destructive/40 bg-destructive/5 px-4 py-3">
          <p className="text-sm text-destructive">{error}</p>
          <button
            className="text-xs text-destructive underline underline-offset-2 mt-1"
            onClick={() => { setError(null); setLoading(true); fetchData() }}
          >
            Try again
          </button>
        </div>
      )}

      {loading && (
        <div className="space-y-3">
          {[...Array(4)].map((_, i) => (
            <Skeleton key={i} className="h-[100px] w-full rounded-lg" />
          ))}
        </div>
      )}

      {!loading && !error && budgets.length === 0 && (
        <div className="flex flex-col items-center justify-center py-20 text-center">
          <div className="rounded-full bg-muted p-4 mb-4">
            <PieChart className="w-6 h-6 text-muted-foreground" />
          </div>
          <p className="font-medium text-sm">No budgets set yet</p>
          <p className="text-sm text-muted-foreground mt-1 mb-4">
            Set a monthly limit per category to start tracking.
          </p>
          <Button size="sm" onClick={() => setModalOpen(true)}>
            <Plus className="w-4 h-4 mr-1.5" />
            Set budget
          </Button>
        </div>
      )}

      {!loading && budgets.length > 0 && (
        <div className="space-y-2.5">
          {budgets.map(b => (
            <BudgetCard
              key={b.id}
              budget={b}
              spent={spentForCategory(b.category)}
              onDelete={handleDelete}
            />
          ))}
        </div>
      )}

      <AddBudgetModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        existingCategories={existingCategories}
        onSubmit={handleAdd}
      />
    </div>
  )
}