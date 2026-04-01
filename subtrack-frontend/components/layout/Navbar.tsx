'use client'
import Link from 'next/link'
import { usePathname, useRouter } from 'next/navigation'
import { createClient } from '@/lib/supabase/client'
import { LayoutDashboard, CreditCard, Receipt, PiggyBank, LogOut } from 'lucide-react'
import { useCurrency } from '@/lib/context/currency'
import type { Currency } from '@/types'

const links = [
  { href: '/dashboard',     label: 'Dashboard',     icon: LayoutDashboard },
  { href: '/subscriptions', label: 'Subscriptions', icon: CreditCard },
  { href: '/expenses',      label: 'Expenses',       icon: Receipt },
  { href: '/budgets',       label: 'Budgets',        icon: PiggyBank },
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
    <aside className="w-52 min-h-screen bg-sidebar border-r border-border flex flex-col py-5 px-3">
      <div className="px-2 mb-7">
        <h1 className="text-sm font-semibold text-foreground tracking-tight">Subtrack</h1>
        <p className="text-xs text-muted-foreground">Finance tracker</p>
      </div>

      <nav className="flex flex-col gap-0.5 flex-1">
        {links.map(({ href, label, icon: Icon }) => (
          <Link
            key={href}
            href={href}
            className={`flex items-center gap-2.5 px-2 py-1.5 rounded-md text-sm transition-colors ${
              pathname === href
                ? 'bg-indigo-50 text-indigo-600 font-medium'
                : 'text-muted-foreground hover:bg-muted hover:text-foreground'
            }`}
          >
            <Icon className="w-4 h-4 shrink-0" />
            {label}
          </Link>
        ))}
      </nav>

      {/* Currency selector */}
      <div className="px-2 mb-3">
        <p className="text-xs text-muted-foreground mb-1.5">Base currency</p>
        <select
          value={baseCurrency}
          disabled={isLoading}
          onChange={e => setBaseCurrency(e.target.value as Currency)}
          className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-ring"
        >
          {CURRENCIES.map(c => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>
      </div>

      <button
        onClick={handleLogout}
        className="flex items-center gap-2.5 px-2 py-1.5 rounded-md text-sm text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
      >
        <LogOut className="w-4 h-4 shrink-0" />
        Logout
      </button>
    </aside>
  )
}