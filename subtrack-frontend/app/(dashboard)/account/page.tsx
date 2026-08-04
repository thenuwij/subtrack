'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { createClient } from '@/lib/supabase/client'
import { useCurrency } from '@/lib/context/currency'
import {
  disconnectGmail,
  getGmailConnectUrl,
  getGmailStatus,
  getPreferences,
  startGmailScan,
  updatePreferences,
} from '@/lib/api'
import type { GmailStatus } from '@/types'
import type { User } from '@supabase/supabase-js'
import type { Currency } from '@/types'
import { Button } from '@/components/ui/button'
import { toast } from 'sonner'

const CURRENCIES: Currency[] = ['AUD', 'USD', 'GBP', 'SGD', 'EUR', 'JPY']

export default function AccountPage() {
  const router = useRouter()
  const [user, setUser] = useState<User | null>(null)
  const [imgError, setImgError] = useState(false)
  const [income, setIncome] = useState('')
  const [incomeStatus, setIncomeStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle')
  const [gmail, setGmail] = useState<GmailStatus | null>(null)
  // The OAuth callback redirects back here with a reason when connecting fails.
  const [gmailError, setGmailError] = useState<string | null>(null)
  const [gmailBusy, setGmailBusy] = useState(false)
  const [confirmDisconnect, setConfirmDisconnect] = useState(false)
  const { baseCurrency, setBaseCurrency, isLoading } = useCurrency()

  useEffect(() => {
    const supabase = createClient()
    supabase.auth.getUser().then(({ data }) => setUser(data.user))

    async function loadIncome() {
      const { data: { session } } = await supabase.auth.getSession()
      if (!session) return
      const prefs = await getPreferences(session.access_token)
      if (prefs.monthly_income !== null && prefs.monthly_income !== undefined) {
        setIncome(String(prefs.monthly_income))
      }
    }
    loadIncome()

    async function loadGmail() {
      const { data: { session } } = await supabase.auth.getSession()
      if (!session) return
      try {
        setGmail(await getGmailStatus(session.access_token))
      } catch {
        // Gmail may not be configured on this deployment; the section just hides.
      }
    }
    loadGmail()

    // Read (and clear) the outcome the callback redirected with, so a failed
    // connect explains itself instead of just appearing not to have worked.
    const params = new URLSearchParams(window.location.search)
    const failure = params.get('gmail_error')
    if (failure) {
      setGmailError(failure)
      window.history.replaceState({}, '', window.location.pathname)
    } else if (params.get('gmail') === 'connected') {
      toast.success('Gmail connected')
      window.history.replaceState({}, '', window.location.pathname)
    }
  }, [])

  // While a scan runs, poll for the outcome. Without this the "Scanning"
  // button stays disabled forever — even after the scan ends — until the
  // user happens to refresh the page.
  useEffect(() => {
    if (gmail?.scan_status !== 'running') return
    const timer = setInterval(async () => {
      const { data: { session } } = await createClient().auth.getSession()
      if (!session) return
      try {
        setGmail(await getGmailStatus(session.access_token))
      } catch {
        // Transient poll failure — keep the last known state and retry.
      }
    }, 5000)
    return () => clearInterval(timer)
  }, [gmail?.scan_status])

  async function withToken<T>(fn: (token: string) => Promise<T>) {
    const { data: { session } } = await createClient().auth.getSession()
    if (!session) return
    setGmailBusy(true)
    try {
      return await fn(session.access_token)
    } finally {
      setGmailBusy(false)
    }
  }

  async function handleConnectGmail() {
    try {
      await withToken(async token => {
        const { auth_url } = await getGmailConnectUrl(token)
        window.location.href = auth_url
      })
    } catch (e) {
      // Show what actually went wrong — unreachable backend, misconfiguration,
      // or a server error all used to read "please try again".
      const message = e instanceof Error ? e.message : 'Could not start the Gmail connection.'
      setGmailError(message)
      toast.error(message)
    }
  }

  async function handleScan() {
    try {
      await withToken(async token => {
        await startGmailScan(token)
        setGmail(g => (g ? { ...g, scan_status: 'running' } : g))
        router.push('/review')
      })
    } catch (e) {
      const message = e instanceof Error ? e.message : 'Could not start the inbox scan.'
      setGmailError(message)
      toast.error(message)
    }
  }

  async function handleDisconnectGmail() {
    try {
      await withToken(async token => {
        await disconnectGmail(token)
        setGmail({ connected: false })
        setConfirmDisconnect(false)
        toast.success('Gmail disconnected')
      })
    } catch {
      toast.error('Could not disconnect Gmail. Please try again.')
    }
  }

  async function handleSaveIncome() {
    const value = Number(income)
    if (!Number.isFinite(value) || value < 0) {
      setIncomeStatus('error')
      return
    }

    setIncomeStatus('saving')
    try {
      const { data: { session } } = await createClient().auth.getSession()
      if (!session) return
      await updatePreferences(session.access_token, { monthly_income: value })
      setIncomeStatus('saved')
    } catch {
      setIncomeStatus('error')
    }
  }

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
            /* External Google avatar; next/image would need a remote-host
               allowlist for a 56px image with no optimization benefit. */
            // eslint-disable-next-line @next/next/no-img-element
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

        <div className="flex items-center justify-between gap-4 border-t border-border pt-4">
          <div>
            <p className="text-sm font-medium">Monthly income</p>
            <p className="text-xs text-muted-foreground mt-0.5">
              Used to show what share of your income goes to recurring payments
            </p>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <input
              type="number"
              min="0"
              inputMode="decimal"
              value={income}
              placeholder="0"
              onChange={e => {
                setIncome(e.target.value)
                setIncomeStatus('idle')
              }}
              className="w-32 rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-primary/40 transition-shadow"
            />
            <Button
              onClick={handleSaveIncome}
              disabled={incomeStatus === 'saving' || income === ''}
            >
              {incomeStatus === 'saving' ? 'Saving' : incomeStatus === 'saved' ? 'Saved' : 'Save'}
            </Button>
          </div>
        </div>

        {incomeStatus === 'error' && (
          <p className="text-xs text-destructive">Enter a valid amount and try again.</p>
        )}
      </div>

      {/* Section 3 — Connected inbox */}
      {gmail && (
        <div id="inbox" className="scroll-mt-6 rounded-2xl bg-card shadow-md p-6 space-y-4">
          <div>
            <h2 className="text-lg font-semibold">Email connection</h2>
            <p className="mt-1 text-xs text-muted-foreground">
              Let Subtrack find recurring payments in Gmail receipts for you to review.
            </p>
          </div>

          {gmail.connected ? (
            <>
              <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
                <div className="min-w-0">
                  <p className="text-sm font-medium truncate">{gmail.email_address}</p>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    {gmail.scan_status === 'running'
                      ? 'Scanning your inbox…'
                      : gmail.last_scanned_at
                        ? `Last scanned ${new Date(gmail.last_scanned_at).toLocaleDateString('en-AU', {
                            day: 'numeric', month: 'short', year: 'numeric',
                          })}`
                        : 'Not scanned yet'}
                  </p>
                </div>
                <div className="flex gap-2 shrink-0">
                  <Button
                    onClick={handleScan}
                    disabled={gmailBusy || gmail.scan_status === 'running'}
                  >
                    {gmail.scan_status === 'running' ? 'Scanning' : 'Scan inbox'}
                  </Button>
                </div>
              </div>

              {gmail.scan_error && (
                <p className="text-xs text-destructive">Last scan failed: {gmail.scan_error}</p>
              )}

              <div className="flex flex-col gap-3 border-t border-border pt-4 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <p className="text-sm font-medium">Disconnect</p>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    Subtrack keeps your recurring payments but stops reading your email
                  </p>
                </div>
                {confirmDisconnect ? (
                  <div className="flex shrink-0 gap-2">
                    <Button variant="destructive" size="sm" onClick={handleDisconnectGmail} disabled={gmailBusy}>
                      {gmailBusy ? 'Disconnecting…' : 'Confirm disconnect'}
                    </Button>
                    <Button variant="ghost" size="sm" onClick={() => setConfirmDisconnect(false)} disabled={gmailBusy}>
                      Cancel
                    </Button>
                  </div>
                ) : (
                  <Button
                    variant="ghost"
                    onClick={() => setConfirmDisconnect(true)}
                    disabled={gmailBusy}
                    className="text-destructive hover:text-destructive hover:bg-destructive/10 shrink-0"
                  >
                    Disconnect Gmail
                  </Button>
                )}
              </div>
            </>
          ) : (
            <div className="space-y-3">
              {/* Connecting happens across a Google redirect, so a failure has
                  to be reported here or it looks like nothing happened. */}
              {gmailError && (
                <div className="rounded-lg border border-destructive/25 bg-destructive/5 p-3">
                  <p className="text-sm font-medium text-destructive">
                    Couldn&apos;t connect Gmail
                  </p>
                  <p className="mt-0.5 text-xs text-muted-foreground">{gmailError}</p>
                </div>
              )}

              <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <p className="text-sm font-medium">Connect Gmail</p>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    Find recurring payments from your receipt emails instead of adding them
                    by hand. Read-only, and nothing is added without your approval.
                  </p>
                </div>
                <Button onClick={handleConnectGmail} disabled={gmailBusy} className="shrink-0">
                  Connect Gmail
                </Button>
              </div>
            </div>
          )}
        </div>
      )}

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
