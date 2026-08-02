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
  if (!res.ok) throw new Error('Failed to fetch subscriptions')
  return res.json()
}

export async function createSubscription(token: string, data: any) {
  const res = await fetch(`${API_URL}/subscriptions/`, {
    method: 'POST',
    headers: await getHeaders(token),
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error('Failed to create subscription')
  return res.json()
}

export async function deleteSubscription(token: string, id: string) {
  const res = await fetch(`${API_URL}/subscriptions/${id}`, {
    method: 'DELETE',
    headers: await getHeaders(token),
  })
  if (!res.ok) throw new Error('Failed to delete subscription')
  return res.json()
}

export async function getSubscriptionChanges(token: string, days: number = 30) {
  const res = await fetch(`${API_URL}/subscriptions/changes?days=${days}`, {
    headers: await getHeaders(token),
  })
  if (!res.ok) throw new Error('Failed to fetch subscription changes')
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

export async function updateSubscription(token: string, id: string, data: any) {
  const res = await fetch(`${API_URL}/subscriptions/${id}`, {
    method: 'PATCH',
    headers: await getHeaders(token),
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error('Failed to update subscription')
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

export async function createSavingsGoal(token: string, data: any) {
  const res = await fetch(`${API_URL}/savings/`, {
    method: 'POST',
    headers: await getHeaders(token),
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error('Failed to create savings goal')
  return res.json()
}

export async function updateSavingsGoal(token: string, id: string, data: any) {
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