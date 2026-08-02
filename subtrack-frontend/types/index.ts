export type BillingCycle = 'weekly' | 'monthly' | 'yearly'

export type Category =
  | 'streaming'
  | 'software'
  | 'cloud'
  | 'utilities'
  | 'fitness'
  | 'food'
  | 'transport'
  | 'other'

export type Currency = 'AUD' | 'USD' | 'GBP' | 'SGD' | 'EUR' | 'JPY'

export interface Subscription {
  id: string
  user_id: string
  name: string
  category: Category
  amount: number
  currency: string
  exchange_rate: number
  converted_amount: number | null  // null for legacy entries
  cycle: BillingCycle
  next_due: string | null
  is_active: boolean
  created_at: string
}

export type ChangeKind = 'added' | 'price_change' | 'removed'

export interface SubscriptionChange {
  id: string
  subscription_id: string
  name: string
  kind: ChangeKind
  old_monthly: number | null
  new_monthly: number | null
  delta: number           // monthly-equivalent change, in the entry's currency
  currency: string
  changed_at: string
}

export interface User {
  id: string
  email: string
  name?: string
}

export interface Rates {
  base: string
  rates: Record<string, number>  // e.g. { USD: 0.63, GBP: 0.52 }
  cached: boolean
  fetched_at: string
}

export interface Preferences {
  base_currency: Currency
  monthly_income: number | null  // null until the user states it
}

export interface SavingsGoal {
  id: string
  user_id: string
  name: string
  target_amount: number
  current_amount: number
  currency: string
  target_date: string | null
  created_by: string
  created_at: string
  completed_at: string | null
}