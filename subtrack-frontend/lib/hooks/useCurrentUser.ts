'use client'

import { useEffect, useState } from 'react'
import type { User } from '@supabase/supabase-js'
import { createClient } from '@/lib/supabase/client'
import { useIsDemo } from '@/lib/auth/session'

const PROVIDER_LABELS: Record<string, string> = {
  google: 'Google',
  email: 'Email and password',
}

export function useCurrentUser() {
  const [user, setUser] = useState<User | null>(null)
  const isDemo = useIsDemo()

  useEffect(() => {
    let active = true
    createClient().auth.getUser().then(({ data }) => {
      if (active) setUser(data.user)
    })
    return () => {
      active = false
    }
  }, [])

  const meta = user?.user_metadata ?? {}
  const name = ((meta.full_name ?? meta.name) as string | undefined)
    ?? (isDemo ? 'Demo user' : '')
  const email = user?.email ?? (isDemo ? 'Sample data, reset after 24 hours' : '')
  const provider = user?.app_metadata?.provider as string | undefined

  return {
    user,
    isDemo,
    name,
    email,
    avatarUrl: meta.avatar_url as string | undefined,
    signInMethod: isDemo ? 'Demo' : provider ? PROVIDER_LABELS[provider] ?? provider : null,
    memberSince: user?.created_at
      ? new Date(user.created_at).toLocaleDateString('en-AU', { month: 'long', year: 'numeric' })
      : null,
  }
}
