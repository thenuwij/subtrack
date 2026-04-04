'use client'

import { useState, useEffect } from 'react'
import { Category, Currency, Expense } from '@/types'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { useCurrency } from '@/lib/context/currency'
import { getRates } from '@/lib/api'
import { createClient } from '@/lib/supabase/client'
import { formatCurrency } from '@/lib/utils/currency'

const CATEGORIES: Category[] = ['streaming', 'software', 'cloud', 'utilities', 'fitness', 'food', 'transport', 'other']
const CURRENCIES: Currency[] = ['AUD', 'USD', 'GBP', 'SGD', 'EUR', 'JPY']
const today = new Date().toISOString().split('T')[0]

interface FormState {
  name: string
  category: Category
  amount: string
  currency: Currency
  date: string
  note: string
}

interface Props {
  open: boolean
  onClose: () => void
  onSubmit: (data: Omit<Expense, 'id' | 'user_id' | 'created_at'>) => Promise<void>
  initialData?: Expense
}

export function AddExpenseModal({ open, onClose, onSubmit, initialData }: Props) {
  const { baseCurrency } = useCurrency()
  const isEditing = !!initialData

  function getInitialForm(): FormState {
    if (!initialData) return {
      name: '', category: 'other', amount: '', currency: baseCurrency, date: today, note: '',
    }
    return {
      name: initialData.name,
      category: initialData.category,
      amount: initialData.amount.toString(),
      currency: initialData.currency as Currency,
      date: new Date(initialData.date).toISOString().split('T')[0],
      note: initialData.note ?? '',
    }
  }

  const [form, setForm] = useState<FormState>(getInitialForm)

  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [exchangeRate, setExchangeRate] = useState<number>(1.0)
  const [rateLoading, setRateLoading] = useState(false)
  const [rateError, setRateError] = useState<string | null>(null)

  useEffect(() => {
    setForm(getInitialForm())
    setExchangeRate(initialData?.exchange_rate ?? 1.0)
    setError(null)
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
    if (!form.date) return setError('Date is required.')
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
        date: new Date(form.date || today).toISOString(),
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
          <DialogTitle>{isEditing ? 'Edit expense' : 'Log expense'}</DialogTitle>
        </DialogHeader>

        <div className="grid gap-4 py-2">
          <div className="grid gap-1.5">
            <Label htmlFor="exp-name">Name</Label>
            <Input id="exp-name" placeholder="Grocery run, Uber…" value={form.name} onChange={e => set('name', e.target.value)} disabled={loading} />
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
              <Label htmlFor="exp-amount">Amount</Label>
              <Input id="exp-amount" type="number" min="0" step="0.01" placeholder="0.00" value={form.amount} onChange={e => set('amount', e.target.value)} disabled={loading} />
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
            <Label htmlFor="exp-date">Date</Label>
            <Input id="exp-date" type="date" value={form.date} onChange={e => set('date', e.target.value)} disabled={loading} />
          </div>

          <div className="grid gap-1.5">
            <Label htmlFor="exp-note">Note <span className="font-normal text-muted-foreground">(optional)</span></Label>
            <Input id="exp-note" placeholder="Any extra details…" value={form.note} onChange={e => set('note', e.target.value)} disabled={loading} />
          </div>

          {error && <p className="text-sm text-destructive">{error}</p>}
        </div>

        <DialogFooter className="gap-2">
          <Button variant="outline" onClick={handleClose} disabled={loading}>Cancel</Button>
          <Button onClick={handleSubmit} disabled={loading || rateLoading}>
            {loading ? (isEditing ? 'Saving…' : 'Saving…') : (isEditing ? 'Save changes' : 'Log expense')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}