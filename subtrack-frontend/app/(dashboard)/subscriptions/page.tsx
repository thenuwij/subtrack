'use client'

import { useEffect, useState, useMemo } from 'react'
import { createClient } from '@/lib/supabase/client'
import { getSubscriptions, createSubscription, deleteSubscription, updateSubscription } from '@/lib/api'
import { Subscription, SubscriptionInput } from '@/types'
import { SubscriptionCard }       from '@/components/subscriptions/SubscriptionCard'
import { AddSubscriptionModal }   from '@/components/subscriptions/AddSubscriptionModal'
import { FilterBar }              from '@/components/shared/FilterBar'
import { Button }                 from '@/components/ui/button'
import { Skeleton }               from '@/components/ui/skeleton'
import { Plus, CreditCard }       from 'lucide-react'
import { useCurrency }            from '@/lib/context/currency'
import { formatCurrency }         from '@/lib/utils/currency'
import { toast } from 'sonner'

function monthlyEquivalent(sub: Subscription): number {
  const amount = sub.converted_amount ?? sub.amount
  if (sub.cycle === 'weekly')  return amount * 52 / 12
  if (sub.cycle === 'yearly')  return amount      / 12
  return amount
}

function inPeriod(dateStr: string | null, period: 'all' | 'day' | 'week' | 'month'): boolean {
  if (period === 'all' || !dateStr) return true
  const d = new Date(dateStr)
  const now = new Date()
  if (period === 'day') {
    return d.toDateString() === now.toDateString()
  }
  if (period === 'week') {
    const week = new Date(now); week.setDate(now.getDate() - 7)
    return d >= week
  }
  if (period === 'month') {
    return d.getMonth() === now.getMonth() && d.getFullYear() === now.getFullYear()
  }
  return true
}

