import type { ReminderInput, SubscriptionInput } from '@/types'

if (process.env.NODE_ENV === 'production' && !process.env.NEXT_PUBLIC_API_URL) {
  throw new Error('NEXT_PUBLIC_API_URL must be configured for production builds.')
}
const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000'
const REQUEST_TIMEOUT_MS = 15_000

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
    // FastAPI puts the useful part in `detail`.
    const detail = await res.json().then(b => b?.detail).catch(() => null)
    throw new Error(
      typeof detail === 'string' && detail
        ? detail
        : `Server returned ${res.status} for ${path}.`
    )
  }
  if (res.status === 204) return null
  return res.json()
}

// Subscriptions
export async function getSubscriptions(token: string) {
  return request('/subscriptions/', token)
}

export async function createSubscription(token: string, data: SubscriptionInput) {
  return request('/subscriptions/', token, {
    method: 'POST',
    body: JSON.stringify(data),
  })
}

export async function deleteSubscription(token: string, id: string) {
  return request(`/subscriptions/${id}`, token, { method: 'DELETE' })
}

export async function getSubscriptionChanges(token: string, days: number = 30) {
  return request(`/subscriptions/changes?days=${days}`, token)
}

// Gmail
export async function getGmailStatus(token: string) {
  return request('/gmail/status', token)
}

export async function getGmailConnectUrl(token: string) {
  return request('/gmail/connect', token)
}

export async function startGmailScan(token: string) {
  return request('/gmail/scan', token, { method: 'POST' })
}

export async function disconnectGmail(token: string) {
  return request('/gmail/disconnect', token, { method: 'DELETE' })
}

// Detected subscriptions (review queue)
export async function getDetected(
  token: string,
  status: 'pending' | 'dismissed' = 'pending'
) {
  return request(`/detected/?status=${status}`, token)
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

export async function getDuplicates(token: string) {
  // This route performs a bounded model comparison rather than a normal DB
  // read, so give it room beyond the standard REST timeout.
  return request('/subscriptions/duplicates', token, {}, 50_000)
}

export async function mergeSubscription(token: string, id: string, into: string) {
  return request(`/subscriptions/${id}/merge`, token, {
    method: 'POST',
    body: JSON.stringify({ into }),
  })
}

// Rates
export async function getRates(token: string, base: string = 'AUD') {
  return request(`/rates?base=${encodeURIComponent(base)}`, token)
}

// Preferences
export async function getPreferences(token: string) {
  return request('/preferences', token)
}

// Send only the fields you want to change — omitted fields are left untouched.
export async function updatePreferences(
  token: string,
  data: { base_currency?: string; monthly_income?: number }
) {
  return request('/preferences', token, {
    method: 'PATCH',
    body: JSON.stringify(data),
  })
}

export async function updateSubscription(token: string, id: string, data: Partial<SubscriptionInput>) {
  return request(`/subscriptions/${id}`, token, {
    method: 'PATCH',
    body: JSON.stringify(data),
  })
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
