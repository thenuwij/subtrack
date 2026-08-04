/** The Subtrack mark: three stacked bars on a repeating beat.
 *
 * A lettermark "S" said nothing about the product. This reads as recurring
 * charges of different sizes — the thing the app is actually about — and stays
 * legible at 20px where a glyph would not. */
export function LogoMark({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
      className={className}
    >
      <rect width="24" height="24" rx="6.5" fill="var(--primary)" />
      <rect x="5.5" y="7" width="13" height="2.6" rx="1.3" fill="var(--primary-foreground)" />
      <rect x="5.5" y="11.2" width="9" height="2.6" rx="1.3" fill="var(--primary-foreground)" opacity="0.75" />
      <rect x="5.5" y="15.4" width="5" height="2.6" rx="1.3" fill="var(--primary-foreground)" opacity="0.5" />
    </svg>
  )
}

export function Logo({ compact = false }: { compact?: boolean }) {
  return (
    <span className="flex items-center gap-2">
      <LogoMark className="h-6 w-6 shrink-0" />
      <span className="flex flex-col leading-none">
        <span className="text-sm font-semibold tracking-tight text-foreground">
          Subtrack
        </span>
        {!compact && (
          <span className="mt-1 text-[11px] leading-none text-muted-foreground">
            Recurring payments
          </span>
        )}
      </span>
    </span>
  )
}
