'use client'

import useSWR, { type SWRConfiguration } from 'swr'
import { createClient } from '@/lib/supabase/client'

export const apiKeys = {
  detected: (status: 'pending' | 'dismissed') => `detected:${status}`,
  gmailStatus: 'gmail-status',
  subscriptions: (scope: 'current' | 'all') => `subscriptions:${scope}`,
  subscriptionChanges: (days: number) => `subscription-changes:${days}`,
  forecast: (days: number) => `forecast:${days}`,
  reminders: (horizonDays: number) => `reminders:${horizonDays}`,
  preferences: 'preferences',
} as const

export function errorMessage(error: unknown, fallback: string) {
  if (!error) return ''
  return error instanceof Error && error.message ? error.message : fallback
}

async function accessToken() {
  const { data: { session } } = await createClient().auth.getSession()
  if (!session) throw new Error('Your session has expired. Sign in again.')
  return session.access_token
}

export function useApi<T>(
  key: string | null,
  load: (token: string) => Promise<T>,
  config?: SWRConfiguration<T>,
) {
  return useSWR<T>(key, async () => load(await accessToken()), config)
}
