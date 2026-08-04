'use client'

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import { usePathname } from 'next/navigation'
import type {
  AgentPage,
  AgentPageContext,
  AgentPageFilters,
} from '@/lib/agent/types'


export interface AgentPageDetails {
  selected_subscription_ids?: string[]
  visible_subscription_ids?: string[]
  visible_detection_ids?: string[]
  filters?: AgentPageFilters
}

interface RegisteredContext {
  token: number
  route: string
  details: AgentPageDetails
}

interface PageContextValue {
  pageContext: AgentPageContext
  register: (route: string, details: AgentPageDetails) => () => void
  rememberCurrentPage: () => void
}

const PageContext = createContext<PageContextValue | null>(null)

function pageFromPath(pathname: string): AgentPage {
  if (pathname.startsWith('/dashboard')) return 'dashboard'
  if (pathname.startsWith('/subscriptions')) return 'subscriptions'
  if (pathname.startsWith('/review')) return 'review'
  if (pathname.startsWith('/account')) return 'account'
  if (pathname.startsWith('/assistant')) return 'assistant'
  return 'unknown'
}

export function agentPageLabel(page: AgentPage) {
  return {
    dashboard: 'Dashboard overview',
    subscriptions: 'Recurring payments',
    review: 'Review queue',
    account: 'Account settings',
    assistant: 'Assistant workspace',
    unknown: 'Subtrack',
  }[page]
}

export function AgentPageContextProvider({ children }: { children: ReactNode }) {
  const pathname = usePathname()
  const nextToken = useRef(0)
  const [registered, setRegistered] = useState<RegisteredContext | null>(null)
  const [sourceContext, setSourceContext] = useState<AgentPageContext | null>(null)

  const register = useCallback((route: string, details: AgentPageDetails) => {
    const token = ++nextToken.current
    setRegistered({ token, route, details })
    return () => {
      setRegistered(current => current?.token === token ? null : current)
    }
  }, [])

  const currentPageContext = useMemo<AgentPageContext>(() => {
    const details = registered?.route === pathname ? registered.details : {}
    return {
      page: pageFromPath(pathname),
      route: pathname,
      selected_subscription_ids: details.selected_subscription_ids?.slice(0, 25) ?? [],
      visible_subscription_ids: details.visible_subscription_ids?.slice(0, 25) ?? [],
      visible_detection_ids: details.visible_detection_ids?.slice(0, 25) ?? [],
      ...(details.filters ? { filters: details.filters } : {}),
    }
  }, [pathname, registered])

  const pageContext = useMemo<AgentPageContext>(() => {
    const source = sourceContext
    if (currentPageContext.page !== 'assistant' || !source) return currentPageContext
    return {
      ...currentPageContext,
      source_page: source.page === 'assistant' ? 'unknown' : source.page,
      source_route: source.route,
      selected_subscription_ids: source.selected_subscription_ids,
      visible_subscription_ids: source.visible_subscription_ids,
      visible_detection_ids: source.visible_detection_ids,
      ...(source.filters ? { filters: source.filters } : {}),
    }
  }, [currentPageContext, sourceContext])

  const rememberCurrentPage = useCallback(() => {
    if (currentPageContext.page !== 'assistant') setSourceContext(currentPageContext)
  }, [currentPageContext])

  const value = useMemo(
    () => ({ pageContext, register, rememberCurrentPage }),
    [pageContext, register, rememberCurrentPage]
  )
  return <PageContext.Provider value={value}>{children}</PageContext.Provider>
}

export function useAgentPageContext() {
  const value = useContext(PageContext)
  if (!value) throw new Error('useAgentPageContext must be used inside AgentPageContextProvider')
  return value.pageContext
}

export function useRememberAgentPageContext() {
  const value = useContext(PageContext)
  if (!value) throw new Error('useRememberAgentPageContext must be used inside AgentPageContextProvider')
  return value.rememberCurrentPage
}

export function useRegisterAgentPageContext(details: AgentPageDetails) {
  const value = useContext(PageContext)
  const pathname = usePathname()
  if (!value) throw new Error('useRegisterAgentPageContext must be used inside AgentPageContextProvider')
  const register = value.register

  // The page owns this small, serializable snapshot.  Using the serialized
  // value as the dependency avoids re-registering solely because an object was
  // allocated during render.
  const serialized = JSON.stringify(details)
  useEffect(() => register(pathname, JSON.parse(serialized)), [pathname, register, serialized])
}
