import Link from 'next/link'
import type { Metadata } from 'next'
import { Bot, BellRing, MailCheck } from 'lucide-react'
import { Logo } from '@/components/layout/Logo'
import { Button } from '@/components/ui/button'
import { PublicFooter } from '@/components/layout/PublicFooter'

export const metadata: Metadata = {
  title: 'Subtrack — Talk to your recurring payments',
  description: 'Track recurring payments and free trials, set reminders, and ask a page-aware AI assistant about your spending.',
}

const FEATURES = [
  {
    icon: MailCheck,
    title: 'Find payments from receipts',
    body: 'A bounded, read-only Gmail scan checks likely receipts from the last three months and puts every finding in a review queue.',
  },
  {
    icon: Bot,
    title: 'Talk to your finances',
    body: 'Ask about recurring costs, changes, duplicates, upcoming charges, or cheaper options. You approve every change before it happens.',
  },
  {
    icon: BellRing,
    title: 'Catch trials before they renew',
    body: 'Track free-trial end dates and place cancellation or renewal reminders directly on your dashboard.',
  },
]

export default function Home() {
  return (
    <main className="min-h-screen bg-background text-foreground">
      <nav className="mx-auto flex max-w-6xl items-center justify-between px-5 py-5 sm:px-8">
        <Logo />
        <Button asChild size="sm">
          <Link href="/login">Sign in</Link>
        </Button>
      </nav>

      <section className="mx-auto grid max-w-6xl gap-12 px-5 pb-20 pt-16 sm:px-8 sm:pt-24 lg:grid-cols-[1.1fr_0.9fr] lg:items-center">
        <div className="max-w-2xl">
          <p className="text-sm font-medium text-primary">Recurring payments, made understandable</p>
          <h1 className="mt-4 text-4xl font-semibold tracking-tight sm:text-6xl">
            See where your money repeats. Ask what to do next.
          </h1>
          <p className="mt-6 max-w-xl text-base leading-7 text-muted-foreground sm:text-lg">
            Subtrack brings subscriptions, bills, memberships, and free trials into one clear monthly view—with an AI assistant that understands the page you are on.
          </p>
          <div className="mt-8 flex flex-col gap-3 sm:flex-row">
            <Button asChild size="lg"><Link href="/login">Start with Google</Link></Button>
            <Button asChild size="lg" variant="outline"><Link href="/privacy">How your data is handled</Link></Button>
          </div>
          <p className="mt-4 text-xs leading-5 text-muted-foreground">
            Gmail access is read-only. Subtrack cannot send, edit, or delete your email.
          </p>
        </div>

        <div className="rounded-3xl bg-card p-6 shadow-sm ring-1 ring-foreground/5 sm:p-8">
          <p className="text-sm text-muted-foreground">This month</p>
          <p className="mt-2 text-5xl font-semibold tracking-tight tabular-nums">$248.40</p>
          <div className="mt-8 space-y-5">
            {['Streaming', 'Software', 'Utilities'].map((label, index) => (
              <div key={label}>
                <div className="mb-2 flex justify-between text-sm">
                  <span>{label}</span>
                  <span className="tabular-nums text-muted-foreground">{[38, 34, 28][index]}%</span>
                </div>
                <div className="h-2 overflow-hidden rounded-full bg-muted">
                  <div
                    className="h-full rounded-full"
                    style={{
                      width: `${[38, 34, 28][index]}%`,
                      background: `var(--category-${['streaming', 'software', 'utilities'][index]})`,
                    }}
                  />
                </div>
              </div>
            ))}
          </div>
          <div className="mt-8 rounded-2xl bg-primary/5 p-4">
            <p className="text-sm font-medium">Ask Subtrack</p>
            <p className="mt-1 text-sm text-muted-foreground">“What increased this month, and is anything duplicated?”</p>
          </div>
        </div>
      </section>

      <section className="border-y border-border bg-card/40">
        <div className="mx-auto grid max-w-6xl gap-5 px-5 py-16 sm:px-8 md:grid-cols-3">
          {FEATURES.map(({ icon: Icon, title, body }) => (
            <article key={title} className="rounded-2xl bg-card p-6 shadow-sm">
              <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary/10 text-primary">
                <Icon className="h-5 w-5" aria-hidden="true" />
              </span>
              <h2 className="mt-5 text-lg font-semibold tracking-tight">{title}</h2>
              <p className="mt-2 text-sm leading-6 text-muted-foreground">{body}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="mx-auto max-w-3xl px-5 py-16 text-center sm:px-8">
        <h2 className="text-3xl font-semibold tracking-tight">Your data stays under your control.</h2>
        <p className="mx-auto mt-4 max-w-2xl text-sm leading-6 text-muted-foreground">
          Subtrack stores an encrypted Gmail refresh token and derived payment findings. Receipt content is processed only to provide the inbox-scanning feature, and disconnecting Gmail removes the stored token.
        </p>
        <Button asChild className="mt-7"><Link href="/login">Continue to Subtrack</Link></Button>
      </section>

      <PublicFooter />
    </main>
  )
}
