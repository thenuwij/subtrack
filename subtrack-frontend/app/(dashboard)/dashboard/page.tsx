'use client'

import { useEffect, useMemo, useState } from 'react'
import { CreditCard, Receipt } from 'lucide-react'
import { createClient } from '@/lib/supabase/client'
import { getSubscriptions, getExpenses, getBudgets } from '@/lib/api'
import type { Subscription, Expense, Budget } from '@/types'
import { useCurrency } from '@/lib/context/currency'
import { formatCurrency } from '@/lib/utils/currency'

function Skeleton({ className }: { className?: string }) {
  return <div className={`animate-pulse rounded-md bg-muted ${className ?? ''}`} />
}

function formatDate(date: string | null | undefined) {
  if (!date) return ''
  return new Date(date).toLocaleDateString('en-AU', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  })
}

function getDaysUntil(date: string | null | undefined) {
  if (!date) return null
  const today = new Date()
  const target = new Date(date)

  const startOfToday = new Date(today.getFullYear(), today.getMonth(), today.getDate())
  const startOfTarget = new Date(target.getFullYear(), target.getMonth(), target.getDate())

  const diffMs = startOfTarget.getTime() - startOfToday.getTime()
  return Math.ceil(diffMs / (1000 * 60 * 60 * 24))
}

function toMonthly(amount: number, cycle: string) {
  if (cycle === 'weekly') return amount * 4.33
  if (cycle === 'yearly') return amount / 12
  return amount
}

function getBudgetTone(percent: number) {
  if (percent >= 100) {
    return {
      bar: 'bg-destructive',
      badge: 'text-destructive bg-destructive/10 border-destructive/20',
      label: 'Over budget',
    }
  }

  if (percent >= 80) {
    return {
      bar: 'bg-amber-500',
      badge: 'text-amber-600 bg-amber-500/10 border-amber-500/20 dark:text-amber-400',
      label: 'Near limit',
    }
  }

  return {
    bar: 'bg-primary',
    badge: 'text-primary bg-primary/10 border-primary/20',
    label: 'On track',
  }
}

