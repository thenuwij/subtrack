import type { SubscriptionInput } from '@/types'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

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
async function request(path: string, token: string, init: RequestInit = {}) {
  let res: Response
  try {
    res = await fetch(`${API_URL}${path}`, {
      ...init,
      headers: { ...(await getHeaders(token)), ...(init.headers ?? {}) },
    })
  } catch {
    // fetch only rejects for network-level failures: no server, DNS, or CORS.
    throw new Error(
      apiIsLocal() && typeof window !== 'undefined'
        && !/^(localhost|127\.0\.0\.1)/.test(window.location.hostname)
        ? `This site is pointed at ${API_URL}, which only exists on the developer's `
          + 'machine. The backend needs deploying and NEXT_PUBLIC_API_URL updating.'
        : `Could not reach the Subtrack server at ${API_URL}.`
    )
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
  return res.json()
}

// Subscriptions
export async function getSubscriptions(token: string) {
  const res = await fetch(`${API_URL}/subscriptions/`, {
    headers: await getHeaders(token),
  })
  if (!res.ok) throw new Error('Failed to fetch recurring payments')
  return res.json()
}

export async function createSubscription(token: string, data: SubscriptionInput) {
  const res = await fetch(`${API_URL}/subscriptions/`, {
    method: 'POST',
    headers: await getHeaders(token),
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error('Failed to create recurring payment')
  return res.json()
}

export async function deleteSubscription(token: string, id: string) {
  const res = await fetch(`${API_URL}/subscriptions/${id}`, {
    method: 'DELETE',
    headers: await getHeaders(token),
  })
  if (!res.ok) throw new Error('Failed to delete recurring payment')
  return res.json()
}

export async function getSubscriptionChanges(token: string, days: number = 30) {
  const res = await fetch(`${API_URL}/subscriptions/changes?days=${days}`, {
    headers: await getHeaders(token),
  })
  if (!res.ok) throw new Error('Failed to fetch payment changes')
  return res.json()
}

// Gmail
export async function getGmailStatus(token: string) {
  const res = await fetch(`${API_URL}/gmail/status`, {
    headers: await getHeaders(token),
  })
  if (!res.ok) throw new Error('Failed to fetch Gmail status')
  return res.json()
}

export async function getGmailConnectUrl(token: string) {
  return request('/gmail/connect', token)
}

export async function startGmailScan(token: string) {
  return request('/gmail/scan', token, { method: 'POST' })
}

export async function disconnectGmail(token: string) {
  const res = await fetch(`${API_URL}/gmail/disconnect`, {
    method: 'DELETE',
    headers: await getHeaders(token),
  })
  if (!res.ok) throw new Error('Failed to disconnect Gmail')
  return res.json()
}

// Detected subscriptions (review queue)
export async function getDetected(
  token: string,
  status: 'pending' | 'dismissed' = 'pending'
) {
  const res = await fetch(`${API_URL}/detected/?status=${status}`, {
    headers: await getHeaders(token),
  })
  if (!res.ok) throw new Error('Failed to fetch detected payments')
  return res.json()
}

export async function restoreDetected(token: string, id: string) {
  const res = await fetch(`${API_URL}/detected/${id}/restore`, {
    method: 'POST',
    headers: await getHeaders(token),
  })
  if (!res.ok) throw new Error('Failed to restore')
  return res.json()
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
  const res = await fetch(`${API_URL}/detected/${id}/approve`, {
    method: 'POST',
    headers: await getHeaders(token),
    body: JSON.stringify(overrides),
  })
  if (!res.ok) throw new Error('Failed to approve')
  return res.json()
}

export async function dismissDetected(token: string, id: string) {
  const res = await fetch(`${API_URL}/detected/${id}/dismiss`, {
    method: 'POST',
    headers: await getHeaders(token),
  })
  if (!res.ok) throw new Error('Failed to dismiss')
  return res.json()
}

export async function getDuplicates(token: string) {
  const res = await fetch(`${API_URL}/subscriptions/duplicates`, {
    headers: await getHeaders(token),
  })
  if (!res.ok) throw new Error('Failed to check for duplicate payments')
  return res.json()
}

export async function mergeSubscription(token: string, id: string, into: string) {
  const res = await fetch(`${API_URL}/subscriptions/${id}/merge`, {
    method: 'POST',
    headers: await getHeaders(token),
    body: JSON.stringify({ into }),
  })
  if (!res.ok) throw new Error('Failed to merge payments')
  return res.json()
}

// Rates
export async function getRates(token: string, base: string = 'AUD') {
  const res = await fetch(`${API_URL}/rates?base=${base}`, {
    headers: await getHeaders(token),
  })
  if (!res.ok) throw new Error('Failed to fetch exchange rates')
  return res.json()
}

// Preferences
export async function getPreferences(token: string) {
  const res = await fetch(`${API_URL}/preferences`, {
    headers: await getHeaders(token),
  })
  if (!res.ok) throw new Error('Failed to fetch preferences')
  return res.json()
}

// Send only the fields you want to change — omitted fields are left untouched.
export async function updatePreferences(
  token: string,
  data: { base_currency?: string; monthly_income?: number }
) {
  const res = await fetch(`${API_URL}/preferences`, {
    method: 'PATCH',
    headers: await getHeaders(token),
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error('Failed to update preferences')
  return res.json()
}

export async function updateSubscription(token: string, id: string, data: Partial<SubscriptionInput>) {
  const res = await fetch(`${API_URL}/subscriptions/${id}`, {
    method: 'PATCH',
    headers: await getHeaders(token),
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error('Failed to update recurring payment')
  return res.json()
}
