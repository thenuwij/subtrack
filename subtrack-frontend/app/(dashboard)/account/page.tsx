'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { createClient } from '@/lib/supabase/client'
import { useCurrency } from '@/lib/context/currency'
import type { User } from '@supabase/supabase-js'
import type { Currency } from '@/types'
import { Button } from '@/components/ui/button'

const CURRENCIES: Currency[] = ['AUD', 'USD', 'GBP', 'SGD', 'EUR', 'JPY']

export default function AccountPage() {
  const router = useRouter()
  const [user, setUser] = useState<User | null>(null)
  const [imgError, setImgError] = useState(false)
  const { baseCurrency, setBaseCurrency, isLoading } = useCurrency()

  useEffect(() => {
    const supabase = createClient()
    supabase.auth.getUser().then(({ data }) => setUser(data.user))
  }, [])

  async function handleSignOut() {
    await createClient().auth.signOut()
    router.push('/login')
  }

  const meta       = user?.user_metadata ?? {}
  const avatarUrl  = meta.avatar_url as string | undefined
  const fullName   = (meta.full_name ?? meta.name ?? '') as string
  const email      = user?.email ?? ''
  const initials   = fullName
    .split(' ')
    .map((n: string) => n[0])
    .join('')
    .toUpperCase()
    .slice(0, 2)
  const memberSince = user?.created_at
    ? new Date(user.created_at).toLocaleDateString('en-AU', { month: 'long', year: 'numeric' })
    : ''

  return (
    <div className="mx-auto w-full max-w-2xl px-4 py-8 space-y-6">

      <h1 className="text-2xl font-semibold tracking-tight">Account</h1>

      {/* Section 1 — Profile */}
      <div className="rounded-2xl bg-card shadow-md p-6 space-y-4">
        <h2 className="text-lg font-semibold">Profile</h2>

        <div className="flex items-center gap-4">
          {/* Avatar */}
          {avatarUrl && !imgError ? (
            <img
              src={avatarUrl}
              alt={fullName}
              onError={() => setImgError(true)}
              className="w-14 h-14 rounded-full object-cover shrink-0"
            />
          ) : (
            <div className="w-14 h-14 rounded-full bg-muted flex items-center justify-center shrink-0">
              <span className="text-base font-semibold text-muted-foreground">{initials || '?'}</span>
            </div>
          )}

          <div className="min-w-0">
            <p className="font-semibold text-sm truncate">{fullName || '—'}</p>
            <p className="text-sm text-muted-foreground truncate">{email}</p>
          </div>
        </div>

        <div className="border-t border-border pt-4 space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-sm text-muted-foreground">Sign-in method</span>
            <span className="text-xs font-medium px-2.5 py-1 rounded-full bg-muted text-foreground">
              Signed in with Google
            </span>
          </div>
          {memberSince && (
            <div className="flex items-center justify-between">
              <span className="text-sm text-muted-foreground">Member since</span>
              <span className="text-sm text-foreground">{memberSince}</span>
            </div>
          )}
        </div>
      </div>

      {/* Section 2 — Preferences */}
      <div className="rounded-2xl bg-card shadow-md p-6 space-y-4">
        <h2 className="text-lg font-semibold">Preferences</h2>

        <div className="flex items-center justify-between gap-4">
          <div>
            <p className="text-sm font-medium">Base currency</p>
            <p className="text-xs text-muted-foreground mt-0.5">All amounts are displayed in this currency</p>
          </div>
          <select
            value={baseCurrency}
            disabled={isLoading}
            onChange={e => setBaseCurrency(e.target.value as Currency)}
            className="rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-primary/40 transition-shadow shrink-0"
          >
            {CURRENCIES.map(c => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>
        </div>
      </div>

      {/* Section 3 — Account actions */}
      <div className="rounded-2xl bg-card shadow-md p-6 space-y-4">
        <h2 className="text-lg font-semibold">Account</h2>

        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm font-medium">Sign out</p>
            <p className="text-xs text-muted-foreground mt-0.5">You will be redirected to the login page</p>
          </div>
          <Button variant="outline" className="text-destructive border-destructive/40 hover:bg-destructive/10 hover:text-destructive shrink-0" onClick={handleSignOut}>
            Sign out
          </Button>
        </div>
      </div>

    </div>
  )
}
