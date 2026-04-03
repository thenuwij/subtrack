'use client'

import { useEffect, useState } from 'react'
import { createClient } from '@/lib/supabase/client'
import { getSubscriptions, createSubscription, deleteSubscription, updateSubscription } from '@/lib/api'
import { Subscription } from '@/types'
import { SubscriptionCard }       from '@/components/subscriptions/SubscriptionCard'
import { AddSubscriptionModal }   from '@/components/subscriptions/AddSubscriptionModal'
import { Button }                 from '@/components/ui/button'
import { Skeleton }               from '@/components/ui/skeleton'
import { Plus, CreditCard }       from 'lucide-react'
import { useCurrency } from '@/lib/context/currency'
import { toast } from 'sonner'

// ─── helpers ─────────────────────────────────────────────────────────────────

function monthlyEquivalent(sub: Subscription): number {
  const amount = sub.converted_amount ?? sub.amount
  if (sub.cycle === 'weekly')  return amount * 52  / 12
  if (sub.cycle === 'yearly')  return amount       / 12
  return amount
}

// ─── page ─────────────────────────────────────────────────────────────────────

export default function SubscriptionsPage() {
  const supabase = createClient()

  const [subscriptions, setSubscriptions] = useState<Subscription[]>([])
  const [loading, setLoading]             = useState(true)
  const [error, setError]                 = useState<string | null>(null)
  const [modalOpen, setModalOpen]         = useState(false)
  const { baseCurrency } = useCurrency()

  // ── fetch ──────────────────────────────────────────────────────────────────

  async function fetchSubscriptions() {
    const { data: { session } } = await supabase.auth.getSession()
    if (!session) return

    try {
      const data = await getSubscriptions(session.access_token)
      setSubscriptions(data)
    } catch (e: any) {
      setError(e?.message ?? 'Failed to load subscriptions.')
      toast.error('Something went wrong')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchSubscriptions() }, []) // eslint-disable-line

  // ── add ────────────────────────────────────────────────────────────────────

  async function handleAdd(formData: Omit<Subscription, 'id' | 'user_id' | 'created_at'>) {
    const { data: { session } } = await supabase.auth.getSession()
    if (!session) throw new Error('Not authenticated')

    const created = await createSubscription(session.access_token, formData)
    setSubscriptions(prev => [created, ...prev])
    toast.success('Subscription added')
  }
    
  // ── update ─────────────────────────────────────────────────────────────────
  const [editingSubscription, setEditingSubscription] = useState<Subscription | null>(null)

  async function handleEdit(formData: Omit<Subscription, 'id' | 'user_id' | 'created_at'>) {
    const { data: { session } } = await supabase.auth.getSession()
    if (!session || !editingSubscription) throw new Error('Not authenticated')
    const updated = await updateSubscription(session.access_token, editingSubscription.id, formData)
    setSubscriptions(prev => prev.map(s => s.id === editingSubscription.id ? updated : s))
    setEditingSubscription(null)
    toast.success('Subscription updated')
  }

  // ── delete ─────────────────────────────────────────────────────────────────

  async function handleDelete(id: string) {
    const { data: { session } } = await supabase.auth.getSession()
    if (!session) throw new Error('Not authenticated')

    await deleteSubscription(session.access_token, id)
    setSubscriptions(prev => prev.filter(s => s.id !== id))
    toast.success('Subscription deleted')
  }

  // ── derived stats ──────────────────────────────────────────────────────────

  const active       = subscriptions.filter(s => s.is_active)
  const totalMonthly = active.reduce((sum, s) => sum + monthlyEquivalent(s), 0)

  // ─── render ────────────────────────────────────────────────────────────────

  return (
    <div className="max-w-2xl mx-auto px-4 py-8 space-y-6">

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Subscriptions</h1>
          {!loading && subscriptions.length > 0 && (
            <p className="text-sm text-muted-foreground mt-0.5">
              {active.length} active · ~{baseCurrency} {totalMonthly.toFixed(2)}/mo
            </p>
          )}
        </div>
        <Button onClick={() => setModalOpen(true)} size="sm">
          <Plus className="w-4 h-4 mr-1.5" />
          Add
        </Button>
      </div>

      {/* Error */}
      {error && (
        <div className="rounded-md border border-destructive/40 bg-destructive/5 px-4 py-3">
          <p className="text-sm text-destructive">{error}</p>
          <button
            className="text-xs text-destructive underline underline-offset-2 mt-1"
            onClick={() => { setError(null); setLoading(true); fetchSubscriptions() }}
          >
            Try again
          </button>
        </div>
      )}

      {/* Loading */}
      {loading && (
        <div className="space-y-3">
          {[...Array(4)].map((_, i) => (
            <Skeleton key={i} className="h-[76px] w-full rounded-lg" />
          ))}
        </div>
      )}

      {/* Empty state */}
      {!loading && !error && subscriptions.length === 0 && (
        <div className="flex flex-col items-center justify-center py-20 text-center">
          <div className="rounded-full bg-muted p-4 mb-4">
            <CreditCard className="w-6 h-6 text-muted-foreground" />
          </div>
          <p className="font-medium text-sm">No subscriptions yet</p>
          <p className="text-sm text-muted-foreground mt-1 mb-4">
            Add your first subscription to start tracking.
          </p>
          <Button size="sm" onClick={() => setModalOpen(true)}>
            <Plus className="w-4 h-4 mr-1.5" />
            Add subscription
          </Button>
        </div>
      )}

      {/* List */}
      {!loading && subscriptions.length > 0 && (
        <div className="space-y-2.5">
          {subscriptions.map(sub => (
            <SubscriptionCard
              key={sub.id}
              subscription={sub}
              onDelete={handleDelete}
              onEdit={setEditingSubscription}
            />
          ))}
        </div>
      )}

      {/* Add Modal */}
      <AddSubscriptionModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        onSubmit={handleAdd}
      />

      {/* Edit Modal */}
      <AddSubscriptionModal
        open={!!editingSubscription}
        onClose={() => setEditingSubscription(null)}
        onSubmit={handleEdit}
        initialData={editingSubscription ?? undefined}
      />

    </div>
  )
}