'use client'

import { useCallback, useSyncExternalStore } from 'react'

const STORAGE_EVENT = 'subtrack:storage'
const memoryFallback = new Map<string, string>()

function readValue(key: string, fallback: string) {
  if (memoryFallback.has(key)) return memoryFallback.get(key) ?? fallback
  try {
    return window.localStorage.getItem(key) ?? fallback
  } catch {
    return fallback
  }
}

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
    () => readValue(key, fallback),
    [fallback, key]
  )
  const getServerSnapshot = useCallback(() => fallback, [fallback])
  const value = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot)

  const setValue = useCallback((next: string) => {
    try {
      window.localStorage.setItem(key, next)
      memoryFallback.delete(key)
    } catch {
      // Storage can be unavailable in privacy-restricted browsers. Keep the UI
      // usable for this tab even when the preference cannot be persisted.
      memoryFallback.set(key, next)
    }
    window.dispatchEvent(new Event(STORAGE_EVENT))
  }, [key])

  const removeValue = useCallback(() => {
    try {
      window.localStorage.removeItem(key)
      memoryFallback.delete(key)
    } catch {
      memoryFallback.set(key, fallback)
    }
    window.dispatchEvent(new Event(STORAGE_EVENT))
  }, [fallback, key])

  return [value, setValue, removeValue] as const
}
