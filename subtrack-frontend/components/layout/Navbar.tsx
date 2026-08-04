'use client'
import Link from 'next/link'
import { usePathname, useRouter } from 'next/navigation'
import { createClient } from '@/lib/supabase/client'
import { useEffect, useState } from 'react'
import { LayoutDashboard, CreditCard, Target, LogOut, UserCircle, MailCheck } from 'lucide-react'
import { getDetected, getGmailStatus } from '@/lib/api'
import { useCurrency } from '@/lib/context/currency'
import type { Currency } from '@/types'

const links = [
  { href: '/dashboard',     label: 'Dashboard',     icon: LayoutDashboard },
  { href: '/subscriptions', label: 'Payments',      icon: CreditCard },
  { href: '/review',        label: 'Inbox',         icon: MailCheck },
  { href: '/savings',       label: 'Savings',       icon: Target },
  { href: '/account',       label: 'Account',       icon: UserCircle },
]

const CURRENCIES: Currency[] = ['AUD', 'USD', 'GBP', 'SGD', 'EUR', 'JPY']

export default function Navbar() {
  const pathname = usePathname()
  const router = useRouter()
  const { baseCurrency, setBaseCurrency, isLoading } = useCurrency()
  const [pendingCount, setPendingCount] = useState(0)
  const [gmailConnected, setGmailConnected] = useState<boolean | null>(null)

  useEffect(() => {
    async function loadPending() {
      const { data: { session } } = await createClient().auth.getSession()
      if (!session) return
      try {
        const [detected, gmail] = await Promise.all([
          getDetected(session.access_token),
          getGmailStatus(session.access_token).catch(() => null),
        ])
        setPendingCount(detected.length)
        setGmailConnected(gmail?.connected ?? null)
      } catch {
        // A badge is not worth surfacing an error for.
      }
    }
    loadPending()
  }, [pathname])

  async function handleLogout() {
    await createClient().auth.signOut()
    router.push('/login')
  }

  function renderNavItems(mobile = false) {
    return links.map(({ href, label, icon: Icon }) => (
      <Link
        key={href}
        href={href}
        aria-current={pathname === href ? 'page' : undefined}
        className={mobile
          ? `relative flex min-w-0 flex-1 flex-col items-center gap-1 rounded-lg px-1 py-2 text-[10px] font-medium transition-colors ${
              pathname === href ? 'text-primary' : 'text-muted-foreground hover:text-foreground'
            }`
          : `flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors ${
              pathname === href
                ? 'bg-primary/10 text-primary font-medium'
                : 'text-muted-foreground hover:bg-muted hover:text-foreground'
            }`
        }
      >
        <Icon className={mobile ? 'h-4 w-4 shrink-0' : 'h-4 w-4 shrink-0'} />
        <span className={mobile ? 'truncate' : undefined}>{label}</span>
        {href === '/review' && pendingCount > 0 && (
          <span className={mobile
            ? 'absolute right-[calc(50%-18px)] top-1 rounded-full bg-primary px-1 text-[9px] font-semibold leading-4 text-primary-foreground'
            : 'ml-auto rounded-full bg-primary px-1.5 py-0.5 text-[10px] font-semibold leading-none text-primary-foreground'
          }>
            {pendingCount}
          </span>
        )}
      </Link>
    ))
  }

  return (
    <>
      <header className="fixed inset-x-0 top-0 z-40 flex h-14 items-center border-b border-border bg-sidebar/95 px-4 backdrop-blur md:hidden">
        <Link href="/dashboard" className="flex items-center gap-2" aria-label="Subtrack dashboard">
          <div className="flex h-6 w-6 items-center justify-center rounded-md bg-primary">
            <span className="text-xs font-bold text-primary-foreground">S</span>
          </div>
          <span className="text-sm font-semibold tracking-tight text-foreground">Subtrack</span>
        </Link>
      </header>

      <aside className="hidden w-56 min-h-screen bg-sidebar border-r border-border md:flex flex-col py-6 px-3">
      
      {/* Logo */}
      <div className="px-3 mb-8">
        <div className="flex items-center gap-2">
          <div className="w-6 h-6 rounded-md bg-primary flex items-center justify-center">
            <span className="text-xs font-bold text-primary-foreground">S</span>
          </div>
          <h1 className="text-sm font-semibold text-foreground tracking-tight">Subtrack</h1>
        </div>
        <p className="text-xs text-muted-foreground mt-1 ml-8">Recurring payment tracker</p>
      </div>

      {/* Nav links */}
      <nav className="flex flex-col gap-0.5 flex-1">
        {renderNavItems()}
      </nav>

      {gmailConnected === false && (
        <Link
          href="/account#inbox"
          className="mx-1 mb-4 rounded-xl border border-border bg-card p-3 shadow-sm transition-colors hover:bg-muted/60"
        >
          <p className="text-xs font-semibold text-foreground">Connect your inbox</p>
          <p className="mt-1 text-[11px] leading-4 text-muted-foreground">
            Find recurring payments from Gmail receipts.
          </p>
          <p className="mt-2 text-xs font-medium text-primary">Set up Gmail →</p>
        </Link>
      )}

      {/* Currency selector */}
      <div className="px-3 mb-4">
        <p className="text-xs font-medium text-muted-foreground mb-2">Base currency</p>
        <select
          value={baseCurrency}
          disabled={isLoading}
          onChange={e => setBaseCurrency(e.target.value as Currency)}
          className="w-full rounded-lg border border-border bg-card px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-primary/40 transition-shadow"
        >
          {CURRENCIES.map(c => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>
      </div>

      {/* Logout */}
      <button
        onClick={handleLogout}
        className="flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm text-muted-foreground hover:bg-muted hover:text-foreground transition-colors mx-0"
      >
        <LogOut className="w-4 h-4 shrink-0" />
        Logout
      </button>
      </aside>

      <nav className="fixed inset-x-0 bottom-0 z-40 flex border-t border-border bg-card/95 px-1 pb-[env(safe-area-inset-bottom)] backdrop-blur md:hidden" aria-label="Primary navigation">
        {renderNavItems(true)}
      </nav>
    </>
  )
}
