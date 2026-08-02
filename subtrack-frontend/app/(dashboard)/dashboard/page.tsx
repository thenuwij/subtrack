'use client'

import { useEffect, useMemo, useState } from 'react'
import Link from 'next/link'
import { ArrowDownRight, ArrowUpRight, CreditCard, Minus } from 'lucide-react'
import { createClient } from '@/lib/supabase/client'
import { getSubscriptions, getSubscriptionChanges, getPreferences } from '@/lib/api'
import type { Subscription, SubscriptionChange } from '@/types'
import { useCurrency } from '@/lib/context/currency'
import { formatCurrency } from '@/lib/utils/currency'

function Skeleton({ className }: { className?: string }) {
  return <div className={`animate-pulse rounded-md bg-muted ${className ?? ''}`} />
}

function toMonthly(amount: number, cycle: string) {
  if (cycle === 'weekly') return amount * 4.33
  if (cycle === 'yearly') return amount / 12
  return amount
}

function formatDate(date: string) {
  return new Date(date).toLocaleDateString('en-AU', { day: 'numeric', month: 'short' })
}

// Framing only — a share of income, not a judgement about what anyone should spend.
function getShareTone(percent: number) {
  if (percent >= 20) return 'text-destructive'
  if (percent >= 10) return 'text-amber-600 dark:text-amber-400'
  return 'text-foreground'
}

