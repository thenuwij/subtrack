'use client'

import { useEffect, useState } from 'react'
import { createClient } from '@/lib/supabase/client'
import { getSubscriptions, getExpenses, getBudgets } from '@/lib/api'
import type { Subscription, Expense, Budget } from '@/types'

export default function DashboardPage() {
  const [subscriptions, setSubscriptions] = useState<Subscription[]>([])
  const [expenses, setExpenses] = useState<Expense[]>([])
  const [budgets, setBudgets] = useState<Budget[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    async function fetchData() {
      const supabase = createClient()
      const { data: { session } } = await supabase.auth.getSession()
      if (!session) return

      const token = session.access_token
      const [subs, exps, buds] = await Promise.all([
        getSubscriptions(token),
        getExpenses(token),
        getBudgets(token),
      ])
      setSubscriptions(subs)
      setExpenses(exps)
      setBudgets(buds)
      setLoading(false)
    }
    fetchData()
  }, [])

  function toMonthly(amount: number, cycle: string) {
    if (cycle === 'weekly') return amount * 4.33
    if (cycle === 'yearly') return amount / 12
    return amount
  }

  const monthlyBurn = subscriptions.reduce(
    (sum, s) => sum + toMonthly(s.amount, s.cycle), 0
  )

  const thisMonth = new Date()
  const monthlyExpenses = expenses.filter(e => {
    const d = new Date(e.date)
    return d.getMonth() === thisMonth.getMonth() &&
      d.getFullYear() === thisMonth.getFullYear()
  })
  const totalExpenses = monthlyExpenses.reduce((sum, e) => sum + e.amount, 0)

  const upcoming = subscriptions
    .filter(s => s.next_due)
    .sort((a, b) => new Date(a.next_due!).getTime() - new Date(b.next_due!).getTime())
    .slice(0, 5)

  if (loading) return (
    <div className="flex items-center justify-center h-64 text-gray-400">
      Loading...
    </div>
  )

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <h1 className="text-2xl font-semibold text-gray-900 mb-6">Dashboard</h1>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-8">
        <div className="bg-white rounded-2xl border border-gray-100 p-5">
          <p className="text-xs text-gray-400 uppercase tracking-wide mb-1">Monthly subscriptions</p>
          <p className="text-2xl font-semibold">${monthlyBurn.toFixed(2)}</p>
          <p className="text-xs text-gray-400 mt-1">${(monthlyBurn * 12).toFixed(0)}/year est.</p>
        </div>
        <div className="bg-white rounded-2xl border border-gray-100 p-5">
          <p className="text-xs text-gray-400 uppercase tracking-wide mb-1">Spent this month</p>
          <p className="text-2xl font-semibold">${totalExpenses.toFixed(2)}</p>
          <p className="text-xs text-gray-400 mt-1">{monthlyExpenses.length} transactions</p>
        </div>
        <div className="bg-white rounded-2xl border border-gray-100 p-5">
          <p className="text-xs text-gray-400 uppercase tracking-wide mb-1">Budgets active</p>
          <p className="text-2xl font-semibold">{budgets.length}</p>
          <p className="text-xs text-gray-400 mt-1">categories tracked</p>
        </div>
      </div>

      <div className="bg-white rounded-2xl border border-gray-100 p-5 mb-6">
        <h2 className="text-sm font-medium text-gray-700 mb-4">Upcoming bills</h2>
        {upcoming.length === 0 ? (
          <p className="text-gray-400 text-sm">No upcoming bills</p>
        ) : (
          <div className="divide-y divide-gray-50">
            {upcoming.map(s => (
              <div key={s.id} className="flex justify-between items-center py-3">
                <div>
                  <p className="text-sm font-medium text-gray-800">{s.name}</p>
                  <p className="text-xs text-gray-400">{s.category}</p>
                </div>
                <div className="text-right">
                  <p className="text-sm font-semibold">${s.amount.toFixed(2)}</p>
                  <p className="text-xs text-gray-400">
                    {s.next_due ? new Date(s.next_due).toLocaleDateString('en-AU') : ''}
                  </p>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="bg-white rounded-2xl border border-gray-100 p-5">
        <h2 className="text-sm font-medium text-gray-700 mb-4">Budget overview</h2>
        {budgets.length === 0 ? (
          <p className="text-gray-400 text-sm">No budgets set yet</p>
        ) : (
          <div className="space-y-3">
            {budgets.map(b => {
              const spent = monthlyExpenses
                .filter(e => e.category === b.category)
                .reduce((sum, e) => sum + e.amount, 0)
              const pct = Math.min((spent / b.monthly_limit) * 100, 100)
              return (
                <div key={b.id}>
                  <div className="flex justify-between text-sm mb-1">
                    <span className="text-gray-700 capitalize">{b.category}</span>
                    <span className="text-gray-500">${spent.toFixed(2)} / ${b.monthly_limit.toFixed(2)}</span>
                  </div>
                  <div className="w-full bg-gray-100 rounded-full h-1.5">
                    <div
                      className={`h-1.5 rounded-full ${pct >= 100 ? 'bg-red-400' : pct >= 80 ? 'bg-yellow-400' : 'bg-green-400'}`}
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}