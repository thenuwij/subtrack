'use client'

import useSWR, { type SWRConfiguration } from 'swr'
import { createClient } from '@/lib/supabase/client'

export const apiKeys = {
  detected: (status: 'pending' | 'dismissed') => `detected:${status}`,
  gmailStatus: 'gmail-status',
} as const

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
