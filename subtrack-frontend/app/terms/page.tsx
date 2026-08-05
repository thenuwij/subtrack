import Link from 'next/link'
import type { Metadata } from 'next'
import { Logo } from '@/components/layout/Logo'
import { PublicFooter } from '@/components/layout/PublicFooter'

export const metadata: Metadata = {
  title: 'Terms — Subtrack',
  description: 'Terms for using the Subtrack recurring-payment tracker and AI assistant.',
}

export default function TermsPage() {
  return (
    <main className="min-h-screen bg-background text-foreground">
      <nav className="mx-auto flex max-w-4xl items-center justify-between px-5 py-5 sm:px-8">
        <Link href="/" aria-label="Subtrack home"><Logo /></Link>
        <Link href="/login" className="text-sm font-medium text-primary hover:underline">Sign in</Link>
      </nav>
      <article className="prose prose-neutral mx-auto max-w-3xl px-5 py-12 dark:prose-invert sm:px-8">
        <p className="text-sm font-medium text-primary">Last updated 5 August 2026</p>
        <h1>Terms of service</h1>
        <p>By using Subtrack, you agree to these terms.</p>

        <h2>What Subtrack provides</h2>
        <p>
          Subtrack helps organise recurring payments, email-derived payment findings, reminders, and AI-assisted summaries. Features may change as the service improves.
        </p>

        <h2>Not financial advice</h2>
        <p>
          Subtrack provides informational summaries and organisation tools. It does not provide investment, tax, legal, credit, or other regulated financial advice. Verify important amounts, dates, alternatives, and cancellation requirements with the relevant provider before acting.
        </p>

        <h2>Your account and data</h2>
        <p>
          You are responsible for activity under your account and for keeping access to your Google account secure. Only connect a mailbox and enter financial information you are authorised to use. Your use of Google data is also subject to Google&apos;s applicable terms.
        </p>

        <h2>AI output and actions</h2>
        <p>
          AI output can be incomplete or incorrect. Subtrack presents data-changing AI actions for confirmation; review every proposal before approving it. Cited prices and alternatives can change after they are researched.
        </p>

        <h2>Acceptable use</h2>
        <p>
          Do not misuse the service, attempt unauthorised access, interfere with other users, evade service limits, or use Subtrack to violate law or another person&apos;s rights.
        </p>

        <h2>Availability and liability</h2>
        <p>
          Subtrack is provided on an as-available basis. Reasonable care is taken to keep the service accurate and available, but uninterrupted operation and error-free results are not guaranteed. To the extent permitted by applicable law, Subtrack is not responsible for indirect losses or decisions made solely from automated output.
        </p>

        <h2>Ending use</h2>
        <p>
          You may disconnect Gmail and delete stored items from the app. Access may be suspended where necessary to protect users, providers, or the service from abuse or security risk.
        </p>

        <h2>Privacy</h2>
        <p>See the <Link href="/privacy">privacy policy</Link> for how information is handled.</p>
      </article>
      <PublicFooter />
    </main>
  )
}
