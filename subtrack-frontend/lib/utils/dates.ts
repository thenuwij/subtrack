/**
 * Subtrack's billing dates are calendar values represented at 12:00 UTC in
 * API datetimes. Comparisons and input boundaries therefore use UTC date
 * components rather than the browser timezone or exact timestamps.
 */
export function utcDateKey(value = new Date()): string {
  return value.toISOString().slice(0, 10)
}

export function storedDateKey(value: string | null | undefined): string {
  return value ? value.slice(0, 10) : ''
}

export function todayUtcDateKey(): string {
  return utcDateKey()
}

export function addUtcDays(dateKey: string, days: number): string {
  const value = new Date(`${dateKey}T12:00:00Z`)
  value.setUTCDate(value.getUTCDate() + days)
  return utcDateKey(value)
}

export function endOfUtcMonthDateKey(dateKey: string): string {
  const value = new Date(`${dateKey}T12:00:00Z`)
  value.setUTCMonth(value.getUTCMonth() + 1, 0)
  return utcDateKey(value)
}

export function dateAtNoonUtc(dateKey: string): string {
  return new Date(`${dateKey}T12:00:00Z`).toISOString()
}

export function formatStoredDate(
  value: string,
  options: Intl.DateTimeFormatOptions = {
    day: 'numeric', month: 'short', year: 'numeric',
  },
): string {
  return new Intl.DateTimeFormat('en-AU', {
    ...options,
    timeZone: 'UTC',
  }).format(new Date(`${storedDateKey(value)}T12:00:00Z`))
}
