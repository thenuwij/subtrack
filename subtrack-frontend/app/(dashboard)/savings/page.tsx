'use client'

import { useEffect, useState } from 'react'
import { createClient } from '@/lib/supabase/client'
import { getSavingsGoals, createSavingsGoal, deleteSavingsGoal, updateSavingsGoal } from '@/lib/api'
import { SavingsGoal } from '@/types'
import { SavingsCard }       from '@/components/savings/SavingsCard'
import { AddSavingsModal }   from '@/components/savings/AddSavingsModal'
import { Button }            from '@/components/ui/button'
import { Skeleton }          from '@/components/ui/skeleton'
import { Plus, Target }      from 'lucide-react'
import { toast } from 'sonner'

export default function SavingsPage() {
  const supabase = createClient()

  const [goals, setGoals]         = useState<SavingsGoal[]>([])
  const [loading, setLoading]     = useState(true)
  const [error, setError]         = useState<string | null>(null)
  const [modalOpen, setModalOpen] = useState(false)
  const [editingGoal, setEditingGoal] = useState<SavingsGoal | null>(null)

  async function fetchGoals() {
    const { data: { session } } = await supabase.auth.getSession()
    if (!session) return
    try {
      const data = await getSavingsGoals(session.access_token)
      setGoals(data)
    } catch (e: any) {
      setError(e?.message ?? 'Failed to load savings goals.')
      toast.error('Something went wrong')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchGoals() }, []) // eslint-disable-line

  async function handleAdd(formData: Omit<SavingsGoal, 'id' | 'user_id' | 'created_by' | 'created_at' | 'completed_at'>) {
    const { data: { session } } = await supabase.auth.getSession()
    if (!session) throw new Error('Not authenticated')
    const created = await createSavingsGoal(session.access_token, formData)
    setGoals(prev => [created, ...prev])
    toast.success('Goal created')
  }

  async function handleEdit(formData: Omit<SavingsGoal, 'id' | 'user_id' | 'created_by' | 'created_at' | 'completed_at'>) {
    const { data: { session } } = await supabase.auth.getSession()
    if (!session || !editingGoal) throw new Error('Not authenticated')
    const updated = await updateSavingsGoal(session.access_token, editingGoal.id, formData)
    setGoals(prev => prev.map(g => g.id === editingGoal.id ? updated : g))
    setEditingGoal(null)
    toast.success('Goal updated')
  }

  async function handleDelete(id: string) {
    const { data: { session } } = await supabase.auth.getSession()
    if (!session) throw new Error('Not authenticated')
    await deleteSavingsGoal(session.access_token, id)
    setGoals(prev => prev.filter(g => g.id !== id))
    toast.success('Goal deleted')
  }

  async function handleComplete(id: string) {
    const { data: { session } } = await supabase.auth.getSession()
    if (!session) throw new Error('Not authenticated')
    const updated = await updateSavingsGoal(session.access_token, id, {
      completed_at: new Date().toISOString(),
    })
    setGoals(prev => prev.map(g => g.id === id ? updated : g))
    toast.success('Goal completed!')
  }

  const activeCount    = goals.filter(g => !g.completed_at).length
  const completedCount = goals.filter(g => !!g.completed_at).length

  return (
    <div className="mx-auto w-full max-w-5xl px-4 py-8 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Savings</h1>
          {!loading && goals.length > 0 && (
            <p className="text-sm text-muted-foreground mt-0.5">
              {activeCount} active{completedCount > 0 ? ` · ${completedCount} completed` : ''}
            </p>
          )}
        </div>
        <Button onClick={() => setModalOpen(true)} size="sm">
          <Plus className="w-4 h-4 mr-1.5" />
          Add
        </Button>
      </div>

      {error && (
        <div className="rounded-md border border-destructive/40 bg-destructive/5 px-4 py-3">
          <p className="text-sm text-destructive">{error}</p>
          <button
            className="text-xs text-destructive underline underline-offset-2 mt-1"
            onClick={() => { setError(null); setLoading(true); fetchGoals() }}
          >
            Try again
          </button>
        </div>
      )}

      {loading && (
        <div className="space-y-3">
          {[...Array(4)].map((_, i) => (
            <Skeleton key={i} className="h-[100px] w-full rounded-lg" />
          ))}
        </div>
      )}

      {!loading && !error && goals.length === 0 && (
        <div className="flex flex-col items-center justify-center py-20 text-center">
          <div className="rounded-full bg-muted p-4 mb-4">
            <Target className="w-6 h-6 text-muted-foreground" />
          </div>
          <p className="font-medium text-sm">No savings goals yet</p>
          <p className="text-sm text-muted-foreground mt-1 mb-4">
            Create a goal to start tracking your progress.
          </p>
          <Button size="sm" onClick={() => setModalOpen(true)}>
            <Plus className="w-4 h-4 mr-1.5" />
            Create goal
          </Button>
        </div>
      )}

      {!loading && goals.length > 0 && (
        <div className="space-y-2.5">
          {goals.map(goal => (
            <SavingsCard
              key={goal.id}
              goal={goal}
              onDelete={handleDelete}
              onEdit={setEditingGoal}
              onComplete={handleComplete}
            />
          ))}
        </div>
      )}

      <AddSavingsModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        onSubmit={handleAdd}
      />
      <AddSavingsModal
        open={!!editingGoal}
        onClose={() => setEditingGoal(null)}
        onSubmit={handleEdit}
        initialData={editingGoal ?? undefined}
      />
    </div>
  )
}