export default function DashboardPage() {
  const [subscriptions, setSubscriptions] = useState<Subscription[]>([])
  const [expenses, setExpenses] = useState<Expense[]>([])
  const [budgets, setBudgets] = useState<Budget[]>([])
  const [loading, setLoading] = useState(true)
  const { baseCurrency, convertAmount } = useCurrency()

  useEffect(() => {
    async function fetchData() {
      try {
        const supabase = createClient()
        const {
          data: { session },
        } = await supabase.auth.getSession()

        if (!session) return

        const token = session.access_token
        console.log("TOKEN:", token) 
        const [subs, exps, buds] = await Promise.all([
          getSubscriptions(token),
          getExpenses(token),
          getBudgets(token),
        ])

        setSubscriptions(subs)
        setExpenses(exps)
        setBudgets(buds)
      } finally {
        setLoading(false)
      }
    }

    fetchData()
  }, [])

  const currentMonth = new Date()

  const monthlyBurn = useMemo(() => {
    return subscriptions.reduce((sum, s) => {
      return sum + convertAmount(toMonthly(s.amount, s.cycle), s.currency)
    }, 0)
  }, [subscriptions, convertAmount])

  const monthlyExpenses = useMemo(() => {
    return expenses.filter((expense) => {
      const expenseDate = new Date(expense.date)
      return (
        expenseDate.getMonth() === currentMonth.getMonth() &&
        expenseDate.getFullYear() === currentMonth.getFullYear()
      )
    })
  }, [expenses, currentMonth])

  const totalExpenses = useMemo(() => {
    return monthlyExpenses.reduce((sum, e) => {
      return sum + convertAmount(e.amount, e.currency)
    }, 0)
  }, [monthlyExpenses, convertAmount])

  const upcoming = useMemo(() => {
    return subscriptions
      .filter((subscription) => subscription.next_due)
      .sort(
        (a, b) =>
          new Date(a.next_due!).getTime() - new Date(b.next_due!).getTime()
      )
      .slice(0, 5)
  }, [subscriptions])

  const totalBudgetLimit = useMemo(() => {
    return budgets.reduce((sum, budget) => sum + budget.monthly_limit, 0)
  }, [budgets])

  const remainingBudget = Math.max(totalBudgetLimit - totalExpenses, 0)

  if (loading) {
    return (
      <div className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
        <div className="space-y-8">
          <div className="space-y-3">
            <Skeleton className="h-8 w-40" />
            <Skeleton className="h-4 w-72" />
          </div>

          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            {[...Array(2)].map((_, index) => (
              <Skeleton key={index} className="h-36 rounded-xl" />
            ))}
          </div>

          <div className="space-y-6">
            <Skeleton className="h-[320px] rounded-xl" />
            <Skeleton className="h-[320px] rounded-xl" />
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
      <div className="space-y-8">
        <section className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
          <div className="space-y-2">
            <p className="text-sm font-medium text-primary">Overview</p>
            <h1 className="text-3xl font-semibold tracking-tight text-foreground">
              Financial dashboard
            </h1>
            <p className="max-w-2xl text-sm text-muted-foreground sm:text-base">
              Track recurring bills, monthly spending, and budget health in one place.
            </p>
          </div>

          <div className="rounded-xl bg-card px-4 py-3 shadow-md">
            <p className="text-xs uppercase tracking-[0.16em] text-muted-foreground">
              Current month
            </p>
            <p className="mt-1 text-sm font-medium text-foreground">
              {currentMonth.toLocaleDateString('en-AU', {
                month: 'long',
                year: 'numeric',
              })}
            </p>
          </div>
        </section>

        <section className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <div className="rounded-xl bg-card p-5 shadow-md">
            <div className="mb-4 flex items-center justify-between">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10 text-primary">
                <CreditCard className="h-5 w-5" />
              </div>
              <span className="text-xs font-medium text-muted-foreground">Recurring</span>
            </div>
            <p className="text-sm font-medium text-foreground">Monthly subscriptions</p>
            <p className="mt-2 text-3xl font-bold tracking-tight tabular-nums text-foreground">
              {formatCurrency(monthlyBurn, baseCurrency)}
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              {formatCurrency(monthlyBurn * 12, baseCurrency)} estimated yearly spend
            </p>
          </div>

          <div className="rounded-xl bg-card p-5 shadow-md">
            <div className="mb-4 flex items-center justify-between">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10 text-primary">
                <Receipt className="h-5 w-5" />
              </div>
              <span className="text-xs font-medium text-muted-foreground">This month</span>
            </div>
            <p className="text-sm font-medium text-foreground">Expense total</p>
            <p className="mt-2 text-3xl font-bold tracking-tight tabular-nums text-foreground">
              {formatCurrency(totalExpenses, baseCurrency)}
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              {monthlyExpenses.length} transaction{monthlyExpenses.length === 1 ? '' : 's'} logged
            </p>
          </div>
        </section>

        <section className="space-y-6">
          <div className="rounded-2xl bg-card p-6 shadow-md">
            <div className="mb-5">
              <h2 className="text-lg font-semibold text-foreground">Upcoming bills</h2>
              <p className="mt-1 text-sm text-muted-foreground">
                Your nearest recurring charges and renewal dates.
              </p>
            </div>

            {upcoming.length === 0 ? (
              <div className="flex min-h-[220px] items-center justify-center rounded-xl border border-dashed border-border bg-muted/30">
                <div className="text-center">
                  <p className="text-sm font-medium text-foreground">No upcoming bills</p>
                  <p className="mt-1 text-sm text-muted-foreground">
                    Add subscriptions to start tracking renewals.
                  </p>
                </div>
              </div>
            ) : (
              <div className="space-y-3">
                {upcoming.map((subscription) => {
                  const daysUntil = getDaysUntil(subscription.next_due)

                  return (
                    <div
                      key={subscription.id}
                      className="flex flex-col gap-4 rounded-xl border border-border bg-background/60 p-4 transition-colors hover:bg-muted/40 sm:flex-row sm:items-center sm:justify-between"
                    >
                      <div className="min-w-0">
                        <div className="flex items-center gap-3">
                          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-sm font-semibold text-primary">
                            {subscription.name.slice(0, 1).toUpperCase()}
                          </div>
                          <div className="min-w-0">
                            <p className="truncate text-sm font-semibold text-foreground">
                              {subscription.name}
                            </p>
                            <p className="text-xs capitalize text-muted-foreground">
                              {subscription.category} · {subscription.cycle}
                            </p>
                          </div>
                        </div>
                      </div>

                      <div className="flex items-center justify-between gap-4 sm:justify-end">
                        <div className="text-left sm:text-right">
                          <p className="text-sm font-semibold text-foreground">
                            {formatCurrency(subscription.amount, subscription.currency)}
                          </p>
                          {subscription.currency !== baseCurrency && (
                            <p className="text-xs text-muted-foreground">
                              ≈ {formatCurrency(convertAmount(subscription.amount, subscription.currency), baseCurrency)}
                            </p>
                          )}
                          <p className="text-xs text-muted-foreground">
                            Due {formatDate(subscription.next_due)}
                          </p>
                        </div>

                        <div className="rounded-full border border-border bg-muted px-3 py-1 text-xs font-medium text-muted-foreground">
                          {daysUntil === null
                            ? 'No date'
                            : daysUntil < 0
                              ? 'Overdue'
                              : daysUntil === 0
                                ? 'Due today'
                                : `${daysUntil}d left`}
                        </div>
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </div>

          <div className="rounded-2xl bg-card p-6 shadow-md">
            <div className="mb-5 flex items-start justify-between gap-4">
              <div>
                <h2 className="text-lg font-semibold text-foreground">Budget overview</h2>
                <p className="mt-1 text-sm text-muted-foreground">
                  See which categories are healthy and which need attention.
                </p>
              </div>
              {budgets.length > 0 && (
                <div className="shrink-0 text-right">
                  <p className="text-sm font-semibold text-foreground">
                    {formatCurrency(remainingBudget, baseCurrency)}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {budgets.length} categor{budgets.length === 1 ? 'y' : 'ies'} · remaining
                  </p>
                </div>
              )}
            </div>

            {budgets.length === 0 ? (
              <div className="flex min-h-[220px] items-center justify-center rounded-xl border border-dashed border-border bg-muted/30">
                <div className="text-center">
                  <p className="text-sm font-medium text-foreground">No budgets set</p>
                  <p className="mt-1 text-sm text-muted-foreground">
                    Add category budgets to monitor monthly limits.
                  </p>
                </div>
              </div>
            ) : (
              <div className="space-y-4">
                {budgets.map((budget) => {
                  const spent = monthlyExpenses
                    .filter((expense) => expense.category === budget.category)
                    .reduce((sum, expense) => sum + (expense.converted_amount ?? convertAmount(expense.amount, expense.currency)), 0)

                  const percent = budget.monthly_limit > 0
                    ? (spent / budget.monthly_limit) * 100
                    : 0

                  const clampedPercent = Math.min(percent, 100)
                  const tone = getBudgetTone(percent)

                  return (
                    <div
                      key={budget.id}
                      className="rounded-xl border border-border bg-background/60 p-4"
                    >
                      <div className="mb-3 flex items-start justify-between gap-3">
                        <div>
                          <p className="text-sm font-semibold capitalize text-foreground">
                            {budget.category}
                          </p>
                          <p className="mt-1 text-xs text-muted-foreground">
                            {formatCurrency(spent,  baseCurrency)} of {formatCurrency(budget.monthly_limit,  baseCurrency)}
                          </p>
                        </div>

                        <span
                          className={`rounded-full border px-2.5 py-1 text-[11px] font-medium ${tone.badge}`}
                        >
                          {tone.label}
                        </span>
                      </div>

                      <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
                        <div
                          className={`h-full rounded-full transition-all ${tone.bar}`}
                          style={{ width: `${clampedPercent}%` }}
                        />
                      </div>

                      <div className="mt-2 flex items-center justify-between text-xs text-muted-foreground">
                        <span>{Math.round(percent)}%</span>
                        <span>
                          {budget.monthly_limit - spent > 0
                            ? `${formatCurrency(budget.monthly_limit - spent,  baseCurrency)} left`
                            : `${formatCurrency(spent - budget.monthly_limit, baseCurrency)} over`}
                        </span>
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        </section>
      </div>
    </div>
  )
}