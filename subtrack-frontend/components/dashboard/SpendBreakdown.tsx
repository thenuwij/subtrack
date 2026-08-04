'use client'

import { useMemo, useState, useSyncExternalStore } from 'react'
import Link from 'next/link'
import { ChevronDown, ChevronUp } from 'lucide-react'
import type { Subscription } from '@/types'
import { formatCurrency } from '@/lib/utils/currency'
import { CATEGORY_ORDER, categoryColor, formatCategory } from '@/lib/utils/categories'

export interface RankedPayment {
  subscription: Subscription
  monthly: number
}

type View = 'chart' | 'categories' | 'payments'

const VIEWS: { key: View; label: string }[] = [
  { key: 'chart', label: 'Chart' },
  { key: 'categories', label: 'Categories' },
  { key: 'payments', label: 'Payments' },
]

// Remembering the choice matters more than it sounds: someone who thinks in
// categories has to re-pick that view on every visit otherwise.
const STORAGE_KEY = 'subtrack.breakdown-view'
const VIEW_CHANGE_EVENT = 'subtrack:breakdown-view'

function isView(value: string | null): value is View {
  return value === 'chart' || value === 'categories' || value === 'payments'
}

// localStorage is the source of truth rather than component state seeded from
// it. Reading it through useSyncExternalStore keeps the server's render ('chart')
// and the client's first render consistent without a second render pass — and
// the `storage` subscription means switching view in one tab updates the others.
function subscribeToView(onChange: () => void) {
  window.addEventListener('storage', onChange)
  window.addEventListener(VIEW_CHANGE_EVENT, onChange)
  return () => {
    window.removeEventListener('storage', onChange)
    window.removeEventListener(VIEW_CHANGE_EVENT, onChange)
  }
}

function readStoredView(): View {
  const saved = localStorage.getItem(STORAGE_KEY)
  return isView(saved) ? saved : 'chart'
}

function storeView(next: View) {
  localStorage.setItem(STORAGE_KEY, next)
  window.dispatchEvent(new Event(VIEW_CHANGE_EVENT))
}

interface Props {
  ranked: RankedPayment[]
  monthlyTotal: number
  baseCurrency: string
}

