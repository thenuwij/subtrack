'use client'

import { useCallback, useEffect, useState, useMemo, useRef } from 'react'
import { createClient } from '@/lib/supabase/client'
import {
  createSubscription,
  deleteSubscription,
  dismissDuplicateSuggestion,
  getDuplicates,
  getSubscriptions,
  mergeSubscription,
  updateSubscription,
} from '@/lib/api'
import { Category, DuplicatePair, Subscription, SubscriptionInput } from '@/types'
import { SubscriptionCard }       from '@/components/subscriptions/SubscriptionCard'
import { AddSubscriptionModal }   from '@/components/subscriptions/AddSubscriptionModal'
import { FilterBar, type SortKey } from '@/components/shared/FilterBar'
import { Button }                 from '@/components/ui/button'
import { Skeleton }               from '@/components/ui/skeleton'
import { Plus, CreditCard }       from 'lucide-react'
import { useCurrency }            from '@/lib/context/currency'
import { formatCurrency }         from '@/lib/utils/currency'
import { formatCategory }         from '@/lib/utils/categories'
import { toast } from 'sonner'
import { useRegisterAgentPageContext } from '@/lib/agent/page-context'
import { ReminderDialog } from '@/components/reminders/ReminderDialog'
import { isActiveTrial } from '@/lib/utils/trials'
import {
  contributesToCommitment,
  isTerminalStatus,
  monthlyEquivalentNative,
  yearlyEquivalentNative,
} from '@/lib/utils/recurrence'
import {
  addUtcDays,
  endOfUtcMonthDateKey,
  storedDateKey,
  todayUtcDateKey,
} from '@/lib/utils/dates'

type RecordScope = 'current' | 'paused' | 'history' | 'all'

function inPeriod(dateStr: string | null, period: 'all' | 'day' | 'week' | 'month'): boolean {
  if (period === 'all') return true
  if (!dateStr) return false
  const date = storedDateKey(dateStr)
  const today = todayUtcDateKey()
  if (period === 'day') {
    return date === today
  }
  if (period === 'week') {
    // Seven calendar dates including today, not today plus seven (eight).
    return date >= today && date <= addUtcDays(today, 6)
  }
  if (period === 'month') {
    return date >= today && date <= endOfUtcMonthDateKey(today)
  }
  return true
}

