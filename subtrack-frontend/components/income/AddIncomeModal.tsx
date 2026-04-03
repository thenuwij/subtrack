'use client'

import { useState, useEffect } from 'react'
import { Frequency, Currency, Income } from '@/types'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { useCurrency } from '@/lib/context/currency'
import { getRates } from '@/lib/api'
import { createClient } from '@/lib/supabase/client'
import { formatCurrency } from '@/lib/utils/currency'

const FREQUENCIES: Frequency[] = ['weekly', 'fortnightly', 'monthly', 'irregular']
const CURRENCIES: Currency[] = ['AUD', 'USD', 'GBP', 'SGD', 'EUR', 'JPY']
const today = new Date().toISOString().split('T')[0]

interface FormState {
  source: string
  amount: string
  currency: Currency
  frequency: Frequency
  date: string
  note: string
}

interface Props {
  open: boolean
  onClose: () => void
  onSubmit: (data: Omit<Income, 'id' | 'user_id' | 'created_at'>) => Promise<void>
  initialData?: Income
}

export function AddIncomeModal({ open, onClose, onSubmit, initialData }: Props) {
  const { baseCurrency } = useCurrency()
  const isEditing = !!initialData

  function getInitialForm(): FormState {
    if (!initialData) return {
      source: '', amount: '', currency: baseCurrency, frequency: 'monthly', date: today, note: '',
    }
    return {
      source: initialData.source ?? '',
      amount: initialData.amount.toString(),
      currency: initialData.currency as Currency,
      frequency: initialData.frequency,
      date: new Date(initialData.date).toISOString().split('T')[0],
      note: initialData.note ?? '',
    }
  }

  const [form, setForm]         = useState<FormState>(getInitialForm)
  const [loading, setLoading]   = useState(false)
  const [error, setError]       = useState<string | null>(null)
  const [exchangeRate, setExchangeRate]   = useState<number>(1.0)
  const [rateLoading, setRateLoading]     = useState(false)
  const [rateError, setRateError]         = useState<string | null>(null)

  useEffect(() => {
    setForm(getInitialForm())
    setExchangeRate(initialData?.exchange_rate ?? 1.0)
    setError(null)
  }, [initialData])

  useEffect(() => {
    if (form.currency === baseCurrency) { setExchangeRate(1.0); return }
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
    if (isNaN(amount) || amount <= 0) return setError('Enter a valid amount greater than 0.')
    if (!form.date) return setError('Date is required.')
    if (rateLoading) return setError('Waiting for exchange rate, please try again.')
    if (rateError) return setError('Exchange rate unavailable. Cannot submit.')

    setLoading(true)
    setError(null)
    try {
      await onSubmit({
        amount,
        currency: form.currency,
        exchange_rate: exchangeRate,
        converted_amount: form.currency === baseCurrency ? amount : convertedAmount,
        frequency: form.frequency,
        source: form.source.trim() || null,
        date: new Date(form.date).toISOString(),
        note: form.note.trim() || null,
      })
      setForm(getInitialForm)
      onClose()
    } catch (e: any) {
      setError(e?.message ?? 'Something went wrong.')
    } finally {
      setLoading(false)
    }
  }

  function handleClose() {
    if (loading) return
    setForm(getInitialForm)
    setError(null)
    onClose()
  }

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{isEditing ? 'Edit income' : 'Log income'}</DialogTitle>
        </DialogHeader>

        <div className="grid gap-4 py-2">
          <div className="grid gap-1.5">
            <Label htmlFor="inc-source">
              Source <span className="font-normal text-muted-foreground">(optional)</span>
            </Label>
            <Input
              id="inc-source"
              placeholder="Salary, Freelance, Dividends…"
              value={form.source}
              onChange={e => set('source', e.target.value)}
              disabled={loading}
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="grid gap-1.5">
              <Label htmlFor="inc-amount">Amount</Label>
              <Input
                id="inc-amount"
                type="number"
                min="0"
                step="0.01"
                placeholder="0.00"
                value={form.amount}
                onChange={e => set('amount', e.target.value)}
                disabled={loading}
              />
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
            <Label>Frequency</Label>
            <Select value={form.frequency} onValueChange={v => set('frequency', v as Frequency)} disabled={loading}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                {FREQUENCIES.map(f => <SelectItem key={f} value={f} className="capitalize">{f}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>

          <div className="grid gap-1.5">
            <Label htmlFor="inc-date">Date</Label>
            <Input id="inc-date" type="date" value={form.date} onChange={e => set('date', e.target.value)} disabled={loading} />
          </div>

          <div className="grid gap-1.5">
            <Label htmlFor="inc-note">
              Note <span className="font-normal text-muted-foreground">(optional)</span>
            </Label>
            <Input id="inc-note" placeholder="Any extra details…" value={form.note} onChange={e => set('note', e.target.value)} disabled={loading} />
          </div>

          {error && <p className="text-sm text-destructive">{error}</p>}
        </div>

        <DialogFooter className="gap-2">
          <Button variant="outline" onClick={handleClose} disabled={loading}>Cancel</Button>
          <Button onClick={handleSubmit} disabled={loading || rateLoading}>
            {loading ? 'Saving…' : isEditing ? 'Save changes' : 'Log income'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
