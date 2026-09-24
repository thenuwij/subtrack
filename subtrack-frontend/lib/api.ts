import type {
  ApiCapabilities,
  AmountType,
  BillingCycle,
  DetectedSubscription,
  DuplicatePair,
  PaymentStatus,
  Preferences,
  RecurrenceUnit,
  Rates,
  ReminderInput,
  Subscription,
  SubscriptionForecast,
  SubscriptionInput,
} from '@/types'
import {
  formatCadence,
  legacyCadence,
  legacyMonthlyEquivalent,
} from '@/lib/utils/recurrence'
import { createClient } from '@/lib/supabase/client'
import { endDemo } from '@/lib/auth/session'
import { API_URL } from '@/lib/config'

const REQUEST_TIMEOUT_MS = 15_000
let sessionExpiryHandled = false

export class SessionExpiredError extends Error {
  constructor() {
    super('Your session expired. Redirecting you to sign in again.')
    this.name = 'SessionExpiredError'
  }
}

export async function handleExpiredSession() {
  if (sessionExpiryHandled || typeof window === 'undefined') return
  sessionExpiryHandled = true
  endDemo()
  try {
    // Local scope clears this browser's stale credentials without revoking
    // every other device the user may still be signed in on.
    await createClient().auth.signOut({ scope: 'local' })
  } catch {
    // Redirect even if local cleanup fails; the login flow will replace the
    // unusable credentials and the proxy will protect private routes.
  } finally {
    window.location.replace('/login?reason=session_expired')
  }
}

let refreshInFlight: Promise<string | null> | null = null

/**
 * Trade the current refresh token for a fresh access token, or null if the
 * session is genuinely over.
 *
 * Deduplicated because the dashboard fires seven requests at once: when the
 * access token has expired they all fail together, and Supabase refresh tokens
 * are single-use. Racing refreshes would leave the losers holding a spent
 * token and signing the user out even though the refresh had just succeeded.
 */
function refreshAccessToken(): Promise<string | null> {
  if (!refreshInFlight) {
    refreshInFlight = createClient().auth.refreshSession()
      .then(({ data, error }) => (error ? null : data.session?.access_token ?? null))
      .catch(() => null)
      .finally(() => { refreshInFlight = null })
  }
  return refreshInFlight
}

async function getHeaders(token: string) {
  return {
    'Content-Type': 'application/json',
    Authorization: `Bearer ${token}`,
  }
}

/** True when the app is deployed but still pointed at a local backend. */
function apiIsLocal() {
  return /^https?:\/\/(localhost|127\.0\.0\.1)/.test(API_URL)
}

function readableDetail(detail: unknown): string | null {
  if (typeof detail === 'string' && detail) return detail
  if (!Array.isArray(detail)) return null
  const messages = detail
    .map(item => item && typeof item === 'object' && 'msg' in item
      ? String((item as { msg: unknown }).msg) : '')
    .filter(Boolean)
    .slice(0, 3)
  return messages.length ? messages.join(' ') : null
}

/**
 * Fetch that explains itself when it fails.
 *
 * A bare `fetch` rejects identically whether the server is unreachable, the
 * request was blocked by CORS, or the backend returned a real error — so every
 * one of those surfaced to users as the same unhelpful "please try again".
 */
async function request(
  path: string,
  token: string,
  init: RequestInit = {},
  timeoutMs: number = REQUEST_TIMEOUT_MS,
  allowRefresh: boolean = true,
) {
  let res: Response
  let timedOut = false
  const controller = new AbortController()
  const forwardAbort = () => controller.abort(init.signal?.reason)
  init.signal?.addEventListener('abort', forwardAbort, { once: true })
  const timeout = window.setTimeout(() => {
    timedOut = true
    controller.abort()
  }, timeoutMs)
  try {
    res = await fetch(`${API_URL}${path}`, {
      ...init,
      signal: controller.signal,
      headers: { ...(await getHeaders(token)), ...(init.headers ?? {}) },
    })
  } catch {
    if (timedOut) {
      throw new Error('The Subtrack server took too long to respond. Try again in a moment.')
    }
    // fetch only rejects for network-level failures: no server, DNS, or CORS.
    throw new Error(
      apiIsLocal() && typeof window !== 'undefined'
        && !/^(localhost|127\.0\.0\.1)/.test(window.location.hostname)
        ? `This site is pointed at ${API_URL}, which only exists on the developer's `
          + 'machine. The backend needs deploying and NEXT_PUBLIC_API_URL updating.'
        : `Could not reach the Subtrack server at ${API_URL}.`
    )
  } finally {
    window.clearTimeout(timeout)
    init.signal?.removeEventListener('abort', forwardAbort)
  }

  if (!res.ok) {
    if (res.status === 401) {
      // A 401 is not proof the session is over. An access token lasts an hour
      // and can expire between being read and being received, and the backend
      // rejects a token it cannot verify for transient reasons too. Signing the
      // user out on the first one turned every recoverable blip into a logout,
      // so refresh and replay once before giving up.
      if (allowRefresh) {
        const refreshed = await refreshAccessToken()
        if (refreshed && refreshed !== token) {
          return request(path, refreshed, init, timeoutMs, false)
        }
      }
      await handleExpiredSession()
      throw new SessionExpiredError()
    }
    // FastAPI puts the useful part in `detail`.
    const detail = await res.json().then(b => b?.detail).catch(() => null)
    const message = readableDetail(detail)
    throw new Error(
      message
        ? message
        : `Server returned ${res.status} for ${path}.`
    )
  }
  if (res.status === 204) return null
  return res.json()
}

