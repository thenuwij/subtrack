'use client'

import { useCallback, useSyncExternalStore } from 'react'

const STORAGE_EVENT = 'subtrack:storage'

function subscribe(callback: () => void) {
  window.addEventListener('storage', callback)
  window.addEventListener(STORAGE_EVENT, callback)
  return () => {
    window.removeEventListener('storage', callback)
    window.removeEventListener(STORAGE_EVENT, callback)
  }
}

/** A hydration-safe localStorage value that also stays in sync across tabs. */
export function useStoredString(key: string, fallback: string) {
  const getSnapshot = useCallback(
    () => window.localStorage.getItem(key) ?? fallback,
    [fallback, key]
  )
  const getServerSnapshot = useCallback(() => fallback, [fallback])
  const value = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot)

  const setValue = useCallback((next: string) => {
    window.localStorage.setItem(key, next)
    window.dispatchEvent(new Event(STORAGE_EVENT))
  }, [key])

  const removeValue = useCallback(() => {
    window.localStorage.removeItem(key)
    window.dispatchEvent(new Event(STORAGE_EVENT))
  }, [key])

  return [value, setValue, removeValue] as const
}
