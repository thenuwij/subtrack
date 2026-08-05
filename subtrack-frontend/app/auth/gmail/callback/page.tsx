'use client'

import { useEffect, useRef } from 'react'
import { useRouter } from 'next/navigation'
import { completeGmailOAuth, SessionExpiredError } from '@/lib/api'
import { createClient } from '@/lib/supabase/client'
import { LogoMark } from '@/components/layout/Logo'

export default function GmailCallbackPage() {
  const router = useRouter()
  const started = useRef(false)

  useEffect(() => {
    if (started.current) return
    started.current = true

    // Google returns to the backend first; the backend puts the one-time
    // credentials in the fragment when it sends the browser back here.
    // Fragments are never included in the request to Vercel or in Referer
    // headers, which keeps the OAuth code and state out of infrastructure
    // logs. Capture them synchronously and scrub the URL before awaiting.
    const params = new URLSearchParams(window.location.hash.slice(1))
    const code = params.get('code')
    const state = params.get('state')
    const providerError = params.get('error')

    // OAuth codes and state are one-time credentials. Remove them from the
    // address bar and browser history before doing any asynchronous work.
    window.history.replaceState({}, '', window.location.pathname)

    async function complete() {
      if (providerError) {
        router.replace('/account?gmail_error=cancelled')
        return
      }
      if (!code || !state) {
        router.replace('/account?gmail_error=invalid_response')
        return
      }

      try {
        const { data: { session } } = await createClient().auth.getSession()
        if (!session) {
          router.replace('/login?reason=session_expired')
          return
        }
        await completeGmailOAuth(session.access_token, { code, state })
        router.replace('/account?gmail=connected')
      } catch (error) {
        // request() owns the expired-session redirect. Do not race it with an
        // account redirect after it has cleared the stale local credentials.
        if (error instanceof SessionExpiredError) return
        router.replace('/account?gmail_error=connection_failed')
      }
    }

    void complete()
  }, [router])

  return (
    <main className="flex min-h-screen items-center justify-center bg-background px-6">
      <div className="max-w-sm text-center" role="status" aria-live="polite">
        <LogoMark className="mx-auto h-10 w-10" />
        <span className="mx-auto mt-6 block h-5 w-5 animate-spin rounded-full border-2 border-muted-foreground/30 border-t-primary" aria-hidden="true" />
        <h1 className="mt-4 text-lg font-semibold text-foreground">Finishing Gmail connection</h1>
        <p className="mt-1 text-sm text-muted-foreground">This should only take a moment.</p>
      </div>
    </main>
  )
}
