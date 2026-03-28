'use client'

import { useState } from 'react'
import { BillingCycle, Category, Subscription } from '@/types'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog'
import { Button }   from '@/components/ui/button'
import { Input }    from '@/components/ui/input'
import { Label }    from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

const CATEGORIES: Category[] = [
  'streaming', 'software', 'cloud', 'utilities',
  'fitness', 'food', 'transport', 'other',
]

const CYCLES: BillingCycle[] = ['weekly', 'monthly', 'yearly']

interface FormState {
  name:      string
  category:  Category
  amount:    string
  currency:  string
  cycle:     BillingCycle
  next_due:  string
  is_active: boolean
}

const DEFAULT_FORM: FormState = {
  name:      '',
  category:  'other',
  amount:    '',
  currency:  'AUD',
  cycle:     'monthly',
  next_due:  '',
  is_active: true,
}

interface Props {
  open:      boolean
  onClose:   () => void
  onSubmit:  (data: Omit<Subscription, 'id' | 'user_id' | 'created_at'>) => Promise<void>
}

export function AddSubscriptionModal({ open, onClose, onSubmit }: Props) {
  const [form, setForm]       = useState<FormState>(DEFAULT_FORM)
  const [loading, setLoading] = useState(false)
  const [error, setError]     = useState<string | null>(null)

  function set<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm(prev => ({ ...prev, [key]: value }))
    setError(null)
  }

  async function handleSubmit() {
    if (!form.name.trim())        return setError('Name is required.')
    const amount = parseFloat(form.amount)
    if (isNaN(amount) || amount <= 0) return setError('Enter a valid amount greater than 0.')
    if (!form.currency.trim())    return setError('Currency is required.')

    setLoading(true)
    setError(null)
    try {
      await onSubmit({
        name:      form.name.trim(),
        category:  form.category,
        amount,
        currency:  form.currency.trim().toUpperCase(),
        cycle:     form.cycle,
        next_due:  form.next_due || null,
        is_active: form.is_active,
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
          <DialogTitle>Add subscription</DialogTitle>
        </DialogHeader>

        <div className="grid gap-4 py-2">

          {/* Name */}
          <div className="grid gap-1.5">
            <Label htmlFor="sub-name">Name</Label>
            <Input
              id="sub-name"
              placeholder="Netflix, GitHub Pro…"
              value={form.name}
              onChange={e => set('name', e.target.value)}
              disabled={loading}
            />
          </div>

          {/* Category */}
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
                  <SelectItem key={c} value={c} className="capitalize">
                    {c}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Amount + Currency */}
          <div className="grid grid-cols-2 gap-3">
            <div className="grid gap-1.5">
              <Label htmlFor="sub-amount">Amount</Label>
              <Input
                id="sub-amount"
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
              <Label htmlFor="sub-currency">Currency</Label>
              <Input
                id="sub-currency"
                placeholder="AUD"
                maxLength={3}
                value={form.currency}
                onChange={e => set('currency', e.target.value.toUpperCase())}
                disabled={loading}
              />
            </div>
          </div>

          {/* Billing cycle */}
          <div className="grid gap-1.5">
            <Label>Billing cycle</Label>
            <Select
              value={form.cycle}
              onValueChange={v => set('cycle', v as BillingCycle)}
              disabled={loading}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {CYCLES.map(c => (
                  <SelectItem key={c} value={c} className="capitalize">
                    {c}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Next due date */}
          <div className="grid gap-1.5">
            <Label htmlFor="sub-due">
              Next renewal date{' '}
              <span className="text-muted-foreground font-normal">(optional)</span>
            </Label>
            <Input
              id="sub-due"
              type="date"
              value={form.next_due}
              onChange={e => set('next_due', e.target.value)}
              disabled={loading}
            />
          </div>

          {/* Error */}
          {error && (
            <p className="text-sm text-destructive">{error}</p>
          )}

        </div>

        <DialogFooter className="gap-2">
          <Button variant="outline" onClick={handleClose} disabled={loading}>
            Cancel
          </Button>
          <Button onClick={handleSubmit} disabled={loading}>
            {loading ? 'Adding…' : 'Add subscription'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}