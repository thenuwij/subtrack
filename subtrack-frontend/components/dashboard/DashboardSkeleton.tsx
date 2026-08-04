function Bar({ className }: { className?: string }) {
  return <div className={`animate-pulse rounded-md bg-muted ${className ?? ''}`} />
}

/** Mirrors the real dashboard's structure and spacing.
 *
 * A generic stack of grey rectangles causes a visible jolt when the content
 * lands in a different shape — matching the layout means the page settles
 * instead of rearranging itself. */
export function DashboardSkeleton() {
  return (
    <div className="mx-auto max-w-5xl px-4 py-8 sm:px-6 lg:px-8">
      <div className="space-y-10" aria-busy="true" aria-live="polite">
        <span className="sr-only">Loading your dashboard</span>

        {/* Hero */}
        <div className="space-y-4">
          <Bar className="h-4 w-40" />
          <Bar className="h-14 w-72" />
          <div className="flex flex-wrap gap-3">
            <Bar className="h-4 w-32" />
            <Bar className="h-4 w-28" />
            <Bar className="h-4 w-36" />
          </div>
          <Bar className="h-3 w-full rounded-full" />
        </div>

        {/* Breakdown */}
        <div className="rounded-2xl bg-card p-6 shadow-sm">
          <div className="flex items-center justify-between">
            <div className="space-y-2">
              <Bar className="h-5 w-48" />
              <Bar className="h-3.5 w-32" />
            </div>
            <Bar className="h-8 w-48 rounded-lg" />
          </div>
          <Bar className="mt-6 h-3 w-full rounded-full" />
          <div className="mt-5 space-y-3">
            {[...Array(4)].map((_, i) => (
              <div key={i} className="flex items-center gap-3">
                <Bar className="h-2.5 w-2.5 rounded-full" />
                <Bar className="h-4 flex-1" />
                <Bar className="h-4 w-10" />
                <Bar className="h-4 w-20" />
              </div>
            ))}
          </div>
        </div>

        {/* Changes */}
        <div className="rounded-2xl bg-card p-6 shadow-sm">
          <div className="space-y-2">
            <Bar className="h-5 w-36" />
            <Bar className="h-3.5 w-64" />
          </div>
          <div className="mt-5 space-y-3">
            {[...Array(3)].map((_, i) => (
              <div key={i} className="flex items-center gap-3">
                <Bar className="h-9 w-9 rounded-lg" />
                <div className="flex-1 space-y-1.5">
                  <Bar className="h-4 w-32" />
                  <Bar className="h-3 w-44" />
                </div>
                <Bar className="h-4 w-20" />
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
