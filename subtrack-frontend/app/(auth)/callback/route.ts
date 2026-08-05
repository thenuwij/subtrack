import { NextResponse } from 'next/server'

/**
 * Legacy alias for /auth/callback.
 *
 * This route used to carry its own copy of the code exchange, which meant two
 * auth callbacks to keep in step — and the copy silently swallowed exchange
 * failures and never gained the same-site check on `next`. Nothing in the app
 * links here any more, but a stale entry in Supabase's redirect allowlist
 * still could, so the path forwards rather than being deleted.
 *
 * The query string carries the one-time code and is preserved verbatim; the
 * PKCE verifier cookie is same-origin, so it survives the hop.
 */
export async function GET(request: Request) {
  const { search, origin } = new URL(request.url)
  return NextResponse.redirect(`${origin}/auth/callback${search}`)
}