const PAYMENT_STATUSES = new Set<PaymentStatus>([
  'active', 'paused', 'cancelling', 'cancelled', 'ended',
])
const RECURRENCE_UNITS = new Set<RecurrenceUnit>(['day', 'week', 'month', 'year'])
const BILLING_CYCLES = new Set<BillingCycle>(['weekly', 'monthly', 'yearly'])

/** Keep legacy API responses usable during the rolling backend deployment. */
function normalizeSubscription(value: Record<string, unknown>): Subscription {
  const cycle = (value.cycle === 'weekly' || value.cycle === 'yearly'
    ? value.cycle
    : 'monthly') as BillingCycle
  const fallbackCadence = legacyCadence(cycle)
  const intervalUnit = RECURRENCE_UNITS.has(value.interval_unit as RecurrenceUnit)
    ? value.interval_unit as RecurrenceUnit
    : fallbackCadence.interval_unit
  const rawCount = Number(value.interval_count)
  const intervalCount = Number.isInteger(rawCount) && rawCount > 0
    ? rawCount
    : fallbackCadence.interval_count
  const amount = Number(value.amount) || 0
  const monthly = typeof value.monthly_equivalent === 'number'
    ? value.monthly_equivalent : Number.NaN
  const yearly = typeof value.yearly_equivalent === 'number'
    ? value.yearly_equivalent : Number.NaN
  const isActive = value.is_active !== false
  const rawStatus = value.status as PaymentStatus
  const status = PAYMENT_STATUSES.has(rawStatus)
    ? rawStatus
    : isActive ? 'active' : 'cancelled'

  return {
    ...(value as unknown as Subscription),
    cycle,
    interval_unit: intervalUnit,
    interval_count: intervalCount,
    cadence_label: typeof value.cadence_label === 'string' && value.cadence_label
      ? value.cadence_label
      : formatCadence(intervalUnit, intervalCount),
    monthly_equivalent: Number.isFinite(monthly)
      ? monthly
      : legacyMonthlyEquivalent(amount, cycle),
    yearly_equivalent: Number.isFinite(yearly)
      ? yearly
      : legacyMonthlyEquivalent(amount, cycle) * 12,
    next_expected_at: typeof value.next_expected_at === 'string'
      ? value.next_expected_at
      : (status === 'active' || status === 'cancelling')
        && typeof value.next_due === 'string'
        ? value.next_due
        : null,
    next_expected_source: typeof value.next_expected_source === 'string'
      ? value.next_expected_source as Subscription['next_expected_source']
      : typeof value.next_due === 'string' ? 'recorded' : 'missing',
    recurrence_end_at: typeof value.recurrence_end_at === 'string'
      ? value.recurrence_end_at : null,
    paused_until: typeof value.paused_until === 'string' ? value.paused_until : null,
    cancellation_effective_at: typeof value.cancellation_effective_at === 'string'
      ? value.cancellation_effective_at : null,
    status,
    amount_type: value.amount_type === 'variable' ? 'variable' : 'fixed',
    spending_type: value.spending_type === 'essential' || value.spending_type === 'optional'
      ? value.spending_type : 'unspecified',
    is_active: status !== 'cancelled' && status !== 'ended',
  }
}

