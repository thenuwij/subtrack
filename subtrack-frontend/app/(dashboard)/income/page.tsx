'use client'

import { useEffect, useState, useMemo } from 'react'
import { createClient } from '@/lib/supabase/client'
import { getIncome, createIncome, deleteIncome, updateIncome } from '@/lib/api'
import { Income } from '@/types'
import { IncomeCard }       from '@/components/income/IncomeCard'
import { AddIncomeModal }   from '@/components/income/AddIncomeModal'
import { FilterBar }        from '@/components/shared/FilterBar'
import { Button }           from '@/components/ui/button'
import { Skeleton }         from '@/components/ui/skeleton'
import { Plus, TrendingUp } from 'lucide-react'
import { useCurrency }      from '@/lib/context/currency'
import { formatCurrency }   from '@/lib/utils/currency'
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

export default function IncomePage() {
  const supabase = createClient()

  const [income, setIncome]       = useState<Income[]>([])
  const [loading, setLoading]     = useState(true)
  const [error, setError]         = useState<string | null>(null)
  const [modalOpen, setModalOpen] = useState(false)
  const [editingIncome, setEditingIncome] = useState<Income | null>(null)
  const { baseCurrency } = useCurrency()

  // filter / sort / group state
  const [search, setSearch]                     = useState('')
  const [selectedCategory, setSelectedCategory] = useState('')
  const [period, setPeriod]                     = useState<'all' | 'day' | 'week' | 'month'>('all')
  const [fromDate, setFromDate]                 = useState('')
  const [toDate, setToDate]                     = useState('')
  const [sortOrder, setSortOrder]               = useState<'desc' | 'asc'>('desc')
  const [groupByCategory, setGroupByCategory]   = useState(false)

  // ── fetch ──────────────────────────────────────────────────────────────────

  async function fetchIncome() {
    const { data: { session } } = await supabase.auth.getSession()
    if (!session) return
    try {
      const data = await getIncome(session.access_token)
      setIncome(data)
    } catch (e: any) {
      setError(e?.message ?? 'Failed to load income.')
      toast.error('Something went wrong')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchIncome() }, []) // eslint-disable-line

  // ── add ────────────────────────────────────────────────────────────────────

  async function handleAdd(formData: Omit<Income, 'id' | 'user_id' | 'created_at'>) {
    const { data: { session } } = await supabase.auth.getSession()
    if (!session) throw new Error('Not authenticated')
    const created = await createIncome(session.access_token, formData)
    setIncome(prev => [created, ...prev])
    toast.success('Income logged')
  }

  // ── update ─────────────────────────────────────────────────────────────────

  async function handleEdit(formData: Omit<Income, 'id' | 'user_id' | 'created_at'>) {
    const { data: { session } } = await supabase.auth.getSession()
    if (!session || !editingIncome) throw new Error('Not authenticated')
    const updated = await updateIncome(session.access_token, editingIncome.id, formData)
    setIncome(prev => prev.map(i => i.id === editingIncome.id ? updated : i))
    setEditingIncome(null)
    toast.success('Income updated')
  }

  // ── delete ─────────────────────────────────────────────────────────────────

  async function handleDelete(id: string) {
    const { data: { session } } = await supabase.auth.getSession()
    if (!session) throw new Error('Not authenticated')
    await deleteIncome(session.access_token, id)
    setIncome(prev => prev.filter(i => i.id !== id))
    toast.success('Income deleted')
  }

  // ── derived stats ──────────────────────────────────────────────────────────

  const thisMonth = new Date()
  const monthlyTotal = income
    .filter(i => {
      const d = new Date(i.date)
      return d.getMonth() === thisMonth.getMonth() && d.getFullYear() === thisMonth.getFullYear()
    })
    .reduce((sum, i) => sum + (i.converted_amount ?? i.amount), 0)

  // ── filter / sort ──────────────────────────────────────────────────────────

  // Income uses frequency as its grouping/filter dimension
  const categories = useMemo(
    () => [...new Set(income.map(i => i.frequency))].sort(),
    [income]
  )

  const filtered = useMemo(() => {
    let list = income.filter(i => {
      if (search && !(i.source ?? '').toLowerCase().includes(search.toLowerCase())) return false
      if (selectedCategory && i.frequency !== selectedCategory) return false
      if (!inPeriod(i.date, period)) return false
      if (fromDate && i.date < fromDate) return false
      if (toDate   && i.date > toDate)   return false
      return true
    })
    list = [...list].sort((a, b) =>
      sortOrder === 'desc'
        ? new Date(b.date).getTime() - new Date(a.date).getTime()
        : new Date(a.date).getTime() - new Date(b.date).getTime()
    )
    return list
  }, [income, search, selectedCategory, period, fromDate, toDate, sortOrder])

  const totalAmount = filtered.reduce((sum, i) => sum + (i.converted_amount ?? i.amount), 0)
  const totalLabel  = filtered.length > 0
    ? `${filtered.length} item${filtered.length !== 1 ? 's' : ''} · ${formatCurrency(totalAmount, baseCurrency)} total`
    : ''

  const isFiltered = !!(search || selectedCategory || period !== 'all' || fromDate || toDate)

  // ── grouped render helper ──────────────────────────────────────────────────

  function renderList(items: Income[]) {
    return (
      <div className="rounded-2xl bg-card shadow-md overflow-hidden divide-y divide-border">
        {items.map(entry => (
          <IncomeCard
            key={entry.id}
            income={entry}
            onDelete={handleDelete}
            onEdit={setEditingIncome}
          />
        ))}
      </div>
    )
  }

  function renderGrouped(items: Income[]) {
    const groups = items.reduce<Record<string, Income[]>>((acc, i) => {
      ;(acc[i.frequency] ??= []).push(i)
      return acc
    }, {})
    return (
      <div className="space-y-4">
        {Object.entries(groups).map(([freq, group]) => (
          <div key={freq}>
            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-1.5 px-1 capitalize">
              {freq}
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
          <h1 className="text-2xl font-semibold tracking-tight">Income</h1>
          {!loading && income.length > 0 && (
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
            onClick={() => { setError(null); setLoading(true); fetchIncome() }}
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
      {!loading && !error && income.length === 0 && (
        <div className="flex flex-col items-center justify-center py-20 text-center">
          <div className="rounded-full bg-muted p-4 mb-4">
            <TrendingUp className="w-6 h-6 text-muted-foreground" />
          </div>
          <p className="font-medium text-sm">No income logged yet</p>
          <p className="text-sm text-muted-foreground mt-1 mb-4">
            Log your first income entry to start tracking.
          </p>
          <Button size="sm" onClick={() => setModalOpen(true)}>
            <Plus className="w-4 h-4 mr-1.5" />
            Log income
          </Button>
        </div>
      )}

      {/* FilterBar + list */}
      {!loading && income.length > 0 && (
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
                <TrendingUp className="w-6 h-6 text-muted-foreground" />
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

      <AddIncomeModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        onSubmit={handleAdd}
      />
      <AddIncomeModal
        open={!!editingIncome}
        onClose={() => setEditingIncome(null)}
        onSubmit={handleEdit}
        initialData={editingIncome ?? undefined}
      />

    </div>
  )
}
