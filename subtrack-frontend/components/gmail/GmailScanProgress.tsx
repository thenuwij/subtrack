import { CheckCircle2, Clock3, Search } from 'lucide-react'
import type { GmailStatus } from '@/types'

interface Props {
  gmail: GmailStatus
  compact?: boolean
}

const STAGE_COPY = {
  queued: ['Preparing your scan…', 'Waiting for an available scanner.'],
  reading: ['Reading receipt emails…', 'Searching the last three months of likely receipts.'],
  analysing: ['Finding recurring patterns…', 'Checking charges, renewals and free trials.'],
  finalising: ['Finishing up…', 'Saving findings safely to your review queue.'],
  complete: ['Scan complete', 'Your latest findings are ready to review.'],
} as const

function progressFor(gmail: GmailStatus) {
  const processed = gmail.scan_processed ?? 0
  const total = gmail.scan_total ?? 0
  const stageProgress = total > 0 ? Math.min(processed / total, 1) : 0
  if (gmail.scan_stage === 'reading') return 5 + stageProgress * 40
  if (gmail.scan_stage === 'analysing') return 45 + stageProgress * 48
  if (gmail.scan_stage === 'finalising') return 96
  if (gmail.scan_stage === 'complete') return 100
  return 3
}

export function GmailScanProgress({ gmail, compact = false }: Props) {
  const running = gmail.scan_status === 'running'
  const showCompletion = gmail.scan_status === 'done' && Boolean(gmail.scan_message)
  if (!running && !showCompletion) return null

  const stage = gmail.scan_stage ?? (running ? 'queued' : 'complete')
  const [title, fallback] = STAGE_COPY[stage]
  const progress = progressFor(gmail)
  const processed = gmail.scan_processed ?? 0
  const total = gmail.scan_total ?? 0
  const detail = running && total > 0
    ? `${processed} of ${total} ${stage === 'reading' ? 'emails' : 'sender groups'}`
    : gmail.scan_message ?? fallback

  return (
    <div
      className={`rounded-xl border p-4 ${
        gmail.scan_partial && !running
          ? 'border-amber-500/25 bg-amber-500/5'
          : 'border-primary/15 bg-primary/5'
      } ${compact ? 'space-y-2.5' : 'space-y-3'}`}
      role="status"
      aria-live="polite"
    >
      <div className="flex items-start gap-3">
        <div className="mt-0.5 text-primary">
          {running
            ? stage === 'queued'
              ? <Clock3 className="h-4 w-4" aria-hidden="true" />
              : <Search className="h-4 w-4" aria-hidden="true" />
            : <CheckCircle2 className="h-4 w-4" aria-hidden="true" />}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-sm font-medium text-foreground">{title}</p>
            {running && (
              <span className="text-xs tabular-nums text-muted-foreground">
                Usually under 2 minutes
              </span>
            )}
          </div>
          <p className="mt-0.5 text-xs text-muted-foreground">{detail}</p>
        </div>
      </div>

      {running && (
        <div
          className="h-1.5 overflow-hidden rounded-full bg-primary/10"
          role="progressbar"
          aria-label="Inbox scan progress"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.round(progress)}
        >
          <div
            className="h-full rounded-full bg-primary transition-[width] duration-500 motion-reduce:transition-none"
            style={{ width: `${progress}%` }}
          />
        </div>
      )}
    </div>
  )
}