export function SpendBreakdown({ ranked, monthlyTotal, baseCurrency }: Props) {
  const view = useSyncExternalStore(subscribeToView, readStoredView, () => 'chart' as View)
  const [expandedCategory, setExpandedCategory] = useState<string | null>(null)
  const [showAllPayments, setShowAllPayments] = useState(false)

  const categories = useMemo(() => {
    const totals = new Map<string, { total: number; items: RankedPayment[] }>()
    for (const entry of ranked) {
      const key = entry.subscription.category ?? 'other'
      const bucket = totals.get(key) ?? { total: 0, items: [] }
      bucket.total += entry.monthly
      bucket.items.push(entry)
      totals.set(key, bucket)
    }
    return [...totals.entries()]
      .map(([category, { total, items }]) => ({
        category,
        total,
        items,
        share: monthlyTotal > 0 ? (total / monthlyTotal) * 100 : 0,
      }))
      .sort(
        (a, b) =>
          CATEGORY_ORDER.indexOf(a.category as (typeof CATEGORY_ORDER)[number]) -
          CATEGORY_ORDER.indexOf(b.category as (typeof CATEGORY_ORDER)[number])
      )
  }, [ranked, monthlyTotal])

  // Ordered by size for the bar so the eye reads largest-first, while the
  // legend below keeps the stable category order.
  const segments = useMemo(
    () => [...categories].sort((a, b) => b.total - a.total),
    [categories]
  )

  if (ranked.length === 0) {
    return (
      <section className="rounded-2xl bg-card p-6 shadow-sm">
        <h2 className="text-base font-semibold text-foreground">Where your money goes</h2>
        <div className="mt-6 flex flex-col items-center justify-center py-10 text-center">
          <p className="text-sm font-medium text-foreground">Nothing to break down yet</p>
          <p className="mt-1 max-w-xs text-sm text-muted-foreground">
            Once you have a few recurring payments, this shows what they add up to.
          </p>
          <Link
            href="/subscriptions"
            className="mt-4 text-sm font-medium text-primary hover:underline"
          >
            Add a payment
          </Link>
        </div>
      </section>
    )
  }

  const visiblePayments = showAllPayments ? ranked : ranked.slice(0, 6)

  return (
    <section className="rounded-2xl bg-card p-6 shadow-sm">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-base font-semibold text-foreground">Where your money goes</h2>
          <p className="mt-0.5 text-sm text-muted-foreground">
            {categories.length} categor{categories.length === 1 ? 'y' : 'ies'} ·{' '}
            {ranked.length} payment{ranked.length === 1 ? '' : 's'}
          </p>
        </div>

        {/* Segmented control. Same pattern as iOS: one visible group, the
            active option filled rather than outlined. */}
        <div
          role="tablist"
          aria-label="Breakdown view"
          className="inline-flex shrink-0 self-start rounded-lg bg-muted p-0.5 sm:self-auto"
        >
          {VIEWS.map(option => (
            <button
              key={option.key}
              role="tab"
              type="button"
              aria-selected={view === option.key}
              onClick={() => storeView(option.key)}
              className={`rounded-[7px] px-3 py-1.5 text-xs font-medium transition-colors ${
                view === option.key
                  ? 'bg-card text-foreground shadow-sm'
                  : 'text-muted-foreground hover:text-foreground'
              }`}
            >
              {option.label}
            </button>
          ))}
        </div>
      </div>

      {view === 'chart' && (
        <div className="mt-6 flex flex-col items-center gap-8 sm:flex-row sm:items-center sm:gap-10">
          {/* A donut rather than another stacked bar: the hero already shows
              the same composition as a strip, and repeating it here would say
              nothing new. Hand-drawn in SVG — a charting library would be
              ~50kB for one shape. */}
          <svg
            viewBox="0 0 200 200"
            className="h-44 w-44 shrink-0 -rotate-90"
            role="img"
            aria-label={segments
              .map(s => `${formatCategory(s.category)} ${s.share.toFixed(0)} percent`)
              .join(', ')}
          >
            {(() => {
              const radius = 74
              const circumference = 2 * Math.PI * radius
              let offset = 0
              return segments.map(segment => {
                const length = (segment.share / 100) * circumference
                // A hairline gap makes adjacent segments legible without a
                // stroke, which would fight the category colour.
                const gap = segments.length > 1 ? 2 : 0
                const dash = Math.max(length - gap, 0.5)
                const element = (
                  <circle
                    key={segment.category}
                    cx="100"
                    cy="100"
                    r={radius}
                    fill="none"
                    stroke={categoryColor(segment.category)}
                    strokeWidth="26"
                    strokeDasharray={`${dash} ${circumference - dash}`}
                    strokeDashoffset={-offset}
                  />
                )
                offset += length
                return element
              })
            })()}
          </svg>

          <ul className="w-full min-w-0 space-y-3">
            {segments.map(segment => (
              <li key={segment.category} className="flex items-center gap-3">
                <span
                  className="h-2.5 w-2.5 shrink-0 rounded-full"
                  style={{ backgroundColor: categoryColor(segment.category) }}
                  aria-hidden="true"
                />
                <span className="min-w-0 flex-1 truncate text-sm text-foreground">
                  {formatCategory(segment.category)}
                </span>
                <span className="w-10 shrink-0 text-right text-sm tabular-nums text-muted-foreground">
                  {segment.share.toFixed(0)}%
                </span>
                <span className="w-28 shrink-0 text-right text-sm font-medium tabular-nums text-foreground">
                  {formatCurrency(segment.total, baseCurrency)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {view === 'categories' && (
        <ul className="mt-6 space-y-2">
          {categories.map(entry => {
            const isOpen = expandedCategory === entry.category
            return (
              <li key={entry.category}>
                <button
                  type="button"
                  aria-expanded={isOpen}
                  onClick={() => setExpandedCategory(isOpen ? null : entry.category)}
                  className="w-full rounded-xl px-3 py-3 text-left transition-colors hover:bg-muted/60"
                >
                  <div className="flex items-center gap-3">
                    <span
                      className="h-2.5 w-2.5 shrink-0 rounded-full"
                      style={{ backgroundColor: categoryColor(entry.category) }}
                      aria-hidden="true"
                    />
                    <span className="min-w-0 flex-1 truncate text-sm font-medium text-foreground">
                      {formatCategory(entry.category)}
                    </span>
                    <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
                      {entry.items.length} item{entry.items.length === 1 ? '' : 's'}
                    </span>
                    <span className="w-10 shrink-0 text-right text-sm tabular-nums text-muted-foreground">
                      {entry.share.toFixed(0)}%
                    </span>
                    <span className="w-28 shrink-0 text-right text-sm font-semibold tabular-nums text-foreground">
                      {formatCurrency(entry.total, baseCurrency)}
                      <span className="font-normal text-muted-foreground">/mo</span>
                    </span>
                    {isOpen ? (
                      <ChevronUp className="h-4 w-4 shrink-0 text-muted-foreground" />
                    ) : (
                      <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground" />
                    )}
                  </div>

                  <div className="mt-2.5 ml-[22px] h-1.5 overflow-hidden rounded-full bg-muted">
                    <div
                      className="h-full rounded-full transition-[width] duration-500"
                      style={{
                        width: `${entry.share}%`,
                        backgroundColor: categoryColor(entry.category),
                      }}
                    />
                  </div>
                </button>

                {isOpen && (
                  <ul className="mt-1 mb-2 ml-[34px] space-y-1.5 border-l border-border pl-4">
                    {entry.items.map(({ subscription, monthly }) => (
                      <li
                        key={subscription.id}
                        className="flex items-center justify-between gap-3 py-1"
                      >
                        <span className="min-w-0 truncate text-sm text-foreground">
                          {subscription.name}
                        </span>
                        <span className="shrink-0 text-sm tabular-nums text-muted-foreground">
                          {formatCurrency(monthly, baseCurrency)}/mo
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            )
          })}
        </ul>
      )}

      {view === 'payments' && (
        <div className="mt-6">
          <ul className="divide-y divide-border">
            {visiblePayments.map(({ subscription, monthly }) => {
              const share = monthlyTotal > 0 ? (monthly / monthlyTotal) * 100 : 0
              return (
                <li key={subscription.id} className="flex items-center gap-3 py-3">
                  <span
                    className="h-2.5 w-2.5 shrink-0 rounded-full"
                    style={{ backgroundColor: categoryColor(subscription.category) }}
                    aria-hidden="true"
                  />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium text-foreground">
                      {subscription.name}
                    </p>
                    <p className="truncate text-xs text-muted-foreground">
                      {formatCategory(subscription.category)} · {subscription.cycle}
                      {subscription.currency !== baseCurrency &&
                        ` · ${formatCurrency(subscription.amount, subscription.currency)}`}
                    </p>
                  </div>
                  <div className="shrink-0 text-right">
                    <p className="text-sm font-semibold tabular-nums text-foreground">
                      {formatCurrency(monthly, baseCurrency)}
                      <span className="font-normal text-muted-foreground">/mo</span>
                    </p>
                    <p className="text-xs tabular-nums text-muted-foreground">
                      {share.toFixed(0)}% · {formatCurrency(monthly * 12, baseCurrency)}/yr
                    </p>
                  </div>
                </li>
              )
            })}
          </ul>

          {ranked.length > 6 && (
            <button
              type="button"
              aria-expanded={showAllPayments}
              onClick={() => setShowAllPayments(value => !value)}
              className="mt-2 flex w-full items-center justify-center gap-1.5 rounded-lg py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            >
              {showAllPayments ? (
                <><ChevronUp className="h-4 w-4" /> Show less</>
              ) : (
                <><ChevronDown className="h-4 w-4" /> Show all {ranked.length}</>
              )}
            </button>
          )}
        </div>
      )}
    </section>
  )
}
