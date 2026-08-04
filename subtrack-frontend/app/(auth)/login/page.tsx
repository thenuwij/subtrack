'use client'
import { useState } from 'react'
import { createClient } from '@/lib/supabase/client'
import { LogoMark } from '@/components/layout/Logo'

const POINTS = [
  {
    title: 'Found from your receipts',
    body: 'Connect Gmail and Subtrack works out which charges repeat. Read-only.',
  },
  {
    title: 'One honest number',
    body: 'What every subscription, bill and membership costs you a month — and a year.',
  },
  {
    title: 'Told when it changes',
    body: 'Price rises and new charges surface instead of quietly going out.',
  },
]

export default function LoginPage() {
  const supabase = createClient()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleGoogleLogin() {
    setBusy(true)
    setError(null)
    try {
      const { error } = await supabase.auth.signInWithOAuth({
        provider: 'google',
        options: { redirectTo: `${window.location.origin}/auth/callback` },
      })
      // A failure here used to leave the button looking like it did nothing.
      if (error) throw error
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not start sign-in. Please try again.')
      setBusy(false)
    }
  }

  return (
    <main className="grid min-h-screen lg:grid-cols-2">
      {/* Sign-in */}
      <div className="flex items-center justify-center px-6 py-12">
        <div className="w-full max-w-sm">
          <LogoMark className="h-10 w-10" />

          <h1 className="mt-8 text-3xl font-semibold tracking-tight text-foreground">
            Know what your recurring payments really cost
          </h1>
          <p className="mt-3 text-sm text-muted-foreground">
            Subscriptions, rent, bills and memberships — found in your inbox and
            added up in one place.
          </p>

          <button
            onClick={handleGoogleLogin}
            disabled={busy}
            className="mt-8 flex w-full items-center justify-center gap-3 rounded-xl border border-border bg-card px-6 py-3 text-sm font-medium text-foreground shadow-sm transition-colors hover:bg-muted disabled:opacity-60"
          >
            {busy ? (
              <>
                <span
                  className="h-4 w-4 animate-spin rounded-full border-2 border-muted-foreground/30 border-t-foreground"
                  aria-hidden="true"
                />
                Opening Google…
              </>
            ) : (
              <>
                <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true">
                  <path fill="#FFC107" d="M43.6 20H24v8h11.3C33.6 33.1 29.3 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3 0 5.8 1.1 7.9 3l5.7-5.7C34.1 6.5 29.3 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.7-.4-4z" />
                  <path fill="#FF3D00" d="M6.3 14.7l6.6 4.8C14.6 15.1 18.9 12 24 12c3 0 5.8 1.1 7.9 3l5.7-5.7C34.1 6.5 29.3 4 24 4 16.3 4 9.7 8.3 6.3 14.7z" />
                  <path fill="#4CAF50" d="M24 44c5.2 0 9.9-1.9 13.5-5l-6.2-5.2C29.4 35.6 26.8 36 24 36c-5.2 0-9.6-2.9-11.3-7.1l-6.5 5C9.5 39.6 16.2 44 24 44z" />
                  <path fill="#1976D2" d="M43.6 20H24v8h11.3c-.9 2.4-2.5 4.4-4.6 5.8l6.2 5.2C40.7 35.7 44 30.3 44 24c0-1.3-.1-2.7-.4-4z" />
                </svg>
                Continue with Google
              </>
            )}
          </button>

          {error && (
            <p role="alert" className="mt-3 text-sm text-destructive">
              {error}
            </p>
          )}

          <p className="mt-6 text-xs text-muted-foreground">
            By continuing you agree to our terms of service. Subtrack only ever
            reads your email — it never sends anything.
          </p>
        </div>
      </div>

      {/* Value proposition. Hidden on small screens, where the sign-in should
          be the entire viewport rather than something to scroll past. */}
      <div className="relative hidden items-center overflow-hidden bg-sidebar px-12 lg:flex">
        <div
          className="pointer-events-none absolute -right-24 -top-24 h-96 w-96 rounded-full opacity-[0.18] blur-3xl"
          style={{ background: 'var(--primary)' }}
          aria-hidden="true"
        />
        <div
          className="pointer-events-none absolute -bottom-32 -left-16 h-80 w-80 rounded-full opacity-[0.12] blur-3xl"
          style={{ background: 'var(--category-streaming)' }}
          aria-hidden="true"
        />

        <ul className="relative z-10 max-w-md space-y-10">
          {POINTS.map((point, i) => (
            <li key={point.title}>
              <span className="flex h-8 w-8 items-center justify-center rounded-full bg-primary/10 text-xs font-semibold text-primary">
                {i + 1}
              </span>
              <p className="mt-4 text-lg font-semibold tracking-tight text-foreground">
                {point.title}
              </p>
              <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">
                {point.body}
              </p>
            </li>
          ))}
        </ul>
      </div>
    </main>
  )
}
