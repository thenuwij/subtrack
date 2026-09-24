'use client'

import { type FormEvent, useEffect, useState } from 'react'
import type {
  AmountType,
  ApiCapabilities,
  Category,
  Currency,
  PaymentStatus,
  RecurrenceUnit,
  SpendingType,
  Subscription,
  SubscriptionInput,
} from '@/types'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { useCurrency } from '@/lib/context/currency'
import { getCapabilities, getSubscriptionEquivalents } from '@/lib/api'
import { formatCurrency } from '@/lib/utils/currency'
import { CATEGORIES, formatCategory } from '@/lib/utils/categories'
import {
  CADENCE_PRESETS,
  cadenceFor,
  exactLegacyCycle,
  formatCadence,
} from '@/lib/utils/recurrence'
import {
  addUtcDays,
  dateAtNoonUtc,
  storedDateKey,
  todayUtcDateKey,
} from '@/lib/utils/dates'
import { getAccessToken } from '@/lib/auth/session'

const CURRENCIES: Currency[] = ['AUD', 'USD', 'GBP', 'SGD', 'EUR', 'JPY']
const RECURRENCE_UNITS: RecurrenceUnit[] = ['day', 'week', 'month', 'year']

function presetKey(unit: RecurrenceUnit, count: number) {
  return CADENCE_PRESETS.find(
    preset => preset.interval_unit === unit && preset.interval_count === count,
  )?.key ?? 'custom'
}

interface FormState {
  name: string
  category: Category
  amount: string
  currency: Currency
  interval_unit: RecurrenceUnit
  interval_count: string
  cadence_preset: string
  next_due: string
  recurrence_end_at: string
  is_trial: boolean
  trial_ends_at: string
  status: PaymentStatus
  paused_until: string
  cancellation_effective_at: string
  amount_type: AmountType
  spending_type: SpendingType
  share_ratio: number
  share_amount: string
}

interface Props {
  open: boolean
  onClose: () => void
  onSubmit: (data: SubscriptionInput) => Promise<void>
  initialData?: Subscription
}

function createInitialForm(baseCurrency: Currency, initialData?: Subscription): FormState {
  if (!initialData) {
    return {
      name: '',
      category: 'other',
      amount: '',
      currency: baseCurrency,
      interval_unit: 'month',
      interval_count: '1',
      cadence_preset: 'monthly',
      next_due: '',
      recurrence_end_at: '',
      is_trial: false,
      trial_ends_at: '',
      status: 'active',
      paused_until: '',
      cancellation_effective_at: '',
      amount_type: 'fixed',
      spending_type: 'unspecified',
      share_ratio: 1,
      share_amount: '',
    }
  }

  const cadence = cadenceFor(initialData)
  return {
    name: initialData.name,
    category: initialData.category,
    amount: (initialData.full_amount ?? initialData.amount).toString(),
    currency: initialData.currency as Currency,
    interval_unit: cadence.interval_unit,
    interval_count: cadence.interval_count.toString(),
    cadence_preset: presetKey(cadence.interval_unit, cadence.interval_count),
    next_due: storedDateKey(initialData.next_due),
    recurrence_end_at: storedDateKey(initialData.recurrence_end_at),
    is_trial: Boolean(
      initialData.trial_ends_at
        && storedDateKey(initialData.trial_ends_at) >= todayUtcDateKey(),
    ),
    trial_ends_at: storedDateKey(initialData.trial_ends_at),
    status: initialData.status,
    paused_until: storedDateKey(initialData.paused_until),
    cancellation_effective_at: storedDateKey(initialData.cancellation_effective_at),
    amount_type: initialData.amount_type,
    spending_type: initialData.spending_type,
    share_ratio: initialData.split_mode === 'ratio' ? initialData.share_ratio : 1,
    share_amount: initialData.split_mode === 'fixed' ? initialData.amount.toString() : '',
  }
}

/**
 * Keep the form mounted only while the dialog is open. Each opening gets a
 * fresh draft without an effect that can erase input when preferences load.
 */
