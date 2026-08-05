import type {
  BillingCycle,
  PaymentStatus,
  RecurrenceUnit,
  Subscription,
} from '@/types'
import { storedDateKey, todayUtcDateKey } from '@/lib/utils/dates'

export interface Cadence {
  interval_unit: RecurrenceUnit
  interval_count: number
}

export const CADENCE_PRESETS: ReadonlyArray<Cadence & { key: string; label: string }> = [
  { key: 'weekly', interval_unit: 'week', interval_count: 1, label: 'Weekly' },
  { key: 'fortnightly', interval_unit: 'week', interval_count: 2, label: 'Every 2 weeks' },
  { key: 'four-weeks', interval_unit: 'week', interval_count: 4, label: 'Every 4 weeks' },
  { key: 'monthly', interval_unit: 'month', interval_count: 1, label: 'Monthly' },
  { key: 'two-months', interval_unit: 'month', interval_count: 2, label: 'Every 2 months' },
  { key: 'quarterly', interval_unit: 'month', interval_count: 3, label: 'Every 3 months' },
  { key: 'six-months', interval_unit: 'month', interval_count: 6, label: 'Every 6 months' },
  { key: 'yearly', interval_unit: 'year', interval_count: 1, label: 'Yearly' },
  { key: 'two-years', interval_unit: 'year', interval_count: 2, label: 'Every 2 years' },
]

export function legacyCadence(cycle: BillingCycle | null | undefined): Cadence {
  if (cycle === 'weekly') return { interval_unit: 'week', interval_count: 1 }
  if (cycle === 'yearly') return { interval_unit: 'year', interval_count: 1 }
  return { interval_unit: 'month', interval_count: 1 }
}

/** Only exact legacy cadences can safely be sent to an older backend. */
export function exactLegacyCycle(unit: RecurrenceUnit, count: number): BillingCycle | null {
  if (count !== 1) return null
  if (unit === 'week') return 'weekly'
  if (unit === 'month') return 'monthly'
  if (unit === 'year') return 'yearly'
  return null
}

export function formatCadence(unit: RecurrenceUnit, count: number): string {
  if (count === 1) {
    return { day: 'Daily', week: 'Weekly', month: 'Monthly', year: 'Yearly' }[unit]
  }
  return `Every ${count} ${unit}s`
}

export function cadenceFor(subscription: Pick<Subscription, 'cycle'> & Partial<Cadence>): Cadence {
  if (subscription.interval_unit && Number.isInteger(subscription.interval_count)
      && Number(subscription.interval_count) > 0) {
    return {
      interval_unit: subscription.interval_unit,
      interval_count: Number(subscription.interval_count),
    }
  }
  return legacyCadence(subscription.cycle)
}

export function cadenceLabel(subscription: Pick<Subscription, 'cycle'> & Partial<Cadence & { cadence_label: string }>) {
  if (subscription.cadence_label) return subscription.cadence_label
  const cadence = cadenceFor(subscription)
  return formatCadence(cadence.interval_unit, cadence.interval_count)
}

/**
 * Compatibility only: old API responses do not include authoritative
 * equivalents. New UI always prefers the backend-provided values.
 */
export function legacyMonthlyEquivalent(amount: number, cycle: BillingCycle): number {
  if (cycle === 'weekly') return amount * 52 / 12
  if (cycle === 'yearly') return amount / 12
  return amount
}

export function monthlyEquivalentNative(subscription: Subscription): number {
  return Number.isFinite(subscription.monthly_equivalent)
    ? subscription.monthly_equivalent
    : legacyMonthlyEquivalent(subscription.amount, subscription.cycle)
}

export function yearlyEquivalentNative(subscription: Subscription): number {
  return Number.isFinite(subscription.yearly_equivalent)
    ? subscription.yearly_equivalent
    : monthlyEquivalentNative(subscription) * 12
}

export function isTerminalStatus(status: PaymentStatus) {
  return status === 'cancelled' || status === 'ended'
}

export function contributesToCommitment(subscription: Pick<Subscription, 'status' | 'trial_ends_at'>) {
  if (subscription.status !== 'active' && subscription.status !== 'cancelling') return false
  if (!subscription.trial_ends_at) return true
  return storedDateKey(subscription.trial_ends_at) < todayUtcDateKey()
}

export function paymentStatusLabel(status: PaymentStatus) {
  return {
    active: 'Active',
    paused: 'Paused',
    cancelling: 'Cancelling',
    cancelled: 'Cancelled',
    ended: 'Ended',
  }[status]
}