export default function SubscriptionsPage() {
  const supabase = createClient()

  const [subscriptions, setSubscriptions] = useState<Subscription[]>([])
  const [loading, setLoading]             = useState(true)
  const [error, setError]                 = useState<string | null>(null)
  const [modalOpen, setModalOpen]         = useState(false)
  const [editingSubscription, setEditingSubscription] = useState<Subscription | null>(null)
  const { baseCurrency } = useCurrency()

  // filter / sort / group state
  const [search, setSearch]                   = useState('')
  const [selectedCategory, setSelectedCategory] = useState('')
  const [period, setPeriod]                   = useState<'all' | 'day' | 'week' | 'month'>('all')
  const [fromDate, setFromDate]               = useState('')
  const [toDate, setToDate]                   = useState('')
  const [sortOrder, setSortOrder]             = useState<'desc' | 'asc'>('desc')
  const [groupByCategory, setGroupByCategory] = useState(false)

  // ── fetch ──────────────────────────────────────────────────────────────────

  async function fetchSubscriptions() {
    const { data: { session } } = await supabase.auth.getSession()
    if (!session) return
    try {
      const data = await getSubscriptions(session.access_token)
      setSubscriptions(data)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load subscriptions.')
      toast.error('Something went wrong')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchSubscriptions() }, []) // eslint-disable-line

  // ── add ────────────────────────────────────────────────────────────────────

  async function handleAdd(formData: SubscriptionInput) {
    const { data: { session } } = await supabase.auth.getSession()
    if (!session) throw new Error('Not authenticated')
    const created = await createSubscription(session.access_token, formData)
    setSubscriptions(prev => [created, ...prev])
    toast.success('Subscription added')
  }

  // ── update ─────────────────────────────────────────────────────────────────

  async function handleEdit(formData: SubscriptionInput) {
    const { data: { session } } = await supabase.auth.getSession()
    if (!session || !editingSubscription) throw new Error('Not authenticated')
    const updated = await updateSubscription(session.access_token, editingSubscription.id, formData)
    setSubscriptions(prev => prev.map(s => s.id === editingSubscription.id ? updated : s))
    setEditingSubscription(null)
    toast.success('Subscription updated')
  }

  // ── delete ─────────────────────────────────────────────────────────────────

  async function handleDelete(id: string) {
    const { data: { session } } = await supabase.auth.getSession()
    if (!session) throw new Error('Not authenticated')
    await deleteSubscription(session.access_token, id)
    setSubscriptions(prev => prev.filter(s => s.id !== id))
    toast.success('Subscription deleted')
  }

  // ── derived stats ──────────────────────────────────────────────────────────

  const active       = subscriptions.filter(s => s.is_active)
  const totalMonthly = active.reduce((sum, s) => sum + monthlyEquivalent(s), 0)

  // ── filter / sort ──────────────────────────────────────────────────────────

  const categories = useMemo(
    () => [...new Set(subscriptions.map(s => s.category))].sort(),
    [subscriptions]
  )

  const filtered = useMemo(() => {
    let list = subscriptions.filter(s => {
      if (search && !s.name.toLowerCase().includes(search.toLowerCase())) return false
      if (selectedCategory && s.category !== selectedCategory) return false
      if (!inPeriod(s.next_due, period)) return false
      if (fromDate && s.next_due && s.next_due < fromDate) return false
      if (toDate   && s.next_due && s.next_due > toDate)   return false
      return true
    })
    list = [...list].sort((a, b) => {
      const da = a.next_due ?? ''
      const db = b.next_due ?? ''
      return sortOrder === 'desc' ? db.localeCompare(da) : da.localeCompare(db)
    })
    return list
  }, [subscriptions, search, selectedCategory, period, fromDate, toDate, sortOrder])

  const totalAmount = filtered.reduce((sum, s) => sum + (s.converted_amount ?? s.amount), 0)
  const totalLabel  = filtered.length > 0
    ? `${filtered.length} item${filtered.length !== 1 ? 's' : ''} · ${formatCurrency(totalAmount, baseCurrency)} total`
    : ''

  const isFiltered = !!(search || selectedCategory || period !== 'all' || fromDate || toDate)

  // ── grouped render helper ──────────────────────────────────────────────────

  function renderList(items: Subscription[]) {
    return (
      <div className="rounded-2xl bg-card shadow-md overflow-hidden divide-y divide-border">
        {items.map(sub => (
          <SubscriptionCard
            key={sub.id}
            subscription={sub}
            onDelete={handleDelete}
            onEdit={setEditingSubscription}
          />
        ))}
      </div>
    )
  }

  function renderGrouped(items: Subscription[]) {
    const groups = items.reduce<Record<string, Subscription[]>>((acc, s) => {
      ;(acc[s.category] ??= []).push(s)
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
          <h1 className="text-2xl font-semibold tracking-tight">Subscriptions</h1>
          {!loading && subscriptions.length > 0 && (
            <p className="text-sm text-muted-foreground mt-0.5">
              {active.length} active · ~{formatCurrency(totalMonthly, baseCurrency)}/mo
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
            onClick={() => { setError(null); setLoading(true); fetchSubscriptions() }}
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
      {!loading && !error && subscriptions.length === 0 && (
        <div className="flex flex-col items-center justify-center py-20 text-center">
          <div className="rounded-full bg-muted p-4 mb-4">
            <CreditCard className="w-6 h-6 text-muted-foreground" />
          </div>
          <p className="font-medium text-sm">No subscriptions yet</p>
          <p className="text-sm text-muted-foreground mt-1 mb-4">
            Add your first subscription to start tracking.
          </p>
          <Button size="sm" onClick={() => setModalOpen(true)}>
            <Plus className="w-4 h-4 mr-1.5" />
            Add subscription
          </Button>
        </div>
      )}

      {/* FilterBar + list */}
      {!loading && subscriptions.length > 0 && (
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
                <CreditCard className="w-6 h-6 text-muted-foreground" />
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

      {/* Add Modal */}
      <AddSubscriptionModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        onSubmit={handleAdd}
      />

      {/* Edit Modal */}
      <AddSubscriptionModal
        open={!!editingSubscription}
        onClose={() => setEditingSubscription(null)}
        onSubmit={handleEdit}
        initialData={editingSubscription ?? undefined}
      />

    </div>
  )
}
