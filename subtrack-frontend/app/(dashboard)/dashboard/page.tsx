'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import Link from 'next/link'
import {
  ArrowDownRight,
  ArrowRight,
  ArrowUpRight,
  ChevronDown,
  ChevronUp,
  Mail,
  Minus,
  Sparkles,
} from 'lucide-react'
import { createClient } from '@/lib/supabase/client'
import {
  dismissReminder,
  getGmailStatus,
  getPreferences,
  getReminders,
  getSubscriptionChanges,
  getSubscriptions,
} from '@/lib/api'
import type {
  GmailStatus,
  PaymentReminder,
  Subscription,
  SubscriptionChange,
} from '@/types'
import { useCurrency } from '@/lib/context/currency'
import { formatCurrency } from '@/lib/utils/currency'
import { categoryColor } from '@/lib/utils/categories'
import { SpendBreakdown } from '@/components/dashboard/SpendBreakdown'
import { DashboardSkeleton } from '@/components/dashboard/DashboardSkeleton'
import { Button } from '@/components/ui/button'
import { ReminderCenter } from '@/components/reminders/ReminderCenter'
import { useRegisterAgentPageContext } from '@/lib/agent/page-context'
import { toast } from 'sonner'
import { isActiveTrial } from '@/lib/utils/trials'

// 52 weeks / 12 months. Using 4.33 loses ~0.04 of a week each month, which
// compounds to a visibly short annual figure on a large weekly bill like rent.
const WEEKS_PER_MONTH = 52 / 12

function toMonthly(amount: number, cycle: string) {
  if (cycle === 'weekly') return amount * WEEKS_PER_MONTH
  if (cycle === 'yearly') return amount / 12
  return amount
}

function formatDate(date: string) {
  return new Date(date).toLocaleDateString('en-AU', { day: 'numeric', month: 'short' })
}

