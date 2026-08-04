'use client'

import { useTheme } from 'next-themes'
import { Monitor, Moon, Sun } from 'lucide-react'
import { useHydrated } from '@/lib/hooks/useHydrated'

const OPTIONS = [
  { value: 'light', label: 'Light', Icon: Sun },
  { value: 'dark', label: 'Dark', Icon: Moon },
  { value: 'system', label: 'System', Icon: Monitor },
] as const

/** Appearance control.
 *
 * The dark tokens already existed and next-themes was already wired to the
 * system preference — but with nothing in the UI to change it, a user who
 * wants dark on a light machine (or the reverse) had no way to get there. */
export function ThemeToggle() {
  const { theme, setTheme } = useTheme()
  // The active theme isn't known until the client has read localStorage and the
  // system query, so no option is marked selected until then — showing a guess
  // would flash the wrong one.
  const hydrated = useHydrated()

  return (
    <div
      role="radiogroup"
      aria-label="Appearance"
      className="inline-flex shrink-0 rounded-lg bg-muted p-0.5"
    >
      {OPTIONS.map(({ value, label, Icon }) => {
        const active = hydrated && theme === value
        return (
          <button
            key={value}
            type="button"
            role="radio"
            aria-checked={active}
            aria-label={label}
            title={label}
            onClick={() => setTheme(value)}
            className={`flex items-center gap-1.5 rounded-[7px] px-2.5 py-1.5 text-xs font-medium transition-colors ${
              active
                ? 'bg-card text-foreground shadow-sm'
                : 'text-muted-foreground hover:text-foreground'
            }`}
          >
            <Icon className="h-3.5 w-3.5" />
            <span className="hidden sm:inline">{label}</span>
          </button>
        )
      })}
    </div>
  )
}
