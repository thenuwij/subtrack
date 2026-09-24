import { useSyncExternalStore } from 'react'
import { API_URL } from '@/lib/config'
import { createClient } from '@/lib/supabase/client'
import { DEMO_COOKIE, isUsableDemoToken } from '@/lib/auth/demo-token'

const DEMO_CHANGE_EVENT = 'subtrack:demo-change'

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

export async function startDemo(): Promise<void> {
  let response: Response
  try {
    response = await fetch(`${API_URL}/demo/session`, { method: 'POST' })
  } catch {
    throw new Error('Could not reach Subtrack. Please try again.')
  }
  const body = await response.json().catch(() => null)
  if (!response.ok) {
    throw new Error(
      typeof body?.detail === 'string' ? body.detail : 'The demo could not be started.',
    )
  }
  const expiresAt = Date.parse(body.expires_at)
  const maxAge = Math.max(60, Math.floor((expiresAt - Date.now()) / 1000))
  const secure = window.location.protocol === 'https:' ? '; Secure' : ''
  document.cookie = `${DEMO_COOKIE}=${encodeURIComponent(body.access_token)}; Path=/; Max-Age=${maxAge}; SameSite=Lax${secure}`
  window.dispatchEvent(new Event(DEMO_CHANGE_EVENT))
}

export function endDemo(): void {
  if (typeof document === 'undefined') return
  document.cookie = `${DEMO_COOKIE}=; Path=/; Max-Age=0; SameSite=Lax`
  window.dispatchEvent(new Event(DEMO_CHANGE_EVENT))
}

function subscribe(callback: () => void) {
  window.addEventListener(DEMO_CHANGE_EVENT, callback)
  return () => window.removeEventListener(DEMO_CHANGE_EVENT, callback)
}

export function useIsDemo(): boolean {
  return useSyncExternalStore(subscribe, isDemoSession, () => false)
}
