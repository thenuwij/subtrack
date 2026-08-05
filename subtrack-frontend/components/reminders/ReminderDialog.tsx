'use client'

import { useCallback, useEffect, useState } from 'react'
import { Bell, LoaderCircle, Trash2 } from 'lucide-react'
import { createClient } from '@/lib/supabase/client'
import {
  createReminder,
  deleteReminder,
  getReminders,
  restoreReminder,
} from '@/lib/api'
import type {
  PaymentReminder,
  ReminderKind,
  Subscription,
} from '@/types'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'


const KIND_LABEL: Record<ReminderKind, string> = {
  cancel: 'Cancel before renewal',
  renewal: 'Renewal heads-up',
  trial_end: 'Free trial ending',
}

function dateInputValue(value: string | null) {
  if (!value) return ''
  const date = new Date(value)
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function formatDate(value: string | null) {
  if (!value) return 'Date needed'
  return new Intl.DateTimeFormat('en-AU', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  }).format(new Date(value))
}

async function accessToken() {
  const { data: { session } } = await createClient().auth.getSession()
  if (!session) throw new Error('Your session has expired. Please sign in again.')
  return session.access_token
}

interface ReminderDialogProps {
  subscription: Subscription
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function ReminderDialog({
  subscription,
  open,
  onOpenChange,
}: ReminderDialogProps) {
  const [reminders, setReminders] = useState<PaymentReminder[]>([])
  const [kind, setKind] = useState<ReminderKind>('cancel')
  const [daysBefore, setDaysBefore] = useState('7')
  const [targetDate, setTargetDate] = useState('')
  const [note, setNote] = useState('')
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [confirmingDelete, setConfirmingDelete] = useState<string | null>(null)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const token = await accessToken()
      const result = await getReminders(token, {
        subscriptionId: subscription.id,
        includeDismissed: true,
        horizonDays: 730,
      })
      setReminders(result)
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : 'Could not load reminders.')
    } finally {
      setLoading(false)
    }
  }, [subscription.id])

  useEffect(() => {
    if (open) void load()
  }, [load, open])

  const parsedDays = Number(daysBefore)
  const scheduleReady = kind === 'trial_end' ? Boolean(targetDate) : Boolean(subscription.next_due)
  const formValid = Number.isInteger(parsedDays)
    && parsedDays >= 0
    && parsedDays <= 365
    && scheduleReady

  async function save() {
    if (!formValid || saving) return
    setSaving(true)
    setError('')
    try {
      const token = await accessToken()
      await createReminder(token, {
        subscription_id: subscription.id,
        kind,
        days_before: parsedDays,
        ...(kind === 'trial_end'
          // Treat a date-only deadline as a calendar date. Noon UTC avoids the
          // common local-midnight conversion that silently stores the previous
          // day for users east of Greenwich.
          ? { target_date: new Date(`${targetDate}T12:00:00Z`).toISOString() }
          : {}),
        ...(note.trim() ? { note: note.trim() } : {}),
      })
      setNote('')
      if (kind === 'trial_end') setTargetDate('')
      await load()
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : 'Could not create reminder.')
    } finally {
      setSaving(false)
    }
  }

  async function remove(id: string) {
    setDeletingId(id)
    setError('')
    try {
      const token = await accessToken()
      await deleteReminder(token, id)
      setReminders(current => current.filter(reminder => reminder.id !== id))
      setConfirmingDelete(null)
    } catch (deleteError) {
      setError(deleteError instanceof Error ? deleteError.message : 'Could not remove reminder.')
    } finally {
      setDeletingId(null)
    }
  }

  async function restore(id: string) {
    setError('')
    try {
      const token = await accessToken()
      const restored = await restoreReminder(token, id)
      setReminders(current => current.map(reminder => reminder.id === id ? restored : reminder))
    } catch (restoreError) {
      setError(restoreError instanceof Error ? restoreError.message : 'Could not restore reminder.')
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[min(42rem,calc(100dvh-2rem))] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Reminders for {subscription.name}</DialogTitle>
          <DialogDescription>
            Alerts appear on your dashboard. Email and push notifications are not enabled yet.
          </DialogDescription>
        </DialogHeader>

        {loading ? (
          <div className="flex items-center justify-center py-8 text-sm text-muted-foreground">
            <LoaderCircle className="mr-2 h-4 w-4 animate-spin" />
            Loading reminders…
          </div>
        ) : reminders.length > 0 ? (
          <div className="divide-y divide-border rounded-xl border border-border">
            {reminders.map(reminder => (
              <div key={reminder.id} className="flex items-center gap-3 p-3">
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                  <Bell className="h-4 w-4" />
                </div>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium">{KIND_LABEL[reminder.kind]}</p>
                  <p className="text-xs text-muted-foreground">
                    {reminder.days_before === 0
                      ? 'On the day'
                      : `${reminder.days_before} day${reminder.days_before === 1 ? '' : 's'} before`}
                    {' · '}{formatDate(reminder.target_at)}
                    {reminder.status === 'dismissed' ? ' · dismissed' : ''}
                  </p>
                </div>
                {confirmingDelete === reminder.id ? (
                  <div className="flex items-center gap-1">
                    <Button
                      size="sm"
                      variant="destructive"
                      disabled={deletingId === reminder.id}
                      onClick={() => void remove(reminder.id)}
                    >
                      {deletingId === reminder.id ? 'Removing…' : 'Remove'}
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => setConfirmingDelete(null)}>
                      Keep
                    </Button>
                  </div>
                ) : reminder.status === 'dismissed' ? (
                  <div className="flex items-center gap-1">
                    <Button size="sm" variant="ghost" onClick={() => void restore(reminder.id)}>
                      Restore
                    </Button>
                    <Button
                      size="icon-sm"
                      variant="ghost"
                      className="text-muted-foreground hover:text-destructive"
                      onClick={() => setConfirmingDelete(reminder.id)}
                      aria-label={`Remove ${KIND_LABEL[reminder.kind]} reminder`}
                    >
                      <Trash2 />
                    </Button>
                  </div>
                ) : (
                  <Button
                    size="icon-sm"
                    variant="ghost"
                    className="text-muted-foreground hover:text-destructive"
                    onClick={() => setConfirmingDelete(reminder.id)}
                    aria-label={`Remove ${KIND_LABEL[reminder.kind]} reminder`}
                  >
                    <Trash2 />
                  </Button>
                )}
              </div>
            ))}
          </div>
        ) : (
          <div className="rounded-xl border border-dashed border-border px-4 py-6 text-center">
            <p className="text-sm font-medium">No reminders yet</p>
            <p className="mt-1 text-xs text-muted-foreground">
              Add one below and it will appear on your dashboard.
            </p>
          </div>
        )}

        <div className="grid gap-4 rounded-xl bg-muted/40 p-4">
          <div className="grid gap-1.5">
            <Label>Reminder type</Label>
            <Select
              value={kind}
              onValueChange={value => {
                const nextKind = value as ReminderKind
                setKind(nextKind)
                if (nextKind === 'trial_end' && subscription.trial_ends_at) {
                  setTargetDate(dateInputValue(subscription.trial_ends_at))
                }
              }}
            >
              <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
              <SelectContent>
                {(Object.entries(KIND_LABEL) as [ReminderKind, string][]).map(([value, label]) => (
                  <SelectItem key={value} value={value}>{label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {kind === 'trial_end' ? (
            <div className="grid gap-1.5">
              <Label htmlFor="reminder-trial-date">Trial end date</Label>
              <Input
                id="reminder-trial-date"
                type="date"
                min={dateInputValue(new Date().toISOString())}
                value={targetDate}
                onChange={event => setTargetDate(event.target.value)}
              />
            </div>
          ) : !subscription.next_due ? (
            <div className="rounded-lg border border-amber-500/25 bg-amber-500/5 px-3 py-2 text-xs text-muted-foreground">
              Edit this payment and add its next payment date before creating a recurring reminder.
            </div>
          ) : (
            <p className="text-xs text-muted-foreground">
              Uses the payment date already saved for this {subscription.cycle} payment: {' '}
              <span className="font-medium text-foreground">{formatDate(subscription.next_due)}</span>.
            </p>
          )}

          <div className="grid gap-1.5">
            <Label htmlFor="reminder-days">Days before</Label>
            <Input
              id="reminder-days"
              type="number"
              min={0}
              max={365}
              step={1}
              inputMode="numeric"
              value={daysBefore}
              onChange={event => setDaysBefore(event.target.value)}
            />
            <p className="text-xs text-muted-foreground">
              Use 0 for an alert on the date itself.
            </p>
          </div>

          <div className="grid gap-1.5">
            <Label htmlFor="reminder-note">Note (optional)</Label>
            <textarea
              id="reminder-note"
              maxLength={300}
              rows={2}
              value={note}
              onChange={event => setNote(event.target.value)}
              placeholder="Check the cancellation policy first"
              className="w-full resize-none rounded-lg border border-input bg-transparent px-2.5 py-2 text-sm outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30"
            />
          </div>
        </div>

        {error ? <p role="alert" className="text-sm text-destructive">{error}</p> : null}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={saving}>
            Close
          </Button>
          <Button onClick={() => void save()} disabled={!formValid || saving}>
            {saving ? 'Adding…' : 'Add reminder'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
