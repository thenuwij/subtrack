'use client'
import { useState } from 'react'
import Link from 'next/link'
import { createClient } from '@/lib/supabase/client'
import { LogoMark } from '@/components/layout/Logo'
import { useHydrated } from '@/lib/hooks/useHydrated'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { authErrorMessage, passwordProblem } from '@/lib/auth/errors'

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

type Mode = 'signin' | 'signup'

export default function LoginPage() {
  const supabase = createClient()
  const [mode, setMode] = useState<Mode>('signin')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState<'email' | 'google' | null>(null)
  const [error, setError] = useState<string | null>(null)
  // Set when a sign-up needs the emailed confirmation link before it has a
  // session. Whether that step exists at all is a Supabase project setting,
  // so both outcomes are handled rather than assumed.
  const [checkEmail, setCheckEmail] = useState<string | null>(null)

  const hydrated = useHydrated()
  const reason = hydrated
    ? new URLSearchParams(window.location.search).get('reason')
    : null
  const sessionExpired = reason === 'session_expired'
  const gmailRevocationFailed = reason === 'data_deleted_gmail_revoke_failed'
  const dataDeleted = reason === 'data_deleted' || gmailRevocationFailed
  const passwordUpdated = reason === 'password_updated'
  const linkInvalid = reason === 'link_invalid'

  function switchMode(next: Mode) {
    setMode(next)
    setError(null)
    setPassword('')
  }

  async function handleEmailSubmit(event: React.FormEvent) {
    event.preventDefault()
    setError(null)

    if (mode === 'signup') {
      const problem = passwordProblem(password)
      if (problem) {
        setError(problem)
        return
      }
    }

    setBusy('email')
    try {
      if (mode === 'signin') {
        const { error } = await supabase.auth.signInWithPassword({ email, password })
        if (error) throw error
        // A full document load, not a client transition: it guarantees the proxy
        // and every server component re-run against the cookies this call just
        // wrote. `replace` so Back doesn't return to a filled-in sign-in form.
        window.location.replace('/dashboard')
        return
      }

      const { data, error } = await supabase.auth.signUp({
        email,
        password,
        options: { emailRedirectTo: `${window.location.origin}/auth/callback` },
      })
      if (error) throw error

      if (data.session) {
        window.location.replace('/dashboard')
        return
      }
      // No session means confirmation is required. Supabase deliberately
      // returns the same shape for an address that already has an account,
      // so this message must not imply the address was or wasn't new.
      setCheckEmail(email)
    } catch (e) {
      setError(authErrorMessage(
        e,
        mode === 'signin'
          ? 'Could not sign you in. Please try again.'
          : 'Could not create your account. Please try again.',
      ))
      setBusy(null)
    }
  }

  async function handleGoogleLogin() {
    setBusy('google')
    setError(null)
    try {
      const { error } = await supabase.auth.signInWithOAuth({
        provider: 'google',
        options: { redirectTo: `${window.location.origin}/auth/callback` },
      })
      // A failure here used to leave the button looking like it did nothing.
      if (error) throw error
    } catch (e) {
      setError(authErrorMessage(e, 'Could not start sign-in. Please try again.'))
      setBusy(null)
    }
  }

  return (
    <main className="grid min-h-screen lg:grid-cols-2">
      {/* Sign-in */}
      <div className="flex items-center justify-center px-6 py-12">
        <div className="w-full max-w-sm">
          <Link href="/" aria-label="Subtrack home" className="inline-flex">
            <LogoMark className="h-10 w-10" />
          </Link>

          {checkEmail ? (
            <>
              <h1 className="mt-8 text-3xl font-semibold tracking-tight text-foreground">
                Confirm your email
              </h1>
              <p className="mt-3 text-sm text-muted-foreground">
                If <span className="font-medium text-foreground">{checkEmail}</span> can
                be used to create an account, a confirmation link is on its way. Open it
                to finish signing up.
              </p>
              <p className="mt-4 text-sm text-muted-foreground">
                Nothing arrived? Check your spam folder, or{' '}
                <button
                  type="button"
                  className="underline hover:text-foreground"
                  onClick={() => { setCheckEmail(null); setBusy(null); switchMode('signup') }}
                >
                  try a different address
                </button>
                .
              </p>
            </>
          ) : (
            <>
              <h1 className="mt-8 text-3xl font-semibold tracking-tight text-foreground">
                {mode === 'signin'
                  ? 'Know what your recurring payments really cost'
                  : 'Create your Subtrack account'}
              </h1>
              <p className="mt-3 text-sm text-muted-foreground">
                {mode === 'signin'
                  ? 'Subscriptions, rent, bills and memberships — found in your inbox and added up in one place.'
                  : 'Start with an email and password. You can connect Gmail afterwards to find recurring charges automatically.'}
              </p>

              {sessionExpired ? (
                <p role="status" className="mt-5 rounded-xl border border-amber-500/25 bg-amber-500/5 px-3 py-2.5 text-sm text-foreground">
                  Your session expired. Sign in again to continue.
                </p>
              ) : linkInvalid ? (
                <p role="status" className="mt-5 rounded-xl border border-amber-500/25 bg-amber-500/5 px-3 py-2.5 text-sm text-foreground">
                  That link has expired or was already used. Sign in, or request a new
                  one from <Link className="underline" href="/forgot-password">forgot password</Link>.
                </p>
              ) : passwordUpdated ? (
                <p role="status" className="mt-5 rounded-xl border border-border bg-muted/50 px-3 py-2.5 text-sm text-foreground">
                  Your password was updated. Sign in with it below.
                </p>
              ) : dataDeleted ? (
                <p role="status" className="mt-5 rounded-xl border border-border bg-muted/50 px-3 py-2.5 text-sm text-foreground">
                  Your Subtrack app data was deleted and you have been signed out.
                  {gmailRevocationFailed
                    ? ' Google could not be reached to revoke the former Gmail permission, so remove Subtrack from your Google Account permissions as well.'
                    : ''}
                </p>
              ) : null}

              <form onSubmit={handleEmailSubmit} className="mt-8 space-y-4">
                <div className="space-y-1.5">
                  <Label htmlFor="email">Email</Label>
                  <Input
                    id="email"
                    type="email"
                    autoComplete="email"
                    required
                    value={email}
                    onChange={e => setEmail(e.target.value)}
                    placeholder="you@example.com"
                  />
                </div>

                <div className="space-y-1.5">
                  <div className="flex items-baseline justify-between">
                    <Label htmlFor="password">Password</Label>
                    {mode === 'signin' ? (
                      <Link
                        href="/forgot-password"
                        className="text-xs text-muted-foreground underline hover:text-foreground"
                      >
                        Forgot password?
                      </Link>
                    ) : null}
                  </div>
                  <Input
                    id="password"
                    type="password"
                    autoComplete={mode === 'signin' ? 'current-password' : 'new-password'}
                    required
                    value={password}
                    onChange={e => setPassword(e.target.value)}
                    placeholder={mode === 'signup' ? 'At least 8 characters' : undefined}
                  />
                </div>

                <Button type="submit" className="w-full" disabled={busy !== null}>
                  {busy === 'email'
                    ? (mode === 'signin' ? 'Signing in…' : 'Creating account…')
                    : (mode === 'signin' ? 'Sign in' : 'Create account')}
                </Button>
              </form>

              <div className="my-6 flex items-center gap-3">
                <span className="h-px flex-1 bg-border" aria-hidden="true" />
                <span className="text-xs text-muted-foreground">or</span>
                <span className="h-px flex-1 bg-border" aria-hidden="true" />
              </div>

              <button
                onClick={handleGoogleLogin}
                disabled={busy !== null}
                className="flex w-full items-center justify-center gap-3 rounded-xl border border-border bg-card px-6 py-3 text-sm font-medium text-foreground shadow-sm transition-colors hover:bg-muted disabled:opacity-60"
              >
                {busy === 'google' ? (
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

              <p className="mt-6 text-sm text-muted-foreground">
                {mode === 'signin' ? (
                  <>
                    New to Subtrack?{' '}
                    <button
                      type="button"
                      className="font-medium text-foreground underline"
                      onClick={() => switchMode('signup')}
                    >
                      Create an account
                    </button>
                  </>
                ) : (
                  <>
                    Already have an account?{' '}
                    <button
                      type="button"
                      className="font-medium text-foreground underline"
                      onClick={() => switchMode('signin')}
                    >
                      Sign in
                    </button>
                  </>
                )}
              </p>

              <p className="mt-6 text-xs leading-5 text-muted-foreground">
                By continuing you agree to our <Link className="underline hover:text-foreground" href="/terms">terms</Link> and acknowledge our <Link className="underline hover:text-foreground" href="/privacy">privacy policy</Link>. Subtrack only ever reads your email—it never sends anything.
              </p>
            </>
          )}
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
