'use client'

import { Search, LayoutGrid, ArrowUp, ArrowDown, X } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { formatCategory } from '@/lib/utils/categories'

type Period = 'all' | 'day' | 'week' | 'month'

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
  sortOrder: 'desc' | 'asc'
  onSortOrderChange: (s: 'desc' | 'asc') => void
  groupByCategory: boolean
  onGroupByCategoryChange: (g: boolean) => void
  totalLabel: string
  searchQuery: string
  onSearchChange: (q: string) => void
  onClearFilters: () => void
}

const PERIODS: { value: Period; label: string }[] = [
  { value: 'all',   label: 'All'   },
  { value: 'day',   label: 'Day'   },
  { value: 'week',  label: 'Week'  },
  { value: 'month', label: 'Month' },
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
  sortOrder,
  onSortOrderChange,
  groupByCategory,
  onGroupByCategoryChange,
  totalLabel,
  searchQuery,
  onSearchChange,
  onClearFilters,
}: FilterBarProps) {
  const hasFilters = Boolean(searchQuery || selectedCategory || period !== 'all' || fromDate || toDate)

  return (
    <div className="flex flex-col gap-3">

      {/* Row 1: Search + Category */}
      <div className="flex flex-wrap items-center gap-3">

        {/* Search */}
        <div className="relative w-40 shrink-0">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground pointer-events-none" />
          <Input
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
          <div className="flex items-center rounded-lg bg-muted p-0.5 gap-0.5">
            {PERIODS.map(p => (
              <button
                key={p.value}
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
          <span className="text-xs text-muted-foreground">From</span>
          <input
            type="date"
            value={fromDate}
            onChange={e => onFromDateChange(e.target.value)}
            className="h-8 rounded-lg border border-border bg-background px-2 text-xs text-foreground outline-none focus:ring-1 focus:ring-ring"
          />
        </div>

        {/* To date */}
        <div className="flex items-center gap-1.5 shrink-0">
          <span className="text-xs text-muted-foreground">To</span>
          <input
            type="date"
            value={toDate}
            onChange={e => onToDateChange(e.target.value)}
            className="h-8 rounded-lg border border-border bg-background px-2 text-xs text-foreground outline-none focus:ring-1 focus:ring-ring"
          />
        </div>

        {/* Sort order */}
        <button
          onClick={() => onSortOrderChange(sortOrder === 'desc' ? 'asc' : 'desc')}
          className={`flex items-center gap-1.5 h-8 rounded-lg px-3 text-xs font-medium transition-colors shrink-0 ${
            sortOrder === 'desc'
              ? 'bg-muted text-foreground'
              : 'bg-muted text-foreground'
          } hover:bg-muted/70`}
          aria-label="Toggle sort order"
        >
          {sortOrder === 'desc'
            ? <><ArrowDown className="w-3.5 h-3.5" /> Newest</>
            : <><ArrowUp   className="w-3.5 h-3.5" /> Oldest</>
          }
        </button>

        {/* Group by category */}
        <button
          onClick={() => onGroupByCategoryChange(!groupByCategory)}
          className={`flex items-center gap-1.5 h-8 rounded-lg px-3 text-xs font-medium transition-colors shrink-0 ${
            groupByCategory
              ? 'bg-primary/10 text-primary hover:bg-primary/15'
              : 'bg-muted text-muted-foreground hover:bg-muted/70'
          }`}
          aria-label="Toggle group by category"
        >
          <LayoutGrid className="w-3.5 h-3.5" />
          Group
        </button>

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
