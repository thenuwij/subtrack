import { BRAND_ICONS, type BrandIcon } from './brand-icons.generated'

/** Lowercase, strip punctuation, collapse whitespace.
 *
 * Payment names arrive as they appear on a receipt — "NETFLIX.COM",
 * "Uber One membership", "Claude Pro subscription" — so matching has to
 * survive casing, dots and trailing product words. */
function normalise(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim()
}

/** Aliases across every brand, longest first.
 *
 * Sorting globally rather than per brand is what makes "Uber Eats" resolve to
 * Uber Eats instead of Uber, and "Apple Music" to Apple Music instead of the
 * bare "apple" alias. Built once at module load. */
const ALIAS_INDEX: ReadonlyArray<{ alias: string, brand: BrandIcon }> =
  BRAND_ICONS
    .flatMap(brand => brand.aliases.map(alias => ({ alias, brand })))
    .sort((a, b) => b.alias.length - a.alias.length)

const cache = new Map<string, BrandIcon | null>()

export function matchBrand(name: string): BrandIcon | null {
  if (!name) return null
  const cached = cache.get(name)
  if (cached !== undefined) return cached

  // Pad both sides so `includes` only ever matches on whole tokens — without
  // this, "max" would match "Maxwell Insurance" and "uber" would match
  // "Uberto Consulting".
  const haystack = ` ${normalise(name)} `
  let found: BrandIcon | null = null
  for (const { alias, brand } of ALIAS_INDEX) {
    if (haystack.includes(` ${alias} `)) {
      found = brand
      break
    }
  }

  cache.set(name, found)
  return found
}

/** Perceived brightness of a brand colour, 0 (black) to 1 (white). */
function luminance(hex: string): number {
  const value = parseInt(hex, 16)
  const r = ((value >> 16) & 255) / 255
  const g = ((value >> 8) & 255) / 255
  const b = (value & 255) / 255
  // Rec. 709 coefficients — good enough to answer "will this disappear?".
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

function mix(hex: string, toward: 'white' | 'black', amount: number): string {
  const value = parseInt(hex, 16)
  const target = toward === 'white' ? 255 : 0
  const channel = (shift: number) => {
    const original = (value >> shift) & 255
    return Math.round(original + (target - original) * amount)
  }
  return `rgb(${channel(16)} ${channel(8)} ${channel(0)})`
}

/**
 * A brand colour that stays visible in both themes.
 *
 * Official marks are picked for a white page, so Apple (#000000) and GitHub
 * (#181717) vanish against a dark background — and a handful of near-white
 * marks disappear against a light one. Only the offenders are adjusted, so
 * Netflix red and Spotify green render exactly as the brand intends.
 */
export function brandColors(hex: string): { light: string, dark: string } {
  const level = luminance(hex)
  return {
    light: level > 0.85 ? mix(hex, 'black', 0.35) : `#${hex}`,
    dark: level < 0.22 ? mix(hex, 'white', 0.72) : `#${hex}`,
  }
}

/**
 * Up to two initials, for payments with no matching brand.
 *
 * Leading noise words are skipped so "The Sydney Morning Herald" reads SM
 * rather than TS. Anything without letters (a bare invoice number) yields a
 * single character rather than an empty chip.
 */
const NOISE = new Set(['the', 'a', 'an', 'my', 'mr', 'mrs', 'dr'])

export function monogram(name: string): string {
  const words = normalise(name).split(' ').filter(w => w && !NOISE.has(w))
  if (words.length === 0) return name.trim().slice(0, 1).toUpperCase() || '•'
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase()
  return (words[0][0] + words[1][0]).toUpperCase()
}