function normalizedCadence(
  value: Record<string, unknown>,
  prefix: '' | 'current_' | 'similar_' = '',
) {
  const cycleValue = value[`${prefix}cycle`]
  const cycle = BILLING_CYCLES.has(cycleValue as BillingCycle)
    ? cycleValue as BillingCycle : null
  const fallback = cycle ? legacyCadence(cycle) : null
  const unitValue = value[`${prefix}interval_unit`]
  const unit = RECURRENCE_UNITS.has(unitValue as RecurrenceUnit)
    ? unitValue as RecurrenceUnit : fallback?.interval_unit ?? null
  const countValue = Number(value[`${prefix}interval_count`])
  const count = Number.isInteger(countValue) && countValue > 0
    ? countValue : fallback?.interval_count ?? null
  return {
    cycle,
    unit,
    count,
    label: typeof value[`${prefix}cadence_label`] === 'string'
      ? value[`${prefix}cadence_label`] as string
      : unit && count ? formatCadence(unit, count) : null,
  }
}

/** Adapt the previous three-cycle detection response during rolling deploys. */
function normalizeDetected(value: Record<string, unknown>): DetectedSubscription {
  const detected = normalizedCadence(value)
  const current = normalizedCadence(value, 'current_')
  const similar = normalizedCadence(value, 'similar_')
  const rawConfidence = value.cadence_confidence
  const cadenceConfidence = rawConfidence === 'high' || rawConfidence === 'medium'
    || rawConfidence === 'unknown'
    ? rawConfidence
    : detected.unit && detected.count ? 'medium' : 'unknown'
  const dueConfidence = value.due_date_confidence

  return {
    ...(value as unknown as DetectedSubscription),
    cycle: cadenceConfidence === 'unknown' ? null : detected.cycle,
    interval_unit: cadenceConfidence === 'unknown' ? null : detected.unit,
    interval_count: cadenceConfidence === 'unknown' ? null : detected.count,
    cadence_label: cadenceConfidence === 'unknown' ? null : detected.label,
    cadence_confidence: cadenceConfidence,
    cadence_evidence: typeof value.cadence_evidence === 'string'
      ? value.cadence_evidence : null,
    amount_type: value.amount_type === 'variable' ? 'variable' : 'fixed',
    next_due: typeof value.next_due === 'string' ? value.next_due : null,
    due_date_confidence: dueConfidence === 'high' || dueConfidence === 'medium'
      || dueConfidence === 'unknown' ? dueConfidence : 'unknown',
    due_date_evidence: typeof value.due_date_evidence === 'string'
      ? value.due_date_evidence : null,
    current_interval_unit: current.unit,
    current_interval_count: current.count,
    current_cadence_label: current.label,
    current_amount_type: value.current_amount_type === 'variable' ? 'variable'
      : value.current_amount_type === 'fixed' ? 'fixed' : null,
    current_currency: typeof value.current_currency === 'string'
      ? value.current_currency : null,
    current_full_amount: typeof value.current_full_amount === 'number'
      ? value.current_full_amount : null,
    current_share_ratio: typeof value.current_share_ratio === 'number'
      ? value.current_share_ratio : null,
    current_split_mode: value.current_split_mode === 'ratio'
      || value.current_split_mode === 'fixed' || value.current_split_mode === 'full'
      ? value.current_split_mode : null,
    current_next_due: typeof value.current_next_due === 'string'
      ? value.current_next_due : null,
    similar_interval_unit: similar.unit,
    similar_interval_count: similar.count,
    similar_cadence_label: similar.label,
    similar_currency: typeof value.similar_currency === 'string'
      ? value.similar_currency : null,
    similar_full_amount: typeof value.similar_full_amount === 'number'
      ? value.similar_full_amount : null,
    similar_share_ratio: typeof value.similar_share_ratio === 'number'
      ? value.similar_share_ratio : null,
    similar_split_mode: value.similar_split_mode === 'ratio'
      || value.similar_split_mode === 'fixed' || value.similar_split_mode === 'full'
      ? value.similar_split_mode : null,
  }
}

// Subscriptions
export async function getSubscriptions(
  token: string,
  options: { includeInactive?: boolean } = {},
): Promise<Subscription[]> {
  const query = options.includeInactive ? '?include_inactive=true' : ''
  const rows = await request(`/subscriptions/${query}`, token)
  return Array.isArray(rows)
    ? rows.map(row => normalizeSubscription(row as Record<string, unknown>))
    : []
}

export async function createSubscription(token: string, data: SubscriptionInput): Promise<Subscription> {
  const row = await request('/subscriptions/', token, {
    method: 'POST',
    body: JSON.stringify(data),
  })
  return normalizeSubscription(row as Record<string, unknown>)
}

export async function deleteSubscription(token: string, id: string) {
  return request(`/subscriptions/${id}`, token, { method: 'DELETE' })
}

export async function getSubscriptionChanges(token: string, days: number = 30) {
  return request(`/subscriptions/changes?days=${days}`, token)
}

