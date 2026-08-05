import type { Subscription } from '@/types'
import { storedDateKey, todayUtcDateKey } from '@/lib/utils/dates'

export function isActiveTrial(
  subscription: Pick<Subscription, 'trial_ends_at'>,
) {
  if (!subscription.trial_ends_at) return false
  return storedDateKey(subscription.trial_ends_at) >= todayUtcDateKey()
}
