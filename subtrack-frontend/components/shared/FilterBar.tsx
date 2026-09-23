'use client'

import { Search, ArrowUpDown, Check, SlidersHorizontal, X } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { formatCategory } from '@/lib/utils/categories'
import { formatStoredDate } from '@/lib/utils/dates'

export type Period = 'all' | 'day' | 'week' | 'month' | 'custom'
export type SortKey = 'due' | 'amount' | 'name' | 'recent'
export type RecordScope = 'current' | 'paused' | 'history' | 'all'

const SORT_OPTIONS: { value: SortKey; label: string }[] = [
  { value: 'due',    label: 'Next payment' },
  { value: 'amount', label: 'Monthly cost' },
  { value: 'name',   label: 'Name' },
  { value: 'recent', label: 'Recently added' },
]

const PERIODS: { value: Period; label: string }[] = [
  { value: 'all',    label: 'Any time' },
  { value: 'day',    label: 'Today' },
  { value: 'week',   label: 'Next 7 days' },
  { value: 'month',  label: 'This month' },
  { value: 'custom', label: 'Custom range' },
]

const SCOPES: { value: RecordScope; label: string }[] = [
  { value: 'current', label: 'Current' },
  { value: 'paused',  label: 'Paused' },
  { value: 'history', label: 'History' },
  { value: 'all',     label: 'All' },
]

interface FilterBarProps {
  scope: RecordScope
  scopeCounts: Record<RecordScope, number>
  onScopeChange: (scope: RecordScope) => void
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
  onClearFilters: () => void
}

function shortDate(value: string) {
  return formatStoredDate(value, { day: 'numeric', month: 'short' })
}

function dueLabel(period: Period, fromDate: string, toDate: string) {
  if (period !== 'custom') return PERIODS.find(option => option.value === period)?.label ?? ''
  if (fromDate && toDate) return `${shortDate(fromDate)} – ${shortDate(toDate)}`
  if (fromDate) return `From ${shortDate(fromDate)}`
  if (toDate) return `Until ${shortDate(toDate)}`
  return 'Custom range'
}

function Chip({ label, onRemove }: { label: string; onRemove: () => void }) {
  return (
    <span className="inline-flex h-7 items-center gap-1 rounded-full bg-primary/10 pl-3 pr-1 text-xs font-medium text-primary">
      {label}
      <button
        type="button"
        onClick={onRemove}
        aria-label={`Remove filter: ${label}`}
        className="flex h-5 w-5 items-center justify-center rounded-full transition-colors hover:bg-primary/15"
      >
        <X className="h-3 w-3" />
      </button>
    </span>
  )
}

function OptionRow({
  selected,
  label,
  onSelect,
}: {
  selected: boolean
  label: string
  onSelect: () => void
}) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      onClick={onSelect}
      className="flex w-full items-center justify-between rounded-md px-2 py-1.5 text-left text-sm transition-colors hover:bg-muted"
    >
      {label}
      {selected ? <Check className="h-4 w-4 text-primary" /> : null}
    </button>
  )
}

