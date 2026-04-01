'use client'

import { createContext, useContext, useEffect, useState } from 'react'
import { createClient } from '@/lib/supabase/client'
import { getPreferences, updatePreferences } from '@/lib/api'
import type { Currency } from '@/types'

// 1. Define what the context holds
interface CurrencyContextType {
  baseCurrency: Currency
  setBaseCurrency: (currency: Currency) => Promise<void>
  isLoading: boolean
}

// 2. Create the context with a default value
const CurrencyContext = createContext<CurrencyContextType>({
  baseCurrency: 'AUD',
  setBaseCurrency: async () => {},
  isLoading: true,
})

// 3. Provider — wraps the app, holds the actual state
export function CurrencyProvider({ children }: { children: React.ReactNode }) {
  const [baseCurrency, setBaseCurrencyState] = useState<Currency>('AUD')
  const [isLoading, setIsLoading] = useState(true)

  // Load preference from backend on mount
  useEffect(() => {
    async function load() {
      const supabase = createClient()
      const { data: { session } } = await supabase.auth.getSession()
      if (!session) return

      const pref = await getPreferences(session.access_token)
      setBaseCurrencyState(pref.base_currency)
      setIsLoading(false)
    }
    load()
  }, [])

  // Update both local state and backend when user changes currency
  async function setBaseCurrency(currency: Currency) {
    const supabase = createClient()
    const { data: { session } } = await supabase.auth.getSession()
    if (!session) return

    setBaseCurrencyState(currency)                              // update UI instantly
    await updatePreferences(session.access_token, currency)    // persist to backend
  }

  return (
    <CurrencyContext.Provider value={{ baseCurrency, setBaseCurrency, isLoading }}>
      {children}
    </CurrencyContext.Provider>
  )
}

// 4. Custom hook — how components access the context
export function useCurrency() {
  return useContext(CurrencyContext)
}