export async function getSubscriptionForecast(
  token: string,
  days: number = 30,
): Promise<SubscriptionForecast> {
  return request(`/subscriptions/forecast?days=${days}`, token)
}

export async function getSubscriptionEquivalents(
  token: string,
  data: { amount: number; interval_unit: RecurrenceUnit; interval_count: number },
): Promise<{
  cadence_label: string
  monthly_equivalent: number
  yearly_equivalent: number
  normalization_convention: string
}> {
  return request('/subscriptions/equivalents', token, {
    method: 'POST',
    body: JSON.stringify(data),
  })
}

function capabilityFlag(payload: Record<string, unknown>, ...names: string[]) {
  const capabilityObject = payload.capabilities && typeof payload.capabilities === 'object'
    ? payload.capabilities as Record<string, unknown>
    : {}
  const featureObject = payload.features && typeof payload.features === 'object'
    ? payload.features as Record<string, unknown>
    : {}
  const featureList = Array.isArray(payload.features) ? new Set(payload.features) : null
  return names.some(name => payload[name] === true
    || capabilityObject[name] === true
    || featureObject[name] === true
    || featureList?.has(name))
}

let capabilitiesCache: ApiCapabilities | null = null

export async function getCapabilities(token: string): Promise<ApiCapabilities> {
  if (capabilitiesCache) return capabilitiesCache
  const payload = await request('/meta/capabilities', token, {}, 5_000) as Record<string, unknown>
  capabilitiesCache = {
    flexible_recurrence: capabilityFlag(
      payload, 'flexible_recurrence', 'flexible_cadence', 'flexible_cadence_v1',
      'recurrence_intervals'
    ),
    payment_lifecycle: capabilityFlag(
      payload, 'payment_lifecycle', 'lifecycle_status', 'lifecycle_v1'
    ),
    variable_amounts: capabilityFlag(
      payload, 'variable_amounts', 'variable_bills', 'variable_amounts_v1'
    ),
    server_equivalents: capabilityFlag(
      payload, 'server_equivalents', 'normalized_equivalents', 'server_equivalents_v1',
      'flexible_cadence_v1'
    ),
    gmail_secure_oauth: capabilityFlag(
      payload, 'gmail_secure_oauth', 'gmail_secure_oauth_v1'
    ),
  }
  return capabilitiesCache
}

// Gmail
export async function getGmailStatus(token: string) {
  return request('/gmail/status', token)
}

export async function getGmailConnectUrl(token: string) {
  return request('/gmail/connect', token)
}

export async function completeGmailOAuth(
  token: string,
  payload: { code: string; state: string },
) {
  return request('/gmail/oauth/complete', token, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function startGmailScan(token: string) {
  return request('/gmail/scan', token, { method: 'POST' })
}

export async function disconnectGmail(token: string): Promise<{
  message: string
  gmail_revocation: 'revoked' | 'failed' | 'not_connected'
}> {
  return request('/gmail/disconnect', token, { method: 'DELETE' })
}

// Account privacy
export async function downloadAccountExport(token: string): Promise<{
  blob: Blob
  filename: string
}> {
  const controller = new AbortController()
  const timeout = window.setTimeout(() => controller.abort(), 120_000)
  let res: Response
  try {
    res = await fetch(`${API_URL}/account/export`, {
      signal: controller.signal,
      headers: { Authorization: `Bearer ${token}` },
    })
    if (res.status === 401) {
      await handleExpiredSession()
      throw new SessionExpiredError()
    }
    if (!res.ok) {
      const detail = await res.json().then(body => body?.detail).catch(() => null)
      const message = readableDetail(detail)
      throw new Error(
        message
          ? message
          : `Server returned ${res.status} while preparing your export.`,
      )
    }
    const blob = await res.blob()
    const disposition = res.headers.get('content-disposition') ?? ''
    const filename = disposition.match(/filename="?([^";]+)"?/i)?.[1]
      ?? `subtrack-data-${new Date().toISOString().slice(0, 10)}.json`
    return { blob, filename }
  } catch (error) {
    if (error instanceof SessionExpiredError) throw error
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new Error('Your export took too long to prepare. Please try again.')
    }
    if (error instanceof Error && !error.message.includes('Failed to fetch')) {
      throw error
    }
    throw new Error(`Could not reach the Subtrack server at ${API_URL}.`)
  } finally {
    window.clearTimeout(timeout)
  }
}

export async function deleteAccountData(
  token: string,
  confirmation: 'DELETE MY SUBTRACK DATA',
): Promise<{
  deleted: boolean
  scope: string
  gmail_revocation: 'revoked' | 'failed' | 'not_connected'
  supabase_auth_identity_deleted: boolean
  message: string
}> {
  return request('/account/data', token, {
    method: 'DELETE',
    body: JSON.stringify({ confirmation }),
  }, 30_000)
}

