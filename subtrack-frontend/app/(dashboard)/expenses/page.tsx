'use client'

import { useEffect, useState, useMemo } from 'react'
import { createClient } from '@/lib/supabase/client'
import { getExpenses, createExpense, deleteExpense, updateExpense } from '@/lib/api'
import { Expense } from '@/types'
import { ExpenseCard }     from '@/components/expenses/ExpenseCard'
import { AddExpenseModal } from '@/components/expenses/AddExpenseModal'
import { FilterBar }       from '@/components/shared/FilterBar'
import { Button }          from '@/components/ui/button'
import { Skeleton }        from '@/components/ui/skeleton'
import { Plus, Receipt }   from 'lucide-react'
import { useCurrency }     from '@/lib/context/currency'
import { formatCurrency }  from '@/lib/utils/currency'
import { toast } from 'sonner'

function inPeriod(dateStr: string, period: 'all' | 'day' | 'week' | 'month'): boolean {
  if (period === 'all') return true
  const d = new Date(dateStr)
  const now = new Date()
  if (period === 'day') return d.toDateString() === now.toDateString()
  if (period === 'week') {
    const week = new Date(now); week.setDate(now.getDate() - 7)
    return d >= week
  }
  if (period === 'month') {
    return d.getMonth() === now.getMonth() && d.getFullYear() === now.getFullYear()
  }
  return true
}

