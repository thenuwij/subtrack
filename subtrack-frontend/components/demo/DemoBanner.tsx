'use client'

import { useRouter } from 'next/navigation'
import { Sparkles } from 'lucide-react'
import { endDemo, useIsDemo } from '@/lib/auth/session'

export function DemoBanner() {
  const router = useRouter()
  const isDemo = useIsDemo()
  if (!isDemo) return null

  function leave() {
    endDemo()
    router.push('/login')
  }

  return (
    <div className="flex flex-wrap items-center justify-center gap-x-3 gap-y-1 border-b border-primary/20 bg-primary/10 px-4 py-2 text-center text-xs text-foreground">
      <span className="inline-flex items-center gap-1.5">
        <Sparkles className="h-3.5 w-3.5 text-primary" aria-hidden="true" />
        You&apos;re exploring a demo with sample data.
      </span>
      <button type="button" onClick={leave} className="font-semibold text-primary underline-offset-2 hover:underline">
        Create a free account
      </button>
      <button type="button" onClick={leave} className="text-muted-foreground underline-offset-2 hover:underline">
        Exit demo
      </button>
    </div>
  )
}
