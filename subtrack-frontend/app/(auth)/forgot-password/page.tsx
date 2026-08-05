'use client'
import { useState } from 'react'
import Link from 'next/link'
import { createClient } from '@/lib/supabase/client'
import { LogoMark } from '@/components/layout/Logo'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { authErrorMessage } from '@/lib/auth/errors'

export default function ForgotPasswordPage() {
  const supabase = createClient()
  const [email, setEmail] = useState('')
  const [busy, setBusy] = useState(false)
  const [sent, setSent] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const { error } = await supabase.auth.resetPasswordForEmail(email, {
        // The link lands on the callback so the code becomes a session before
        // the form that sets the new password renders.
        redirectTo: `${window.location.origin}/auth/callback?next=/reset-password`,
      })
      if (error) throw error
      setSent(true)
    } catch (e) {
      setError(authErrorMessage(e, 'Could not send the reset link. Please try again.'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center px-6 py-12">
      <div className="w-full max-w-sm">
        <Link href="/" aria-label="Subtrack home" className="inline-flex">
          <LogoMark className="h-10 w-10" />
        </Link>

        {sent ? (
          <>
            <h1 className="mt-8 text-3xl font-semibold tracking-tight text-foreground">
              Check your email
            </h1>
            {/* Worded so it reveals nothing about whether the address has an
                account — the form would otherwise confirm who is a user. */}
            <p className="mt-3 text-sm text-muted-foreground">
              If <span className="font-medium text-foreground">{email}</span> has a
              Subtrack account, a link to set a new password is on its way. It expires
              after an hour.
            </p>
            <p className="mt-6 text-sm text-muted-foreground">
              <Link href="/login" className="font-medium text-foreground underline">
                Back to sign in
              </Link>
            </p>
          </>
        ) : (
          <>
            <h1 className="mt-8 text-3xl font-semibold tracking-tight text-foreground">
              Reset your password
            </h1>
            <p className="mt-3 text-sm text-muted-foreground">
              Enter the email you signed up with and we&apos;ll send a link to set a
              new one.
            </p>

            <form onSubmit={handleSubmit} className="mt-8 space-y-4">
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
              <Button type="submit" className="w-full" disabled={busy}>
                {busy ? 'Sending…' : 'Send reset link'}
              </Button>
            </form>

            {error && (
              <p role="alert" className="mt-3 text-sm text-destructive">
                {error}
              </p>
            )}

            <p className="mt-6 text-sm text-muted-foreground">
              Remembered it?{' '}
              <Link href="/login" className="font-medium text-foreground underline">
                Sign in
              </Link>
            </p>
          </>
        )}
      </div>
    </main>
  )
}
