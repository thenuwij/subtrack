'use client'

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import { createClient } from '@/lib/supabase/client'
import { getPreferences, updatePreferences, getRates } from '@/lib/api'
import type { Currency, Preferences } from '@/types'

interface CurrencyUpdateResult {
  preferences: Preferences
  ratesAvailable: boolean
}

interface CurrencyContextType {
  baseCurrency: Currency
  setBaseCurrency: (currency: Currency) => Promise<CurrencyUpdateResult>
  isLoading: boolean
  isUpdating: boolean
  rates: Record<string, number>
  ratesLoading: boolean
  ratesStale: boolean
  ratesAsOf: string | null
  canConvert: (from: string) => boolean
  convertAmount: (amount: number, from: string) => number | null
}

const CurrencyContext = createContext<CurrencyContextType>({
  baseCurrency: 'AUD',
  setBaseCurrency: async () => ({
    preferences: { base_currency: 'AUD', monthly_income: null, timezone: 'UTC' },
    ratesAvailable: false,
  }),
  isLoading: true,
  isUpdating: false,
  rates: {},
  ratesLoading: true,
  ratesStale: false,
  ratesAsOf: null,
  canConvert: (from) => from === 'AUD',
  convertAmount: (amount) => amount,
})

export function CurrencyProvider({ children }: { children: React.ReactNode }) {
  const [baseCurrency, setBaseCurrencyState] = useState<Currency>('AUD')
  const [isLoading, setIsLoading]           = useState(true)
  const [rates, setRates]                   = useState<Record<string, number>>({})
  const [ratesLoading, setRatesLoading]     = useState(true)
  const ratesFetchedAt = useRef<Date | null>(null)
  const ratesFetchedFor = useRef<string | null>(null)
  const [isUpdating, setIsUpdating] = useState(false)
  const [ratesStale, setRatesStale] = useState(false)
  const [ratesAsOf, setRatesAsOf] = useState<string | null>(null)

  const fetchRates = useCallback(async (currency: string, token: string) => {
    const now = new Date()
    const fetchedAt = ratesFetchedAt.current
    if (
      fetchedAt &&
      ratesFetchedFor.current === currency &&
      now.getTime() - fetchedAt.getTime() < 60 * 60 * 1000
    ) return

    const baseChanged = ratesFetchedFor.current !== null && ratesFetchedFor.current !== currency
    if (baseChanged) setRates({})
    setRatesLoading(true)
    try {
      const data = await getRates(token, currency)
      setRates(data.rates)
      setRatesStale(Boolean(data.stale))
      setRatesAsOf(data.provider_date ?? data.fetched_at)
      ratesFetchedAt.current = now
      ratesFetchedFor.current = currency
    } catch (error) {
      // Rates are base-specific. Never reuse a prior base's table as though it
      // belonged to the newly selected currency.
      if (baseChanged) setRates({})
      if (baseChanged) {
        setRatesStale(false)
        setRatesAsOf(null)
      }
      throw error
    } finally {
      setRatesLoading(false)
    }
  }, [])

  useEffect(() => {
    async function load() {
      try {
        const supabase = createClient()
        const { data: { session } } = await supabase.auth.getSession()
        if (!session) {
          setRatesLoading(false)
          return
        }

        const pref = await getPreferences(session.access_token)
        setBaseCurrencyState(pref.base_currency)
        await fetchRates(pref.base_currency, session.access_token)
      } catch {
        // Keep the AUD fallback. Consumers can distinguish unavailable rates
        // with canConvert instead of silently treating currencies as 1:1.
        setRatesLoading(false)
      } finally {
        setIsLoading(false)
      }
    }
    void load()
  }, []) // eslint-disable-line

  const setBaseCurrency = useCallback(async (currency: Currency) => {
    if (currency === baseCurrency) {
      return {
        preferences: {
          base_currency: baseCurrency,
          monthly_income: null,
          timezone: 'UTC',
        },
        ratesAvailable: Object.keys(rates).length > 0,
      }
    }
    const supabase = createClient()
    const { data: { session } } = await supabase.auth.getSession()
    if (!session) throw new Error('Your session has expired.')

    setIsUpdating(true)
    try {
      // Persist first. If this fails, every consumer keeps the former base and
      // its matching rate table instead of displaying mathematically invalid
      // conversions from mixed bases.
      const preferences = await updatePreferences(
        session.access_token,
        { base_currency: currency },
      )
      setBaseCurrencyState(currency)
      setRates({})
      setRatesStale(false)
      setRatesAsOf(null)
      ratesFetchedAt.current = null
      ratesFetchedFor.current = null
      let ratesAvailable = true
      try {
        await fetchRates(currency, session.access_token)
      } catch {
        ratesAvailable = false
      }
      return { preferences, ratesAvailable }
    } finally {
      setIsUpdating(false)
    }
  }, [baseCurrency, fetchRates, rates])

  const convertAmount = useCallback((amount: number, from: string): number | null => {
    if (from === baseCurrency) return amount
    const rate = rates[from]
    if (!rate) return null
    return amount / rate
  }, [baseCurrency, rates])

  const canConvert = useCallback((from: string): boolean => {
    if (from === baseCurrency) return true
    const rate = rates[from]
    return Number.isFinite(rate) && rate > 0
  }, [baseCurrency, rates])

  const value = useMemo(
    () => ({ baseCurrency, setBaseCurrency, isLoading, isUpdating, rates, ratesLoading, ratesStale, ratesAsOf, canConvert, convertAmount }),
    [baseCurrency, setBaseCurrency, isLoading, isUpdating, rates, ratesLoading, ratesStale, ratesAsOf, canConvert, convertAmount],
  )

  return (
    <CurrencyContext.Provider value={value}>
      {children}
    </CurrencyContext.Provider>
  )
}

export function useCurrency() {
  return useContext(CurrencyContext)
}
