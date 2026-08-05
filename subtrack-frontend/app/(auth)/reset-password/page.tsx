'use client'
import { useEffect, useState } from 'react'
import Link from 'next/link'
import { createClient } from '@/lib/supabase/client'
import { LogoMark } from '@/components/layout/Logo'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { authErrorMessage, passwordProblem } from '@/lib/auth/errors'

export default function ResetPasswordPage() {
  const supabase = createClient()
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // The reset link is exchanged for a session by /auth/callback before this
  // page renders. Landing here without one means the link was never opened,
  // was already used, or has expired.
  const [linked, setLinked] = useState<boolean | null>(null)

  useEffect(() => {
    let active = true
    supabase.auth.getSession().then(({ data }) => {
      if (active) setLinked(data.session !== null)
    })
    return () => { active = false }
  }, [supabase])

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    setError(null)

    const problem = passwordProblem(password)
    if (problem) {
      setError(problem)
      return
    }
    if (password !== confirm) {
      setError('Those passwords do not match.')
      return
    }

    setBusy(true)
    try {
      const { error } = await supabase.auth.updateUser({ password })
      if (error) throw error
      // Signing out sends them back through the front door with the new
      // password, which both proves it works and retires the link's session.
      await supabase.auth.signOut({ scope: 'local' })
      window.location.replace('/login?reason=password_updated')
    } catch (e) {
      setError(authErrorMessage(e, 'Could not update your password. Please try again.'))
      setBusy(false)
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center px-6 py-12">
      <div className="w-full max-w-sm">
        <Link href="/" aria-label="Subtrack home" className="inline-flex">
          <LogoMark className="h-10 w-10" />
        </Link>

        {linked === false ? (
          <>
            <h1 className="mt-8 text-3xl font-semibold tracking-tight text-foreground">
              This link is no longer valid
            </h1>
            <p className="mt-3 text-sm text-muted-foreground">
              Password links can only be used once, and expire after an hour.
            </p>
            <p className="mt-6 text-sm text-muted-foreground">
              <Link href="/forgot-password" className="font-medium text-foreground underline">
                Send a new link
              </Link>
            </p>
          </>
        ) : (
          <>
            <h1 className="mt-8 text-3xl font-semibold tracking-tight text-foreground">
              Set a new password
            </h1>
            <p className="mt-3 text-sm text-muted-foreground">
              Choose a password you don&apos;t use anywhere else.
            </p>

            <form onSubmit={handleSubmit} className="mt-8 space-y-4">
              <div className="space-y-1.5">
                <Label htmlFor="password">New password</Label>
                <Input
                  id="password"
                  type="password"
                  autoComplete="new-password"
                  required
                  value={password}
                  onChange={e => setPassword(e.target.value)}
                  placeholder="At least 8 characters"
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="confirm">Confirm new password</Label>
                <Input
                  id="confirm"
                  type="password"
                  autoComplete="new-password"
                  required
                  value={confirm}
                  onChange={e => setConfirm(e.target.value)}
                />
              </div>
              <Button type="submit" className="w-full" disabled={busy || linked === null}>
                {busy ? 'Updating…' : 'Update password'}
              </Button>
            </form>

            {error && (
              <p role="alert" className="mt-3 text-sm text-destructive">
                {error}
              </p>
            )}
          </>
        )}
      </div>
    </main>
  )
}