export default function ExpensesPage() {
  const supabase = createClient()

  const [expenses, setExpenses]   = useState<Expense[]>([])
  const [loading, setLoading]     = useState(true)
  const [error, setError]         = useState<string | null>(null)
  const [modalOpen, setModalOpen] = useState(false)
  const [editingExpense, setEditingExpense] = useState<Expense | null>(null)
  const { baseCurrency, convertAmount } = useCurrency()

  // filter / sort / group state
  const [search, setSearch]                     = useState('')
  const [selectedCategory, setSelectedCategory] = useState('')
  const [period, setPeriod]                     = useState<'all' | 'day' | 'week' | 'month'>('all')
  const [fromDate, setFromDate]                 = useState('')
  const [toDate, setToDate]                     = useState('')
  const [sortOrder, setSortOrder]               = useState<'desc' | 'asc'>('desc')
  const [groupByCategory, setGroupByCategory]   = useState(false)

  // ── fetch ──────────────────────────────────────────────────────────────────

  async function fetchExpenses() {
    const { data: { session } } = await supabase.auth.getSession()
    if (!session) return
    try {
      const data = await getExpenses(session.access_token)
      setExpenses(data)
    } catch (e: any) {
      setError(e?.message ?? 'Failed to load expenses.')
      toast.error('Something went wrong')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchExpenses() }, []) // eslint-disable-line

  // ── add ────────────────────────────────────────────────────────────────────

  async function handleAdd(formData: Omit<Expense, 'id' | 'user_id' | 'created_at'>) {
    const { data: { session } } = await supabase.auth.getSession()
    if (!session) throw new Error('Not authenticated')
    const created = await createExpense(session.access_token, formData)
    setExpenses(prev => [created, ...prev])
    toast.success('Expense logged')
  }

  // ── update ─────────────────────────────────────────────────────────────────

  async function handleEdit(formData: Omit<Expense, 'id' | 'user_id' | 'created_at'>) {
    const { data: { session } } = await supabase.auth.getSession()
    if (!session || !editingExpense) throw new Error('Not authenticated')
    const updated = await updateExpense(session.access_token, editingExpense.id, formData)
    setExpenses(prev => prev.map(e => e.id === editingExpense.id ? updated : e))
    setEditingExpense(null)
    toast.success('Expense updated')
  }

  // ── delete ─────────────────────────────────────────────────────────────────

  async function handleDelete(id: string) {
    const { data: { session } } = await supabase.auth.getSession()
    if (!session) throw new Error('Not authenticated')
    await deleteExpense(session.access_token, id)
    setExpenses(prev => prev.filter(e => e.id !== id))
    toast.success('Expense deleted')
  }

  // ── derived stats ──────────────────────────────────────────────────────────

  const thisMonth = new Date()
  const monthlyTotal = expenses
    .filter(e => {
      const d = new Date(e.date)
      return d.getMonth() === thisMonth.getMonth() && d.getFullYear() === thisMonth.getFullYear()
    })
    .reduce((sum, e) => sum + convertAmount(e.amount, e.currency), 0)

  // ── filter / sort ──────────────────────────────────────────────────────────

  const categories = useMemo(
    () => [...new Set(expenses.map(e => e.category))].sort(),
    [expenses]
  )

  const filtered = useMemo(() => {
    let list = expenses.filter(e => {
      if (search && !e.name.toLowerCase().includes(search.toLowerCase())) return false
      if (selectedCategory && e.category !== selectedCategory) return false
      if (!inPeriod(e.date, period)) return false
      if (fromDate && e.date < fromDate) return false
      if (toDate   && e.date > toDate)   return false
      return true
    })
    list = [...list].sort((a, b) =>
      sortOrder === 'desc'
        ? new Date(b.date).getTime() - new Date(a.date).getTime()
        : new Date(a.date).getTime() - new Date(b.date).getTime()
    )
    return list
  }, [expenses, search, selectedCategory, period, fromDate, toDate, sortOrder])

  const totalAmount = filtered.reduce((sum, e) => sum + convertAmount(e.amount, e.currency), 0)
  const totalLabel  = filtered.length > 0
    ? `${filtered.length} item${filtered.length !== 1 ? 's' : ''} · ${formatCurrency(totalAmount, baseCurrency)} total`
    : ''

  const isFiltered = !!(search || selectedCategory || period !== 'all' || fromDate || toDate)

  // ── grouped render helper ──────────────────────────────────────────────────

  function renderList(items: Expense[]) {
    return (
      <div className="rounded-2xl bg-card shadow-md overflow-hidden divide-y divide-border">
        {items.map(exp => (
          <ExpenseCard
            key={exp.id}
            expense={exp}
            onDelete={handleDelete}
            onEdit={setEditingExpense}
          />
        ))}
      </div>
    )
  }

  function renderGrouped(items: Expense[]) {
    const groups = items.reduce<Record<string, Expense[]>>((acc, e) => {
      ;(acc[e.category] ??= []).push(e)
      return acc
    }, {})
    return (
      <div className="space-y-4">
        {Object.entries(groups).map(([cat, group]) => (
          <div key={cat}>
            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-1.5 px-1 capitalize">
              {cat}
            </p>
            {renderList(group)}
          </div>
        ))}
      </div>
    )
  }

  // ─── render ────────────────────────────────────────────────────────────────

  return (
    <div className="mx-auto w-full max-w-5xl px-4 py-8 space-y-6">

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Expenses</h1>
          {!loading && expenses.length > 0 && (
            <p className="text-sm text-muted-foreground mt-0.5">
              {formatCurrency(monthlyTotal, baseCurrency)} this month
            </p>
          )}
        </div>
        <Button onClick={() => setModalOpen(true)} size="sm">
          <Plus className="w-4 h-4 mr-1.5" />
          Add
        </Button>
      </div>

      {/* Error */}
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

      {/* Loading */}
      {loading && (
        <div className="space-y-3">
          {[...Array(4)].map((_, i) => (
            <Skeleton key={i} className="h-[52px] w-full rounded-lg" />
          ))}
        </div>
      )}

      {/* True empty state */}
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

      {/* FilterBar + list */}
      {!loading && expenses.length > 0 && (
        <>
          <FilterBar
            categories={categories}
            selectedCategory={selectedCategory}
            onCategoryChange={setSelectedCategory}
            period={period}
            onPeriodChange={p => setPeriod(p as 'all' | 'day' | 'week' | 'month')}
            fromDate={fromDate}
            toDate={toDate}
            onFromDateChange={setFromDate}
            onToDateChange={setToDate}
            sortOrder={sortOrder}
            onSortOrderChange={setSortOrder}
            groupByCategory={groupByCategory}
            onGroupByCategoryChange={setGroupByCategory}
            totalLabel={totalLabel}
            searchQuery={search}
            onSearchChange={setSearch}
          />

          {/* Filtered empty state */}
          {filtered.length === 0 && isFiltered && (
            <div className="flex flex-col items-center justify-center py-16 text-center">
              <div className="rounded-full bg-muted p-4 mb-4">
                <Receipt className="w-6 h-6 text-muted-foreground" />
              </div>
              <p className="font-medium text-sm">
                {search
                  ? 'No results for your search'
                  : selectedCategory
                  ? `No ${selectedCategory} items`
                  : 'No items in this period'}
              </p>
            </div>
          )}

          {filtered.length > 0 && (
            groupByCategory ? renderGrouped(filtered) : renderList(filtered)
          )}
        </>
      )}

      <AddExpenseModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        onSubmit={handleAdd}
      />
      <AddExpenseModal
        open={!!editingExpense}
        onClose={() => setEditingExpense(null)}
        onSubmit={handleEdit}
        initialData={editingExpense ?? undefined}
      />

    </div>
  )
}
