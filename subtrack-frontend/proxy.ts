import { createServerClient } from '@supabase/ssr'
import { NextResponse, type NextRequest } from 'next/server'
import { supabaseAnonKey, supabaseUrl } from '@/lib/supabase/config'

// Next 16 renamed the `middleware` convention to `proxy`. It only runs from the
// project root — while this lived at app/middleware.ts it never executed at all.
export async function proxy(request: NextRequest) {
  let supabaseResponse = NextResponse.next({
    request,
  })

  const supabase = createServerClient(
    supabaseUrl,
    supabaseAnonKey,
    {
      cookies: {
        getAll() {
          return request.cookies.getAll()
        },
        setAll(cookiesToSet) {
          cookiesToSet.forEach(({ name, value }) =>
            request.cookies.set(name, value)
          )
          supabaseResponse = NextResponse.next({
            request,
          })
          cookiesToSet.forEach(({ name, value, options }) =>
            supabaseResponse.cookies.set(name, value, options)
          )
        },
      },
    }
  )

  /** Redirect without dropping refreshed auth cookies.
   *
   * `getUser()` below may rotate the refresh token. Supabase spends the old
   * one when it does, so returning a bare `NextResponse.redirect` — which
   * carries none of the cookies written above — leaves the browser holding a
   * token the server has already consumed. The next refresh then fails and the
   * user is signed out mid-session for no visible reason. */
  function redirectKeepingSession(path: string) {
    const response = NextResponse.redirect(new URL(path, request.url))
    for (const cookie of supabaseResponse.cookies.getAll()) {
      response.cookies.set(cookie)
    }
    return response
  }

  const {
    data: { user },
  } = await supabase.auth.getUser()

  const isAuthPage = request.nextUrl.pathname.startsWith('/login')
  const isProtectedPage = ['/dashboard', '/subscriptions', '/review', '/assistant', '/account'].some(
    path => request.nextUrl.pathname.startsWith(path)
  )

  if (!user && isProtectedPage) {
    return redirectKeepingSession('/login')
  }

  if (user && isAuthPage) {
    return redirectKeepingSession('/dashboard')
  }

  return supabaseResponse
}

export const config = {
  matcher: ['/dashboard/:path*', '/subscriptions/:path*', '/review/:path*', '/assistant/:path*', '/account/:path*', '/login'],
}
