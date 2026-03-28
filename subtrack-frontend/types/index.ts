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

export interface Subscription {
  id: string
  user_id: string
  name: string
  category: Category
  amount: number
  currency: string
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