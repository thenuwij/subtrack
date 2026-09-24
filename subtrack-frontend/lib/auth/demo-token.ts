export const DEMO_COOKIE = 'subtrack_demo'

function tokenExpiry(token: string): number | null {
  try {
    const payload = JSON.parse(atob(token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')))
    return typeof payload.exp === 'number' ? payload.exp * 1000 : null
  } catch {
    return null
  }
}

export function isUsableDemoToken(token: string | undefined | null): token is string {
  if (!token) return false
  const expiry = tokenExpiry(token)
  return expiry !== null && expiry > Date.now()
}
