import type { Subscription } from '@/types'

export function isActiveTrial(
  subscription: Pick<Subscription, 'trial_ends_at'>,
  now = new Date()
) {
  if (!subscription.trial_ends_at) return false
  const end = new Date(subscription.trial_ends_at)
  const today = new Date(now)
  today.setHours(0, 0, 0, 0)
  return end.getTime() >= today.getTime()
}
