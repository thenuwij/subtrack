'use client'

import Link from 'next/link'
import type { DetectedSubscription, GmailStatus, SubscriptionForecast } from '@/types'

interface Props {
  detections: DetectedSubscription[]
  forecast: SubscriptionForecast | null
  gmail: GmailStatus | null
  gmailScanStale: boolean
}

export function NeedsAttention({ detections, forecast, gmail, gmailScanStale }: Props) {
  const uncertainDetections = detections.filter(item =>
    item.confidence !== 'high'
    || item.cadence_confidence !== 'high'
    || (item.next_due !== null && item.due_date_confidence !== 'high')
    || (item.next_due === null && !item.cancelled && !item.trial_ends_at)
  ).length
  const unknownTrialPrices = detections.filter(item =>
    Boolean(item.trial_ends_at) && item.amount <= 0 && !item.cancelled
  ).length
  const missingDates = forecast?.missing_due_date_count ?? 0
  const unconverted = forecast?.unconverted_occurrence_count ?? 0
  const pausedWithoutResume = forecast?.paused_without_resume_count ?? 0
  const estimatedPayments = new Set(
    forecast?.charges
      .filter(charge => charge.charge_amount_is_estimate)
      .map(charge => charge.id) ?? [],
  ).size
  const scanIsPartial = Boolean(gmail?.connected && gmail.scan_partial)

  if (!uncertainDetections && !unknownTrialPrices && !missingDates
      && !unconverted && !pausedWithoutResume && !estimatedPayments
      && !gmailScanStale && !scanIsPartial) {
    return null
  }

  return (
    <section className="rounded-2xl bg-card p-5 shadow-sm" aria-labelledby="needs-attention-heading">
      <h2 id="needs-attention-heading" className="text-sm font-semibold text-foreground">Needs attention</h2>
      <ul className="mt-3 space-y-2 text-sm">
        {uncertainDetections > 0 ? (
          <li className="flex items-start justify-between gap-4">
            <span className="text-muted-foreground">
              Check the frequency or next date on {uncertainDetections} inbox finding{uncertainDetections === 1 ? '' : 's'}.
            </span>
            <Link href="/review" className="shrink-0 font-medium text-primary hover:underline">Review</Link>
          </li>
        ) : null}
        {unknownTrialPrices > 0 ? (
          <li className="flex items-start justify-between gap-4">
            <span className="text-muted-foreground">
              Add the post-trial price for {unknownTrialPrices} free trial{unknownTrialPrices === 1 ? '' : 's'}.
            </span>
            <Link href="/review" className="shrink-0 font-medium text-primary hover:underline">Review</Link>
          </li>
        ) : null}
        {missingDates > 0 ? (
          <li className="flex items-start justify-between gap-4">
            <span className="text-muted-foreground">
              {missingDates} current payment{missingDates === 1 ? '' : 's'} need a next expected date.
            </span>
            <Link href="/subscriptions" className="shrink-0 font-medium text-primary hover:underline">Payments</Link>
          </li>
        ) : null}
        {pausedWithoutResume > 0 ? (
          <li className="flex items-start justify-between gap-4">
            <span className="text-muted-foreground">
              {pausedWithoutResume} paused payment{pausedWithoutResume === 1 ? ' has' : 's have'} no resume date.
            </span>
            <Link href="/subscriptions" className="shrink-0 font-medium text-primary hover:underline">Payments</Link>
          </li>
        ) : null}
        {unconverted > 0 ? (
          <li className="flex items-start justify-between gap-4">
            <span className="text-muted-foreground">
              {unconverted} upcoming occurrence{unconverted === 1 ? '' : 's'} cannot be converted to your base currency yet.
            </span>
            <Link href="/subscriptions" className="shrink-0 font-medium text-primary hover:underline">Payments</Link>
          </li>
        ) : null}
        {estimatedPayments > 0 ? (
          <li className="flex items-start justify-between gap-4">
            <span className="text-muted-foreground">
              {estimatedPayments} variable payment{estimatedPayments === 1 ? ' uses' : 's use'} the latest saved estimate.
            </span>
            <Link href="/subscriptions" className="shrink-0 font-medium text-primary hover:underline">Payments</Link>
          </li>
        ) : null}
        {scanIsPartial ? (
          <li className="flex items-start justify-between gap-4">
            <span className="text-muted-foreground">
              The latest inbox scan ended early. Findings saved so far are ready to review.
            </span>
            <Link href="/review" className="shrink-0 font-medium text-primary hover:underline">Review</Link>
          </li>
        ) : gmailScanStale ? (
          <li className="flex items-start justify-between gap-4">
            <span className="text-muted-foreground">
              Gmail has not been scanned in over 30 days, so recent changes may be missing.
            </span>
            <Link href="/review" className="shrink-0 font-medium text-primary hover:underline">Scan</Link>
          </li>
        ) : null}
      </ul>
    </section>
  )
}
