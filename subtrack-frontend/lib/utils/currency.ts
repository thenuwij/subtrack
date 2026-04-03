export const CURRENCY_SYMBOLS: Record<string, string> = {
  AUD: 'A$',
  USD: 'US$',
  GBP: '£',
  EUR: '€',
  SGD: 'S$',
  JPY: '¥',
}

export function formatCurrency(amount: number, currency: string): string {
  const symbol = CURRENCY_SYMBOLS[currency] ?? currency
  return `${symbol} ${amount.toLocaleString('en-AU', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`
}