export default function DashboardPage() {
  const [subscriptions, setSubscriptions] = useState<Subscription[]>([])
  const [changes, setChanges] = useState<SubscriptionChange[]>([])
  const [monthlyIncome, setMonthlyIncome] = useState<number | null>(null)
  const [loading, setLoading] = useState(true)
  const { baseCurrency, convertAmount } = useCurrency()

  useEffect(() => {
    async function fetchData() {
      try {
        const supabase = createClient()
        const { data: { session } } = await supabase.auth.getSession()
        if (!session) return

        const token = session.access_token
        const [subs, chgs, prefs] = await Promise.all([
          getSubscriptions(token),
          getSubscriptionChanges(token, 30),
          getPreferences(token),
        ])

        setSubscriptions(subs)
        setChanges(chgs)
        setMonthlyIncome(prefs.monthly_income ?? null)
      } finally {
        setLoading(false)
      }
    }

    fetchData()
  }, [])

  const currentMonth = new Date()

  // Everything is normalised to a monthly figure in the base currency so the
  // numbers on this page are actually comparable to each other.
  const ranked = useMemo(() => {
    return subscriptions
      .map((s) => ({
        subscription: s,
        monthly: convertAmount(toMonthly(s.amount, s.cycle), s.currency),
      }))
      .sort((a, b) => b.monthly - a.monthly)
  }, [subscriptions, convertAmount])

  const monthlyTotal = useMemo(
    () => ranked.reduce((sum, r) => sum + r.monthly, 0),
    [ranked]
  )

  const shareOfIncome =
    monthlyIncome && monthlyIncome > 0 ? (monthlyTotal / monthlyIncome) * 100 : null

  const netChange = useMemo(
    () => changes.reduce((sum, c) => sum + convertAmount(c.delta, c.currency), 0),
    [changes, convertAmount]
  )

  if (loading) {
    return (
      <div className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
        <div className="space-y-8">
          <div className="space-y-3">
            <Skeleton className="h-8 w-56" />
            <Skeleton className="h-4 w-72" />
          </div>
          <Skeleton className="h-44 rounded-2xl" />
          <Skeleton className="h-64 rounded-2xl" />
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
              What you&apos;re committed to
            </h1>
            <p className="max-w-2xl text-sm text-muted-foreground sm:text-base">
              Every recurring charge you&apos;re signed up for, what it adds up to, and what
              changed since last month.
            </p>
          </div>

          <div className="rounded-xl bg-card px-4 py-3 shadow-md">
            <p className="text-xs uppercase tracking-[0.16em] text-muted-foreground">
              Current month
            </p>
            <p className="mt-1 text-sm font-medium text-foreground">
              {currentMonth.toLocaleDateString('en-AU', { month: 'long', year: 'numeric' })}
            </p>
          </div>
        </section>

        {/* The headline number */}
        <section className="rounded-2xl bg-card p-6 shadow-md">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10 text-primary">
              <CreditCard className="h-5 w-5" />
            </div>
            <p className="text-sm font-medium text-foreground">Monthly subscriptions</p>
          </div>

          <p className="mt-4 text-5xl font-bold tracking-tight tabular-nums text-foreground">
            {formatCurrency(monthlyTotal, baseCurrency)}
          </p>

          <div className="mt-4 flex flex-col gap-2 text-sm text-muted-foreground sm:flex-row sm:items-center sm:gap-6">
            <span>
              {formatCurrency(monthlyTotal * 12, baseCurrency)} a year
            </span>
            <span>
              {subscriptions.length} active subscription{subscriptions.length === 1 ? '' : 's'}
            </span>
            {shareOfIncome !== null ? (
              <span className={getShareTone(shareOfIncome)}>
                {shareOfIncome.toFixed(1)}% of your monthly income
              </span>
            ) : (
              <Link href="/account" className="text-primary underline underline-offset-4">
                Add your income to see this as a share
              </Link>
            )}
          </div>
        </section>

        {/* What changed */}
        <section className="rounded-2xl bg-card p-6 shadow-md">
          <div className="mb-5 flex items-start justify-between gap-4">
            <div>
              <h2 className="text-lg font-semibold text-foreground">What changed</h2>
              <p className="mt-1 text-sm text-muted-foreground">
                Additions, price rises, and cancellations in the last 30 days.
              </p>
            </div>
            {changes.length > 0 && (
              <div className="shrink-0 text-right">
                <p
                  className={`text-sm font-semibold tabular-nums ${
                    netChange > 0
                      ? 'text-destructive'
                      : netChange < 0
                        ? 'text-emerald-600 dark:text-emerald-400'
                        : 'text-foreground'
                  }`}
                >
                  {netChange > 0 ? '+' : netChange < 0 ? '−' : ''}
                  {formatCurrency(Math.abs(netChange), baseCurrency)}
                </p>
                <p className="text-xs text-muted-foreground">net per month</p>
              </div>
            )}
          </div>

          {changes.length === 0 ? (
            <div className="flex min-h-[140px] items-center justify-center rounded-xl border border-dashed border-border bg-muted/30">
              <div className="text-center">
                <p className="text-sm font-medium text-foreground">Nothing changed</p>
                <p className="mt-1 text-sm text-muted-foreground">
                  Your subscriptions cost the same as they did last month.
                </p>
              </div>
            </div>
          ) : (
            <div className="space-y-3">
              {changes.map((change) => {
                const delta = convertAmount(change.delta, change.currency)
                const isIncrease = delta > 0

                return (
                  <div
                    key={change.id}
                    className="flex items-center justify-between gap-4 rounded-xl border border-border bg-background/60 p-4"
                  >
                    <div className="flex min-w-0 items-center gap-3">
                      <div
                        className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${
                          isIncrease
                            ? 'bg-destructive/10 text-destructive'
                            : delta < 0
                              ? 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400'
                              : 'bg-muted text-muted-foreground'
                        }`}
                      >
                        {isIncrease ? (
                          <ArrowUpRight className="h-4 w-4" />
                        ) : delta < 0 ? (
                          <ArrowDownRight className="h-4 w-4" />
                        ) : (
                          <Minus className="h-4 w-4" />
                        )}
                      </div>
                      <div className="min-w-0">
                        <p className="truncate text-sm font-semibold text-foreground">
                          {change.name}
                        </p>
                        <p className="text-xs text-muted-foreground">
                          {change.kind === 'added'
                            ? 'Added'
                            : change.kind === 'removed'
                              ? 'Cancelled'
                              : `${formatCurrency(
                                  convertAmount(change.old_monthly ?? 0, change.currency),
                                  baseCurrency
                                )} → ${formatCurrency(
                                  convertAmount(change.new_monthly ?? 0, change.currency),
                                  baseCurrency
                                )}`}{' '}
                          · {formatDate(change.changed_at)}
                        </p>
                      </div>
                    </div>

                    <p
                      className={`shrink-0 text-sm font-semibold tabular-nums ${
                        isIncrease
                          ? 'text-destructive'
                          : delta < 0
                            ? 'text-emerald-600 dark:text-emerald-400'
                            : 'text-muted-foreground'
                      }`}
                    >
                      {isIncrease ? '+' : delta < 0 ? '−' : ''}
                      {formatCurrency(Math.abs(delta), baseCurrency)}/mo
                    </p>
                  </div>
                )
              })}
            </div>
          )}
        </section>

        {/* Where the money actually goes */}
        <section className="rounded-2xl bg-card p-6 shadow-md">
          <div className="mb-5">
            <h2 className="text-lg font-semibold text-foreground">Biggest first</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Ranked by what each one costs you over a year.
            </p>
          </div>

          {ranked.length === 0 ? (
            <div className="flex min-h-[180px] items-center justify-center rounded-xl border border-dashed border-border bg-muted/30">
              <div className="text-center">
                <p className="text-sm font-medium text-foreground">No subscriptions yet</p>
                <Link
                  href="/subscriptions"
                  className="mt-1 inline-block text-sm text-primary underline underline-offset-4"
                >
                  Add your first one
                </Link>
              </div>
            </div>
          ) : (
            <div className="space-y-3">
              {ranked.map(({ subscription, monthly }) => {
                const share = monthlyTotal > 0 ? (monthly / monthlyTotal) * 100 : 0

                return (
                  <div
                    key={subscription.id}
                    className="rounded-xl border border-border bg-background/60 p-4"
                  >
                    <div className="flex items-start justify-between gap-4">
                      <div className="min-w-0">
                        <p className="truncate text-sm font-semibold text-foreground">
                          {subscription.name}
                        </p>
                        <p className="text-xs capitalize text-muted-foreground">
                          {subscription.category} · {subscription.cycle}
                          {subscription.currency !== baseCurrency &&
                            ` · ${formatCurrency(subscription.amount, subscription.currency)}`}
                        </p>
                      </div>

                      <div className="shrink-0 text-right">
                        <p className="text-sm font-semibold tabular-nums text-foreground">
                          {formatCurrency(monthly * 12, baseCurrency)}
                          <span className="font-normal text-muted-foreground">/yr</span>
                        </p>
                        <p className="text-xs tabular-nums text-muted-foreground">
                          {formatCurrency(monthly, baseCurrency)}/mo
                        </p>
                      </div>
                    </div>

                    <div className="mt-3 h-1.5 w-full overflow-hidden rounded-full bg-muted">
                      <div
                        className="h-full rounded-full bg-primary transition-all"
                        style={{ width: `${share}%` }}
                      />
                    </div>
                    <p className="mt-1.5 text-xs tabular-nums text-muted-foreground">
                      {share.toFixed(0)}% of your subscription spend
                    </p>
                  </div>
                )
              })}
            </div>
          )}
        </section>
      </div>
    </div>
  )
}