export function FilterBar({
  scope,
  scopeCounts,
  onScopeChange,
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
  onClearFilters,
}: FilterBarProps) {
  const dueActive = period !== 'all'
  const activeFilterCount = (selectedCategory ? 1 : 0) + (dueActive ? 1 : 0)
  const hasFilters = Boolean(searchQuery || activeFilterCount)
  const showCategories = categories.length > 1 || Boolean(selectedCategory)

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
        <div className="flex items-center gap-1 rounded-xl bg-muted p-1" role="group" aria-label="Payment record scope">
          {SCOPES.map(option => (
            <button
              key={option.value}
              type="button"
              aria-pressed={scope === option.value}
              onClick={() => onScopeChange(option.value)}
              className={`flex-1 rounded-lg px-3 py-1.5 text-xs font-medium transition-colors sm:flex-none ${
                scope === option.value
                  ? 'bg-card text-foreground shadow-sm'
                  : 'text-muted-foreground hover:text-foreground'
              }`}
            >
              {option.label} <span className="ml-1 tabular-nums opacity-70">{scopeCounts[option.value]}</span>
            </button>
          ))}
        </div>

        <div className="flex min-w-0 flex-1 items-center gap-2 sm:justify-end">
          <div className="relative min-w-0 flex-1 sm:max-w-64">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input
              aria-label="Search recurring payments"
              value={searchQuery}
              onChange={e => onSearchChange(e.target.value)}
              placeholder="Search payments…"
              className="h-8 pl-8 text-xs md:text-xs"
            />
          </div>

          <Popover>
            <PopoverTrigger asChild>
              <button
                type="button"
                className={`flex h-8 shrink-0 items-center gap-1.5 rounded-lg px-3 text-xs font-medium transition-colors ${
                  activeFilterCount
                    ? 'bg-primary/10 text-primary hover:bg-primary/15'
                    : 'bg-muted text-foreground hover:bg-muted/70'
                }`}
              >
                <SlidersHorizontal className="h-3.5 w-3.5" />
                Filter
                {activeFilterCount ? (
                  <span className="rounded-full bg-primary px-1.5 text-[10px] leading-4 text-primary-foreground tabular-nums">
                    {activeFilterCount}
                  </span>
                ) : null}
              </button>
            </PopoverTrigger>
            <PopoverContent align="end" className="w-72">
              <p className="px-2 pt-1 pb-1.5 text-[11px] font-medium text-muted-foreground">Next payment due</p>
              <div role="radiogroup" aria-label="Next payment due">
                {PERIODS.map(option => (
                  <OptionRow
                    key={option.value}
                    selected={period === option.value}
                    label={option.label}
                    onSelect={() => onPeriodChange(option.value)}
                  />
                ))}
              </div>
              {period === 'custom' ? (
                <div className="grid grid-cols-2 gap-2 px-2 pt-1 pb-1.5">
                  <label className="flex flex-col gap-1 text-[11px] text-muted-foreground">
                    From
                    <input
                      type="date"
                      value={fromDate}
                      max={toDate || undefined}
                      onChange={e => onFromDateChange(e.target.value)}
                      className="h-8 rounded-lg border border-border bg-background px-2 text-xs text-foreground outline-none focus:ring-1 focus:ring-ring"
                    />
                  </label>
                  <label className="flex flex-col gap-1 text-[11px] text-muted-foreground">
                    To
                    <input
                      type="date"
                      value={toDate}
                      min={fromDate || undefined}
                      onChange={e => onToDateChange(e.target.value)}
                      className="h-8 rounded-lg border border-border bg-background px-2 text-xs text-foreground outline-none focus:ring-1 focus:ring-ring"
                    />
                  </label>
                </div>
              ) : null}

              {showCategories ? (
                <>
                  <div className="my-1.5 h-px bg-border" />
                  <p className="px-2 pt-1 pb-1.5 text-[11px] font-medium text-muted-foreground">Category</p>
                  <div className="flex flex-wrap gap-1.5 px-2 pb-1.5">
                    {['', ...categories].map(cat => (
                      <button
                        key={cat || 'all'}
                        type="button"
                        aria-pressed={selectedCategory === cat}
                        onClick={() => onCategoryChange(cat)}
                        className={`h-7 rounded-full px-3 text-xs font-medium transition-colors ${
                          selectedCategory === cat
                            ? 'bg-primary text-primary-foreground'
                            : 'bg-muted text-muted-foreground hover:bg-muted/70'
                        }`}
                      >
                        {cat ? formatCategory(cat) : 'All'}
                      </button>
                    ))}
                  </div>
                </>
              ) : null}
            </PopoverContent>
          </Popover>

          <Popover>
            <PopoverTrigger asChild>
              <button
                type="button"
                aria-label={`Sort: ${SORT_OPTIONS.find(option => option.value === sortBy)?.label}`}
                className="flex h-8 shrink-0 items-center gap-1.5 rounded-lg bg-muted px-3 text-xs font-medium text-foreground transition-colors hover:bg-muted/70"
              >
                <ArrowUpDown className="h-3.5 w-3.5" />
                <span className="hidden sm:inline">
                  {SORT_OPTIONS.find(option => option.value === sortBy)?.label}
                  {groupByCategory ? <span className="text-muted-foreground"> · grouped</span> : null}
                </span>
              </button>
            </PopoverTrigger>
            <PopoverContent align="end" className="w-56">
              <p className="px-2 pt-1 pb-1.5 text-[11px] font-medium text-muted-foreground">Sort by</p>
              <div role="radiogroup" aria-label="Sort payments by">
                {SORT_OPTIONS.map(option => (
                  <OptionRow
                    key={option.value}
                    selected={sortBy === option.value}
                    label={option.label}
                    onSelect={() => onSortByChange(option.value)}
                  />
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
        </div>
      </div>

      {hasFilters ? (
        <div className="flex flex-wrap items-center gap-1.5">
          {searchQuery ? (
            <Chip label={`“${searchQuery}”`} onRemove={() => onSearchChange('')} />
          ) : null}
          {selectedCategory ? (
            <Chip label={formatCategory(selectedCategory)} onRemove={() => onCategoryChange('')} />
          ) : null}
          {dueActive ? (
            <Chip label={`Due: ${dueLabel(period, fromDate, toDate)}`} onRemove={() => onPeriodChange('all')} />
          ) : null}
          <button
            type="button"
            onClick={onClearFilters}
            className="h-7 rounded-full px-2 text-xs font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            Clear all
          </button>
        </div>
      ) : null}

      {totalLabel && (
        <p className="text-xs text-muted-foreground">{totalLabel}</p>
      )}
    </div>
  )
}