// Detected subscriptions (review queue)
export async function getDetected(
  token: string,
  status: 'pending' | 'dismissed' = 'pending'
): Promise<DetectedSubscription[]> {
  const rows = await request(`/detected/?status=${status}`, token)
  return Array.isArray(rows)
    ? rows.map(row => normalizeDetected(row as Record<string, unknown>))
    : []
}

export async function restoreDetected(token: string, id: string) {
  return request(`/detected/${id}/restore`, token, { method: 'POST' })
}

export async function approveDetected(
  token: string,
  id: string,
  overrides: {
    name?: string
    category?: string
    amount?: number
    cycle?: string
    interval_unit?: RecurrenceUnit
    interval_count?: number
    trial_ends_at?: string | null
    next_due?: string | null
    amount_type?: AmountType
    share_ratio?: number
    share_amount?: number
    replace_subscription_id?: string
  } = {}
) {
  return request(`/detected/${id}/approve`, token, {
    method: 'POST',
    body: JSON.stringify(overrides),
  })
}

export async function dismissDetected(token: string, id: string) {
  return request(`/detected/${id}/dismiss`, token, { method: 'POST' })
}

export async function getDuplicates(token: string): Promise<DuplicatePair[]> {
  // This route performs a bounded model comparison rather than a normal DB
  // read, so give it room beyond the standard REST timeout.
  return request('/subscriptions/duplicates', token, {}, 50_000)
}

export async function dismissDuplicateSuggestion(
  token: string,
  subscriptionId: string,
  possibleDuplicateId: string,
) {
  return request('/subscriptions/duplicates/dismiss', token, {
    method: 'POST',
    body: JSON.stringify({
      subscription_id: subscriptionId,
      possible_duplicate_id: possibleDuplicateId,
    }),
  })
}

export async function mergeSubscription(token: string, id: string, into: string) {
  return request(`/subscriptions/${id}/merge`, token, {
    method: 'POST',
    body: JSON.stringify({ into }),
  })
}

// Rates
export async function getRates(token: string, base: string = 'AUD'): Promise<Rates> {
  return request(`/rates?base=${encodeURIComponent(base)}`, token)
}

// Preferences
export async function getPreferences(token: string) {
  return request('/preferences', token) as Promise<Preferences>
}

// Send only the fields you want to change — omitted fields are left untouched.
export async function updatePreferences(
  token: string,
  data: { base_currency?: string; monthly_income?: number | null; onboarding_completed?: boolean }
): Promise<Preferences> {
  return request('/preferences', token, {
    method: 'PATCH',
    body: JSON.stringify(data),
  })
}

export async function updateSubscription(
  token: string,
  id: string,
  data: Partial<SubscriptionInput>,
): Promise<Subscription> {
  const row = await request(`/subscriptions/${id}`, token, {
    method: 'PATCH',
    body: JSON.stringify(data),
  })
  return normalizeSubscription(row as Record<string, unknown>)
}

// In-app reminders
export async function getReminders(
  token: string,
  options: {
    subscriptionId?: string
    includeInactive?: boolean
    includeDismissed?: boolean
    horizonDays?: number
  } = {}
) {
  const query = new URLSearchParams()
  if (options.subscriptionId) query.set('subscription_id', options.subscriptionId)
  if (options.includeInactive) query.set('include_inactive', 'true')
  if (options.includeDismissed) query.set('include_dismissed', 'true')
  if (options.horizonDays) query.set('horizon_days', String(options.horizonDays))
  const suffix = query.size ? `?${query.toString()}` : ''
  return request(`/reminders${suffix}`, token)
}

export function createReminder(token: string, data: ReminderInput) {
  return request('/reminders', token, {
    method: 'POST',
    body: JSON.stringify(data),
  })
}

export function updateReminder(
  token: string,
  id: string,
  data: Partial<Omit<ReminderInput, 'subscription_id'>> & { is_active?: boolean }
) {
  return request(`/reminders/${id}`, token, {
    method: 'PATCH',
    body: JSON.stringify(data),
  })
}

export function deleteReminder(token: string, id: string) {
  return request(`/reminders/${id}`, token, { method: 'DELETE' })
}

export function dismissReminder(token: string, id: string) {
  return request(`/reminders/${id}/dismiss`, token, { method: 'POST' })
}

export function restoreReminder(token: string, id: string) {
  return request(`/reminders/${id}/restore`, token, { method: 'POST' })
}
