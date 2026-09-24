'use client'

import { useEffect, useState, type CSSProperties, type KeyboardEvent, type PointerEvent } from 'react'
import { usePathname, useRouter } from 'next/navigation'
import { MessageCircle, X } from 'lucide-react'
import { AgentWorkspace } from '@/components/agent/AgentWorkspace'
import { useStoredString } from '@/lib/hooks/useStoredState'
import { useRememberAgentPageContext } from '@/lib/agent/page-context'

const WIDTH_KEY = 'subtrack:agent-panel-width'
const MIN_WIDTH = 360
const MAX_WIDTH = 720
const DEFAULT_WIDTH = 440

function clampWidth(value: number) {
  return Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, value))
}

export function AgentChat() {
  const pathname = usePathname()
  const router = useRouter()
  const rememberPageContext = useRememberAgentPageContext()
  const [open, setOpen] = useState(false)
  const [hasOpened, setHasOpened] = useState(false)
  const [draftRequest, setDraftRequest] = useState<{ id: number; text: string } | null>(null)
  const [storedWidth, setStoredWidth] = useStoredString(WIDTH_KEY, String(DEFAULT_WIDTH))
  const parsedWidth = Number(storedWidth)
  const width = clampWidth(Number.isFinite(parsedWidth) ? parsedWidth : DEFAULT_WIDTH)

  useEffect(() => {
    function openWithDraft(event: Event) {
      const detail = (event as CustomEvent<{ prompt?: string }>).detail
      if (!detail?.prompt) return
      setDraftRequest({ id: Date.now(), text: detail.prompt })
      setHasOpened(true)
      setOpen(true)
    }
    window.addEventListener('subtrack:ask-agent', openWithDraft)
    return () => window.removeEventListener('subtrack:ask-agent', openWithDraft)
  }, [])

  function resizeStart(event: PointerEvent<HTMLDivElement>) {
    event.preventDefault()
    const startX = event.clientX
    const startWidth = width

    function move(pointerEvent: globalThis.PointerEvent) {
      setStoredWidth(String(clampWidth(startWidth + startX - pointerEvent.clientX)))
    }
    function finish() {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', finish)
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', finish, { once: true })
  }

  function resizeKey(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === 'ArrowLeft') {
      event.preventDefault()
      setStoredWidth(String(clampWidth(width + 24)))
    }
    if (event.key === 'ArrowRight') {
      event.preventDefault()
      setStoredWidth(String(clampWidth(width - 24)))
    }
  }

  // The dedicated page owns the assistant UI there. Keeping this component
  // out avoids two workspaces issuing duplicate history requests.
  if (pathname === '/assistant') return null

  const panelStyle = {
    '--agent-panel-width': `${width}px`,
  } as CSSProperties

  return (
    <>
      <button
        type="button"
        data-tour="assistant"
        onClick={() => {
          if (!open) setHasOpened(true)
          setOpen(value => !value)
        }}
        aria-label={open ? 'Minimise financial assistant' : 'Open financial assistant'}
        aria-expanded={open}
        className={`fixed bottom-[calc(5rem+env(safe-area-inset-bottom))] right-4 z-50 flex h-12 w-12 items-center justify-center rounded-full bg-primary text-primary-foreground shadow-lg transition-all hover:bg-primary/90 md:bottom-6 md:right-6 ${open ? 'pointer-events-none scale-90 opacity-0' : ''}`}
      >
        {open ? <X className="h-5 w-5" /> : <MessageCircle className="h-5 w-5" />}
      </button>

      <section
        aria-label="Subtrack financial assistant"
        style={panelStyle}
        className={`${open ? 'flex' : 'hidden'} fixed inset-0 z-50 flex-col overflow-hidden bg-card sm:inset-auto sm:bottom-6 sm:right-6 sm:h-[min(720px,calc(100vh-3rem))] sm:w-[var(--agent-panel-width)] sm:rounded-2xl sm:border sm:border-border sm:shadow-xl`}
      >
        <div
          role="separator"
          aria-label="Resize assistant panel"
          aria-orientation="vertical"
          aria-valuemin={MIN_WIDTH}
          aria-valuemax={MAX_WIDTH}
          aria-valuenow={width}
          tabIndex={0}
          onPointerDown={resizeStart}
          onKeyDown={resizeKey}
          className="absolute inset-y-3 left-0 z-30 hidden w-2 -translate-x-1/2 cursor-ew-resize touch-none rounded-full focus-visible:bg-primary/20 sm:block"
        />
        {hasOpened ? (
          <AgentWorkspace
            variant="panel"
            draftRequest={draftRequest}
            onClose={() => setOpen(false)}
            onOpenFullPage={() => {
              rememberPageContext()
              setOpen(false)
              router.push('/assistant')
            }}
          />
        ) : null}
      </section>
    </>
  )
}
