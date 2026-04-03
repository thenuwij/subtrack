'use client'

import { useState, useEffect } from 'react'
import { Currency, SavingsGoal } from '@/types'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { useCurrency } from '@/lib/context/currency'

const CURRENCIES: Currency[] = ['AUD', 'USD', 'GBP', 'SGD', 'EUR', 'JPY']

interface FormState {
  name: string
  target_amount: string
  current_amount: string
  currency: Currency
  target_date: string
}

interface Props {
  open: boolean
  onClose: () => void
  onSubmit: (data: Omit<SavingsGoal, 'id' | 'user_id' | 'created_by' | 'created_at' | 'completed_at'>) => Promise<void>
  initialData?: SavingsGoal
}

export function AddSavingsModal({ open, onClose, onSubmit, initialData }: Props) {
  const { baseCurrency } = useCurrency()
  const isEditing = !!initialData

  function getInitialForm(): FormState {
    if (!initialData) return {
      name: '', target_amount: '', current_amount: '', currency: baseCurrency, target_date: '',
    }
    return {
      name: initialData.name,
      target_amount: initialData.target_amount.toString(),
      current_amount: initialData.current_amount.toString(),
      currency: initialData.currency as Currency,
      target_date: initialData.target_date
        ? new Date(initialData.target_date).toISOString().split('T')[0]
        : '',
    }
  }

  const [form, setForm]         = useState<FormState>(getInitialForm)
  const [loading, setLoading]   = useState(false)
  const [error, setError]       = useState<string | null>(null)

  useEffect(() => {
    setForm(getInitialForm())
    setError(null)
  }, [initialData])

  function set<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm(prev => ({ ...prev, [key]: value }))
    setError(null)
  }

  async function handleSubmit() {
    const target = parseFloat(form.target_amount)
    if (!form.name.trim()) return setError('Name is required.')
    if (isNaN(target) || target <= 0) return setError('Enter a valid target amount greater than 0.')

    const current = form.current_amount ? parseFloat(form.current_amount) : 0
    if (isNaN(current) || current < 0) return setError('Current amount cannot be negative.')

    setLoading(true)
    setError(null)
    try {
      await onSubmit({
        name: form.name.trim(),
        target_amount: target,
        current_amount: current,
        currency: form.currency,
        target_date: form.target_date ? new Date(form.target_date).toISOString() : null,
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
          <DialogTitle>{isEditing ? 'Edit goal' : 'New savings goal'}</DialogTitle>
        </DialogHeader>

        <div className="grid gap-4 py-2">
          <div className="grid gap-1.5">
            <Label htmlFor="sav-name">Goal name</Label>
            <Input
              id="sav-name"
              placeholder="Emergency fund, Holiday, New laptop…"
              value={form.name}
              onChange={e => set('name', e.target.value)}
              disabled={loading}
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="grid gap-1.5">
              <Label htmlFor="sav-target">Target amount</Label>
              <Input
                id="sav-target"
                type="number"
                min="0"
                step="0.01"
                placeholder="0.00"
                value={form.target_amount}
                onChange={e => set('target_amount', e.target.value)}
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

          <div className="grid gap-1.5">
            <Label htmlFor="sav-current">
              Current amount <span className="font-normal text-muted-foreground">(optional)</span>
            </Label>
            <Input
              id="sav-current"
              type="number"
              min="0"
              step="0.01"
              placeholder="0.00"
              value={form.current_amount}
              onChange={e => set('current_amount', e.target.value)}
              disabled={loading}
            />
          </div>

          <div className="grid gap-1.5">
            <Label htmlFor="sav-date">
              Target date <span className="font-normal text-muted-foreground">(optional)</span>
            </Label>
            <Input id="sav-date" type="date" value={form.target_date} onChange={e => set('target_date', e.target.value)} disabled={loading} />
          </div>

          {error && <p className="text-sm text-destructive">{error}</p>}
        </div>

        <DialogFooter className="gap-2">
          <Button variant="outline" onClick={handleClose} disabled={loading}>Cancel</Button>
          <Button onClick={handleSubmit} disabled={loading}>
            {loading ? 'Saving…' : isEditing ? 'Save changes' : 'Create goal'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
