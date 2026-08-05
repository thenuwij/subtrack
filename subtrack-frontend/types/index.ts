/** Legacy compatibility value. New recurrence logic uses interval_unit/count. */
export type BillingCycle = 'weekly' | 'monthly' | 'yearly'
export type RecurrenceUnit = 'day' | 'week' | 'month' | 'year'
export type PaymentStatus = 'active' | 'paused' | 'cancelling' | 'cancelled' | 'ended'
export type AmountType = 'fixed' | 'variable'
export type SpendingType = 'unspecified' | 'essential' | 'optional'

export type Category =
  | 'housing'
  | 'insurance'
  | 'phone_internet'
  | 'streaming'
  | 'software'
  | 'cloud'
  | 'utilities'
  | 'fitness'
  | 'food'
  | 'transport'
  | 'education'
  | 'childcare'
  | 'debt'
  | 'memberships'
  | 'donations'
  | 'business'
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
  exchange_rate: number | null       // null when no honest conversion snapshot exists
  converted_amount: number | null  // null for legacy entries
  cycle: BillingCycle               // compatibility field; never use for new calculations
  interval_unit: RecurrenceUnit
  interval_count: number
  cadence_label: string
  monthly_equivalent: number        // native currency; calculated by the backend
  yearly_equivalent: number         // native currency; calculated by the backend
  next_due: string | null
  next_expected_at: string | null   // projected by the backend from the saved anchor
  next_expected_source: 'recorded' | 'projected_from_recorded_cycle' | 'missing' | 'ended' | 'inactive' | 'paused_without_resume'
  recurrence_end_at: string | null
  trial_ends_at: string | null       // post-trial price is stored in `amount`
  status: PaymentStatus
  paused_until: string | null
  cancellation_effective_at: string | null
  amount_type: AmountType
  spending_type: SpendingType
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
  cycle?: BillingCycle
  interval_unit?: RecurrenceUnit
  interval_count?: number
  next_due?: string | null
  recurrence_end_at?: string | null
  trial_ends_at?: string | null
  status?: PaymentStatus
  paused_until?: string | null
  cancellation_effective_at?: string | null
  amount_type?: AmountType
  spending_type?: SpendingType
  is_active?: boolean
  full_amount?: number | null
  share_ratio?: number
  share_amount?: number
}

export interface GmailStatus {
  connected: boolean
  configured?: boolean
  email_address?: string
  connected_at?: string | null
  last_scanned_at?: string | null
  scan_status?: 'idle' | 'running' | 'done' | 'error'
  scan_error?: string | null
  scan_stage?: 'queued' | 'reading' | 'analysing' | 'finalising' | 'complete' | null
  scan_processed?: number
  scan_total?: number
  scan_partial?: boolean
  scan_message?: string | null
}

export interface DetectedSubscription {
  id: string
  merchant: string
  sender_domain: string
  category: Category
  cycle: BillingCycle | null
  interval_unit: RecurrenceUnit | null
  interval_count: number | null
  cadence_label: string | null
  cadence_confidence: 'high' | 'medium' | 'unknown'
  cadence_evidence: string | null
  amount_type: AmountType
  amount: number
  currency: string
  previous_amount: number | null
  cancelled: boolean
  confidence: 'high' | 'medium'
  charge_count: number
  trial_ends_at: string | null
  next_due: string | null
  due_date_confidence: 'high' | 'medium' | 'unknown'
  due_date_evidence: string | null
  existing_subscription_id: string | null
  product_key: string
  current_amount: number | null                       // what you pay today, if tracked
  current_currency: string | null
  current_full_amount: number | null
  current_share_ratio: number | null
  current_split_mode: 'full' | 'ratio' | 'fixed' | null
  current_name: string | null                         // name of the subscription it will update
  current_cycle: string | null
  current_interval_unit: RecurrenceUnit | null
  current_interval_count: number | null
  current_cadence_label: string | null
  current_amount_type: AmountType | null
  current_next_due: string | null
  // A tracked subscription that looks like the same service under a different
  // name (e.g. "Claude" vs "Anthropic"). Offered as a choice, never applied.
  similar_subscription_id: string | null
  similar_reason: string | null
  similar_name: string | null
  similar_amount: number | null
  similar_currency: string | null
  similar_full_amount: number | null
  similar_share_ratio: number | null
  similar_split_mode: 'full' | 'ratio' | 'fixed' | null
  similar_cycle: string | null   // set when this is a price change
  similar_interval_unit: RecurrenceUnit | null
  similar_interval_count: number | null
  similar_cadence_label: string | null
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
  stale: boolean
  provider_date: string | null
}

export interface Preferences {
  base_currency: Currency
  monthly_income: number | null  // null until the user states it
  timezone: string
  income_converted?: boolean
  income_conversion_rate_as_of?: string | null
}

export type ReminderKind = 'cancel' | 'renewal' | 'trial_end'
export type ReminderStatus = 'due' | 'upcoming' | 'overdue' | 'dismissed' | 'needs_date'

export interface PaymentReminder {
  id: string
  subscription_id: string
  subscription_name: string
  kind: ReminderKind
  days_before: number
  target_at: string | null
  alert_at: string | null
  date_source: 'fixed_date' | 'recorded' | 'projected_from_recorded_cycle' | 'missing'
  status: ReminderStatus
  days_until_target: number | null
  days_until_alert: number | null
  note: string | null
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface ReminderInput {
  subscription_id: string
  kind: ReminderKind
  days_before: number
  target_date?: string | null
  note?: string | null
}

export interface DuplicateBrief {
  id: string
  name: string
  amount: number
  currency: string
  cycle: BillingCycle
  interval_unit: RecurrenceUnit
  interval_count: number
  cadence_label: string
}

export interface DuplicatePair {
  keep: DuplicateBrief
  merge: DuplicateBrief
  reason: string
}

/** Optional deployment capabilities. A failed fetch must fall back safely. */
export interface ApiCapabilities {
  flexible_recurrence: boolean
  payment_lifecycle: boolean
  variable_amounts: boolean
  server_equivalents: boolean
  gmail_secure_oauth: boolean
}

export interface ForecastCharge {
  id: string
  name: string
  category: Category
  due_at: string
  amount: number
  currency: string
  base_currency: string
  charge_amount_in_base: number | null
  charge_amount_is_estimate: boolean
  charge_kind: 'renewal' | 'trial_conversion'
  days_until_due: number
  due_date_source: 'recorded' | 'projected_from_recorded_cycle'
}

export interface SubscriptionForecast {
  scope: string
  forecast_semantics: string
  window_start: string
  window_end: string
  window_days: number
  charges: ForecastCharge[]
  occurrence_count: number
  forecast_total_in_base: number
  missing_due_date_count: number
  unconverted_occurrence_count: number
  paused_without_resume_count: number
  currency_conversion: {
    base_currency: string
    status: 'exact' | 'current_rates' | 'estimated' | 'incomplete'
    rates_as_of: string | null
    rates_stale: boolean
    warning: string | null
  }
}
