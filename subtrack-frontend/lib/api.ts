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

export async function updatePreferences(token: string, base_currency: string) {
  const res = await fetch(`${API_URL}/preferences`, {
    method: 'PATCH',
    headers: await getHeaders(token),
    body: JSON.stringify({ base_currency }),
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

export async function updateExpense(token: string, id: string, data: any) {
  const res = await fetch(`${API_URL}/expenses/${id}`, {
    method: 'PATCH',
    headers: await getHeaders(token),
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error('Failed to update expense')
  return res.json()
}

// Income
export async function getIncome(token: string) {
  const res = await fetch(`${API_URL}/income/`, {
    headers: await getHeaders(token),
  })
  if (!res.ok) throw new Error('Failed to fetch income')
  return res.json()
}

export async function createIncome(token: string, data: any) {
  const res = await fetch(`${API_URL}/income/`, {
    method: 'POST',
    headers: await getHeaders(token),
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error('Failed to create income')
  return res.json()
}

export async function updateIncome(token: string, id: string, data: any) {
  const res = await fetch(`${API_URL}/income/${id}`, {
    method: 'PATCH',
    headers: await getHeaders(token),
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error('Failed to update income')
  return res.json()
}

export async function deleteIncome(token: string, id: string) {
  const res = await fetch(`${API_URL}/income/${id}`, {
    method: 'DELETE',
    headers: await getHeaders(token),
  })
  if (!res.ok) throw new Error('Failed to delete income')
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