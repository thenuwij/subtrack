import type { SavingsGoalInput, SubscriptionInput } from '@/types'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

async function getHeaders(token: string) {
  return {
    'Content-Type': 'application/json',
    Authorization: `Bearer ${token}`,
  }
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
  const res = await fetch(`${API_URL}/gmail/connect`, {
    headers: await getHeaders(token),
  })
  if (!res.ok) throw new Error('Failed to start Gmail connection')
  return res.json()
}

export async function startGmailScan(token: string) {
  const res = await fetch(`${API_URL}/gmail/scan`, {
    method: 'POST',
    headers: await getHeaders(token),
  })
  if (!res.ok) throw new Error('Failed to start scan')
  return res.json()
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

// Savings Goals
export async function getSavingsGoals(token: string) {
  const res = await fetch(`${API_URL}/savings/`, {
    headers: await getHeaders(token),
  })
  if (!res.ok) throw new Error('Failed to fetch savings goals')
  return res.json()
}

export async function createSavingsGoal(token: string, data: SavingsGoalInput) {
  const res = await fetch(`${API_URL}/savings/`, {
    method: 'POST',
    headers: await getHeaders(token),
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error('Failed to create savings goal')
  return res.json()
}

export async function updateSavingsGoal(token: string, id: string, data: Partial<SavingsGoalInput>) {
  const res = await fetch(`${API_URL}/savings/${id}`, {
    method: 'PATCH',
    headers: await getHeaders(token),
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error('Failed to update savings goal')
  return res.json()
}

export async function deleteSavingsGoal(token: string, id: string) {
  const res = await fetch(`${API_URL}/savings/${id}`, {
    method: 'DELETE',
    headers: await getHeaders(token),
  })
  if (!res.ok) throw new Error('Failed to delete savings goal')
  return res.json()
}
