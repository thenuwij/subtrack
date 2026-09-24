'use client'

import useSWR, { type SWRConfiguration } from 'swr'
import { getAccessToken } from '@/lib/auth/session'

export const apiKeys = {
  detected: (status: 'pending' | 'dismissed') => `detected:${status}`,
  gmailStatus: 'gmail-status',
  subscriptions: (scope: 'current' | 'all') => `subscriptions:${scope}`,
  subscriptionChanges: (days: number) => `subscription-changes:${days}`,
  forecast: (days: number) => `forecast:${days}`,
  reminders: (horizonDays: number) => `reminders:${horizonDays}`,
  preferences: 'preferences',
  duplicates: 'duplicates',
  agentThreads: 'agent-threads',
} as const

export function errorMessage(error: unknown, fallback: string) {
  if (!error) return ''
  return error instanceof Error && error.message ? error.message : fallback
}

async function accessToken() {
  const accessToken = await getAccessToken()
  if (!accessToken) throw new Error('Your session has expired. Sign in again.')
  return accessToken
}

export function useApi<T>(
  key: string | null,
  load: (token: string) => Promise<T>,
  config?: SWRConfiguration<T>,
) {
  return useSWR<T>(key, async () => load(await accessToken()), config)
}
