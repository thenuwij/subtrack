import Link from 'next/link'
import type { Metadata } from 'next'
import { Logo } from '@/components/layout/Logo'
import { PublicFooter } from '@/components/layout/PublicFooter'

const SUPPORT_EMAIL = process.env.NEXT_PUBLIC_SUPPORT_EMAIL

export const metadata: Metadata = {
  title: 'Privacy — Subtrack',
  description: 'How Subtrack accesses, processes, stores, and protects account and Google user data.',
}

export default function PrivacyPage() {
  return (
    <main className="min-h-screen bg-background text-foreground">
      <nav className="mx-auto flex max-w-4xl items-center justify-between px-5 py-5 sm:px-8">
        <Link href="/" aria-label="Subtrack home"><Logo /></Link>
        <Link href="/login" className="text-sm font-medium text-primary hover:underline">Sign in</Link>
      </nav>
      <article className="prose prose-neutral mx-auto max-w-3xl px-5 py-12 dark:prose-invert sm:px-8">
        <p className="text-sm font-medium text-primary">Last updated 5 August 2026</p>
        <h1>Privacy policy</h1>
        <p>
          Subtrack is a recurring-payment tracker. This policy explains the information Subtrack accesses, why it is used, where it is processed, and the controls available to you.
        </p>

        <h2>Information you provide</h2>
        <p>
          Subtrack stores the recurring payments, trial dates, reminders, preferences, and AI conversations you choose to create. Google and Supabase provide basic account information needed to sign you in.
        </p>

        <h2>Google user data</h2>
        <p>
          If you connect Gmail, Subtrack requests the read-only Gmail scope. It searches likely receipt, renewal, invoice, and trial emails from the last three months and reads the sender, subject, date, amount-like text, and a short relevant excerpt. Subtrack cannot send, change, or delete email.
        </p>
        <p>
          Candidate receipt details are sent to Anthropic&apos;s API to classify recurring payments and trials for the user-facing review queue. Raw Gmail messages are not stored in Subtrack&apos;s database. Subtrack stores the resulting payment findings and an encrypted Google refresh token so you can run later scans.
        </p>
        <p>
          Subtrack&apos;s use and transfer of information received from Google APIs adheres to the Google API Services User Data Policy, including the Limited Use requirements. Google user data is used only to provide and improve the visible inbox-scanning feature; it is not sold or used for advertising.
        </p>

        <h2>Other processors</h2>
        <p>
          Subtrack uses Supabase for authentication, Neon for the application database, Render for the API, Vercel for the website, Anthropic for AI processing, and Google for Gmail and sign-in. Each provider processes only the information needed for its role.
        </p>

        <h2>Retention and control</h2>
        <ul>
          <li>Disconnecting Gmail deletes Subtrack&apos;s stored Google refresh token.</li>
          <li>You can approve, dismiss, edit, or delete derived payment information.</li>
          <li>You can delete individual AI conversations from the assistant history.</li>
          <li>Security and operational logs may be retained for a limited period to keep the service reliable.</li>
        </ul>

        <h2>Security</h2>
        <p>
          Access tokens are verified on the API, user-owned records are scoped to the signed-in user, Google refresh tokens are encrypted at rest, and AI-proposed changes require your confirmation before they run. No internet service can promise absolute security.
        </p>

        <h2>Contact</h2>
        <p>
          For privacy questions or deletion requests, {SUPPORT_EMAIL ? (
            <a href={`mailto:${SUPPORT_EMAIL}`}>{SUPPORT_EMAIL}</a>
          ) : (
            <>use the developer contact listed on Subtrack&apos;s Google OAuth consent screen. Do not post personal or financial information in a public issue.</>
          )}
        </p>
      </article>
      <PublicFooter />
    </main>
  )
}
