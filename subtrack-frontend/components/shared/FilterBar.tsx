'use client'

import { Search, ArrowUpDown, Check, X } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { formatCategory } from '@/lib/utils/categories'

type Period = 'all' | 'day' | 'week' | 'month'
export type SortKey = 'due' | 'amount' | 'name' | 'recent'

const SORT_OPTIONS: { value: SortKey; label: string }[] = [
  { value: 'due',    label: 'Next payment' },
  { value: 'amount', label: 'Monthly cost' },
  { value: 'name',   label: 'Name' },
  { value: 'recent', label: 'Recently added' },
]

interface FilterBarProps {
  categories: string[]
  selectedCategory: string
  onCategoryChange: (c: string) => void
  period: Period
  onPeriodChange: (p: Period) => void
  fromDate: string
  toDate: string
  onFromDateChange: (d: string) => void
  onToDateChange: (d: string) => void
  sortBy: SortKey
  onSortByChange: (s: SortKey) => void
  groupByCategory: boolean
  onGroupByCategoryChange: (g: boolean) => void
  totalLabel: string
  searchQuery: string
  onSearchChange: (q: string) => void
  hasFilters: boolean
  onClearFilters: () => void
}

const PERIODS: { value: Period; label: string }[] = [
  { value: 'all',   label: 'Any date' },
  { value: 'day',   label: 'Today' },
  { value: 'week',  label: 'Next 7 days' },
  { value: 'month', label: 'This month' },
]

export function FilterBar({
  categories,
  selectedCategory,
  onCategoryChange,
  period,
  onPeriodChange,
  fromDate,
  toDate,
  onFromDateChange,
  onToDateChange,
  sortBy,
  onSortByChange,
  groupByCategory,
  onGroupByCategoryChange,
  totalLabel,
  searchQuery,
  onSearchChange,
  hasFilters,
  onClearFilters,
}: FilterBarProps) {
  return (
    <div className="flex flex-col gap-3">

      {/* Row 1: Search + Category */}
      <div className="flex flex-wrap items-center gap-3">

        {/* Search */}
        <div className="relative w-40 shrink-0">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground pointer-events-none" />
          <Input
            aria-label="Search recurring payments"
            value={searchQuery}
            onChange={e => onSearchChange(e.target.value)}
            placeholder="Search…"
            className="pl-7 h-8 text-xs"
          />
        </div>

        {/* Category pills */}
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-xs text-muted-foreground shrink-0">Category</span>
          <button
            type="button"
            aria-pressed={selectedCategory === ''}
            onClick={() => onCategoryChange('')}
            className={`h-7 rounded-full px-3 text-xs font-medium transition-colors ${
              selectedCategory === ''
                ? 'bg-primary text-primary-foreground'
                : 'bg-muted text-muted-foreground hover:bg-muted/70'
            }`}
          >
            All
          </button>
          {categories.map(cat => (
            <button
              key={cat}
              type="button"
              aria-pressed={selectedCategory === cat}
              onClick={() => onCategoryChange(cat === selectedCategory ? '' : cat)}
              className={`h-7 rounded-full px-3 text-xs font-medium capitalize transition-colors ${
                selectedCategory === cat
                  ? 'bg-primary text-primary-foreground'
                  : 'bg-muted text-muted-foreground hover:bg-muted/70'
              }`}
            >
              {formatCategory(cat)}
            </button>
          ))}
        </div>

      </div>

      {/* Row 2: Period + Dates + Sort + Group */}
      <div className="flex flex-wrap items-center gap-3">

        {/* Period toggle */}
        <div className="flex items-center gap-1.5">
          <span className="text-xs text-muted-foreground shrink-0">Period</span>
          <div className="flex flex-wrap items-center rounded-lg bg-muted p-0.5 gap-0.5" role="group" aria-label="Expected payment date">
            {PERIODS.map(p => (
              <button
                key={p.value}
                type="button"
                aria-pressed={period === p.value}
                onClick={() => onPeriodChange(p.value)}
                className={`h-6 rounded-md px-2.5 text-xs font-medium transition-colors ${
                  period === p.value
                    ? 'bg-background text-foreground shadow-sm'
                    : 'text-muted-foreground hover:text-foreground'
                }`}
              >
                {p.label}
              </button>
            ))}
          </div>
        </div>

        {/* From date */}
        <div className="flex items-center gap-1.5 shrink-0">
          <label htmlFor="payment-filter-from" className="text-xs text-muted-foreground">From</label>
          <input
            id="payment-filter-from"
            type="date"
            value={fromDate}
            onChange={e => onFromDateChange(e.target.value)}
            className="h-8 rounded-lg border border-border bg-background px-2 text-xs text-foreground outline-none focus:ring-1 focus:ring-ring"
          />
        </div>

        {/* To date */}
        <div className="flex items-center gap-1.5 shrink-0">
          <label htmlFor="payment-filter-to" className="text-xs text-muted-foreground">To</label>
          <input
            id="payment-filter-to"
            type="date"
            value={toDate}
            onChange={e => onToDateChange(e.target.value)}
            className="h-8 rounded-lg border border-border bg-background px-2 text-xs text-foreground outline-none focus:ring-1 focus:ring-ring"
          />
        </div>

        <Popover>
          <PopoverTrigger asChild>
            <button
              type="button"
              className="flex h-8 shrink-0 items-center gap-1.5 rounded-lg bg-muted px-3 text-xs font-medium text-foreground transition-colors hover:bg-muted/70"
            >
              <ArrowUpDown className="h-3.5 w-3.5" />
              {SORT_OPTIONS.find(option => option.value === sortBy)?.label}
              {groupByCategory ? <span className="text-muted-foreground">· grouped</span> : null}
            </button>
          </PopoverTrigger>
          <PopoverContent align="end" className="w-56">
            <p className="px-2 pt-1 pb-1.5 text-[11px] font-medium text-muted-foreground">Sort by</p>
            <div role="radiogroup" aria-label="Sort payments by">
              {SORT_OPTIONS.map(option => (
                <button
                  key={option.value}
                  type="button"
                  role="radio"
                  aria-checked={sortBy === option.value}
                  onClick={() => onSortByChange(option.value)}
                  className="flex w-full items-center justify-between rounded-md px-2 py-1.5 text-left text-sm transition-colors hover:bg-muted"
                >
                  {option.label}
                  {sortBy === option.value ? <Check className="h-4 w-4 text-primary" /> : null}
                </button>
              ))}
            </div>
            <div className="my-1.5 h-px bg-border" />
            <label className="flex cursor-pointer items-center justify-between rounded-md px-2 py-1.5 text-sm transition-colors hover:bg-muted">
              Group by category
              <input
                type="checkbox"
                checked={groupByCategory}
                onChange={event => onGroupByCategoryChange(event.target.checked)}
                className="h-4 w-4 accent-primary"
              />
            </label>
          </PopoverContent>
        </Popover>

        {hasFilters && (
          <button
            type="button"
            onClick={onClearFilters}
            className="flex h-8 shrink-0 items-center gap-1.5 rounded-lg px-2 text-xs font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            <X className="h-3.5 w-3.5" />
            Clear filters
          </button>
        )}

      </div>

      {/* Total label */}
      {totalLabel && (
        <p className="text-xs text-muted-foreground">{totalLabel}</p>
      )}

    </div>
  )
}
