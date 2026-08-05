'use client'

import { useState } from 'react'
import Link from 'next/link'
import { Bell, CalendarClock, Check, Clock3 } from 'lucide-react'
import type { PaymentReminder } from '@/types'
import { Button } from '@/components/ui/button'
import { formatStoredDate } from '@/lib/utils/dates'


function formatDate(value: string | null) {
  if (!value) return 'Date needed'
  return formatStoredDate(value, {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
  })
}

function reminderCopy(reminder: PaymentReminder) {
  const target = formatDate(reminder.target_at)
  if (reminder.kind === 'trial_end') return `Trial ends ${target}`
  if (reminder.kind === 'cancel') return `Cancel before the ${target} renewal`
  return `Renews ${target}`
}

function timingCopy(reminder: PaymentReminder) {
  if (reminder.status === 'overdue') return 'The saved date has passed'
  if (reminder.status === 'due') {
    return reminder.days_until_target === 0
      ? 'Due today'
      : `${reminder.days_until_target} day${reminder.days_until_target === 1 ? '' : 's'} left`
  }
  if (reminder.days_until_alert === 1) return 'Reminder starts tomorrow'
  if (reminder.days_until_alert === null) return 'Date needed'
  return `Reminder starts in ${reminder.days_until_alert} days`
}

interface ReminderCenterProps {
  reminders: PaymentReminder[]
  onDismiss: (id: string) => Promise<void>
}

export function ReminderCenter({ reminders, onDismiss }: ReminderCenterProps) {
  const [busyId, setBusyId] = useState<string | null>(null)
  if (reminders.length === 0) return null

  async function dismiss(id: string) {
    setBusyId(id)
    try {
      await onDismiss(id)
    } finally {
      setBusyId(null)
    }
  }

  return (
    <section className="overflow-hidden rounded-2xl bg-card shadow-sm" aria-labelledby="dashboard-reminders-title">
      <div className="flex items-start justify-between gap-4 border-b border-border px-5 py-4">
        <div>
          <div className="flex items-center gap-2">
            <Bell className="h-4 w-4 text-primary" />
            <h2 id="dashboard-reminders-title" className="text-sm font-semibold text-foreground">
              Upcoming reminders
            </h2>
          </div>
          <p className="mt-1 text-xs text-muted-foreground">
            Renewal and trial dates you asked Subtrack to keep visible.
          </p>
        </div>
        <Link href="/subscriptions" className="text-xs font-medium text-primary hover:underline">
          Manage
        </Link>
      </div>

      <ul className="divide-y divide-border">
        {reminders.slice(0, 6).map(reminder => {
          const active = reminder.status === 'due' || reminder.status === 'overdue'
          return (
            <li key={reminder.id} className="flex flex-col gap-3 px-5 py-4 sm:flex-row sm:items-center">
              <div className="flex min-w-0 flex-1 items-start gap-3">
                <div className={`mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${
                  active ? 'bg-amber-500/10 text-amber-600 dark:text-amber-400' : 'bg-primary/10 text-primary'
                }`}>
                  {reminder.kind === 'trial_end' ? <Clock3 className="h-4 w-4" /> : <CalendarClock className="h-4 w-4" />}
                </div>
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="truncate text-sm font-semibold text-foreground">
                      {reminder.subscription_name}
                    </p>
                    {active ? (
                      <span className="rounded-full bg-amber-500/10 px-2 py-0.5 text-[10px] font-semibold text-amber-700 dark:text-amber-300">
                        {reminder.status === 'overdue' ? 'Date passed' : 'Active now'}
                      </span>
                    ) : null}
                  </div>
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    {reminderCopy(reminder)} · {timingCopy(reminder)}
                  </p>
                  {reminder.note ? (
                    <p className="mt-1 text-xs text-foreground/80">{reminder.note}</p>
                  ) : null}
                </div>
              </div>
              <Button
                size="sm"
                variant="ghost"
                disabled={busyId === reminder.id}
                onClick={() => void dismiss(reminder.id)}
                className="self-start text-muted-foreground sm:self-center"
              >
                <Check data-icon="inline-start" />
                {busyId === reminder.id ? 'Dismissing…' : 'Dismiss'}
              </Button>
            </li>
          )
        })}
      </ul>
    </section>
  )
}
