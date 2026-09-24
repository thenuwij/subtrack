import { createClient } from '@/lib/supabase/client'

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

export function readDemoToken(): string | null {
  if (typeof document === 'undefined') return null
  const match = document.cookie
    .split('; ')
    .find(part => part.startsWith(`${DEMO_COOKIE}=`))
  const token = match ? decodeURIComponent(match.slice(DEMO_COOKIE.length + 1)) : null
  return isUsableDemoToken(token) ? token : null
}

export function isDemoSession(): boolean {
  return readDemoToken() !== null
}

export async function getAccessToken(): Promise<string | null> {
  const demoToken = readDemoToken()
  if (demoToken) return demoToken
  const { data: { session } } = await createClient().auth.getSession()
  return session?.access_token ?? null
}
