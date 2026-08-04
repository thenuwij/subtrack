'use client'

import { useSyncExternalStore } from 'react'

// Nothing ever changes, so a subscriber is never called back.
const noopSubscribe = () => () => {}

/** True once the client has taken over from the server-rendered markup.
 *
 * The usual `useState(false)` + `useEffect(() => setState(true))` does the same
 * job but sets state during an effect, which React 19 flags as a cascading
 * render. Reading it as an external store gives the same answer — `false` on
 * the server, `true` on the client — with no extra render pass. */
export function useHydrated(): boolean {
  return useSyncExternalStore(
    noopSubscribe,
    () => true,
    () => false
  )
}
