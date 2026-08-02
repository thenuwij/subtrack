'use client'

import { useState, useEffect } from 'react'
import { BillingCycle, Category, Currency, Subscription } from '@/types'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { useCurrency } from '@/lib/context/currency'
import { getRates } from '@/lib/api'
import { createClient } from '@/lib/supabase/client'
import { formatCurrency } from '@/lib/utils/currency'

const today = new Date().toISOString().split('T')[0]

const CATEGORIES: Category[] = ['streaming', 'software', 'cloud', 'utilities', 'fitness', 'food', 'transport', 'other']
const CYCLES: BillingCycle[] = ['weekly', 'monthly', 'yearly']
const CURRENCIES: Currency[] = ['AUD', 'USD', 'GBP', 'SGD', 'EUR', 'JPY']

interface FormState {
  name: string
  category: Category
  amount: string
  currency: Currency
  cycle: BillingCycle
  next_due: string
  is_active: boolean
}

interface Props {
  open: boolean
  onClose: () => void
  onSubmit: (data: Omit<Subscription, 'id' | 'user_id' | 'created_at'>) => Promise<void>
  initialData?: Subscription  // when provided = edit mode
}

export function AddSubscriptionModal({ open, onClose, onSubmit, initialData }: Props) {
  const { baseCurrency } = useCurrency()
  const isEditing = !!initialData  // true if editing, false if adding

  const DEFAULT_FORM: FormState = {
    name: '',
    category: 'other',
    amount: '',
    currency: baseCurrency,
    cycle: 'monthly',
    next_due: today,
    is_active: true,
  }

  // When initialData changes (modal opens for edit), pre-fill the form
  function getInitialForm(): FormState {
    if (!initialData) return DEFAULT_FORM
    return {
      name: initialData.name,
      category: initialData.category,
      amount: initialData.amount.toString(),
      currency: initialData.currency as Currency,
      cycle: initialData.cycle,
      next_due: initialData.next_due
        ? new Date(initialData.next_due).toISOString().split('T')[0]
        : '',
      is_active: initialData.is_active,
    }
  }

  const [form, setForm] = useState<FormState>(getInitialForm)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [exchangeRate, setExchangeRate] = useState<number>(initialData?.exchange_rate ?? 1.0)
  const [rateLoading, setRateLoading] = useState(false)
  const [rateError, setRateError] = useState<string | null>(null)

  // Re-fill form when initialData changes — handles opening different items
  useEffect(() => {
    setForm(getInitialForm())
    setExchangeRate(initialData?.exchange_rate ?? 1.0)
    setError(null)
    // Re-init only when the edited item changes. Including getInitialForm would
    // also fire when baseCurrency loads, wiping a form the user is typing in.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialData])

  useEffect(() => {
    if (form.currency === baseCurrency) {
      setExchangeRate(1.0)
      return
    }
    async function fetchRate() {
      setRateLoading(true)
      setRateError(null)
      try {
        const supabase = createClient()
        const { data: { session } } = await supabase.auth.getSession()
        if (!session) return
        const data = await getRates(session.access_token, baseCurrency)
        const rate = data.rates[form.currency]
        if (!rate) { setRateError('Rate unavailable'); return }
        setExchangeRate(parseFloat((1 / rate).toFixed(6)))
      } catch {
        setRateError('Could not fetch exchange rate')
      } finally {
        setRateLoading(false)
      }
    }
    fetchRate()
  }, [form.currency, baseCurrency])

  const amount = parseFloat(form.amount)
  const convertedAmount = !isNaN(amount) && amount > 0
    ? parseFloat((amount * exchangeRate).toFixed(2))
    : null

  function set<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm(prev => ({ ...prev, [key]: value }))
    setError(null)
  }

  async function handleSubmit() {
    if (!form.name.trim()) return setError('Name is required.')
    if (isNaN(amount) || amount <= 0) return setError('Enter a valid amount greater than 0.')
    if (rateLoading) return setError('Waiting for exchange rate, please try again.')
    if (rateError) return setError('Exchange rate unavailable. Cannot submit.')

    setLoading(true)
    setError(null)
    try {
      await onSubmit({
        name: form.name.trim(),
        category: form.category,
        amount,
        currency: form.currency,
        exchange_rate: exchangeRate,
        converted_amount: form.currency === baseCurrency ? amount : convertedAmount,
        cycle: form.cycle,
        next_due: form.next_due ? new Date(form.next_due).toISOString() : new Date(today).toISOString(),
        is_active: form.is_active,
      })
      setForm(DEFAULT_FORM)
      onClose()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Something went wrong.')
    } finally {
      setLoading(false)
    }
  }

  function handleClose() {
    if (loading) return
    setForm(DEFAULT_FORM)
    setError(null)
    onClose()
  }

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          {/* Title changes based on mode */}
          <DialogTitle>{isEditing ? 'Edit subscription' : 'Add subscription'}</DialogTitle>
        </DialogHeader>

        <div className="grid gap-4 py-2">
          <div className="grid gap-1.5">
            <Label htmlFor="sub-name">Name</Label>
            <Input id="sub-name" placeholder="Netflix, GitHub Pro…" value={form.name} onChange={e => set('name', e.target.value)} disabled={loading} />
          </div>

          <div className="grid gap-1.5">
            <Label>Category</Label>
            <Select value={form.category} onValueChange={v => set('category', v as Category)} disabled={loading}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                {CATEGORIES.map(c => <SelectItem key={c} value={c} className="capitalize">{c}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="grid gap-1.5">
              <Label htmlFor="sub-amount">Amount</Label>
              <Input id="sub-amount" type="number" min="0" step="0.01" placeholder="0.00" value={form.amount} onChange={e => set('amount', e.target.value)} disabled={loading} />
            </div>
            <div className="grid gap-1.5">
              <Label>Currency</Label>
              <Select value={form.currency} onValueChange={v => set('currency', v as Currency)} disabled={loading}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  {CURRENCIES.map(c => <SelectItem key={c} value={c}>{c}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
          </div>

          {form.currency !== baseCurrency && (
            <div className="rounded-md bg-muted px-3 py-2 text-xs text-muted-foreground">
              {rateLoading && 'Fetching rate…'}
              {rateError && <span className="text-destructive">{rateError}</span>}
              {!rateLoading && !rateError && (
                <span>
                  1 {form.currency} = {exchangeRate.toFixed(4)} {baseCurrency}
                  {convertedAmount && <span className="ml-2 font-medium text-foreground">≈ {formatCurrency(convertedAmount, baseCurrency)}</span>}
                </span>
              )}
            </div>
          )}

          <div className="grid gap-1.5">
            <Label>Billing cycle</Label>
            <Select value={form.cycle} onValueChange={v => set('cycle', v as BillingCycle)} disabled={loading}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                {CYCLES.map(c => <SelectItem key={c} value={c} className="capitalize">{c}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>

          <div className="grid gap-1.5">
            <Label htmlFor="sub-due">Next renewal date <span className="font-normal text-muted-foreground">(optional)</span></Label>
            <Input id="sub-due" type="date" value={form.next_due} onChange={e => set('next_due', e.target.value)} disabled={loading} />
          </div>

          {error && <p className="text-sm text-destructive">{error}</p>}
        </div>

        <DialogFooter className="gap-2">
          <Button variant="outline" onClick={handleClose} disabled={loading}>Cancel</Button>
          <Button onClick={handleSubmit} disabled={loading || rateLoading}>
            {loading ? (isEditing ? 'Saving…' : 'Adding…') : (isEditing ? 'Save changes' : 'Add subscription')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}