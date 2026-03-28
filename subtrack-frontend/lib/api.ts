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

// Expenses
export async function getExpenses(token: string) {
  const res = await fetch(`${API_URL}/expenses/`, {
    headers: await getHeaders(token),
  })
  if (!res.ok) throw new Error('Failed to fetch expenses')
  return res.json()
}

export async function createExpense(token: string, data: any) {
  const res = await fetch(`${API_URL}/expenses/`, {
    method: 'POST',
    headers: await getHeaders(token),
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error('Failed to create expense')
  return res.json()
}

export async function deleteExpense(token: string, id: string) {
  const res = await fetch(`${API_URL}/expenses/${id}`, {
    method: 'DELETE',
    headers: await getHeaders(token),
  })
  if (!res.ok) throw new Error('Failed to delete expense')
  return res.json()
}

// Budgets
export async function getBudgets(token: string) {
  const res = await fetch(`${API_URL}/budgets/`, {
    headers: await getHeaders(token),
  })
  if (!res.ok) throw new Error('Failed to fetch budgets')
  return res.json()
}

export async function createBudget(token: string, data: any) {
  const res = await fetch(`${API_URL}/budgets/`, {
    method: 'POST',
    headers: await getHeaders(token),
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error('Failed to create budget')
  return res.json()
}

export async function deleteBudget(token: string, id: string) {
  const res = await fetch(`${API_URL}/budgets/${id}`, {
    method: 'DELETE',
    headers: await getHeaders(token),
  })
  if (!res.ok) throw new Error('Failed to delete budget')
  return res.json()
}