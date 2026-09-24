'use client'

import { useEffect, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import { createClient } from '@/lib/supabase/client'
import { useCurrency } from '@/lib/context/currency'
import { useSWRConfig } from 'swr'
import { apiKeys, errorMessage, useApi } from '@/lib/hooks/useApi'
import {
  deleteAccountData,
  disconnectGmail,
  downloadAccountExport,
  getGmailConnectUrl,
  getGmailStatus,
  getPreferences,
  startGmailScan,
  updatePreferences,
} from '@/lib/api'
import type { GmailStatus } from '@/types'
import type { Currency } from '@/types'
import { Button } from '@/components/ui/button'
import { ThemeToggle } from '@/components/layout/ThemeToggle'
import { START_TOUR_EVENT } from '@/components/onboarding/OnboardingTour'
import { toast } from 'sonner'
import { GmailScanProgress } from '@/components/gmail/GmailScanProgress'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { endDemo, getAccessToken, signOut } from '@/lib/auth/session'
import { useCurrentUser } from '@/lib/hooks/useCurrentUser'
import { UserAvatar } from '@/components/layout/UserAvatar'
import { LogOut } from 'lucide-react'

const CURRENCIES: Currency[] = ['AUD', 'USD', 'GBP', 'SGD', 'EUR', 'JPY']
/** Keyed by the code the Gmail callback forwards: Google's own OAuth error,
 *  the backend's `invalid_oauth_response`, or one of our own outcomes. */
const GMAIL_ERROR_MESSAGES: Record<string, string> = {
  cancelled: 'Google sign-in was cancelled. Nothing was connected.',
  access_denied:
    'You declined the Google permission request, so nothing was connected. '
    + 'Connect again and allow read access to continue.',
  invalid_scope:
    'Google would not grant the permission Subtrack asked for. Connect again, '
    + 'and make sure the tickbox for viewing your email is ticked.',
  invalid_oauth_response:
    'Google’s reply could not be verified, so it was rejected. This is '
    + 'usually a stale or reused link — connect again from this page.',
  invalid_response: 'Google returned an invalid connection response. Please start again.',
  server_error: 'Google had a problem on its side. Try connecting again in a moment.',
  temporarily_unavailable:
    'Google is temporarily unavailable. Try connecting again in a moment.',
  connection_failed: 'Gmail could not be connected. Please start again.',
}
const DELETE_CONFIRMATION = 'DELETE MY SUBTRACK DATA' as const

export default function AccountPage() {
  const router = useRouter()
  const [income, setIncome] = useState('')
  const [incomeStatus, setIncomeStatus] = useState<'idle' | 'saving' | 'saved' | 'cleared' | 'error'>('idle')
  const [incomeError, setIncomeError] = useState('')
  const incomeEdited = useRef(false)
  const [hasSavedIncome, setHasSavedIncome] = useState(false)
  const gmailQuery = useApi<GmailStatus>(apiKeys.gmailStatus, getGmailStatus, {
    refreshInterval: latest => (latest?.scan_status === 'running' ? 3000 : 0),
  })
  const gmailLoadFailed = Boolean(gmailQuery.error) && !gmailQuery.data
  const gmail: GmailStatus | null = gmailQuery.data ?? (gmailLoadFailed ? { connected: false } : null)
  const { mutate: mutateCache } = useSWRConfig()
  const [gmailError, setGmailError] = useState<string | null>(null)
  const shownGmailError = gmailError
    ?? (gmailLoadFailed ? errorMessage(gmailQuery.error, 'Could not load Gmail status.') : null)
  // The OAuth callback redirects back here with a reason when connecting fails.
  const [gmailBusy, setGmailBusy] = useState(false)
  const [confirmDisconnect, setConfirmDisconnect] = useState(false)
  const [exportBusy, setExportBusy] = useState(false)
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false)
  const [deleteConfirmation, setDeleteConfirmation] = useState('')
  const [deleteBusy, setDeleteBusy] = useState(false)
  const currentUser = useCurrentUser()
  const { baseCurrency, setBaseCurrency, isLoading, isUpdating: currencyUpdating } = useCurrency()

  useEffect(() => {
    async function loadIncome() {
      const accessToken = await getAccessToken()
      if (!accessToken) return
      try {
        const prefs = await getPreferences(accessToken)
        if (!incomeEdited.current
            && prefs.monthly_income !== null && prefs.monthly_income !== undefined) {
          setIncome(String(prefs.monthly_income))
          setHasSavedIncome(true)
        }
      } catch (error) {
        toast.error(error instanceof Error ? error.message : 'Could not load account preferences.')
      }
    }
    void loadIncome()

    // Read (and clear) the outcome the callback redirected with, so a failed
    // connect explains itself instead of just appearing not to have worked.
    const params = new URLSearchParams(window.location.search)
    const failure = params.get('gmail_error')
    if (failure) {
      // The backend's own wording is more specific than anything mapped from
      // a code here — "this request expired" versus "could not be connected"
      // is the difference between knowing to retry and guessing.
      const detail = params.get('gmail_detail')?.trim()
      setGmailError(
        detail
          || GMAIL_ERROR_MESSAGES[failure]
          || 'Gmail could not be connected. Please start again.',
      )
      window.history.replaceState({}, '', window.location.pathname)
    } else if (params.get('gmail') === 'connected') {
      toast.success('Gmail connected')
      window.history.replaceState({}, '', window.location.pathname)
    }
  }, [])

  async function withToken<T>(fn: (token: string) => Promise<T>) {
    const accessToken = await getAccessToken()
    if (!accessToken) return
    setGmailBusy(true)
    try {
      return await fn(accessToken)
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
        void gmailQuery.mutate(g => (g ? {
          ...g,
          scan_status: 'running',
          scan_error: null,
          scan_stage: 'queued',
          scan_processed: 0,
          scan_total: 0,
          scan_partial: false,
          scan_message: null,
        } : g), { revalidate: false })
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
        const result = await disconnectGmail(token)
        void gmailQuery.mutate({ connected: false }, { revalidate: false })
        setConfirmDisconnect(false)
        if (result.gmail_revocation === 'failed') {
          toast.warning('Gmail was disconnected from Subtrack, but Google could not be reached to revoke access. Remove Subtrack from your Google Account permissions to revoke it manually.')
        } else {
          toast.success('Gmail disconnected')
        }
      })
    } catch {
      toast.error('Could not disconnect Gmail. Please try again.')
    }
  }

  async function handleSaveIncome() {
    const value = Number(income)
    if (!Number.isFinite(value) || value < 0) {
      setIncomeStatus('error')
      setIncomeError('Enter a valid amount of zero or more.')
      return
    }

    setIncomeStatus('saving')
    try {
      const accessToken = await getAccessToken()
      if (!accessToken) throw new Error('Your session has expired.')
      await updatePreferences(accessToken, { monthly_income: value })
      incomeEdited.current = false
      setHasSavedIncome(true)
      setIncomeStatus('saved')
      void mutateCache(apiKeys.preferences)
      setIncomeError('')
    } catch (error) {
      setIncomeStatus('error')
      setIncomeError(error instanceof Error ? error.message : 'Could not save your income.')
    }
  }

  async function handleCurrencyChange(currency: Currency) {
    try {
      const result = await setBaseCurrency(currency)
      void mutateCache(apiKeys.preferences)
      if (result.preferences.monthly_income !== null) {
        setIncome(String(result.preferences.monthly_income))
        setHasSavedIncome(true)
        incomeEdited.current = false
      }
      if (result.ratesAvailable) {
        toast.success(
          result.preferences.income_converted
            ? `Base currency and saved income converted to ${currency}`
            : `Base currency changed to ${currency}`,
        )
      } else {
        toast.warning(
          `Base currency changed to ${currency}, but exchange rates are currently unavailable. Foreign-currency totals will be excluded.`,
        )
      }
    } catch (error) {
      toast.error(
        error instanceof Error
          ? error.message
          : 'Could not update your base currency.',
      )
    }
  }

  async function handleClearIncome() {
    setIncomeStatus('saving')
    try {
      const accessToken = await getAccessToken()
      if (!accessToken) throw new Error('Your session has expired.')
      await updatePreferences(accessToken, { monthly_income: null })
      setIncome('')
      incomeEdited.current = false
      setHasSavedIncome(false)
      setIncomeStatus('cleared')
      void mutateCache(apiKeys.preferences)
      setIncomeError('')
    } catch (error) {
      setIncomeStatus('error')
      setIncomeError(error instanceof Error ? error.message : 'Could not clear your income.')
    }
  }

  async function handleSignOut() {
    await signOut()
    router.push('/login')
  }

  function handleCreateAccount() {
    endDemo()
    window.location.replace('/login?mode=signup')
  }

  async function handleExport() {
    setExportBusy(true)
    try {
      const accessToken = await getAccessToken()
      if (!accessToken) throw new Error('Your session has expired.')
      const { blob, filename } = await downloadAccountExport(accessToken)
      const href = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = href
      link.download = filename
      document.body.appendChild(link)
      link.click()
      link.remove()
      window.setTimeout(() => URL.revokeObjectURL(href), 1_000)
      toast.success('Your Subtrack data export is ready')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Could not download your data.')
    } finally {
      setExportBusy(false)
    }
  }

  async function handleDeleteData() {
    if (deleteConfirmation !== DELETE_CONFIRMATION) return
    setDeleteBusy(true)
    const supabase = createClient()
    let gmailRevocationFailed = false
    try {
      const accessToken = await getAccessToken()
      if (!accessToken) throw new Error('Your session has expired.')
      const result = await deleteAccountData(accessToken, DELETE_CONFIRMATION)
      gmailRevocationFailed = result.gmail_revocation === 'failed'
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Your data was not deleted.')
      setDeleteBusy(false)
      return
    }

    // The destructive server operation has succeeded at this point. Keep
    // sign-out failure reporting separate so we never tell someone their data
    // remains after it was actually deleted.
    try {
      await supabase.auth.signOut({ scope: 'local' })
      router.replace(
        gmailRevocationFailed
          ? '/login?reason=data_deleted_gmail_revoke_failed'
          : '/login?reason=data_deleted',
      )
    } catch {
      setDeleteDialogOpen(false)
      setDeleteConfirmation('')
      setDeleteBusy(false)
      toast.warning('Your Subtrack data was deleted, but this browser could not sign out. Please use Sign out before leaving this device.')
    }
  }

  return (
    <div className="mx-auto w-full max-w-3xl space-y-6 px-4 py-8">
      <h1 className="text-2xl font-semibold tracking-tight">Account</h1>

      <section className="flex flex-col gap-5 rounded-2xl bg-card p-6 shadow-sm sm:flex-row sm:items-center">
        <UserAvatar
          name={currentUser.name}
          email={currentUser.email}
          avatarUrl={currentUser.avatarUrl}
          className="h-16 w-16 text-lg"
        />
        <div className="min-w-0 flex-1">
          <p className="truncate text-lg font-semibold text-foreground">
            {currentUser.name || currentUser.email || 'Your account'}
          </p>
          {currentUser.name && currentUser.email ? (
            <p className="truncate text-sm text-muted-foreground">{currentUser.email}</p>
          ) : null}
          <div className="mt-2 flex flex-wrap gap-2 text-xs">
            {currentUser.signInMethod ? (
              <span className="rounded-full bg-muted px-2.5 py-1 font-medium text-foreground">
                {currentUser.isDemo ? 'Demo session' : `Signed in with ${currentUser.signInMethod}`}
              </span>
            ) : null}
            {currentUser.memberSince && !currentUser.isDemo ? (
              <span className="rounded-full bg-muted px-2.5 py-1 text-muted-foreground">
                Member since {currentUser.memberSince}
              </span>
            ) : null}
          </div>
        </div>
        <Button variant="outline" onClick={handleSignOut} className="h-9 shrink-0 gap-2 px-4">
          <LogOut aria-hidden="true" />
          Sign out
        </Button>
      </section>

      <Section title="Preferences">
        <Row title="Appearance" description="System follows your device setting">
          <ThemeToggle />
        </Row>

        <Row title="Base currency" description="All amounts are displayed in this currency">
          <select
            value={baseCurrency}
            disabled={isLoading || currencyUpdating}
            onChange={event => void handleCurrencyChange(event.target.value as Currency)}
            aria-label="Base currency"
            className="rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground transition-shadow focus:outline-none focus:ring-2 focus:ring-primary/40"
          >
            {CURRENCIES.map(c => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>
        </Row>

        <Row
          title="Monthly income"
          description="Used to show what share of your income goes to recurring payments"
          note={incomeStatus === 'cleared' ? (
            <p role="status" className="mt-1.5 text-xs text-muted-foreground">Monthly income removed.</p>
          ) : incomeStatus === 'error' ? (
            <p role="alert" className="mt-1.5 text-xs text-destructive">{incomeError || 'Could not update your income.'}</p>
          ) : null}
        >
          <div className="flex flex-wrap items-center justify-end gap-2">
            <input
              type="number"
              min="0"
              inputMode="decimal"
              value={income}
              placeholder="0"
              onChange={e => {
                incomeEdited.current = true
                setIncome(e.target.value)
                setIncomeStatus('idle')
                setIncomeError('')
              }}
              aria-label={`Monthly income in ${baseCurrency}`}
              className="w-32 rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground transition-shadow focus:outline-none focus:ring-2 focus:ring-primary/40"
            />
            <Button
              type="button"
              onClick={handleSaveIncome}
              disabled={incomeStatus === 'saving' || income === ''}
            >
              {incomeStatus === 'saving' ? 'Saving' : incomeStatus === 'saved' ? 'Saved' : 'Save'}
            </Button>
            {hasSavedIncome ? (
              <Button
                type="button"
                variant="ghost"
                onClick={handleClearIncome}
                disabled={incomeStatus === 'saving'}
                className="text-muted-foreground"
              >
                Clear
              </Button>
            ) : null}
          </div>
        </Row>
      </Section>

      {gmail && (
        <div id="inbox" className="scroll-mt-6 rounded-2xl bg-card shadow-sm p-6 space-y-4">
          <div>
            <h2 className="text-lg font-semibold">Email connection</h2>
            <p className="mt-1 text-xs text-muted-foreground">
              Let Subtrack find recurring payments in Gmail receipts for you to review.
            </p>
          </div>

          {currentUser.isDemo ? (
            <div className="flex flex-col gap-4 rounded-xl bg-muted/50 p-4 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <p className="text-sm font-medium">Not available in the demo</p>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  The demo uses sample findings instead of a real inbox. Create a free account to connect your own Gmail.
                </p>
              </div>
              <Button variant="outline" onClick={handleCreateAccount} className="shrink-0">
                Create a free account
              </Button>
            </div>
          ) : gmail.connected ? (
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
                    disabled={gmailBusy || gmail.scan_status === 'running' || gmail.configured === false}
                  >
                    {gmail.scan_status === 'running' ? 'Scanning' : 'Scan inbox'}
                  </Button>
                </div>
              </div>

              {gmail.scan_error && (
                <p className="text-xs text-destructive">Last scan failed: {gmail.scan_error}</p>
              )}

              {gmail.configured === false ? (
                <p className="text-xs text-amber-700 dark:text-amber-300">
                  Gmail credentials are not configured for this deployment. Your saved connection is retained, but scanning is unavailable until the operator fixes the server configuration.
                </p>
              ) : null}

              {(gmail.scan_status === 'running' || gmail.scan_partial) && (
                <GmailScanProgress gmail={gmail} compact />
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
              {shownGmailError && (
                <div className="rounded-lg border border-destructive/25 bg-destructive/5 p-3">
                  <p className="text-sm font-medium text-destructive">
                    Couldn&apos;t connect Gmail
                  </p>
                  <p className="mt-0.5 text-xs text-muted-foreground">{shownGmailError}</p>
                </div>
              )}

              <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <p className="text-sm font-medium">Connect Gmail</p>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    Find recurring payments from your receipt emails instead of adding them
                    by hand. Read-only, and nothing is added without your approval.
                  </p>
                  {/* Google renders read access to Gmail as its own tickbox and
                      leaves it unticked. Continuing past it returns a valid
                      token that cannot read any mail, so the connection fails
                      at the last step — by far the most common first attempt.
                      Saying so up front is cheaper than explaining it after. */}
                  <p className="text-xs text-muted-foreground mt-1.5">
                    Google will show a tickbox for viewing your email. It starts
                    unticked — tick it, or the connection can&apos;t be completed.
                  </p>
                </div>
                {gmail.configured === false ? (
                  <span className="shrink-0 rounded-full bg-muted px-3 py-1.5 text-xs font-medium text-muted-foreground">
                    Not configured
                  </span>
                ) : (
                  <Button onClick={handleConnectGmail} disabled={gmailBusy} className="shrink-0">
                    Connect Gmail
                  </Button>
                )}
              </div>
              {gmail.configured === false ? (
                <p className="text-xs text-amber-700 dark:text-amber-300">
                  This deployment cannot connect Gmail until its Google OAuth credentials and encryption key are configured.
                </p>
              ) : null}
            </div>
          )}
        </div>
      )}

      <Section title="Help">
        <Row title="Guided tour" description="A quick walkthrough of where everything lives">
          <Button
            variant="outline"
            size="sm"
            onClick={() => window.dispatchEvent(new Event(START_TOUR_EVENT))}
          >
            Replay tour
          </Button>
        </Row>
      </Section>

      <Section title="Your data">
        <Row
          title="Download your data"
          description="Export payments, reminders, review findings, preferences, and assistant history as JSON. Secret tokens are excluded."
        >
          <Button variant="outline" onClick={handleExport} disabled={exportBusy}>
            {exportBusy ? 'Preparing…' : 'Download export'}
          </Button>
        </Row>
      </Section>

      <Section title="Danger zone" tone="danger">
        <Row
          title="Delete Subtrack app data"
          description={currentUser.isDemo
            ? 'Not available in the demo. Demo data is cleared automatically after 24 hours.'
            : 'Permanently deletes your Subtrack records and disconnects Gmail. Your sign-in account itself remains.'}
        >
          <Button
            variant="destructive"
            onClick={() => setDeleteDialogOpen(true)}
            disabled={currentUser.isDemo}
          >
            Delete app data
          </Button>
        </Row>
      </Section>

      <Dialog
        open={deleteDialogOpen}
        onOpenChange={open => {
          if (deleteBusy) return
          setDeleteDialogOpen(open)
          if (!open) setDeleteConfirmation('')
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete all Subtrack app data?</DialogTitle>
            <DialogDescription>
              This permanently removes your payments, reminders, Gmail findings and connection, preferences, and assistant history. It cannot be undone. Your external Supabase sign-in identity is not deleted.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <label htmlFor="delete-app-data-confirmation" className="text-sm font-medium">
              Type <span className="font-mono text-xs">{DELETE_CONFIRMATION}</span> to continue
            </label>
            <Input
              id="delete-app-data-confirmation"
              autoComplete="off"
              spellCheck={false}
              value={deleteConfirmation}
              onChange={event => setDeleteConfirmation(event.target.value)}
              aria-invalid={deleteConfirmation.length > 0 && deleteConfirmation !== DELETE_CONFIRMATION}
            />
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setDeleteDialogOpen(false)}
              disabled={deleteBusy}
            >
              Keep my data
            </Button>
            <Button
              variant="destructive"
              onClick={handleDeleteData}
              disabled={deleteBusy || deleteConfirmation !== DELETE_CONFIRMATION}
            >
              {deleteBusy ? 'Deleting…' : 'Permanently delete'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

    </div>
  )
}

function Section({
  title,
  tone,
  children,
}: {
  title: string
  tone?: 'danger'
  children: React.ReactNode
}) {
  return (
    <section
      className={
        tone === 'danger'
          ? 'rounded-2xl border border-destructive/30 bg-card p-6 shadow-sm'
          : 'rounded-2xl bg-card p-6 shadow-sm'
      }
    >
      <h2 className={tone === 'danger' ? 'text-lg font-semibold text-destructive' : 'text-lg font-semibold'}>
        {title}
      </h2>
      <div className="mt-2 divide-y divide-border">{children}</div>
    </section>
  )
}

function Row({
  title,
  description,
  note,
  children,
}: {
  title: string
  description: string
  note?: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <div className="flex flex-col gap-3 py-4 last:pb-0 sm:flex-row sm:items-center sm:justify-between">
      <div className="min-w-0">
        <p className="text-sm font-medium">{title}</p>
        <p className="mt-0.5 text-xs text-muted-foreground">{description}</p>
        {note}
      </div>
      <div className="shrink-0">{children}</div>
    </div>
  )
}
