'use client'

import { useMemo, useState } from 'react'
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
import {
  dismissReminder,
  restoreReminder,
  getDetected,
  getGmailStatus,
  getPreferences,
  getReminders,
  getSubscriptionChanges,
  getSubscriptionForecast,
  getSubscriptions,
} from '@/lib/api'
import type {
  GmailStatus,
  DetectedSubscription,
  PaymentReminder,
  Preferences,
  Subscription,
  SubscriptionChange,
  SubscriptionForecast,
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
import {
  contributesToCommitment,
  monthlyEquivalentNative,
  yearlyEquivalentNative,
} from '@/lib/utils/recurrence'
import { UpcomingCharges } from '@/components/dashboard/UpcomingCharges'
import { NeedsAttention } from '@/components/dashboard/NeedsAttention'
import { GettingStarted } from '@/components/onboarding/GettingStarted'
import { apiKeys, errorMessage, useApi } from '@/lib/hooks/useApi'
import { getAccessToken, useIsDemo } from '@/lib/auth/session'

function formatDate(date: string) {
  return new Date(date).toLocaleDateString('en-AU', { day: 'numeric', month: 'short' })
}

export default function DashboardPage() {
  const [changesExpanded, setChangesExpanded] = useState(false)
  const {
    baseCurrency, canConvert, convertAmount, ratesLoading, ratesStale, ratesAsOf,
  } = useCurrency()

  const subscriptionsQuery = useApi<Subscription[]>(
    apiKeys.subscriptions('current'), token => getSubscriptions(token),
  )
  const changesQuery = useApi<SubscriptionChange[]>(
    apiKeys.subscriptionChanges(30), token => getSubscriptionChanges(token, 30),
  )
  const preferencesQuery = useApi<Preferences>(apiKeys.preferences, getPreferences)
  const gmailQuery = useApi<GmailStatus>(apiKeys.gmailStatus, getGmailStatus)
  const remindersQuery = useApi<PaymentReminder[]>(
    apiKeys.reminders(90), token => getReminders(token, { horizonDays: 90 }),
  )
  const forecastQuery = useApi<SubscriptionForecast>(
    apiKeys.forecast(14), token => getSubscriptionForecast(token, 14),
  )
  const detectionsQuery = useApi<DetectedSubscription[]>(
    apiKeys.detected('pending'), token => getDetected(token, 'pending'),
  )

  const queries = [
    subscriptionsQuery, changesQuery, preferencesQuery, gmailQuery,
    remindersQuery, forecastQuery, detectionsQuery,
  ]
  const loading = queries.some(query => query.isLoading)

  const subscriptions = useMemo(() => subscriptionsQuery.data ?? [], [subscriptionsQuery.data])
  const changes = useMemo(() => changesQuery.data ?? [], [changesQuery.data])
  const reminders = useMemo(() => remindersQuery.data ?? [], [remindersQuery.data])
  const pendingDetections = useMemo(() => detectionsQuery.data ?? [], [detectionsQuery.data])
  const monthlyIncome = preferencesQuery.data?.monthly_income ?? null
  const gmail = gmailQuery.data ?? null
  const isDemo = useIsDemo()
  const forecast = forecastQuery.data ?? null

  const loadError = errorMessage(subscriptionsQuery.error, 'Could not load recurring payments.')
  const changesError = errorMessage(changesQuery.error, 'Could not load recent changes.')
  const reminderError = errorMessage(remindersQuery.error, 'Could not load reminders.')
  const forecastError = errorMessage(forecastQuery.error, 'Could not calculate upcoming charges.')
  const remindersRetrying = remindersQuery.isValidating
  const forecastRetrying = forecastQuery.isValidating

  const [openedAt] = useState(() => Date.now())
  const gmailScanStale = useMemo(() => {
    const lastScanTime = gmail?.last_scanned_at
      ? new Date(gmail.last_scanned_at).getTime()
      : Number.NaN
    return Boolean(
      gmail?.connected
      && gmail.scan_status !== 'running'
      && Number.isFinite(lastScanTime)
      && openedAt - lastScanTime > 30 * 24 * 60 * 60 * 1000,
    )
  }, [gmail, openedAt])

  function refreshAll() {
    for (const query of queries) void query.mutate()
  }

  useRegisterAgentPageContext({
    visible_subscription_ids: subscriptions.slice(0, 25).map(subscription => subscription.id),
    visible_detection_ids: pendingDetections.slice(0, 25).map(detection => detection.id),
    visible_reminder_ids: reminders.slice(0, 25).map(reminder => reminder.id),
  })

  // Everything is normalised to a monthly figure in the base currency so the
  // numbers on this page are actually comparable to each other.
  const ranked = useMemo(() => {
    return subscriptions
      .filter(contributesToCommitment)
      .filter(subscription => canConvert(subscription.currency))
      .map((s) => ({
        subscription: s,
        monthly: convertAmount(monthlyEquivalentNative(s), s.currency) ?? 0,
        yearly: convertAmount(yearlyEquivalentNative(s), s.currency) ?? 0,
      }))
      .sort((a, b) => b.monthly - a.monthly)
  }, [subscriptions, canConvert, convertAmount])

  const activeTrials = useMemo(
    () => subscriptions.filter(subscription =>
      (subscription.status === 'active' || subscription.status === 'cancelling')
      && isActiveTrial(subscription)
    ),
    [subscriptions]
  )

  const contributingPayments = useMemo(
    () => subscriptions.filter(contributesToCommitment),
    [subscriptions],
  )

  const unavailableCurrencies = contributingPayments.length - ranked.length
  const hasVariableAmounts = ranked.some(entry => entry.subscription.amount_type === 'variable')

  const monthlyTotal = useMemo(
    () => ranked.reduce((sum, r) => sum + r.monthly, 0),
    [ranked]
  )

  const yearlyTotal = useMemo(
    () => ranked.reduce((sum, r) => sum + r.yearly, 0),
    [ranked],
  )

  const shareOfIncome =
    monthlyIncome && monthlyIncome > 0 ? (monthlyTotal / monthlyIncome) * 100 : null

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
    const accessToken = await getAccessToken()
    if (!accessToken) throw new Error('Your session has expired.')
    try {
      await dismissReminder(accessToken, id)
      void remindersQuery.mutate(
        current => current?.filter(reminder => reminder.id !== id),
        { revalidate: false },
      )
      toast.success('Reminder dismissed', {
        action: { label: 'Undo', onClick: () => void handleUndoDismissReminder(id) },
      })
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Could not dismiss reminder.')
    }
  }

  async function handleUndoDismissReminder(id: string) {
    try {
      const accessToken = await getAccessToken()
      if (!accessToken) throw new Error('Your session has expired.')
      await restoreReminder(accessToken, id)
      void remindersQuery.mutate()
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Could not restore reminder.')
    }
  }

  // Do not flash a base-currency-only subtotal while foreign exchange rates
  // are still loading. If the rate request fails, ratesLoading still settles
  // and the explicit exclusion message below takes over.
  const needsForeignRates = subscriptions.some(
    subscription => subscription.currency !== baseCurrency,
  )
  if (loading || (ratesLoading && needsForeignRates)) return <DashboardSkeleton />

  const hasPayments = subscriptions.length > 0

  if (loadError && !hasPayments) {
    return (
      <div className="mx-auto max-w-xl px-4 py-16 text-center sm:px-6">
        <div className="rounded-2xl border border-destructive/20 bg-card p-8 shadow-sm">
          <h1 className="text-xl font-semibold text-foreground">Couldn&apos;t load your dashboard</h1>
          <p className="mt-2 text-sm text-muted-foreground">{loadError}</p>
          <Button
            className="mt-5"
            onClick={refreshAll}
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

        <div className="mx-auto mt-12 max-w-md">
          <GettingStarted
            gmailConnected={Boolean(gmail?.connected)}
            hasPayments={hasPayments}
            hasIncome={monthlyIncome !== null}
          />
        </div>
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
      <div className="space-y-10">

        {loadError && (
          <div className="flex flex-col gap-3 rounded-xl border border-destructive/20 bg-destructive/5 p-4 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-sm text-muted-foreground">Couldn&apos;t refresh your payments. Showing the last loaded totals.</p>
            <Button variant="outline" size="sm" onClick={refreshAll}>Retry</Button>
          </div>
        )}

        {/* ── Hero ────────────────────────────────────────────────────────
            No card, no border, no icon chip. One number, given the room to
            be the thing you look at first. */}
        <section>
          <div className="flex items-start justify-between gap-4">
            <p className="text-sm font-medium text-muted-foreground">
              {hasVariableAmounts ? 'Estimated monthly commitment' : 'Your monthly commitment'}
            </p>
            <Link
              href="/subscriptions"
              className="shrink-0 text-sm font-medium text-primary hover:underline"
            >
              Manage
            </Link>
          </div>

          <p className="mt-2 text-5xl font-semibold tracking-tight tabular-nums text-foreground sm:text-6xl">
            {hasVariableAmounts ? '≈ ' : ''}{formatCurrency(monthlyTotal, baseCurrency)}
          </p>

          <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-1.5 text-sm text-muted-foreground">
            <span className="tabular-nums">
              {hasVariableAmounts ? '≈ ' : ''}{formatCurrency(yearlyTotal, baseCurrency)} annual equivalent
            </span>
            <span className="tabular-nums">
              {contributingPayments.length} paid payment{contributingPayments.length === 1 ? '' : 's'}
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

          {unavailableCurrencies > 0 ? (
            <p className="mt-4 text-xs leading-5 text-amber-700 dark:text-amber-300">
              {unavailableCurrencies} payment{unavailableCurrencies === 1 ? ' is' : 's are'} excluded from these totals because a reliable exchange rate is unavailable.
            </p>
          ) : null}
          {ratesStale ? (
            <p className="mt-2 text-xs leading-5 text-muted-foreground">
              Foreign-currency totals use the latest available cached rates{ratesAsOf ? ` from ${formatDate(ratesAsOf)}` : ''} and are estimates.
            </p>
          ) : null}
        </section>

        <div className="grid gap-10 xl:grid-cols-[minmax(0,1fr)_22rem] xl:items-start xl:gap-8">
        <div className="min-w-0 space-y-10 xl:col-start-2 xl:row-start-1 xl:space-y-6">
        <GettingStarted
          gmailConnected={Boolean(gmail?.connected)}
          hasPayments={hasPayments}
          hasIncome={monthlyIncome !== null}
        />
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
              onClick={() => void remindersQuery.mutate()}
              className="self-start sm:self-center"
            >
              {remindersRetrying ? 'Trying again…' : 'Try again'}
            </Button>
          </section>
        ) : null}

        <NeedsAttention
          detections={pendingDetections}
          forecast={forecast}
          gmail={gmail}
          gmailScanStale={gmailScanStale}
        />

        <UpcomingCharges
          forecast={forecast}
          error={forecastError}
          retrying={forecastRetrying}
          onRetry={() => void forecastQuery.mutate()}
        />

        {/* ── Inbox nudge — only while there's something to act on ─────── */}
        {gmail && !gmail.connected && !isDemo && (
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

        </div>

        <div className="min-w-0 space-y-10 xl:col-start-1 xl:row-start-1 xl:space-y-8">
        {/* ── Where your money goes ───────────────────────────────────── */}
        <SpendBreakdown
          ranked={ranked}
          monthlyTotal={monthlyTotal}
          baseCurrency={baseCurrency}
          unavailableCount={unavailableCurrencies}
        />

        {/* ── What changed ────────────────────────────────────────────── */}
        <section className="rounded-2xl bg-card p-6 shadow-sm">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h2 className="text-base font-semibold text-foreground">What changed</h2>
              <p className="mt-0.5 text-sm text-muted-foreground">
                Last 30 days
              </p>
            </div>
          </div>

          {changesError ? (
            <div className="mt-5 flex flex-col gap-3 rounded-xl border border-amber-500/25 bg-amber-500/5 p-4 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <p className="text-sm font-medium text-foreground">Recent changes are unavailable</p>
                <p className="mt-0.5 text-xs text-muted-foreground">We won&apos;t guess that nothing changed.</p>
              </div>
              <Button size="sm" variant="outline" onClick={() => void changesQuery.mutate()}>Try again</Button>
            </div>
          ) : changes.length === 0 ? (
            <div className="mt-6 py-8 text-center">
              <p className="text-sm font-medium text-foreground">Nothing changed</p>
              <p className="mt-1 text-sm text-muted-foreground">
                Your recurring payments cost the same as they did last month.
              </p>
            </div>
          ) : (
            <ul id="dashboard-changes-list" className="mt-4 divide-y divide-border">
              {(changesExpanded ? changes : changes.slice(0, 4)).map((change) => {
                const conversionAvailable = canConvert(change.currency)
                const delta = conversionAvailable
                  ? convertAmount(change.delta, change.currency) ?? 0
                  : change.delta
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
                        {!conversionAvailable
                          ? `${change.currency} conversion unavailable`
                          : change.kind === 'added'
                          ? 'Added'
                          : change.kind === 'removed'
                            ? 'Removed'
                            : `${formatCurrency(
                                convertAmount(change.old_monthly ?? 0, change.currency) ?? 0,
                                baseCurrency
                              )} → ${formatCurrency(
                                convertAmount(change.new_monthly ?? 0, change.currency) ?? 0,
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
                      {formatCurrency(Math.abs(delta), conversionAvailable ? baseCurrency : change.currency)}/mo
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
          {!ratesLoading && changes.some(change => change.currency !== baseCurrency) ? (
            <p className="mt-3 text-xs leading-5 text-muted-foreground">
              Foreign amounts use today&apos;s exchange rates.
            </p>
          ) : null}
        </section>
        </div>
        </div>
      </div>
    </div>
  )
}
