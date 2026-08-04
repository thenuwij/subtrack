const CATEGORY_LABELS: Record<string, string> = {
  streaming: 'Entertainment',
  software: 'Apps & software',
  cloud: 'Cloud & hosting',
  utilities: 'Housing & utilities',
  fitness: 'Health & fitness',
  food: 'Food plans',
  transport: 'Transport',
  other: 'Other recurring',
}

export function formatCategory(category: string) {
  return CATEGORY_LABELS[category] ?? category
}

// Display order for legends and grouped lists. Fixed rather than derived from
// the data, so a category doesn't jump position between renders as amounts change.
export const CATEGORY_ORDER = [
  'utilities',
  'software',
  'streaming',
  'cloud',
  'transport',
  'fitness',
  'food',
  'other',
] as const

/** The category's colour, as a CSS variable reference.
 *
 * Returned as `var(--category-x)` rather than a hex value so it follows the
 * light/dark token automatically — hard-coded colours would need a second
 * lookup table and would drift out of sync with the theme. */
export function categoryColor(category: string): string {
  const known = (CATEGORY_ORDER as readonly string[]).includes(category)
  return `var(--category-${known ? category : 'other'})`
}
