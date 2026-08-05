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
          Subtrack is a recurring-payment tracker. This policy explains what information Subtrack accesses, why it is used, which services process it, how long it is kept, and the controls available to you. It applies to the Subtrack website, API, Gmail connection, and AI assistant.
        </p>

        <h2>Information Subtrack handles</h2>
        <h3>Account and sign-in information</h3>
        <p>
          When you sign in, Google and Supabase provide identifiers and basic profile information such as your email address, display name, avatar, and account creation time. Supabase manages the sign-in session. Subtrack&apos;s API uses the verified Supabase user identifier to keep each user&apos;s records separate.
        </p>
        <h3>Financial organisation data</h3>
        <p>
          Subtrack stores information you enter or approve, including recurring-payment names, amounts, currencies, billing cadence, categories, due and lifecycle dates, shared-bill details, free trials, reminders, income preference, and essential or optional labels. Subtrack is not a bank ledger and does not connect to a bank account.
        </p>
        <h3>Assistant data</h3>
        <p>
          Subtrack stores assistant conversations, limited page context, proposed actions, confirmations, and cited alternative-research results so conversations survive refreshes and actions can be audited. Page context contains allow-listed route, filter, and record identifiers; it does not grant the assistant access to another user&apos;s records.
        </p>

        <h2>Google user data</h2>
        <p>
          Gmail connection is optional and separate from Google sign-in. If you connect Gmail, Subtrack requests <code>gmail.readonly</code>, email identity, and OpenID scopes. The Gmail scope is read-only: Subtrack cannot send, change, move, or delete email.
        </p>
        <p>
          A scan searches likely receipt, invoice, renewal, cancellation, and trial emails from approximately the previous three months. For candidate messages it temporarily processes the sender, subject, date, and relevant message text needed to identify a recurring payment. Candidate details may be sent to Anthropic&apos;s API for classification. Raw Gmail messages and bodies are not stored in Subtrack&apos;s database. Subtrack stores only derived review findings, confidence and evidence summaries, scan status, the connected email address, and an encrypted Google refresh token needed for later scans.
        </p>
        <p>
          OAuth state is one-time, hashed, bound to the signed-in user, and expires after ten minutes. The PKCE verifier and refresh token are encrypted. Authorization credentials are returned to the browser in a URL fragment, removed immediately, and are not placed in Vercel request URLs.
        </p>
        <p>
          Subtrack&apos;s use and transfer of information received from Google APIs adheres to the <a href="https://developers.google.com/terms/api-services-user-data-policy">Google API Services User Data Policy</a>, including Limited Use requirements. Google user data is used only to provide the user-facing inbox-scanning and review feature. Subtrack does not sell it, use it for advertising, or expose it to other users.
        </p>

        <h2>How information is used</h2>
        <ul>
          <li>Operate sign-in and keep records scoped to the correct user.</li>
          <li>Calculate recurring-cost equivalents and forecast expected charges.</li>
          <li>Find possible recurring payments in Gmail for you to review.</li>
          <li>Show in-app reminders, free trials, data-quality warnings, and possible duplicates.</li>
          <li>Answer assistant questions and prepare changes that require your confirmation.</li>
          <li>Protect, diagnose, and improve the reliability and security of the service.</li>
        </ul>

        <h2>AI processing and automated decisions</h2>
        <p>
          Anthropic processes candidate email content, assistant messages, and the minimum relevant recurring-payment context needed for the requested feature. AI results can be wrong. Gmail findings enter a review queue, and every AI-proposed data change remains inert until you confirm it. Subtrack does not make investment, credit, insurance, employment, or other legally significant decisions about users.
        </p>

        <h2>Service providers and disclosure</h2>
        <p>
          Subtrack uses Google for sign-in and optional Gmail access, Supabase for authentication, Neon for the application database, Render for the API, Vercel for the website, Anthropic for AI processing, and Frankfurter for exchange-rate data. Providers process information for their stated technical role and under their own terms and privacy practices. Information may be processed in countries where these providers operate. Subtrack may also disclose information when legally required or necessary to protect users and the service. Subtrack does not sell personal information.
        </p>

        <h2>Retention</h2>
        <ul>
          <li>Recurring-payment records, reminders, preferences, derived Gmail findings, and assistant history remain until you delete them or delete your Subtrack app data.</li>
          <li>Raw Gmail message content exists only during a scan and is not retained in Subtrack&apos;s database.</li>
          <li>The encrypted Gmail refresh token remains until you disconnect Gmail or delete your Subtrack app data.</li>
          <li>One-time Gmail connection state expires after ten minutes and is consumed on use.</li>
          <li>Alternative-research cache entries stop being used after approximately 24 hours; an expired database row may remain until your app data is deleted.</li>
          <li>Operational and security logs may be retained for the periods configured by the relevant hosting provider. Subtrack avoids intentionally logging email bodies, OAuth credentials, assistant financial content, and raw external error bodies.</li>
        </ul>

        <h2>Your choices and controls</h2>
        <ul>
          <li>You can use core tracking without connecting Gmail and can disconnect Gmail at any time.</li>
          <li>Disconnecting deletes the encrypted refresh token and attempts to revoke it with Google. Previously approved payment records remain until you delete them.</li>
          <li>You can approve, correct, dismiss, edit, pause, end, or delete app records from Subtrack.</li>
          <li>You can download an authenticated JSON export from Account. It excludes refresh tokens, OAuth credentials, shared exchange-rate cache data, and the external Supabase identity.</li>
          <li>You can permanently delete all user-owned Subtrack application records from Account using an exact confirmation phrase.</li>
        </ul>
        <p>
          App-data deletion removes Subtrack&apos;s database records and signs the current browser out. It does not delete the identity held by Supabase because the current API is not configured with Supabase administrator credentials. If you sign in again, a new empty Subtrack data set can be created. This limitation will remain disclosed until external identity deletion is implemented and verified.
        </p>

        <h2>Cookies and local browser storage</h2>
        <p>
          Supabase uses browser storage and cookies needed to maintain authentication. Subtrack also stores limited interface preferences, such as theme and assistant panel size or view choice. Subtrack does not currently use advertising cookies.
        </p>

        <h2>Security</h2>
        <p>
          Controls include API verification of access tokens, user-scoped database queries, encrypted Google credentials, one-time OAuth state and PKCE, restricted CORS configuration, bounded external calls, and confirmation-gated AI actions with expiry and replay protection. Data is protected in transit using HTTPS in production. No internet service can promise absolute security.
        </p>

        <h2>Children</h2>
        <p>
          Subtrack is not directed to children. Do not use the service if you are not legally able to consent to its data handling in your location.
        </p>

        <h2>Policy changes</h2>
        <p>
          Material changes will be reflected on this page with an updated date. If a change materially affects optional Google-data use, Subtrack will provide notice appropriate to the change before relying on it.
        </p>

        <h2>Contact</h2>
        <p>
          For privacy questions, access concerns, or deletion assistance, {SUPPORT_EMAIL ? (
            <a href={`mailto:${SUPPORT_EMAIL}`}>{SUPPORT_EMAIL}</a>
          ) : (
            <>use the operator contact listed on Subtrack&apos;s Google OAuth consent screen. A dedicated public support email must be configured before broad public release. Do not post personal or financial information in a public issue.</>
          )}
        </p>
      </article>
      <PublicFooter />
    </main>
  )
}
