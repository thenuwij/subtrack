import { createClient } from '@/lib/supabase/server'
import { NextResponse } from 'next/server'

/** Only same-site paths may be used as a post-callback destination.
 *
 * `next` arrives from a link in an email, so treating it as a bare redirect
 * target would let anyone craft a Subtrack sign-in link that lands on their
 * own site while the user believes they are still here. A leading `//` or
 * `/\` is how a protocol-relative URL smuggles a host past a naive
 * "starts with /" check, so both are rejected. */
function safeNext(value: string | null): string {
  if (!value || !value.startsWith('/')) return '/dashboard'
  if (value.startsWith('//') || value.startsWith('/\\')) return '/dashboard'
  return value
}

export async function GET(request: Request) {
  const { searchParams, origin } = new URL(request.url)
  const code = searchParams.get('code')
  const next = safeNext(searchParams.get('next'))

  if (code) {
    const supabase = await createClient()
    const { error } = await supabase.auth.exchangeCodeForSession(code)
    // An expired or already-used link would otherwise land on the dashboard
    // with no session, which the proxy bounces to /login with no explanation.
    if (error) {
      return NextResponse.redirect(`${origin}/login?reason=link_invalid`)
    }
  }

  return NextResponse.redirect(`${origin}${next}`)
}