export default function SubscriptionsPage() {
  const [subscriptions, setSubscriptions] = useState<Subscription[]>([])
  // Two rows for one service double-counts the cost, and detection can easily
  // produce "Claude" and "Anthropic (Claude)" separately.
  const [duplicates, setDuplicates] = useState<DuplicatePair[]>([])
  const [duplicateError, setDuplicateError] = useState('')
  const [duplicateChecking, setDuplicateChecking] = useState(false)
  const [merging, setMerging] = useState<string | null>(null)
  const [dismissingDuplicate, setDismissingDuplicate] = useState<string | null>(null)
  const [loading, setLoading]             = useState(true)
  const [error, setError]                 = useState<string | null>(null)
  const [modalOpen, setModalOpen]         = useState(false)
  const [editingSubscription, setEditingSubscription] = useState<Subscription | null>(null)
  const [reminderSubscription, setReminderSubscription] = useState<Subscription | null>(null)
  const [assistantSubscription, setAssistantSubscription] = useState<Subscription | null>(null)
  const { baseCurrency, canConvert, convertAmount, ratesLoading, ratesStale } = useCurrency()
  const duplicateRequestRef = useRef(0)
  const subscriptionRequestRef = useRef(0)
  const duplicateOperationRef = useRef(false)

  // filter / sort / group state
  const [search, setSearch]                   = useState('')
  const [selectedCategory, setSelectedCategory] = useState<Category | ''>('')
  const [period, setPeriod]                   = useState<'all' | 'day' | 'week' | 'month'>('all')
  const [fromDate, setFromDate]               = useState('')
  const [toDate, setToDate]                   = useState('')
  const [sortBy, setSortBy]                   = useState<SortKey>('due')
  const [groupByCategory, setGroupByCategory] = useState(false)
  const [scope, setScope]                     = useState<RecordScope>('current')

  // ── fetch ──────────────────────────────────────────────────────────────────

  const refreshDuplicates = useCallback(async (accessToken: string, clear = false) => {
    const requestId = ++duplicateRequestRef.current
    if (clear) setDuplicates([])
    setDuplicateError('')
    setDuplicateChecking(true)
    try {
      const result = await getDuplicates(accessToken)
      if (requestId !== duplicateRequestRef.current) return
      setDuplicates(result)
    } catch {
      if (requestId !== duplicateRequestRef.current) return
      setDuplicateError('Could not check for possible duplicates. Your payments and totals are still available.')
    } finally {
      if (requestId === duplicateRequestRef.current) setDuplicateChecking(false)
    }
  }, [])

  const fetchSubscriptions = useCallback(async () => {
    const requestId = ++subscriptionRequestRef.current
    const supabase = createClient()
    const { data: { session } } = await supabase.auth.getSession()
    if (!session || requestId !== subscriptionRequestRef.current) {
      if (requestId === subscriptionRequestRef.current) {
        setError('Your session has expired. Sign in again to load recurring payments.')
        setLoading(false)
      }
      return
    }
    try {
      const data = await getSubscriptions(session.access_token, { includeInactive: true })
      if (requestId !== subscriptionRequestRef.current) return
      setSubscriptions(data)
      setError(null)
      void refreshDuplicates(session.access_token)
    } catch (e) {
      if (requestId !== subscriptionRequestRef.current) return
      setError(e instanceof Error ? e.message : 'Failed to load recurring payments.')
      toast.error('Something went wrong')
    } finally {
      if (requestId === subscriptionRequestRef.current) setLoading(false)
    }
  }, [refreshDuplicates])

  useEffect(() => {
    void fetchSubscriptions()
    const refresh = () => { void fetchSubscriptions() }
    window.addEventListener('subtrack:data-changed', refresh)
    return () => window.removeEventListener('subtrack:data-changed', refresh)
  }, [fetchSubscriptions])

  async function handleMerge(pair: DuplicatePair) {
    if (merging || dismissingDuplicate || duplicateOperationRef.current) return
    duplicateOperationRef.current = true
    const supabase = createClient()
    const { data: { session } } = await supabase.auth.getSession()
    if (!session) {
      duplicateOperationRef.current = false
      toast.error('Your session has expired.')
      return
    }
    setMerging(pair.merge.id)
    try {
      await mergeSubscription(session.access_token, pair.merge.id, pair.keep.id)
      duplicateRequestRef.current += 1
      setDuplicateChecking(false)
      setDuplicates(prev => prev.filter(p => p.merge.id !== pair.merge.id))
      toast.success(`Merged into ${pair.keep.name}`)
      await fetchSubscriptions()
    } catch {
      toast.error('Could not merge')
    } finally {
      duplicateOperationRef.current = false
      setMerging(null)
    }
  }

  function duplicatePairKey(pair: DuplicatePair) {
    return [pair.keep.id, pair.merge.id].sort().join(':')
  }

  async function handleDismissDuplicate(pair: DuplicatePair) {
    if (merging || dismissingDuplicate || duplicateOperationRef.current) return
    duplicateOperationRef.current = true
    const { data: { session } } = await createClient().auth.getSession()
    if (!session) {
      toast.error('Your session has expired.')
      duplicateOperationRef.current = false
      return
    }
    const key = duplicatePairKey(pair)
    setDismissingDuplicate(key)
    try {
      await dismissDuplicateSuggestion(
        session.access_token,
        pair.keep.id,
        pair.merge.id,
      )
      duplicateRequestRef.current += 1
      setDuplicateChecking(false)
      setDuplicateError('')
      setDuplicates(current => current.filter(item => duplicatePairKey(item) !== key))
      toast.success('These payments will stay separate')
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : 'Could not save this decision.')
    } finally {
      duplicateOperationRef.current = false
      setDismissingDuplicate(null)
    }
  }

  async function retryDuplicateCheck() {
    const { data: { session } } = await createClient().auth.getSession()
    if (!session) {
      toast.error('Your session has expired.')
      return
    }
    await refreshDuplicates(session.access_token)
  }

  // ── add ────────────────────────────────────────────────────────────────────

  async function handleAdd(formData: SubscriptionInput) {
    const supabase = createClient()
    const { data: { session } } = await supabase.auth.getSession()
    if (!session) throw new Error('Not authenticated')
    const created = await createSubscription(session.access_token, formData)
    setSubscriptions(prev => [created, ...prev])
    void refreshDuplicates(session.access_token, true)
    toast.success('Payment added')
  }

  // ── update ─────────────────────────────────────────────────────────────────

  async function handleEdit(formData: SubscriptionInput) {
    const supabase = createClient()
    const { data: { session } } = await supabase.auth.getSession()
    if (!session || !editingSubscription) throw new Error('Not authenticated')
    const updated = await updateSubscription(session.access_token, editingSubscription.id, formData)
    setSubscriptions(prev => prev.map(s => s.id === editingSubscription.id ? updated : s))
    void refreshDuplicates(session.access_token, true)
    setEditingSubscription(null)
    toast.success('Payment updated')
  }

  // ── delete ─────────────────────────────────────────────────────────────────

  async function handleDelete(id: string) {
    const supabase = createClient()
    const { data: { session } } = await supabase.auth.getSession()
    if (!session) throw new Error('Not authenticated')
    await deleteSubscription(session.access_token, id)
    setSubscriptions(prev => prev.filter(s => s.id !== id))
    setDuplicates(current => current.filter(
      pair => pair.keep.id !== id && pair.merge.id !== id,
    ))
    void refreshDuplicates(session.access_token)
    toast.success('Payment deleted')
  }

  function askAssistant(subscription: Subscription) {
    setAssistantSubscription(subscription)
    window.setTimeout(() => {
      window.dispatchEvent(new CustomEvent('subtrack:ask-agent', {
        detail: {
          prompt: `Find current cheaper alternatives to ${subscription.name}. Compare like-for-like plans and cite the pricing sources.`,
        },
      }))
    }, 0)
  }

  // ── derived stats ──────────────────────────────────────────────────────────

  const current = subscriptions.filter(
    subscription => subscription.status === 'active' || subscription.status === 'cancelling',
  )
  const trials = current.filter(subscription => isActiveTrial(subscription))
  const paid = subscriptions.filter(contributesToCommitment)
  const convertiblePaid = paid.filter(subscription => canConvert(subscription.currency))
  const totalMonthly = convertiblePaid.reduce(
    (sum, subscription) => sum + (convertAmount(
      monthlyEquivalentNative(subscription), subscription.currency,
    ) ?? 0),
    0,
  )
  const totalYearly = convertiblePaid.reduce(
    (sum, subscription) => sum + (convertAmount(
      yearlyEquivalentNative(subscription), subscription.currency,
    ) ?? 0),
    0,
  )
  const unconvertedCurrent = paid.length - convertiblePaid.length
  const hasVariableAmounts = paid.some(subscription => subscription.amount_type === 'variable')
  const missingDates = current.filter(
    subscription => !isActiveTrial(subscription) && !subscription.next_due,
  ).length

  // ── filter / sort ──────────────────────────────────────────────────────────

  const categories = useMemo(
    () => [...new Set(subscriptions.map(s => s.category))].sort(),
    [subscriptions]
  )

  const filtered = useMemo(() => {
    let list = subscriptions.filter(s => {
      if (scope === 'current' && s.status !== 'active' && s.status !== 'cancelling') return false
      if (scope === 'paused' && s.status !== 'paused') return false
      if (scope === 'history' && !isTerminalStatus(s.status)) return false
      if (search && !s.name.toLowerCase().includes(search.toLowerCase())) return false
      if (selectedCategory && s.category !== selectedCategory) return false
      if (!inPeriod(s.next_expected_at, period)) return false
      const dueDate = storedDateKey(s.next_expected_at)
      if (fromDate && (!dueDate || dueDate < fromDate)) return false
      if (toDate && (!dueDate || dueDate > toDate)) return false
      return true
    })
    const monthlyCost = (subscription: Subscription) =>
      convertAmount(monthlyEquivalentNative(subscription), subscription.currency)
    list = [...list].sort((a, b) => {
      if (sortBy === 'name') return a.name.localeCompare(b.name)
      if (sortBy === 'recent') return b.created_at.localeCompare(a.created_at)
      if (sortBy === 'amount') {
        const ma = monthlyCost(a)
        const mb = monthlyCost(b)
        if (ma === null && mb === null) return a.name.localeCompare(b.name)
        if (ma === null) return 1
        if (mb === null) return -1
        return mb - ma
      }
      const da = a.next_expected_at ?? ''
      const db = b.next_expected_at ?? ''
      if (!da && !db) return 0
      if (!da) return 1
      if (!db) return -1
      return da.localeCompare(db)
    })
    return list
  }, [subscriptions, scope, search, selectedCategory, period, fromDate, toDate, sortBy, convertAmount])

  const filteredContributing = filtered.filter(contributesToCommitment)
  const filteredConvertible = filteredContributing.filter(
    subscription => canConvert(subscription.currency),
  )
  const totalAmount = filteredConvertible.reduce(
    (sum, subscription) => sum + (convertAmount(
      monthlyEquivalentNative(subscription), subscription.currency,
    ) ?? 0),
    0,
  )
  const filteredUnavailable = filteredContributing.length - filteredConvertible.length
  const totalLabel  = filtered.length > 0
    ? ratesLoading
      ? `${filtered.length} item${filtered.length !== 1 ? 's' : ''} · updating exchange rates…`
      : `${filtered.length} item${filtered.length !== 1 ? 's' : ''} · ${formatCurrency(totalAmount, baseCurrency)}/mo current commitment${filteredUnavailable ? ` · ${filteredUnavailable} excluded (FX unavailable)` : ''}`
    : ''

  const isFiltered = !!(scope !== 'current' || search || selectedCategory || period !== 'all' || fromDate || toDate)

  useRegisterAgentPageContext({
    selected_subscription_ids: editingSubscription
      ? [editingSubscription.id]
      : reminderSubscription
        ? [reminderSubscription.id]
        : assistantSubscription
          ? [assistantSubscription.id]
          : [],
    visible_subscription_ids: filtered.slice(0, 25).map(subscription => subscription.id),
    filters: {
      ...(search ? { search } : {}),
      ...(selectedCategory ? { category: selectedCategory } : {}),
      due_period: period,
      ...(fromDate ? { from_date: fromDate } : {}),
      ...(toDate ? { to_date: toDate } : {}),
      sort_by: sortBy,
      group_by_category: groupByCategory,
      record_scope: scope,
    },
  })

  // ── grouped render helper ──────────────────────────────────────────────────

  function renderList(items: Subscription[]) {
    return (
      <div className="rounded-2xl bg-card shadow-sm overflow-hidden divide-y divide-border">
        {items.map(sub => (
          <SubscriptionCard
            key={sub.id}
            subscription={sub}
            onDelete={handleDelete}
            onEdit={setEditingSubscription}
            onReminders={setReminderSubscription}
            onAskAssistant={askAssistant}
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
            <p className="mb-1.5 px-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              {formatCategory(cat)}
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
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Recurring payments</h1>
          {!loading && subscriptions.length > 0 && (
            <p className="text-sm text-muted-foreground mt-1 tabular-nums">
              {paid.length} paid{trials.length ? ` · ${trials.length} free trial${trials.length === 1 ? '' : 's'}` : ''} ·{' '}
              {ratesLoading ? 'updating exchange rates…' : (
                <>
                  {hasVariableAmounts ? '≈ ' : ''}{formatCurrency(totalMonthly, baseCurrency)}/mo ·{' '}
                  {hasVariableAmounts ? '≈ ' : ''}{formatCurrency(totalYearly, baseCurrency)}/yr
                  {unconvertedCurrent ? ` · ${unconvertedCurrent} excluded (FX unavailable)` : ''}
                </>
              )}
            </p>
          )}
          {!loading && ratesStale ? (
            <p className="mt-1 text-xs text-muted-foreground">Foreign-currency totals use cached rates and are estimates.</p>
          ) : null}
        </div>
        <Button onClick={() => setModalOpen(true)} className="shrink-0">
          <Plus className="w-4 h-4 mr-1.5" />
          Add payment
        </Button>
      </div>

      {/* Same service tracked twice — the totals are wrong until it's resolved. */}
      {duplicates.map(pair => (
        <div
          key={pair.merge.id}
          className="rounded-xl border border-amber-500/25 bg-amber-500/5 p-4"
        >
          <p className="text-sm font-medium text-foreground">
            Possible duplicate payment: {pair.keep.name} and {pair.merge.name}
          </p>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {pair.reason} Keeping both may double-count this recurring commitment.
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            <Button size="sm" onClick={() => handleMerge(pair)} disabled={merging !== null || dismissingDuplicate !== null}>
              Merge into {pair.keep.name}
            </Button>
            <Button
              size="sm"
              variant="ghost"
              className="text-muted-foreground"
              onClick={() => void handleDismissDuplicate(pair)}
              disabled={merging !== null || dismissingDuplicate !== null}
            >
              {dismissingDuplicate === duplicatePairKey(pair) ? 'Saving…' : 'They’re different'}
            </Button>
          </div>
        </div>
      ))}

      {duplicateError ? (
        <div className="flex flex-col gap-2 rounded-xl border border-border bg-muted/30 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-xs text-muted-foreground">{duplicateError}</p>
          <Button
            type="button"
            size="sm"
            variant="ghost"
            disabled={duplicateChecking}
            onClick={() => void retryDuplicateCheck()}
          >
            {duplicateChecking ? 'Checking…' : 'Try duplicate check again'}
          </Button>
        </div>
      ) : null}

      {!loading && (missingDates > 0 || (!ratesLoading && unconvertedCurrent > 0)) ? (
        <section className="rounded-xl border border-amber-500/25 bg-amber-500/5 p-4" aria-labelledby="payment-attention-heading">
          <h2 id="payment-attention-heading" className="text-sm font-semibold text-foreground">Needs attention</h2>
          <ul className="mt-1 space-y-1 text-xs leading-5 text-muted-foreground">
            {missingDates > 0 ? (
              <li>{missingDates} current payment{missingDates === 1 ? '' : 's'} need a next expected date for reminders and forecasts.</li>
            ) : null}
            {!ratesLoading && unconvertedCurrent > 0 ? (
              <li>{unconvertedCurrent} payment{unconvertedCurrent === 1 ? '' : 's'} are excluded from totals until a reliable exchange rate is available.</li>
            ) : null}
          </ul>
        </section>
      ) : null}

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

      {/* Loading — shaped like the list it becomes, so the page doesn't
          rearrange itself when the data lands. */}
      {loading && (
        <div aria-busy="true" aria-live="polite">
          <span className="sr-only">Loading your recurring payments</span>
          <Skeleton className="h-10 w-full rounded-xl" />
          <div className="mt-4 divide-y divide-border overflow-hidden rounded-2xl bg-card shadow-sm">
            {[...Array(5)].map((_, i) => (
              <div key={i} className="flex items-center gap-3 px-4 py-3.5">
                <Skeleton className="h-2 w-2 shrink-0 rounded-full" />
                <div className="flex-1 space-y-1.5">
                  <Skeleton className="h-4 w-40" />
                  <Skeleton className="h-3 w-28" />
                </div>
                <Skeleton className="h-4 w-20" />
              </div>
            ))}
          </div>
        </div>
      )}

      {/* True empty state */}
      {!loading && !error && subscriptions.length === 0 && (
        <div className="flex flex-col items-center justify-center py-20 text-center">
          <div className="rounded-full bg-muted p-4 mb-4">
            <CreditCard className="w-6 h-6 text-muted-foreground" />
          </div>
          <p className="font-medium text-sm">No recurring payments yet</p>
          <p className="text-sm text-muted-foreground mt-1 mb-4">
            Add rent, a utility bill, membership, subscription, or any payment that repeats.
          </p>
          <Button size="sm" onClick={() => setModalOpen(true)}>
            <Plus className="w-4 h-4 mr-1.5" />
            Add payment
          </Button>
        </div>
      )}

      {/* FilterBar + list */}
      {!loading && subscriptions.length > 0 && (
        <>
          <div className="flex flex-wrap items-center gap-1 rounded-xl bg-muted p-1" role="group" aria-label="Payment record scope">
            {([
              { value: 'current', label: 'Current', count: current.length },
              { value: 'paused', label: 'Paused', count: subscriptions.filter(item => item.status === 'paused').length },
              { value: 'history', label: 'History', count: subscriptions.filter(item => isTerminalStatus(item.status)).length },
              { value: 'all', label: 'All', count: subscriptions.length },
            ] as const).map(option => (
              <button
                key={option.value}
                type="button"
                aria-pressed={scope === option.value}
                onClick={() => setScope(option.value)}
                className={`rounded-lg px-3 py-1.5 text-xs font-medium transition-colors ${
                  scope === option.value
                    ? 'bg-card text-foreground shadow-sm'
                    : 'text-muted-foreground hover:text-foreground'
                }`}
              >
                {option.label} <span className="ml-1 tabular-nums opacity-70">{option.count}</span>
              </button>
            ))}
          </div>

          <FilterBar
            categories={categories}
            selectedCategory={selectedCategory}
            onCategoryChange={category => setSelectedCategory(category as Category | '')}
            period={period}
            onPeriodChange={p => setPeriod(p as 'all' | 'day' | 'week' | 'month')}
            fromDate={fromDate}
            toDate={toDate}
            onFromDateChange={setFromDate}
            onToDateChange={setToDate}
            sortBy={sortBy}
            onSortByChange={setSortBy}
            groupByCategory={groupByCategory}
            onGroupByCategoryChange={setGroupByCategory}
            totalLabel={totalLabel}
            searchQuery={search}
            onSearchChange={setSearch}
            hasFilters={isFiltered}
            onClearFilters={() => {
              setScope('current')
              setSearch('')
              setSelectedCategory('')
              setPeriod('all')
              setFromDate('')
              setToDate('')
            }}
          />

          {/* Filtered empty state */}
          {filtered.length === 0 && (
            <div className="flex flex-col items-center justify-center py-16 text-center">
              <div className="rounded-full bg-muted p-4 mb-4">
                <CreditCard className="w-6 h-6 text-muted-foreground" />
              </div>
              <p className="font-medium text-sm">
                {search
                  ? 'No results for your search'
                  : selectedCategory
                  ? `No ${formatCategory(selectedCategory)} items`
                  : period !== 'all' || fromDate || toDate
                    ? 'No payments due in this period'
                  : scope === 'current'
                    ? 'No current payments'
                  : scope === 'paused'
                    ? 'No paused payments'
                    : scope === 'history'
                      ? 'No payment history yet'
                      : 'No payments match these filters'}
              </p>
              <Button
                variant="ghost"
                size="sm"
                className="mt-3"
                onClick={() => {
                  setScope(scope === 'current' && !isFiltered ? 'all' : 'current')
                  setSearch('')
                  setSelectedCategory('')
                  setPeriod('all')
                  setFromDate('')
                  setToDate('')
                }}
              >
                {scope === 'current' && !isFiltered ? 'View all payments' : 'Clear filters'}
              </Button>
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

      {reminderSubscription ? (
        <ReminderDialog
          subscription={reminderSubscription}
          open
          onOpenChange={open => {
            if (!open) setReminderSubscription(null)
          }}
        />
      ) : null}

    </div>
  )
}
