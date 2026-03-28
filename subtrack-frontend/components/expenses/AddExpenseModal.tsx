'use client'

import { useState } from 'react'
import { Category, Expense } from '@/types'
import {
  Dialog, DialogContent, DialogHeader,
  DialogTitle, DialogFooter,
} from '@/components/ui/dialog'
import { Button }   from '@/components/ui/button'
import { Input }    from '@/components/ui/input'
import { Label }    from '@/components/ui/label'
import {
  Select, SelectContent, SelectItem,
  SelectTrigger, SelectValue,
} from '@/components/ui/select'

const CATEGORIES: Category[] = [
  'streaming', 'software', 'cloud', 'utilities',
  'fitness', 'food', 'transport', 'other',
]

interface FormState {
  name:     string
  category: Category
  amount:   string
  currency: string
  date:     string
  note:     string
}

const today = new Date().toISOString().split('T')[0]

const DEFAULT_FORM: FormState = {
  name:     '',
  category: 'other',
  amount:   '',
  currency: 'AUD',
  date:     today,
  note:     '',
}

interface Props {
  open:     boolean
  onClose:  () => void
  onSubmit: (data: Omit<Expense, 'id' | 'user_id' | 'created_at'>) => Promise<void>
}

export function AddExpenseModal({ open, onClose, onSubmit }: Props) {
  const [form, setForm]       = useState<FormState>(DEFAULT_FORM)
  const [loading, setLoading] = useState(false)
  const [error, setError]     = useState<string | null>(null)

  function set<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm(prev => ({ ...prev, [key]: value }))
    setError(null)
  }

  async function handleSubmit() {
    if (!form.name.trim()) return setError('Name is required.')
    const amount = parseFloat(form.amount)
    if (isNaN(amount) || amount <= 0) return setError('Enter a valid amount greater than 0.')
    if (!form.date) return setError('Date is required.')

    setLoading(true)
    setError(null)
    try {
      await onSubmit({
        name:     form.name.trim(),
        category: form.category,
        amount,
        currency: form.currency.trim().toUpperCase(),
        date:     new Date(form.date).toISOString(),
        note:     form.note.trim() || null,
      })
      setForm(DEFAULT_FORM)
      onClose()
    } catch (e: any) {
      setError(e?.message ?? 'Something went wrong.')
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
          <DialogTitle>Log expense</DialogTitle>
        </DialogHeader>

        <div className="grid gap-4 py-2">
          <div className="grid gap-1.5">
            <Label htmlFor="exp-name">Name</Label>
            <Input
              id="exp-name"
              placeholder="Grocery run, Uber…"
              value={form.name}
              onChange={e => set('name', e.target.value)}
              disabled={loading}
            />
          </div>

          <div className="grid gap-1.5">
            <Label>Category</Label>
            <Select
              value={form.category}
              onValueChange={v => set('category', v as Category)}
              disabled={loading}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {CATEGORIES.map(c => (
                  <SelectItem key={c} value={c} className="capitalize">{c}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="grid gap-1.5">
              <Label htmlFor="exp-amount">Amount</Label>
              <Input
                id="exp-amount"
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
              <Label htmlFor="exp-currency">Currency</Label>
              <Input
                id="exp-currency"
                placeholder="AUD"
                maxLength={3}
                value={form.currency}
                onChange={e => set('currency', e.target.value.toUpperCase())}
                disabled={loading}
              />
            </div>
          </div>

          <div className="grid gap-1.5">
            <Label htmlFor="exp-date">Date</Label>
            <Input
              id="exp-date"
              type="date"
              value={form.date}
              onChange={e => set('date', e.target.value)}
              disabled={loading}
            />
          </div>

          <div className="grid gap-1.5">
            <Label htmlFor="exp-note">
              Note{' '}
              <span className="text-muted-foreground font-normal">(optional)</span>
            </Label>
            <Input
              id="exp-note"
              placeholder="Any extra details…"
              value={form.note}
              onChange={e => set('note', e.target.value)}
              disabled={loading}
            />
          </div>

          {error && <p className="text-sm text-destructive">{error}</p>}
        </div>

        <DialogFooter className="gap-2">
          <Button variant="outline" onClick={handleClose} disabled={loading}>
            Cancel
          </Button>
          <Button onClick={handleSubmit} disabled={loading}>
            {loading ? 'Saving…' : 'Log expense'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}