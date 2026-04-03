'use client'

import { createContext, useContext, useEffect, useState } from 'react'
import { createClient } from '@/lib/supabase/client'
import { getPreferences, updatePreferences, getRates } from '@/lib/api'
import type { Currency } from '@/types'

interface CurrencyContextType {
  baseCurrency: Currency
  setBaseCurrency: (currency: Currency) => Promise<void>
  isLoading: boolean
  rates: Record<string, number>
  ratesLoading: boolean
  convertAmount: (amount: number, from: string) => number
}

const CurrencyContext = createContext<CurrencyContextType>({
  baseCurrency: 'AUD',
  setBaseCurrency: async () => {},
  isLoading: true,
  rates: {},
  ratesLoading: true,
  convertAmount: (amount) => amount,
})

export function CurrencyProvider({ children }: { children: React.ReactNode }) {
  const [baseCurrency, setBaseCurrencyState] = useState<Currency>('AUD')
  const [isLoading, setIsLoading]           = useState(true)
  const [rates, setRates]                   = useState<Record<string, number>>({})
  const [ratesLoading, setRatesLoading]     = useState(true)
  const [ratesFetchedAt, setRatesFetchedAt] = useState<Date | null>(null)
  const [ratesFetchedFor, setRatesFetchedFor] = useState<string | null>(null)

  async function fetchRates(currency: string, token: string) {
    const now = new Date()
    if (
      ratesFetchedAt &&
      ratesFetchedFor === currency &&
      now.getTime() - ratesFetchedAt.getTime() < 60 * 60 * 1000
    ) return

    setRatesLoading(true)
    try {
      const data = await getRates(token, currency)
      setRates(data.rates)
      setRatesFetchedAt(now)
      setRatesFetchedFor(currency)
    } catch {
      // leave existing rates in place on error
    } finally {
      setRatesLoading(false)
    }
  }

  useEffect(() => {
    async function load() {
      const supabase = createClient()
      const { data: { session } } = await supabase.auth.getSession()
      if (!session) return

      const pref = await getPreferences(session.access_token)
      setBaseCurrencyState(pref.base_currency)
      setIsLoading(false)

      await fetchRates(pref.base_currency, session.access_token)
    }
    load()
  }, []) // eslint-disable-line

  async function setBaseCurrency(currency: Currency) {
    const supabase = createClient()
    const { data: { session } } = await supabase.auth.getSession()
    if (!session) return

    setBaseCurrencyState(currency)
    await updatePreferences(session.access_token, currency)
    await fetchRates(currency, session.access_token)
  }

  function convertAmount(amount: number, from: string): number {
    if (from === baseCurrency) return amount
    const rate = rates[from]
    if (!rate) return amount
    return amount / rate
  }

  return (
    <CurrencyContext.Provider value={{ baseCurrency, setBaseCurrency, isLoading, rates, ratesLoading, convertAmount }}>
      {children}
    </CurrencyContext.Provider>
  )
}

export function useCurrency() {
  return useContext(CurrencyContext)
}
