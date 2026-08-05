import { brandColors, matchBrand, monogram } from '@/lib/utils/brands'
import { categoryColor } from '@/lib/utils/categories'
import { cn } from '@/lib/utils'

interface Props {
  name: string
  /** Tints the monogram fallback, so an unmatched payment still reads as
   *  belonging to its category rather than as a broken logo. */
  category?: string
  className?: string
}

/**
 * The company's mark beside its name, falling back to initials.
 *
 * Icons are bundled rather than fetched. A logo CDN would have to be told
 * which companies this user pays, which is the one thing a subscription
 * tracker should never leak.
 */
export function BrandLogo({ name, category, className }: Props) {
  const brand = matchBrand(name)

  const shell = cn(
    'flex h-8 w-8 shrink-0 items-center justify-center rounded-lg',
    className,
  )

  if (!brand) {
    const tint = categoryColor(category ?? 'other')
    return (
      <span
        className={cn(shell, 'text-[11px] font-semibold')}
        style={{
          // color-mix keeps one source of truth for the category colour
          // instead of a parallel table of faded variants.
          backgroundColor: `color-mix(in srgb, ${tint} 14%, transparent)`,
          color: tint,
        }}
        aria-hidden="true"
      >
        {monogram(name)}
      </span>
    )
  }

  const { light, dark } = brandColors(brand.hex)

  return (
    <span
      className={cn(shell, 'bg-[var(--brand-tint)] dark:bg-[var(--brand-tint-dark)]')}
      style={{
        '--brand-light': light,
        '--brand-dark': dark,
        '--brand-tint': `color-mix(in srgb, ${light} 12%, transparent)`,
        '--brand-tint-dark': `color-mix(in srgb, ${dark} 16%, transparent)`,
      } as React.CSSProperties}
      aria-hidden="true"
    >
      <svg
        viewBox="0 0 24 24"
        className="h-[18px] w-[18px] fill-[var(--brand-light)] dark:fill-[var(--brand-dark)]"
        role="img"
      >
        <title>{brand.title}</title>
        <path d={brand.path} />
      </svg>
    </span>
  )
}
