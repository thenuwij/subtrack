'use client'

import Link from 'next/link'
import { usePathname, useRouter } from 'next/navigation'
import { createClient } from '@/lib/supabase/client'

const links = [
  { href: '/dashboard', label: 'Dashboard' },
  { href: '/subscriptions', label: 'Subscriptions' },
  { href: '/expenses', label: 'Expenses' },
  { href: '/budgets', label: 'Budgets' },
]

export default function Navbar() {
  const pathname = usePathname()
  const router = useRouter()

  async function handleLogout() {
    const supabase = createClient()
    await supabase.auth.signOut()
    router.push('/login')
  }

  return (
    <aside className="w-56 min-h-screen bg-white border-r border-gray-100 flex flex-col p-5">
      <div className="mb-8">
        <h1 className="text-lg font-semibold text-gray-900">Subtrack</h1>
        <p className="text-xs text-gray-400">Finance tracker</p>
      </div>

      <nav className="flex flex-col gap-1 flex-1">
        {links.map(link => (
          <Link
            key={link.href}
            href={link.href}
            className={`px-3 py-2 rounded-lg text-sm font-medium transition ${
              pathname === link.href
                ? 'bg-gray-100 text-gray-900'
                : 'text-gray-500 hover:bg-gray-50 hover:text-gray-900'
            }`}
          >
            {link.label}
          </Link>
        ))}
      </nav>

      <button
        onClick={handleLogout}
        className="px-3 py-2 rounded-lg text-sm font-medium text-gray-400 hover:bg-gray-50 hover:text-gray-900 transition text-left"
      >
        Logout
      </button>
    </aside>
  )
}