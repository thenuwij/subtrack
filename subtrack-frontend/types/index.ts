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

export interface Expense {
  id: string
  user_id: string
  name: string
  category: Category
  amount: number
  currency: string
  exchange_rate: number
  converted_amount: number | null  // null for legacy entries
  date: string
  note: string | null
  created_at: string
}

export interface Budget {
  id: string
  user_id: string
  category: Category
  monthly_limit: number
  currency: string
  created_at: string
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
}