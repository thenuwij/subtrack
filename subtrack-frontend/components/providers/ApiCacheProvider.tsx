'use client'

import { useEffect, type ReactNode } from 'react'
import { SWRConfig, useSWRConfig } from 'swr'

function RevalidateOnDataChange() {
  const { mutate } = useSWRConfig()

  useEffect(() => {
    const refresh = () => { void mutate(() => true) }
    window.addEventListener('subtrack:data-changed', refresh)
    return () => window.removeEventListener('subtrack:data-changed', refresh)
  }, [mutate])

  return null
}

export function ApiCacheProvider({ children }: { children: ReactNode }) {
  return (
    <SWRConfig
      value={{
        provider: () => new Map(),
        dedupingInterval: 5_000,
        shouldRetryOnError: false,
      }}
    >
      <RevalidateOnDataChange />
      {children}
    </SWRConfig>
  )
}
