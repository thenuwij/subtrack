'use client'

import { useCallback, useEffect, useState } from 'react'
import { driver, type DriveStep } from 'driver.js'
import 'driver.js/dist/driver.css'
import { useSWRConfig } from 'swr'
import { getPreferences, updatePreferences } from '@/lib/api'
import { apiKeys, useApi } from '@/lib/hooks/useApi'
import type { Preferences } from '@/types'
import { LogoMark } from '@/components/layout/Logo'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { getAccessToken, isDemoSession } from '@/lib/auth/session'

export const START_TOUR_EVENT = 'subtrack:start-tour'

function visible(selector: string) {
  return () => {
    const matches = Array.from(document.querySelectorAll(selector))
    return matches.find(element => (element as HTMLElement).offsetParent !== null) ?? matches[0]
  }
}

function firstVisible(...selectors: string[]) {
  return () => {
    for (const selector of selectors) {
      const match = Array.from(document.querySelectorAll(selector))
        .find(element => (element as HTMLElement).offsetParent !== null)
      if (match) return match
    }
    return document.body
  }
}

const steps: DriveStep[] = [
  {
    element: visible('[data-tour="nav-review"]'),
    popover: {
      title: 'Your inbox findings',
      description: 'Connect Gmail and Subtrack finds recurring payments in your receipts. Each one waits here until you approve it.',
    },
  },
  {
    element: visible('[data-tour="nav-subscriptions"]'),
    popover: {
      title: 'Every recurring payment',
      description: 'Add, edit or remove anything by hand, and search, filter or sort by what is due next.',
    },
  },
  {
    element: visible('[data-tour="nav-dashboard"]'),
    popover: {
      title: 'Your monthly picture',
      description: 'Your total monthly commitment, the charges coming up, and anything that changed recently.',
    },
  },
  {
    element: firstVisible('[data-tour="assistant"]', '[data-tour="nav-assistant"]'),
    popover: {
      title: 'Ask the assistant',
      description: 'Ask questions in plain English. It can prepare changes for you, and nothing happens until you confirm.',
    },
  },
]

const finalStep: DriveStep = {
  popover: {
    title: 'You are all set',
    description: 'Start by connecting Gmail in Account, or add your first payment. You can replay this tour from Account settings.',
  },
}

const demoFinalStep: DriveStep = {
  popover: {
    title: 'You are all set',
    description: 'Explore the sample payments, review the inbox findings, or ask the assistant a question. You can replay this tour from Account.',
  },
}

async function markCompleted() {
  const accessToken = await getAccessToken()
  if (!accessToken) return
  await updatePreferences(accessToken, { onboarding_completed: true })
}

export function OnboardingTour() {
  const { mutate } = useSWRConfig()
  const preferences = useApi<Preferences>(apiKeys.preferences, getPreferences)
  const [dismissed, setDismissed] = useState(false)
  const welcomeOpen = preferences.data?.onboarding_completed === false && !dismissed

  const finish = useCallback(async () => {
    setDismissed(true)
    await markCompleted().catch(() => undefined)
    void mutate(apiKeys.preferences)
  }, [mutate])

  const startTour = useCallback(() => {
    setDismissed(true)
    const tour = driver({
      steps: [...steps, isDemoSession() ? demoFinalStep : finalStep],
      showProgress: true,
      progressText: '{{current}} of {{total}}',
      nextBtnText: 'Next',
      prevBtnText: 'Back',
      doneBtnText: 'Done',
      popoverClass: 'subtrack-tour',
      stagePadding: 6,
      stageRadius: 10,
      overlayOpacity: 0.55,
      onDestroyed: () => { void finish() },
    })
    tour.drive()
  }, [finish])

  useEffect(() => {
    window.addEventListener(START_TOUR_EVENT, startTour)
    return () => window.removeEventListener(START_TOUR_EVENT, startTour)
  }, [startTour])

  return (
    <Dialog open={welcomeOpen} onOpenChange={open => { if (!open) void finish() }}>
      <DialogContent showCloseButton={false}>
        <DialogHeader>
          <LogoMark className="mb-2 h-10 w-10" />
          <DialogTitle>Welcome to Subtrack</DialogTitle>
          <DialogDescription>
            Subtrack finds your recurring payments in your Gmail receipts, shows what they really cost each month, and flags anything that changes. Want a quick look around?
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="ghost" onClick={() => void finish()}>Skip</Button>
          <Button onClick={startTour}>Show me around</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
