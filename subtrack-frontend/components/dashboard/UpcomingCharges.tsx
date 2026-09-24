'use client'

import { useState } from 'react'
import Link from 'next/link'
import { CalendarDays, ChevronDown, ChevronUp } from 'lucide-react'
import type { SubscriptionForecast } from '@/types'
import { Button } from '@/components/ui/button'
import { formatCurrency } from '@/lib/utils/currency'
import { formatStoredDate } from '@/lib/utils/dates'
import { BrandLogo } from '@/components/shared/BrandLogo'

function formatDueDate(value: string) {
  return formatStoredDate(value, {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
  })
}

interface Props {
  forecast: SubscriptionForecast | null
  error: string
  retrying: boolean
  onRetry: () => void
}

export function UpcomingCharges({ forecast, error, retrying, onRetry }: Props) {
  const [showAll, setShowAll] = useState(false)
  if (error && !forecast) {
    return (
      <section className="flex flex-col gap-3 rounded-2xl bg-card p-5 shadow-sm sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-base font-semibold text-foreground">Upcoming charges</h2>
          <p className="mt-1 text-sm text-muted-foreground">We couldn&apos;t calculate the next 2 weeks.</p>
        </div>
        <Button type="button" size="sm" variant="outline" disabled={retrying} onClick={onRetry}>
          {retrying ? 'Trying again…' : 'Try again'}
        </Button>
      </section>
    )
  }

  if (!forecast) return null
  const visible = showAll ? forecast.charges : forecast.charges.slice(0, 6)
  const conversionEstimated = forecast.currency_conversion.status === 'estimated'
  const hasVariableEstimates = forecast.charges.some(charge => charge.charge_amount_is_estimate)
  const totalIsEstimate = conversionEstimated || hasVariableEstimates

  return (
    <section className="rounded-2xl bg-card p-6 shadow-sm" aria-labelledby="upcoming-charges-heading">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 id="upcoming-charges-heading" className="text-base font-semibold text-foreground">Upcoming charges</h2>
          <p className="mt-0.5 text-sm text-muted-foreground">
            Next 2 weeks ·{' '}
            <span className="tabular-nums">
              {totalIsEstimate ? '≈ ' : ''}
              {formatCurrency(
                forecast.forecast_total_in_base,
                forecast.currency_conversion.base_currency,
              )}
              {forecast.unconverted_occurrence_count > 0 ? ' converted subtotal' : ''}
            </span>
          </p>
        </div>
        <Link href="/subscriptions" className="shrink-0 text-sm font-medium text-primary hover:underline">
          Manage
        </Link>
      </div>

      {error ? (
        <div className="mt-4 flex flex-col gap-3 rounded-xl border border-amber-500/25 bg-amber-500/5 p-3 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-xs text-muted-foreground">
            We couldn&apos;t refresh this forecast. The saved projection below may be out of date.
          </p>
          <Button type="button" size="sm" variant="outline" disabled={retrying} onClick={onRetry}>
            {retrying ? 'Trying again…' : 'Try again'}
          </Button>
        </div>
      ) : null}

      {visible.length === 0 ? (
        <div className="py-8 text-center">
          <CalendarDays className="mx-auto h-5 w-5 text-muted-foreground" aria-hidden="true" />
          <p className="mt-2 text-sm font-medium text-foreground">No charges are projected</p>
          <p className="mt-1 text-sm text-muted-foreground">Nothing with a saved date falls in the next 2 weeks.</p>
        </div>
      ) : (
        <ol className="mt-4 divide-y divide-border">
          {visible.map((charge, index) => {
            const baseAmount = charge.charge_amount_in_base
            return (
              <li key={`${charge.id}-${charge.due_at}-${index}`} className="flex items-center gap-3 py-3">
                <time dateTime={charge.due_at} className="w-20 shrink-0 text-xs font-medium tabular-nums text-muted-foreground sm:w-24">
                  {formatDueDate(charge.due_at)}
                </time>
                <BrandLogo name={charge.name} category={charge.category} className="h-7 w-7" />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium text-foreground">{charge.name}</p>
                  {charge.charge_kind === 'trial_conversion' ? (
                    <p className="mt-0.5 truncate text-xs text-muted-foreground">First charge after trial</p>
                  ) : null}
                </div>
                <div className="shrink-0 text-right">
                  <p className="text-sm font-semibold tabular-nums text-foreground">
                    {charge.charge_amount_is_estimate
                      || (conversionEstimated && charge.currency !== charge.base_currency)
                      ? '≈ ' : ''}
                    {formatCurrency(baseAmount ?? charge.amount, baseAmount === null ? charge.currency : charge.base_currency)}
                  </p>
                  {baseAmount !== null && charge.currency !== charge.base_currency ? (
                    <p className="mt-0.5 text-xs tabular-nums text-muted-foreground">
                      {formatCurrency(charge.amount, charge.currency)}
                    </p>
                  ) : baseAmount === null ? (
                    <p className="mt-0.5 text-[10px] text-muted-foreground">FX unavailable</p>
                  ) : null}
                </div>
              </li>
            )
          })}
        </ol>
      )}

      {forecast.charges.length > 6 ? (
        <button
          type="button"
          aria-expanded={showAll}
          onClick={() => setShowAll(value => !value)}
          className="mt-2 flex w-full items-center justify-center gap-1.5 rounded-lg py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
        >
          {showAll ? (
            <><ChevronUp className="h-4 w-4" /> Show fewer</>
          ) : (
            <><ChevronDown className="h-4 w-4" /> Show all {forecast.charges.length} occurrences</>
          )}
        </button>
      ) : null}

      <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
        {forecast.missing_due_date_count > 0 ? (
          <span>{forecast.missing_due_date_count} payment{forecast.missing_due_date_count === 1 ? '' : 's'} missing a date</span>
        ) : null}
        {forecast.unconverted_occurrence_count > 0 ? (
          <span>{forecast.unconverted_occurrence_count} occurrence{forecast.unconverted_occurrence_count === 1 ? '' : 's'} shown in native currency</span>
        ) : null}
        {forecast.currency_conversion.warning ? (
          <span>{forecast.currency_conversion.warning}</span>
        ) : null}
      </div>
    </section>
  )
}
