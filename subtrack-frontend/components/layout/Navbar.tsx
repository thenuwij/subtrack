'use client'
import Link from 'next/link'
import { usePathname, useRouter } from 'next/navigation'
import { createClient } from '@/lib/supabase/client'
import { LayoutDashboard, CreditCard, LogOut, UserCircle, MailCheck, Sparkles } from 'lucide-react'
import { getDetected, getGmailStatus } from '@/lib/api'
import { apiKeys, useApi } from '@/lib/hooks/useApi'
import { endDemo } from '@/lib/auth/session'
import type { GmailStatus } from '@/types'
import { Logo, LogoMark } from '@/components/layout/Logo'

const links = [
  { href: '/dashboard',     label: 'Dashboard',     icon: LayoutDashboard },
  { href: '/subscriptions', label: 'Payments',      icon: CreditCard },
  { href: '/review',        label: 'Inbox',         icon: MailCheck },
  { href: '/assistant',     label: 'Assistant',     icon: Sparkles },
  { href: '/account',       label: 'Account',       icon: UserCircle },
]

export default function Navbar() {
  const pathname = usePathname()
  const router = useRouter()
  const detected = useApi(apiKeys.detected('pending'), token => getDetected(token, 'pending'))
  const gmail = useApi<GmailStatus>(apiKeys.gmailStatus, token => getGmailStatus(token))
  const pendingCount = detected.data?.length ?? 0
  const gmailConnected = gmail.data ? gmail.data.connected : null

  async function handleLogout() {
    endDemo()
    await createClient().auth.signOut()
    router.push('/login')
  }

  function renderNavItems(mobile = false) {
    return links.map(({ href, label, icon: Icon }) => {
      const active = pathname === href
      return (
        <Link
          key={href}
          href={href}
          data-tour={`nav-${href.slice(1)}`}
          aria-current={active ? 'page' : undefined}
          className={mobile
            ? `relative flex min-w-0 flex-1 flex-col items-center gap-1 rounded-lg px-1 py-2 text-[10px] font-medium transition-colors ${
                active ? 'text-primary' : 'text-muted-foreground hover:text-foreground'
              }`
            : `group relative flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors ${
                active
                  ? 'bg-primary/10 text-primary font-medium'
                  : 'text-muted-foreground hover:bg-muted hover:text-foreground'
              }`
          }
        >
          {/* An active-state marker that doesn't rely on colour alone. */}
          {!mobile && active && (
            <span
              className="absolute left-0 top-1/2 h-4 w-0.5 -translate-y-1/2 rounded-r-full bg-primary"
              aria-hidden="true"
            />
          )}
          <Icon className="h-4 w-4 shrink-0" />
          <span className={mobile ? 'truncate' : undefined}>{label}</span>
          {href === '/review' && pendingCount > 0 && (
            <span
              aria-label={`${pendingCount} waiting for review`}
              className={mobile
                ? 'absolute right-[calc(50%-18px)] top-1 rounded-full bg-primary px-1 text-[9px] font-semibold leading-4 text-primary-foreground'
                : 'ml-auto rounded-full bg-primary px-1.5 py-0.5 text-[10px] font-semibold leading-none text-primary-foreground'
              }
            >
              {pendingCount}
            </span>
          )}
        </Link>
      )
    })
  }

  return (
    <>
      {/* Mobile top bar */}
      <header className="fixed inset-x-0 top-0 z-40 flex h-14 items-center border-b border-border bg-sidebar/80 px-4 backdrop-blur-xl md:hidden">
        <Link href="/dashboard" className="flex items-center gap-2" aria-label="Subtrack dashboard">
          <LogoMark className="h-6 w-6" />
          <span className="text-sm font-semibold tracking-tight text-foreground">Subtrack</span>
        </Link>
        <button
          type="button"
          onClick={handleLogout}
          aria-label="Log out"
          className="ml-auto flex h-9 w-9 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
        >
          <LogOut className="h-4 w-4" />
        </button>
      </header>

      <aside className="hidden w-60 shrink-0 flex-col border-r border-border bg-sidebar px-3 py-6 md:flex">
        <div className="mb-8 px-3">
          <Link href="/dashboard" aria-label="Subtrack dashboard">
            <Logo />
          </Link>
        </div>

        <nav className="flex flex-1 flex-col gap-0.5" aria-label="Main">
          {renderNavItems()}
        </nav>

        {gmailConnected === false && (
          <Link
            href="/account#inbox"
            className="mx-1 mb-4 rounded-xl bg-card p-3 shadow-sm transition-colors hover:bg-muted/60"
          >
            <p className="text-xs font-semibold text-foreground">Connect your inbox</p>
            <p className="mt-1 text-[11px] leading-4 text-muted-foreground">
              Find recurring payments from Gmail receipts.
            </p>
            <p className="mt-2 text-xs font-medium text-primary">Set up Gmail →</p>
          </Link>
        )}

        <button
          onClick={handleLogout}
          className="mx-0 flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
        >
          <LogOut className="h-4 w-4 shrink-0" />
          Logout
        </button>
      </aside>

      <nav
        className="fixed inset-x-0 bottom-0 z-40 flex border-t border-border bg-card/80 px-1 pb-[env(safe-area-inset-bottom)] backdrop-blur-xl md:hidden"
        aria-label="Main"
      >
        {renderNavItems(true)}
      </nav>
    </>
  )
}