export function AddSubscriptionModal(props: Props) {
  if (!props.open) return null
  return <OpenSubscriptionModal {...props} />
}

function OpenSubscriptionModal({ onClose, onSubmit, initialData }: Props) {
  const { baseCurrency, rates, ratesLoading: sharedRatesLoading } = useCurrency()
  const isEditing = Boolean(initialData)
  const [form, setForm] = useState<FormState>(() => createInitialForm(baseCurrency, initialData))
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [trialTouched, setTrialTouched] = useState(false)
  const [capabilities, setCapabilities] = useState<ApiCapabilities | null>(null)
  const [capabilityState, setCapabilityState] = useState<'loading' | 'ready' | 'legacy'>('loading')
  const [equivalence, setEquivalence] = useState<{
    key: string
    monthly: number | null
    yearly: number | null
    failed: boolean
  } | null>(null)

  useEffect(() => {
    let cancelled = false
    async function loadCapabilities() {
      try {
        const accessToken = await getAccessToken()
        if (!accessToken) throw new Error('Your session has expired.')
        const next = await getCapabilities(accessToken)
        if (!cancelled) {
          setCapabilities(next)
          setCapabilityState('ready')
        }
      } catch {
        if (!cancelled) setCapabilityState('legacy')
      }
    }
    void loadCapabilities()
    return () => { cancelled = true }
  }, [])

  const supportsFlexibleCadence = capabilityState === 'ready'
    && Boolean(capabilities?.flexible_recurrence)
  const supportsLifecycle = capabilityState === 'ready'
    && Boolean(capabilities?.payment_lifecycle)
  const supportsVariableAmounts = capabilityState === 'ready'
    && Boolean(capabilities?.variable_amounts)
  const originalCadence = initialData ? cadenceFor(initialData) : null
  const originalIsCustom = Boolean(originalCadence
    && !exactLegacyCycle(originalCadence.interval_unit, originalCadence.interval_count))
  const quotedRate = Number(rates[form.currency])
  const hasReliableRate = form.currency === baseCurrency
    || (Number.isFinite(quotedRate) && quotedRate > 0)
  const exchangeRate = form.currency === baseCurrency
    ? 1 : hasReliableRate ? Number((1 / quotedRate).toFixed(6)) : 1
  const rateLoading = form.currency !== baseCurrency && sharedRatesLoading
  const rateError = form.currency !== baseCurrency && !rateLoading && !hasReliableRate
    ? 'Could not fetch a reliable exchange rate.' : null

  const amount = Number(form.amount)
  const intervalCount = Number(form.interval_count)
  const fixedShare = Number(form.share_amount)
  const hasExactShareInput = form.share_amount.trim().length > 0
  const exactShareIsValid = Number.isFinite(fixedShare)
    && fixedShare > 0 && Number.isFinite(amount) && fixedShare <= amount
  const hasFixed = Number.isFinite(fixedShare) && fixedShare > 0 && fixedShare < amount
  const isShared = hasFixed || form.share_ratio < 1
  const myAmount = hasFixed
    ? fixedShare
    : Number.isFinite(amount)
      ? Number((amount * form.share_ratio).toFixed(2))
      : amount
  const convertedAmount = Number.isFinite(myAmount) && myAmount > 0
    ? Number((myAmount * exchangeRate).toFixed(2))
    : null
  const equivalenceKey = `${myAmount}:${form.interval_unit}:${intervalCount}`

  useEffect(() => {
    if (!supportsFlexibleCadence || !Number.isFinite(myAmount) || myAmount <= 0
        || !Number.isInteger(intervalCount) || intervalCount < 1 || intervalCount > 1200) {
      return
    }
    let cancelled = false
    const timer = window.setTimeout(async () => {
      try {
        const accessToken = await getAccessToken()
        if (!accessToken) throw new Error('Your session has expired.')
        const preview = await getSubscriptionEquivalents(accessToken, {
          amount: myAmount,
          interval_unit: form.interval_unit,
          interval_count: intervalCount,
        })
        if (!cancelled) {
          setEquivalence({
            key: equivalenceKey,
            monthly: preview.monthly_equivalent,
            yearly: preview.yearly_equivalent,
            failed: false,
          })
        }
      } catch {
        if (!cancelled) {
          setEquivalence({ key: equivalenceKey, monthly: null, yearly: null, failed: true })
        }
      }
    }, 250)
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [equivalenceKey, form.interval_unit, intervalCount, myAmount, supportsFlexibleCadence])

  function set<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm(previous => ({ ...previous, [key]: value }))
    setError(null)
  }

  function selectPreset(key: string) {
    if (key === 'custom') {
      setForm(previous => ({ ...previous, cadence_preset: key }))
      return
    }
    const preset = CADENCE_PRESETS.find(option => option.key === key)
    if (!preset) return
    setForm(previous => ({
      ...previous,
      cadence_preset: key,
      interval_unit: preset.interval_unit,
      interval_count: preset.interval_count.toString(),
    }))
    setError(null)
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!form.name.trim()) return setError('Name is required.')
    if (!Number.isFinite(amount) || amount <= 0) {
      return setError('Enter a valid amount greater than 0.')
    }
    if (hasExactShareInput && !exactShareIsValid) {
      return setError('Your exact share must be greater than 0 and no more than the full bill.')
    }
    if (!Number.isInteger(intervalCount) || intervalCount < 1 || intervalCount > 1200) {
      return setError('Billing interval must be a whole number from 1 to 1,200.')
    }
    if (form.is_trial && !form.trial_ends_at) {
      return setError('Add the date this free trial ends.')
    }
    if (supportsLifecycle && form.status === 'cancelling'
        && !form.cancellation_effective_at) {
      return setError('Add the date access ends for this cancelling payment.')
    }
    if (supportsLifecycle && form.status === 'paused' && form.paused_until
        && form.paused_until <= todayUtcDateKey()) {
      return setError('The resume date must be in the future.')
    }
    const effectiveNextDue = form.is_trial ? form.trial_ends_at : form.next_due
    if (form.recurrence_end_at && effectiveNextDue && form.recurrence_end_at < effectiveNextDue) {
      return setError('The final recurrence date cannot be before the next payment date.')
    }
    if (capabilityState === 'loading') return setError('Checking server compatibility. Please wait.')

    const legacyCycle = exactLegacyCycle(form.interval_unit, intervalCount)
    if (!supportsFlexibleCadence && !legacyCycle && !originalIsCustom) {
      return setError('This server does not yet support custom billing intervals.')
    }

    const payload: SubscriptionInput = {
      name: form.name.trim(),
      category: form.category,
      amount: myAmount,
      full_amount: isShared ? amount : null,
      share_ratio: hasFixed ? undefined : form.share_ratio,
      share_amount: hasFixed ? fixedShare : undefined,
      currency: form.currency,
      next_due: effectiveNextDue ? dateAtNoonUtc(effectiveNextDue) : null,
    }

    if (form.currency === baseCurrency) {
      payload.exchange_rate = 1
      payload.converted_amount = myAmount
    } else if (!rateLoading && !rateError && convertedAmount !== null) {
      payload.exchange_rate = exchangeRate
      payload.converted_amount = convertedAmount
    } else {
      // Never invent a 1:1 conversion. The backend persists the native amount
      // and can attach its shared rate snapshot; until then totals explicitly
      // exclude this payment instead of overstating accuracy.
      payload.converted_amount = null
    }

    if (!initialData || trialTouched) {
      payload.trial_ends_at = form.is_trial ? dateAtNoonUtc(form.trial_ends_at) : null
    }

    if (supportsLifecycle) {
      payload.is_active = form.status !== 'cancelled' && form.status !== 'ended'
    } else if (!initialData) {
      // Never send a compatibility is_active flag while editing if lifecycle
      // capability discovery failed: a new backend would interpret it as a
      // request to overwrite an existing paused/cancelling state.
      payload.is_active = true
    }

    if (supportsFlexibleCadence) {
      payload.interval_unit = form.interval_unit
      payload.interval_count = intervalCount
    } else if (legacyCycle) {
      payload.cycle = legacyCycle
    }

    if (supportsLifecycle) {
      payload.status = form.status
      payload.recurrence_end_at = form.recurrence_end_at
        ? dateAtNoonUtc(form.recurrence_end_at) : null
      payload.paused_until = form.status === 'paused' && form.paused_until
        ? dateAtNoonUtc(form.paused_until) : null
      payload.cancellation_effective_at = form.status === 'cancelling'
        && form.cancellation_effective_at
        ? dateAtNoonUtc(form.cancellation_effective_at) : null
    }

    if (supportsVariableAmounts) {
      payload.amount_type = form.amount_type
      payload.spending_type = form.spending_type
    }

    setLoading(true)
    setError(null)
    try {
      await onSubmit(payload)
      onClose()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Something went wrong.')
    } finally {
      setLoading(false)
    }
  }

  function handleClose() {
    if (!loading) onClose()
  }

  const cadenceText = formatCadence(form.interval_unit, Number.isFinite(intervalCount) ? intervalCount : 1)
  const currentEquivalence = equivalence?.key === equivalenceKey ? equivalence : null

  return (
    <Dialog open onOpenChange={nextOpen => { if (!nextOpen) handleClose() }}>
      <DialogContent className="max-h-[calc(100dvh-2rem)] overflow-y-auto sm:max-w-xl">
        <form onSubmit={handleSubmit} noValidate>
          <DialogHeader>
            <DialogTitle>{isEditing ? 'Edit recurring payment' : 'Add recurring payment'}</DialogTitle>
          </DialogHeader>

          <div className="grid gap-5 py-4">
            <div className="grid gap-1.5">
              <Label htmlFor="sub-name">Name</Label>
              <Input
                id="sub-name"
                autoFocus
                autoComplete="off"
                placeholder="Rent, Netflix, gym membership…"
                value={form.name}
                onChange={event => set('name', event.target.value)}
                disabled={loading}
              />
            </div>

            <div className="grid gap-1.5">
              <Label htmlFor="sub-category">Category</Label>
              <Select value={form.category} onValueChange={value => set('category', value as Category)} disabled={loading}>
                <SelectTrigger id="sub-category"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {CATEGORIES.map(category => (
                    <SelectItem key={category} value={category}>{formatCategory(category)}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="grid gap-1.5">
                <Label htmlFor="sub-amount">
                  {form.is_trial ? 'Price after trial' : isShared ? 'Full bill' : 'Amount'}
                </Label>
                <Input
                  id="sub-amount"
                  inputMode="decimal"
                  type="number"
                  min="0.01"
                  step="0.01"
                  placeholder="0.00"
                  value={form.amount}
                  onChange={event => set('amount', event.target.value)}
                  disabled={loading}
                />
              </div>
              <div className="grid gap-1.5">
                <Label htmlFor="sub-currency">Currency</Label>
                <Select value={form.currency} onValueChange={value => set('currency', value as Currency)} disabled={loading}>
                  <SelectTrigger id="sub-currency"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {CURRENCIES.map(currency => <SelectItem key={currency} value={currency}>{currency}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
            </div>

            {supportsVariableAmounts ? (
              <div className="grid gap-3 rounded-xl border border-border bg-muted/25 p-3 sm:grid-cols-2">
                <div className="grid gap-1.5">
                  <Label htmlFor="sub-amount-type">Amount behaviour</Label>
                  <Select value={form.amount_type} onValueChange={value => set('amount_type', value as AmountType)} disabled={loading}>
                    <SelectTrigger id="sub-amount-type"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="fixed">Usually fixed</SelectItem>
                      <SelectItem value="variable">Varies each bill</SelectItem>
                    </SelectContent>
                  </Select>
                  <p className="text-xs leading-5 text-muted-foreground">
                    Variable amounts are treated as estimates in totals.
                  </p>
                </div>
                <div className="grid gap-1.5">
                  <Label htmlFor="sub-spending-type">Spending type</Label>
                  <Select value={form.spending_type} onValueChange={value => set('spending_type', value as SpendingType)} disabled={loading}>
                    <SelectTrigger id="sub-spending-type"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="unspecified">Not specified</SelectItem>
                      <SelectItem value="essential">Essential</SelectItem>
                      <SelectItem value="optional">Optional</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div>
            ) : null}

            <div className="grid gap-1.5">
              <Label>Split</Label>
              <div className="flex flex-wrap items-center gap-1.5">
                {[
                  { label: 'I pay all', ratio: 1 },
                  { label: '½', ratio: 1 / 2 },
                  { label: '⅓', ratio: 1 / 3 },
                  { label: '¼', ratio: 1 / 4 },
                ].map(option => (
                  <button
                    key={option.label}
                    type="button"
                    disabled={loading}
                    aria-pressed={Math.abs(form.share_ratio - option.ratio) < 0.001 && !hasFixed}
                    onClick={() => setForm(previous => ({
                      ...previous,
                      share_ratio: option.ratio,
                      share_amount: '',
                    }))}
                    className={`rounded-md border px-2.5 py-1.5 text-xs font-medium transition-colors disabled:opacity-50 ${
                      Math.abs(form.share_ratio - option.ratio) < 0.001 && !hasFixed
                        ? 'border-primary bg-primary/10 text-primary'
                        : 'border-border text-muted-foreground hover:bg-muted hover:text-foreground'
                    }`}
                  >
                    {option.label}
                  </button>
                ))}
                <div className="flex items-center gap-1">
                  <Label htmlFor="sub-fixed-share" className="text-xs font-normal text-muted-foreground">or exactly</Label>
                  <Input
                    id="sub-fixed-share"
                    aria-label="Exact amount you pay"
                    type="number"
                    min="0.01"
                    step="0.01"
                    placeholder="320"
                    value={form.share_amount}
                    onChange={event => set('share_amount', event.target.value)}
                    aria-invalid={hasExactShareInput && !exactShareIsValid}
                    disabled={loading}
                    className="h-8 w-24 text-xs"
                  />
                </div>
              </div>
              {isShared && Number.isFinite(amount) && amount > 0 ? (
                <p className="text-xs leading-5 text-muted-foreground">
                  You pay <span className="font-medium text-foreground">{formatCurrency(myAmount, form.currency)}</span>{' '}
                  of {formatCurrency(amount, form.currency)} · {cadenceText.toLowerCase()}
                  {hasFixed ? ' · stays fixed if the bill changes' : ' · scales if the bill changes'}
                </p>
              ) : null}
            </div>

            {form.currency !== baseCurrency ? (
              <div className="rounded-md bg-muted px-3 py-2 text-xs text-muted-foreground" aria-live="polite">
                {rateLoading ? 'Fetching exchange rate…' : null}
                {rateError ? (
                  <span className="text-amber-700 dark:text-amber-300">
                    {rateError} You can still save this in {form.currency}; base-currency totals will exclude it until a rate is available.
                  </span>
                ) : null}
                {!rateLoading && !rateError ? (
                  <span>
                    1 {form.currency} = {exchangeRate.toFixed(4)} {baseCurrency}
                    {convertedAmount !== null ? (
                      <span className="ml-2 font-medium text-foreground">≈ {formatCurrency(convertedAmount, baseCurrency)}</span>
                    ) : null}
                  </span>
                ) : null}
              </div>
            ) : null}

            <div className="grid gap-1.5">
              <Label htmlFor="sub-cadence">Billing frequency</Label>
              {capabilityState === 'loading' ? (
                <div className="h-9 animate-pulse rounded-md bg-muted" aria-label="Checking available billing frequencies" />
              ) : supportsFlexibleCadence ? (
                <>
                  <Select value={form.cadence_preset} onValueChange={selectPreset} disabled={loading}>
                    <SelectTrigger id="sub-cadence"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {CADENCE_PRESETS.map(preset => (
                        <SelectItem key={preset.key} value={preset.key}>{preset.label}</SelectItem>
                      ))}
                      <SelectItem value="custom">Custom interval…</SelectItem>
                    </SelectContent>
                  </Select>
                  {form.cadence_preset === 'custom' ? (
                    <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)] gap-2 pt-1">
                      <div>
                        <Label htmlFor="sub-interval-count" className="sr-only">Interval count</Label>
                        <Input
                          id="sub-interval-count"
                          type="number"
                          min="1"
                          max="1200"
                          step="1"
                          value={form.interval_count}
                          onChange={event => set('interval_count', event.target.value)}
                          disabled={loading}
                        />
                      </div>
                      <Select value={form.interval_unit} onValueChange={value => set('interval_unit', value as RecurrenceUnit)} disabled={loading}>
                        <SelectTrigger aria-label="Interval unit"><SelectValue /></SelectTrigger>
                        <SelectContent>
                          {RECURRENCE_UNITS.map(unit => (
                            <SelectItem key={unit} value={unit}>{unit[0].toUpperCase() + unit.slice(1)}s</SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                  ) : null}
                </>
              ) : originalIsCustom ? (
                <div className="rounded-lg border border-amber-500/25 bg-amber-500/5 p-3">
                  <p className="text-sm font-medium text-foreground">{cadenceText}</p>
                  <p className="mt-1 text-xs leading-5 text-muted-foreground">
                    Billing frequency is preserved, but cannot be changed until server compatibility is available.
                  </p>
                </div>
              ) : (
                <Select
                  value={exactLegacyCycle(form.interval_unit, intervalCount) ?? 'monthly'}
                  onValueChange={value => {
                    const preset = CADENCE_PRESETS.find(option => option.key === value)
                    if (preset) selectPreset(preset.key)
                  }}
                  disabled={loading}
                >
                  <SelectTrigger id="sub-cadence"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="weekly">Weekly</SelectItem>
                    <SelectItem value="monthly">Monthly</SelectItem>
                    <SelectItem value="yearly">Yearly</SelectItem>
                  </SelectContent>
                </Select>
              )}
              {capabilityState === 'legacy' && !originalIsCustom ? (
                <p className="text-xs leading-5 text-muted-foreground">
                  More billing frequencies will appear after the API deployment is up to date.
                </p>
              ) : null}
              {currentEquivalence && !currentEquivalence.failed
                  && currentEquivalence.monthly !== null
                  && currentEquivalence.yearly !== null ? (
                <p className="text-xs tabular-nums text-muted-foreground">
                  {formatCurrency(currentEquivalence.monthly, form.currency)}/mo ·{' '}
                  {formatCurrency(currentEquivalence.yearly, form.currency)}/yr equivalent
                </p>
              ) : currentEquivalence?.failed ? (
                <p className="text-xs text-muted-foreground">Could not calculate the preview. Equivalents will be calculated when you save.</p>
              ) : supportsFlexibleCadence ? (
                <p className="text-xs text-muted-foreground" aria-live="polite">Calculating monthly and annual equivalents…</p>
              ) : null}
            </div>

            <label className="flex cursor-pointer items-start gap-3 rounded-xl border border-border bg-muted/30 p-3">
              <input
                type="checkbox"
                checked={form.is_trial}
                onChange={event => {
                  setTrialTouched(true)
                  setForm(previous => ({
                    ...previous,
                    is_trial: event.target.checked,
                    trial_ends_at: event.target.checked
                      && previous.trial_ends_at >= todayUtcDateKey()
                      ? previous.trial_ends_at : '',
                  }))
                  setError(null)
                }}
                disabled={loading}
                className="mt-0.5 h-4 w-4 accent-primary"
              />
              <span>
                <span className="block text-sm font-medium text-foreground">This is a free trial</span>
                <span className="mt-0.5 block text-xs leading-5 text-muted-foreground">
                  The amount above is the price after the trial. Subtrack creates a dashboard reminder seven days before it ends.
                </span>
              </span>
            </label>

            {form.is_trial ? (
              <div className="grid gap-1.5">
                <Label htmlFor="sub-trial-end">Trial end date</Label>
                <Input
                  id="sub-trial-end"
                  type="date"
                  min={todayUtcDateKey()}
                  value={form.trial_ends_at}
                  onChange={event => {
                    setTrialTouched(true)
                    set('trial_ends_at', event.target.value)
                  }}
                  disabled={loading}
                />
                <p className="text-xs text-muted-foreground">Also saved as the first expected charge date.</p>
              </div>
            ) : (
              <div className="grid gap-1.5">
                <Label htmlFor="sub-due">Next expected payment <span className="font-normal text-muted-foreground">(optional)</span></Label>
                <Input id="sub-due" type="date" value={form.next_due} onChange={event => set('next_due', event.target.value)} disabled={loading} />
              </div>
            )}

            {supportsLifecycle ? (
              <div className="grid gap-4 rounded-xl border border-border p-3">
                <div className="grid gap-1.5">
                  <Label htmlFor="sub-status">Payment status</Label>
                  <Select value={form.status} onValueChange={value => set('status', value as PaymentStatus)} disabled={loading}>
                    <SelectTrigger id="sub-status"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="active">Active</SelectItem>
                      <SelectItem value="paused">Paused</SelectItem>
                      <SelectItem value="cancelling">Cancelling</SelectItem>
                      <SelectItem value="cancelled">Cancelled</SelectItem>
                      <SelectItem value="ended">Ended</SelectItem>
                    </SelectContent>
                  </Select>
                  <p className="text-xs leading-5 text-muted-foreground">
                    Paused and finished payments stay in history without inflating current totals.
                  </p>
                </div>

                {form.status === 'paused' ? (
                  <div className="grid gap-1.5">
                    <Label htmlFor="sub-paused-until">Resume date <span className="font-normal text-muted-foreground">(optional)</span></Label>
                    <Input id="sub-paused-until" type="date" min={addUtcDays(todayUtcDateKey(), 1)} value={form.paused_until} onChange={event => set('paused_until', event.target.value)} disabled={loading} />
                  </div>
                ) : null}

                {form.status === 'cancelling' ? (
                  <div className="grid gap-1.5">
                    <Label htmlFor="sub-cancels-on">Access ends</Label>
                    <Input id="sub-cancels-on" type="date" min={todayUtcDateKey()} required value={form.cancellation_effective_at} onChange={event => set('cancellation_effective_at', event.target.value)} disabled={loading} />
                  </div>
                ) : null}

                <div className="grid gap-1.5">
                  <Label htmlFor="sub-recurs-until">Stop recurring after <span className="font-normal text-muted-foreground">(optional)</span></Label>
                  <Input id="sub-recurs-until" type="date" value={form.recurrence_end_at} onChange={event => set('recurrence_end_at', event.target.value)} disabled={loading} />
                  <p className="text-xs leading-5 text-muted-foreground">Useful for instalments or contracts with a known final date.</p>
                </div>
              </div>
            ) : initialData && initialData.status !== 'active' ? (
              <p className="rounded-lg border border-border bg-muted/30 p-3 text-xs text-muted-foreground">
                Status is preserved as <span className="font-medium text-foreground">{initialData.status}</span> while compatibility information is unavailable.
              </p>
            ) : null}

            {error ? <p role="alert" className="text-sm text-destructive">{error}</p> : null}
          </div>

          <DialogFooter className="gap-2">
            <Button type="button" variant="outline" onClick={handleClose} disabled={loading}>Cancel</Button>
            <Button type="submit" disabled={loading || capabilityState === 'loading'}>
              {loading ? (isEditing ? 'Saving…' : 'Adding…') : (isEditing ? 'Save changes' : 'Add payment')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
