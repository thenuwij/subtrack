# Subtrack

Subtrack is a recurring-payment tracker that finds your subscriptions by reading your Gmail receipts — no bank-feed access and no manual expense logging. It normalizes what it finds into one view across currencies and billing cadences, and layers an AI assistant on top for analysis and changes you confirm.

Live frontend: [subtrack-beryl.vercel.app](https://subtrack-beryl.vercel.app)

## What it does

- Tracks subscriptions, rent, bills, memberships, and other recurring payments.
- Supports flexible cadences such as fortnightly, every four weeks, quarterly, semiannual, multi-year, and custom every N days/weeks/months/years.
- Shows normalized monthly/yearly equivalents separately from exact date-window charge forecasts.
- Detects likely recurring payments and trials from the last three months of Gmail receipts, staged for approval rather than tracked automatically.
- Creates dashboard reminders for renewals, cancellation dates, and expiring free trials.
- Flags duplicate records, price changes, and user-labelled opportunities to review costs.
- Provides a persistent, resizable AI workspace with conversation history and page context.
- Proposes add, edit, remove, merge, reminder, and review actions; the user confirms every write before it runs.
- Researches cheaper alternatives with citations.
- Supports AUD, USD, GBP, SGD, EUR, and JPY with explicit stale/unconverted states.
- Distinguishes fixed estimates, variable bills, active/paused/cancelling/cancelled/ended payments, shared bills, and user-controlled essential/optional labels across 17 spending categories.
- Lets authenticated users export their Subtrack app data or permanently delete all user-owned app records.

Subtrack provides spending information and organisation tools, not investment, tax, credit, or regulated financial advice.

## How it works

### Finding subscriptions in your inbox

Connecting Gmail grants read-only access. Subtrack searches the last three months for receipts, invoices, and trial notices, then works out the merchant, amount, currency, and billing cadence from what it finds.

Nothing it finds is tracked automatically. Every detection waits in a review queue for your verdict, because email parsing is noisy and a single wrong entry makes the whole total untrustworthy. Anything the scan cannot read confidently is sent to review as unknown rather than guessed at, and a receipt it fails on never costs you the rest of the results.

### Understanding what you actually pay

Real billing cycles are messier than "monthly". Subtrack handles fortnightly, four-weekly, quarterly, multi-year, and arbitrary custom intervals, and keeps two different numbers apart: a normalized rate for budgeting, and an exact forecast of the charges genuinely landing in a date range. Month-end and leap-year edges are handled properly, so a payment anchored to the 31st does not drift.

It also tracks the shape of a commitment over time — paused, cancelling, ended, still in a free trial, split with someone else, or a variable bill whose amount moves.

### Working in more than one currency

Amounts are stored in the currency you were actually charged in. A converted figure appears only when a genuine exchange rate is available; Subtrack never invents a 1:1 fallback to fill a gap. Every total says how good its conversion is — exact, converted at the current rate, converted at a stale rate, or not converted at all — so a number never looks more precise than it is.

### The assistant

The assistant can see your tracked payments and the page you are on, and answer questions about totals, upcoming charges, duplicates, price changes, and where you might be overspending.

It cannot change anything. Every action it suggests — adding, editing, removing, merging, setting a reminder, approving a detection — is only a proposal until you confirm it. Confirming is a separate step that re-checks the record still looks the way it did when the proposal was made, so a stale or mistaken suggestion cannot quietly rewrite your data.

### Keeping your data yours

Every query is scoped to your verified account, and the browser never talks to the database directly. Gmail access uses read-only scope with encrypted tokens, and disconnecting revokes it. You can export everything Subtrack holds about you, or delete all of it.

## Stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 16 (App Router), React 19, TypeScript, Tailwind CSS 4, Radix UI |
| Backend | FastAPI, SQLAlchemy 2.0, Alembic |
| Database | Neon PostgreSQL |
| Authentication | Supabase Auth — Google OAuth plus email/password sign-up, sign-in, and reset |
| AI | Anthropic Claude API |
| Gmail | Google Gmail API with read-only scope |
| Exchange rates | Frankfurter API |
| Deployment | Vercel frontend, Render API |

## Repository

```text
subtrack/
├── subtrack-frontend/       # Next.js application
├── subtrack-backend/        # FastAPI application, tests, and migrations
├── render.yaml              # Render Blueprint
└── README.md
```

## What the numbers mean

- **Normalized equivalent** spreads a recurring commitment into a budgeting rate. Day cadences use 365 days/year and week cadences use 52 weeks/year. It does not mean the payment is charged monthly.
- **Exact forecast** counts the real charges falling inside a date window. It honours end and cancellation dates and does not use prorated averages.
- **Recorded history** means changes to tracked commitments and what was found in email — not a complete bank-transaction ledger. Subtrack does not claim exact historical spending.
- Billing and reminder dates are treated as calendar dates, so a timezone difference can never shift a bill to the previous day.
- Variable bills use the latest amount you approved, clearly labelled as an estimate.