export default function DashboardPage() {
  const [subscriptions, setSubscriptions] = useState<Subscription[]>([])
  const [changes, setChanges] = useState<SubscriptionChange[]>([])
  const [monthlyIncome, setMonthlyIncome] = useState<number | null>(null)
  const [gmail, setGmail] = useState<GmailStatus | null>(null)
  const [reminders, setReminders] = useState<PaymentReminder[]>([])
  const [reminderError, setReminderError] = useState('')
  const [remindersRetrying, setRemindersRetrying] = useState(false)
  const [changesExpanded, setChangesExpanded] = useState(false)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const { baseCurrency, convertAmount } = useCurrency()

  const fetchData = useCallback(async () => {
    try {
      const supabase = createClient()
      const { data: { session } } = await supabase.auth.getSession()
      if (!session) return

      const token = session.access_token
      const [subsResult, changesResult, preferencesResult, gmailStatus, reminderResult] = await Promise.all([
        getSubscriptions(token)
          .then(rows => ({ rows, error: '' }))
          .catch(error => ({
            rows: null,
            error: error instanceof Error ? error.message : 'Could not load recurring payments.',
          })),
        getSubscriptionChanges(token, 30).catch(() => null),
        getPreferences(token).catch(() => null),
        getGmailStatus(token).catch(() => null),
        getReminders(token, { horizonDays: 90 })
          .then(rows => ({ rows, error: '' }))
          .catch(error => ({
            rows: [],
            error: error instanceof Error ? error.message : 'Could not load reminders.',
          })),
      ])

      if (subsResult.rows) {
        setSubscriptions(subsResult.rows)
        setLoadError('')
      } else {
        setLoadError(subsResult.error)
      }
      if (changesResult) setChanges(changesResult)
      if (preferencesResult) setMonthlyIncome(preferencesResult.monthly_income ?? null)
      setGmail(gmailStatus)
      setReminders(reminderResult.rows)
      setReminderError(reminderResult.error)
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : 'Could not load your dashboard.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void fetchData()
    const refresh = () => { void fetchData() }
    window.addEventListener('subtrack:data-changed', refresh)
    return () => window.removeEventListener('subtrack:data-changed', refresh)
  }, [fetchData])

  useRegisterAgentPageContext({
    visible_subscription_ids: subscriptions.slice(0, 25).map(subscription => subscription.id),
    visible_reminder_ids: reminders.slice(0, 25).map(reminder => reminder.id),
  })

  // Everything is normalised to a monthly figure in the base currency so the
  // numbers on this page are actually comparable to each other.
  const ranked = useMemo(() => {
    return subscriptions
      .filter(subscription => !isActiveTrial(subscription))
      .map((s) => ({
        subscription: s,
        monthly: convertAmount(toMonthly(s.amount, s.cycle), s.currency),
      }))
      .sort((a, b) => b.monthly - a.monthly)
  }, [subscriptions, convertAmount])

  const activeTrials = useMemo(
    () => subscriptions.filter(subscription => isActiveTrial(subscription)),
    [subscriptions]
  )

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

  // The hero bar, in the same colours as the breakdown below it, so the two
  // read as one system rather than two unrelated charts.
  const heroSegments = useMemo(() => {
    const totals = new Map<string, number>()
    for (const { subscription, monthly } of ranked) {
      const key = subscription.category ?? 'other'
      totals.set(key, (totals.get(key) ?? 0) + monthly)
    }
    return [...totals.entries()]
      .map(([category, total]) => ({
        category,
        share: monthlyTotal > 0 ? (total / monthlyTotal) * 100 : 0,
      }))
      .sort((a, b) => b.share - a.share)
  }, [ranked, monthlyTotal])

  async function handleDismissReminder(id: string) {
    const { data: { session } } = await createClient().auth.getSession()
    if (!session) throw new Error('Your session has expired.')
    try {
      await dismissReminder(session.access_token, id)
      setReminders(current => current.filter(reminder => reminder.id !== id))
      toast.success('Reminder dismissed')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Could not dismiss reminder.')
    }
  }

  async function retryReminders() {
    setRemindersRetrying(true)
    try {
      const { data: { session } } = await createClient().auth.getSession()
      if (!session) throw new Error('Your session has expired.')
      const rows = await getReminders(session.access_token, { horizonDays: 90 })
      setReminders(rows)
      setReminderError('')
    } catch (error) {
      setReminderError(error instanceof Error ? error.message : 'Could not load reminders.')
    } finally {
      setRemindersRetrying(false)
    }
  }

  if (loading) return <DashboardSkeleton />

  const hasPayments = subscriptions.length > 0

  if (loadError && !hasPayments) {
    return (
      <div className="mx-auto max-w-xl px-4 py-16 text-center sm:px-6">
        <div className="rounded-2xl border border-destructive/20 bg-card p-8 shadow-sm">
          <h1 className="text-xl font-semibold text-foreground">Couldn&apos;t load your dashboard</h1>
          <p className="mt-2 text-sm text-muted-foreground">{loadError}</p>
          <Button
            className="mt-5"
            onClick={() => {
              setLoading(true)
              void fetchData()
            }}
          >
            Try again
          </Button>
        </div>
      </div>
    )
  }

  // First run is the product's one chance to explain itself. A dashboard of
  // zeroes explains nothing, so the empty state sells the thing that makes
  // this worth using instead.
  if (!hasPayments) {
    return (
      <div className="mx-auto max-w-3xl px-4 py-12 sm:px-6 lg:px-8">
        <div className="text-center">
          <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-primary/10 text-primary">
            <Sparkles className="h-7 w-7" />
          </div>
          <h1 className="mt-6 text-3xl font-semibold tracking-tight text-foreground sm:text-4xl">
            Let&apos;s find what you&apos;re paying for
          </h1>
          <p className="mx-auto mt-3 max-w-lg text-base text-muted-foreground">
            Subtrack reads the receipts already sitting in your inbox and works out
            which ones are recurring — so you don&apos;t have to remember them.
          </p>

          <div className="mt-8 flex flex-col items-center justify-center gap-3 sm:flex-row">
            <Button asChild size="lg">
              <Link href={gmail?.connected ? '/review' : '/account#inbox'}>
                {gmail?.connected ? 'Review what we found' : 'Connect Gmail'}
                <ArrowRight className="ml-1.5 h-4 w-4" />
              </Link>
            </Button>
            <Button asChild variant="ghost" size="lg">
              <Link href="/subscriptions">Add one manually</Link>
            </Button>
          </div>
        </div>

        <ol className="mx-auto mt-14 grid max-w-2xl gap-6 text-left sm:grid-cols-3">
          {[
            { step: '1', title: 'Connect Gmail', body: 'Read-only access to receipt emails. Nothing else is touched.' },
            { step: '2', title: 'We scan for receipts', body: 'Repeated charges from the same biller become a suggestion.' },
            { step: '3', title: 'You approve', body: 'Nothing joins your list until you say so.' },
          ].map(item => (
            <li key={item.step}>
              <span className="flex h-7 w-7 items-center justify-center rounded-full bg-muted text-xs font-semibold text-muted-foreground">
                {item.step}
              </span>
              <p className="mt-3 text-sm font-semibold text-foreground">{item.title}</p>
              <p className="mt-1 text-sm text-muted-foreground">{item.body}</p>
            </li>
          ))}
        </ol>
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-5xl px-4 py-8 sm:px-6 lg:px-8">
      <div className="space-y-10">

        {loadError && (
          <div className="flex flex-col gap-3 rounded-xl border border-destructive/20 bg-destructive/5 p-4 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-sm text-muted-foreground">Couldn&apos;t refresh your payments. Showing the last loaded totals.</p>
            <Button variant="outline" size="sm" onClick={() => void fetchData()}>Retry</Button>
          </div>
        )}

        {/* ── Hero ────────────────────────────────────────────────────────
            No card, no border, no icon chip. One number, given the room to
            be the thing you look at first. */}
        <section>
          <div className="flex items-start justify-between gap-4">
            <p className="text-sm font-medium text-muted-foreground">
              Your monthly commitment
            </p>
            <Link
              href="/subscriptions"
              className="shrink-0 text-sm font-medium text-primary hover:underline"
            >
              Manage
            </Link>
          </div>

          <p className="mt-2 text-5xl font-semibold tracking-tight tabular-nums text-foreground sm:text-6xl">
            {formatCurrency(monthlyTotal, baseCurrency)}
          </p>

          <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-1.5 text-sm text-muted-foreground">
            <span className="tabular-nums">
              {formatCurrency(monthlyTotal * 12, baseCurrency)} a year
            </span>
            <span className="tabular-nums">
              {ranked.length} paid payment{ranked.length === 1 ? '' : 's'}
              {activeTrials.length > 0
                ? ` · ${activeTrials.length} free trial${activeTrials.length === 1 ? '' : 's'}`
                : ''}
            </span>
            {shareOfIncome !== null ? (
              // Stated plainly. Colouring this red would be scolding someone
              // for their rent, which is not a judgement this app should make.
              <span className="tabular-nums">
                <span className="font-medium text-foreground">
                  {shareOfIncome.toFixed(0)}%
                </span>{' '}
                of your income
              </span>
            ) : (
              <Link href="/account" className="text-primary hover:underline">
                Add your income to see this as a share
              </Link>
            )}
          </div>

          {heroSegments.length > 0 && (
            <div
              className="mt-6 flex h-2.5 w-full gap-0.5 overflow-hidden rounded-full"
              aria-hidden="true"
            >
              {heroSegments.map(segment => (
                <div
                  key={segment.category}
                  className="h-full first:rounded-l-full last:rounded-r-full"
                  style={{
                    width: `${Math.max(segment.share, 0.8)}%`,
                    backgroundColor: categoryColor(segment.category),
                  }}
                />
              ))}
            </div>
          )}
        </section>

        <ReminderCenter
          reminders={reminders}
          onDismiss={handleDismissReminder}
        />
        {reminderError ? (
          <section className="flex flex-col gap-3 rounded-2xl border border-amber-500/25 bg-amber-500/5 p-4 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <p className="text-sm font-semibold text-foreground">Reminders are unavailable</p>
              <p className="mt-0.5 text-xs text-muted-foreground">{reminderError}</p>
            </div>
            <Button
              size="sm"
              variant="outline"
              disabled={remindersRetrying}
              onClick={() => void retryReminders()}
              className="self-start sm:self-center"
            >
              {remindersRetrying ? 'Trying again…' : 'Try again'}
            </Button>
          </section>
        ) : null}

        {/* ── Inbox nudge — only while there's something to act on ─────── */}
        {gmail && !gmail.connected && (
          <section className="flex flex-col gap-4 rounded-2xl bg-card p-5 shadow-sm sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-start gap-3">
              <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                <Mail className="h-4 w-4" />
              </div>
              <div>
                <p className="text-sm font-semibold text-foreground">
                  Find the ones you&apos;ve forgotten
                </p>
                <p className="mt-0.5 text-sm text-muted-foreground">
                  Connect Gmail and Subtrack will spot recurring charges in your
                  receipts. Read-only, and nothing is added without your approval.
                </p>
              </div>
            </div>
            <Button asChild className="shrink-0 self-start sm:self-center">
              <Link href="/account#inbox">Connect Gmail</Link>
            </Button>
          </section>
        )}

        {/* ── Where your money goes ───────────────────────────────────── */}
        <SpendBreakdown
          ranked={ranked}
          monthlyTotal={monthlyTotal}
          baseCurrency={baseCurrency}
        />

        {/* ── What changed ────────────────────────────────────────────── */}
        <section className="rounded-2xl bg-card p-6 shadow-sm">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h2 className="text-base font-semibold text-foreground">What changed</h2>
              <p className="mt-0.5 text-sm text-muted-foreground">
                Additions, price rises, and cancellations in the last 30 days.
              </p>
            </div>
            {changes.length > 0 && netChange !== 0 && (
              <div className="shrink-0 text-right">
                <p
                  className="text-sm font-semibold tabular-nums"
                  style={{ color: netChange > 0 ? 'var(--increase)' : 'var(--decrease)' }}
                >
                  {netChange > 0 ? '+' : '−'}
                  {formatCurrency(Math.abs(netChange), baseCurrency)}
                </p>
                <p className="text-xs text-muted-foreground">net per month</p>
              </div>
            )}
          </div>

          {changes.length === 0 ? (
            <div className="mt-6 py-8 text-center">
              <p className="text-sm font-medium text-foreground">Nothing changed</p>
              <p className="mt-1 text-sm text-muted-foreground">
                Your recurring payments cost the same as they did last month.
              </p>
            </div>
          ) : (
            <ul id="dashboard-changes-list" className="mt-4 divide-y divide-border">
              {(changesExpanded ? changes : changes.slice(0, 4)).map((change) => {
                const delta = convertAmount(change.delta, change.currency)
                const tone =
                  delta > 0 ? 'var(--increase)' : delta < 0 ? 'var(--decrease)' : undefined

                return (
                  <li key={change.id} className="flex items-center gap-3 py-3">
                    <div
                      className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg"
                      style={{
                        backgroundColor: tone
                          ? `color-mix(in oklch, ${tone} 12%, transparent)`
                          : 'var(--muted)',
                        color: tone ?? 'var(--muted-foreground)',
                      }}
                    >
                      {delta > 0 ? (
                        <ArrowUpRight className="h-4 w-4" />
                      ) : delta < 0 ? (
                        <ArrowDownRight className="h-4 w-4" />
                      ) : (
                        <Minus className="h-4 w-4" />
                      )}
                    </div>

                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium text-foreground">
                        {change.name}
                      </p>
                      <p className="truncate text-xs text-muted-foreground">
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

                    <p
                      className="shrink-0 text-sm font-semibold tabular-nums"
                      style={{ color: tone ?? 'var(--muted-foreground)' }}
                    >
                      {delta > 0 ? '+' : delta < 0 ? '−' : ''}
                      {formatCurrency(Math.abs(delta), baseCurrency)}/mo
                    </p>
                  </li>
                )
              })}
              {changes.length > 4 && (
                <li>
                  <button
                    type="button"
                    aria-expanded={changesExpanded}
                    aria-controls="dashboard-changes-list"
                    onClick={() => setChangesExpanded(value => !value)}
                    className="flex w-full items-center justify-center gap-1.5 rounded-lg py-2.5 text-sm font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                  >
                    {changesExpanded ? (
                      <><ChevronUp className="h-4 w-4" /> Show less</>
                    ) : (
                      <><ChevronDown className="h-4 w-4" /> Show {changes.length - 4} more</>
                    )}
                  </button>
                </li>
              )}
            </ul>
          )}
        </section>
      </div>
    </div>
  )
}
