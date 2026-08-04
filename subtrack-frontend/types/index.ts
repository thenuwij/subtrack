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
  amount: number                   // what YOU pay (your share of a split bill)
  full_amount: number | null       // the whole bill, when shared; null = you pay it all
  share_ratio: number              // amount = full_amount * share_ratio
  split_mode: 'full' | 'ratio' | 'fixed'  // fixed shares don't rescale when the bill changes
  currency: string
  exchange_rate: number
  converted_amount: number | null  // null for legacy entries
  cycle: BillingCycle
  next_due: string | null
  is_active: boolean
  created_at: string
}

// Payload shapes for create/update calls — mirror the backend Pydantic models.
export interface SubscriptionInput {
  name: string
  category: Category
  amount: number
  currency?: string
  exchange_rate?: number
  converted_amount?: number | null
  cycle: BillingCycle
  next_due?: string | null
  is_active?: boolean
  full_amount?: number | null
  share_ratio?: number
  share_amount?: number
}

export interface GmailStatus {
  connected: boolean
  email_address?: string
  connected_at?: string | null
  last_scanned_at?: string | null
  scan_status?: 'idle' | 'running' | 'done' | 'error'
  scan_error?: string | null
}

export interface DetectedSubscription {
  id: string
  merchant: string
  sender_domain: string
  category: Category
  cycle: BillingCycle
  amount: number
  currency: string
  previous_amount: number | null
  cancelled: boolean
  confidence: 'high' | 'medium'
  charge_count: number
  existing_subscription_id: string | null
  product_key: string
  current_amount: number | null                       // what you pay today, if tracked
  current_split_mode: 'full' | 'ratio' | 'fixed' | null
  current_name: string | null                         // name of the subscription it will update
  current_cycle: string | null
  // A tracked subscription that looks like the same service under a different
  // name (e.g. "Claude" vs "Anthropic"). Offered as a choice, never applied.
  similar_subscription_id: string | null
  similar_reason: string | null
  similar_name: string | null
  similar_amount: number | null
  similar_cycle: string | null   // set when this is a price change
  detected_at: string
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

export interface DuplicateBrief {
  id: string
  name: string
  amount: number
  currency: string
  cycle: string
}

export interface DuplicatePair {
  keep: DuplicateBrief
  merge: DuplicateBrief
  reason: string
}
