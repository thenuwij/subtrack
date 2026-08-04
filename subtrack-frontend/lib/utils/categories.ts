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
