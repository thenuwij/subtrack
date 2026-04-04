'use client'
import Link from 'next/link'
import { usePathname, useRouter } from 'next/navigation'
import { createClient } from '@/lib/supabase/client'
import { LayoutDashboard, CreditCard, Receipt, PiggyBank, TrendingUp, Target, LogOut, UserCircle } from 'lucide-react'
import { useCurrency } from '@/lib/context/currency'
import type { Currency } from '@/types'

const links = [
  { href: '/dashboard',     label: 'Dashboard',     icon: LayoutDashboard },
  { href: '/subscriptions', label: 'Subscriptions', icon: CreditCard },
  { href: '/expenses',      label: 'Expenses',      icon: Receipt },
  { href: '/income',        label: 'Income',        icon: TrendingUp },
  { href: '/budgets',       label: 'Budgets',       icon: PiggyBank },
  { href: '/savings',       label: 'Savings',       icon: Target },
  { href: '/account',       label: 'Account',       icon: UserCircle },
]

const CURRENCIES: Currency[] = ['AUD', 'USD', 'GBP', 'SGD', 'EUR', 'JPY']

export default function Navbar() {
  const pathname = usePathname()
  const router = useRouter()
  const { baseCurrency, setBaseCurrency, isLoading } = useCurrency()

  async function handleLogout() {
    await createClient().auth.signOut()
    router.push('/login')
  }

  return (
    <aside className="w-56 min-h-screen bg-sidebar border-r border-border flex flex-col py-6 px-3">
      
      {/* Logo */}
      <div className="px-3 mb-8">
        <div className="flex items-center gap-2">
          <div className="w-6 h-6 rounded-md bg-primary flex items-center justify-center">
            <span className="text-xs font-bold text-primary-foreground">S</span>
          </div>
          <h1 className="text-sm font-semibold text-foreground tracking-tight">Subtrack</h1>
        </div>
        <p className="text-xs text-muted-foreground mt-1 ml-8">Finance tracker</p>
      </div>

      {/* Nav links */}
      <nav className="flex flex-col gap-0.5 flex-1">
        {links.map(({ href, label, icon: Icon }) => (
          <Link
            key={href}
            href={href}
            className={`flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm transition-colors ${
              pathname === href
                ? 'bg-primary/10 text-primary font-medium'
                : 'text-muted-foreground hover:bg-muted hover:text-foreground'
            }`}
          >
            <Icon className="w-4 h-4 shrink-0" />
            {label}
          </Link>
        ))}
      </nav>

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
  )
}