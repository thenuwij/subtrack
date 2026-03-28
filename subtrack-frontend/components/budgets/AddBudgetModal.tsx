'use client'

import { useState } from 'react'
import { Category, Budget } from '@/types'
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
  category:      Category
  monthly_limit: string
  currency:      string
}

const DEFAULT_FORM: FormState = {
  category:      'other',
  monthly_limit: '',
  currency:      'AUD',
}

interface Props {
  open:            boolean
  onClose:         () => void
  existingCategories: Category[]
  onSubmit:        (data: Omit<Budget, 'id' | 'user_id' | 'created_at'>) => Promise<void>
}

export function AddBudgetModal({ open, onClose, existingCategories, onSubmit }: Props) {
  const [form, setForm]       = useState<FormState>(DEFAULT_FORM)
  const [loading, setLoading] = useState(false)
  const [error, setError]     = useState<string | null>(null)

  const availableCategories = CATEGORIES.filter(c => !existingCategories.includes(c))

  function set<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm(prev => ({ ...prev, [key]: value }))
    setError(null)
  }

  async function handleSubmit() {
    const limit = parseFloat(form.monthly_limit)
    if (isNaN(limit) || limit <= 0) return setError('Enter a valid limit greater than 0.')

    setLoading(true)
    setError(null)
    try {
      await onSubmit({
        category:      form.category,
        monthly_limit: limit,
        currency:      form.currency.trim().toUpperCase(),
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
          <DialogTitle>Set budget</DialogTitle>
        </DialogHeader>

        <div className="grid gap-4 py-2">
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
                {availableCategories.map(c => (
                  <SelectItem key={c} value={c} className="capitalize">{c}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="grid gap-1.5">
              <Label htmlFor="budget-limit">Monthly limit</Label>
              <Input
                id="budget-limit"
                type="number"
                min="0"
                step="0.01"
                placeholder="0.00"
                value={form.monthly_limit}
                onChange={e => set('monthly_limit', e.target.value)}
                disabled={loading}
              />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="budget-currency">Currency</Label>
              <Input
                id="budget-currency"
                placeholder="AUD"
                maxLength={3}
                value={form.currency}
                onChange={e => set('currency', e.target.value.toUpperCase())}
                disabled={loading}
              />
            </div>
          </div>

          {error && <p className="text-sm text-destructive">{error}</p>}
        </div>

        <DialogFooter className="gap-2">
          <Button variant="outline" onClick={handleClose} disabled={loading}>
            Cancel
          </Button>
          <Button onClick={handleSubmit} disabled={loading || availableCategories.length === 0}>
            {loading ? 'Saving…' : 'Set budget'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}