'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { ArrowUpRight, Check, Mail, X } from 'lucide-react'
import { createClient } from '@/lib/supabase/client'
import {
  approveDetected,
  dismissDetected,
  getDetected,
  getGmailStatus,
  startGmailScan,
} from '@/lib/api'
import type { DetectedSubscription, GmailStatus } from '@/types'
import { formatCurrency } from '@/lib/utils/currency'
import { Button } from '@/components/ui/button'

function Skeleton({ className }: { className?: string }) {
  return <div className={`animate-pulse rounded-md bg-muted ${className ?? ''}`} />
}

function toMonthly(amount: number, cycle: string) {
  if (cycle === 'weekly') return amount * 4.33
  if (cycle === 'yearly') return amount / 12
  return amount
}

async function token() {
  const { data: { session } } = await createClient().auth.getSession()
  return session?.access_token ?? null
}

export default function ReviewPage() {
  const [items, setItems] = useState<DetectedSubscription[]>([])
  const [gmail, setGmail] = useState<GmailStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState<string | null>(null)
  const [shares, setShares] = useState<Record<string, number>>({})
  const [custom, setCustom] = useState<Record<string, string>>({})

  async function load() {
    const t = await token()
    if (!t) return
    const [detected, status] = await Promise.all([getDetected(t), getGmailStatus(t)])
    setItems(detected)
    setGmail(status)
    return status as GmailStatus
  }

  useEffect(() => {
    load().finally(() => setLoading(false))
  }, [])

  // Per-detection share of the bill. A receipt shows the whole cost, but the
  // user may only pay part of it (rent split with housemates, a shared energy
  // bill), so the split is chosen at review time.
  const SPLIT_OPTIONS = [
    { label: 'All', ratio: 1 },
    { label: '½', ratio: 1 / 2 },
    { label: '⅓', ratio: 1 / 3 },
    { label: '¼', ratio: 1 / 4 },
  ]

  function setShare(id: string, ratio: number) {
    setShares(prev => ({ ...prev, [id]: ratio }))
    setCustom(prev => ({ ...prev, [id]: '' }))
  }

  function setCustomShare(id: string, value: string, billed: number) {
    setCustom(prev => ({ ...prev, [id]: value }))
    const mine = parseFloat(value)
    setShares(prev => ({
      ...prev,
      [id]: Number.isFinite(mine) && mine > 0 && mine <= billed ? mine / billed : 1,
    }))
  }

  // While a scan runs there's nothing to show until it finishes, so poll for it.
  useEffect(() => {
    if (gmail?.scan_status !== 'running') return
    const timer = setInterval(() => { load() }, 4000)
    return () => clearInterval(timer)
  }, [gmail?.scan_status])

  async function resolve(id: string, action: 'approve' | 'dismiss') {
    const t = await token()
    if (!t) return
    setBusy(id)
    try {
      if (action === 'approve') {
        // Only send a ratio when the bill is actually shared — omitting it
        // stores the full amount, which is the common case.
        const ratio = shares[id]
        await approveDetected(t, id, ratio && ratio < 1 ? { share_ratio: ratio } : {})
      } else await dismissDetected(t, id)
      // Drop it locally rather than refetching — the row is gone either way.
      setItems(prev => prev.filter(i => i.id !== id))
    } finally {
      setBusy(null)
    }
  }

  async function rescan() {
    const t = await token()
    if (!t) return
    await startGmailScan(t)
    setGmail(g => (g ? { ...g, scan_status: 'running' } : g))
  }

  if (loading) {
    return (
      <div className="mx-auto max-w-4xl px-4 py-6 sm:px-6 lg:px-8">
        <div className="space-y-6">
          <Skeleton className="h-9 w-56" />
          <Skeleton className="h-24 rounded-2xl" />
          <Skeleton className="h-40 rounded-2xl" />
        </div>
      </div>
    )
  }

  const scanning = gmail?.scan_status === 'running'

  return (
    <div className="mx-auto max-w-4xl px-4 py-6 sm:px-6 lg:px-8">
      <div className="space-y-6">
        <section className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
          <div className="space-y-2">
            <p className="text-sm font-medium text-primary">From your inbox</p>
            <h1 className="text-3xl font-semibold tracking-tight text-foreground">
              Review detections
            </h1>
            <p className="max-w-2xl text-sm text-muted-foreground">
              Found in your email receipts. Nothing is added to your subscriptions
              until you approve it.
            </p>
          </div>

          {gmail?.connected && (
            <Button variant="outline" onClick={rescan} disabled={scanning} className="shrink-0">
              {scanning ? 'Scanning…' : 'Rescan inbox'}
            </Button>
          )}
        </section>

        {!gmail?.connected ? (
          <div className="rounded-2xl bg-card p-6 shadow-md">
            <div className="flex items-start gap-3">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                <Mail className="h-5 w-5" />
              </div>
              <div>
                <p className="font-medium text-foreground">No inbox connected</p>
                <p className="mt-1 text-sm text-muted-foreground">
                  Connect Gmail and Subtrack will find your subscriptions from receipt
                  emails instead of you entering them by hand.
                </p>
                <Link
                  href="/account"
                  className="mt-3 inline-block text-sm text-primary underline underline-offset-4"
                >
                  Connect Gmail on the account page
                </Link>
              </div>
            </div>
          </div>
        ) : gmail.scan_error ? (
          <div className="rounded-2xl border border-destructive/20 bg-destructive/5 p-6">
            <p className="text-sm font-medium text-destructive">Last scan failed</p>
            <p className="mt-1 text-sm text-muted-foreground">{gmail.scan_error}</p>
          </div>
        ) : null}

        {scanning && (
          <div className="rounded-2xl bg-card p-6 shadow-md">
            <p className="text-sm font-medium text-foreground">Reading your inbox…</p>
            <p className="mt-1 text-sm text-muted-foreground">
              This takes a minute or two. Results appear here as they&apos;re found.
            </p>
          </div>
        )}

        {items.length === 0 && !scanning && gmail?.connected ? (
          <div className="flex min-h-[200px] items-center justify-center rounded-2xl border border-dashed border-border bg-muted/30">
            <div className="text-center">
              <p className="text-sm font-medium text-foreground">Nothing to review</p>
              <p className="mt-1 text-sm text-muted-foreground">
                {gmail.last_scanned_at
                  ? 'Everything found has been approved or dismissed.'
                  : 'Run a scan to look for subscriptions in your email.'}
              </p>
            </div>
          </div>
        ) : (
          <div className="space-y-3">
            {items.map(item => {
              const ratio = shares[item.id] ?? 1
              const myAmount = Math.round(item.amount * ratio * 100) / 100
              const isShared = ratio < 1
              const monthly = toMonthly(myAmount, item.cycle)
              const isPriceChange = item.existing_subscription_id !== null
              const rose =
                item.previous_amount !== null && item.amount > item.previous_amount

              return (
                <div
                  key={item.id}
                  className="rounded-2xl bg-card p-5 shadow-md"
                >
                  <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
                    <div className="min-w-0 space-y-2">
                      <div className="flex flex-wrap items-center gap-2">
                        <p className="font-semibold text-foreground">{item.merchant}</p>

                        {isPriceChange && (
                          <span className="rounded-full border border-amber-500/20 bg-amber-500/10 px-2 py-0.5 text-[11px] font-medium text-amber-600 dark:text-amber-400">
                            Price change
                          </span>
                        )}
                        {item.cancelled && (
                          <span className="rounded-full border border-border bg-muted px-2 py-0.5 text-[11px] font-medium text-muted-foreground">
                            Cancelled
                          </span>
                        )}
                        {item.confidence === 'medium' && (
                          <span className="rounded-full border border-border bg-muted px-2 py-0.5 text-[11px] font-medium text-muted-foreground">
                            Less certain
                          </span>
                        )}
                      </div>

                      <p className="text-sm text-muted-foreground">
                        {isShared ? (
                          <>
                            <span className="line-through opacity-60">
                              {formatCurrency(item.amount, item.currency)}
                            </span>{' '}
                            <span className="font-medium text-foreground">
                              {formatCurrency(myAmount, item.currency)}
                            </span>
                          </>
                        ) : (
                          formatCurrency(item.amount, item.currency)
                        )}
                        {' / '}
                        {item.cycle}
                        {item.cycle !== 'monthly' && (
                          <> · {formatCurrency(monthly, item.currency)}/mo</>
                        )}
                        {' · '}
                        {formatCurrency(monthly * 12, item.currency)}/yr
                      </p>

                      {/* The evidence. You're being asked to trust a guess, so
                          show what it's based on. */}
                      <p className="text-xs text-muted-foreground">
                        {item.charge_count > 0
                          ? `${item.charge_count} charge${item.charge_count === 1 ? '' : 's'} found`
                          : 'No charges found — detected from cancellation notice'}
                        {' · '}
                        <span className="capitalize">{item.category}</span>
                        {' · via '}
                        {item.sender_domain}
                      </p>

                      {item.previous_amount !== null && (
                        <p className="flex items-center gap-1 text-xs font-medium text-amber-600 dark:text-amber-400">
                          {rose && <ArrowUpRight className="h-3 w-3" />}
                          {formatCurrency(item.previous_amount, item.currency)} →{' '}
                          {formatCurrency(item.amount, item.currency)}
                          {isPriceChange && ' — updates your existing subscription'}
                        </p>
                      )}

                      {/* Receipts show the whole bill. Shared costs — rent,
                          household utilities — need only the user's portion. */}
                      <div className="flex flex-wrap items-center gap-1.5 pt-1">
                        <span className="mr-1 text-xs text-muted-foreground">
                          I pay
                        </span>
                        {SPLIT_OPTIONS.map(option => {
                          const active =
                            Math.abs(ratio - option.ratio) < 0.001 && !custom[item.id]
                          return (
                            <button
                              key={option.label}
                              type="button"
                              onClick={() => setShare(item.id, option.ratio)}
                              className={`rounded-md border px-2 py-1 text-xs font-medium transition-colors ${
                                active
                                  ? 'border-primary bg-primary/10 text-primary'
                                  : 'border-border text-muted-foreground hover:bg-muted hover:text-foreground'
                              }`}
                            >
                              {option.label}
                            </button>
                          )
                        })}
                        <div className="flex items-center gap-1">
                          <span className="text-xs text-muted-foreground">or</span>
                          <input
                            type="number"
                            min="0"
                            max={item.amount}
                            step="0.01"
                            inputMode="decimal"
                            placeholder="exact"
                            value={custom[item.id] ?? ''}
                            onChange={e =>
                              setCustomShare(item.id, e.target.value, item.amount)
                            }
                            className="w-20 rounded-md border border-border bg-background px-2 py-1 text-xs text-foreground focus:outline-none focus:ring-2 focus:ring-primary/40"
                          />
                        </div>
                        {isShared && (
                          <span className="text-xs text-muted-foreground">
                            of {formatCurrency(item.amount, item.currency)}
                          </span>
                        )}
                      </div>
                    </div>

                    <div className="flex shrink-0 gap-2">
                      <Button
                        size="sm"
                        onClick={() => resolve(item.id, 'approve')}
                        disabled={busy === item.id}
                      >
                        <Check className="mr-1 h-3.5 w-3.5" />
                        {isPriceChange ? 'Update' : 'Add'}
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => resolve(item.id, 'dismiss')}
                        disabled={busy === item.id}
                        className="text-muted-foreground hover:text-foreground"
                      >
                        <X className="mr-1 h-3.5 w-3.5" />
                        Dismiss
                      </Button>
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        )}

        {items.length > 0 && (
          <p className="text-xs text-muted-foreground">
            Dismissed items won&apos;t be suggested again on future scans.
          </p>
        )}
      </div>
    </div>
  )
}
