# Subtrack

Subtrack is a recurring-payment tracker that finds your subscriptions by reading Gmail receipts — no bank-feed access and no manual expense logging. It normalizes what it finds into one view across currencies and billing cadences, and layers a tool-using AI assistant on top for analysis and user-confirmed changes.

Live frontend: [subtrack-beryl.vercel.app](https://subtrack-beryl.vercel.app)

## What it does

- Tracks subscriptions, rent, bills, memberships, and other recurring payments.
- Supports flexible cadences such as fortnightly, every four weeks, quarterly, semiannual, multi-year, and custom every N days/weeks/months/years.
- Shows backend-owned normalized monthly/yearly equivalents separately from exact date-window charge forecasts.
- Detects likely recurring payments and trials from the last three months of Gmail receipts, staged for approval rather than tracked automatically.
- Creates dashboard reminders for renewals, cancellation dates, and expiring free trials.
- Flags duplicate records, price changes, and user-labelled opportunities to review costs.
- Provides a persistent, resizable AI workspace with conversation history and page context.
- Proposes add, edit, remove, merge, reminder, and review actions; the user confirms every write before it runs.
- Researches cheaper alternatives with citations and a bounded per-user cache/rate limit.
- Supports AUD, USD, GBP, SGD, EUR, and JPY with a persistent shared exchange-rate cache and explicit stale/unconverted states.
- Distinguishes fixed estimates, variable bills, active/paused/cancelling/cancelled/ended payments, shared bills, and user-controlled essential/optional labels across 17 spending categories.
- Lets authenticated users export their Subtrack app data or permanently delete all user-owned app records.

Subtrack provides spending information and organisation tools, not investment, tax, credit, or regulated financial advice.

## Stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 16 (App Router), React 19, TypeScript, Tailwind CSS 4, Radix UI, `next-themes`, `react-markdown` |
| Backend | FastAPI, SQLAlchemy 2.0, Alembic |
| Database | Neon PostgreSQL |
| Authentication | Supabase Auth — Google OAuth plus email/password sign-up, sign-in, and reset |
| AI | Anthropic Claude API via the official Python SDK, with a hand-rolled tool-calling loop (no agent framework) |
| Gmail | Google Gmail API with read-only scope |
| Exchange rates | Frankfurter API, hourly cache with a persisted shared snapshot |
| Deployment | Vercel frontend, Render API |

## Repository

```text
subtrack/
├── subtrack-frontend/       # Next.js application
├── subtrack-backend/        # FastAPI application, tests, and migrations
├── render.yaml              # Render Blueprint
└── README.md
```

Every user-owned database query is scoped by the verified Supabase user ID. The frontend never connects directly to PostgreSQL. Gmail OAuth uses user-bound one-time state, PKCE, encrypted refresh tokens, and an authenticated completion step.

## Architecture

### Authentication

Supabase issues tokens entirely on the frontend; the backend only verifies them. `verify_token` checks ES256 tokens against the Supabase JWKS and still accepts legacy HS256 tokens, then returns the `user_id` that scopes every query. A Next.js proxy (`proxy.ts`) checks the session server-side and gates `/dashboard`, `/subscriptions`, `/review`, `/assistant`, and `/account`.

Access tokens can expire between being read and being received, so a 401 triggers a refresh-and-replay rather than an immediate sign-out. Supabase refresh tokens are single-use, so that refresh is deduplicated across concurrent requests — the dashboard issues several in parallel, and racing refreshes would otherwise sign the user out despite succeeding.

### Gmail detection

The scanner searches the Purchases category plus receipt, invoice, and trial keywords over a three-month window, then extracts merchant, amount, currency, and cadence using regex heuristics followed by an LLM pass. Results are written to `detected_subscriptions` with a `pending` status and never enter tracked totals until the user approves them — email parsing is noisy, and one wrong entry makes the whole total untrustworthy.

Model calls are batched by sender domain. A row whose cadence is claimed confidently but lacks the backing interval fields is routed to manual review rather than raising, so one malformed row cannot discard its whole batch. Transient provider failures (429/5xx) get bounded explicit retries; timeouts are excluded by name, since `APITimeoutError` subclasses `APIConnectionError` and retrying one would burn the scan's time budget twice.

### Recurrence

`app/services/recurrence.py` is the single authority for cadence normalization, calendar-safe occurrence enumeration (month-end and leap-year edges), lifecycle cutoffs, and monthly/annual equivalents. These formulas are not duplicated in frontend or agent code.

### Multi-currency

Creating or changing a payment through the REST API, Gmail review, or an assistant confirmation puts conversion in the backend's hands. It stores the native currency and amount, plus a base-currency estimate only when a valid shared rate exists. There is no 1:1 fallback — missing FX stays null and unconverted. Every aggregate carries a `conversion_quality` label of `exact`, `current_rate`, `stale_rate`, or `unconverted`, so nothing reads as more precise than it is. Historical native change values stay stable; base-currency history may be re-expressed at the clearly disclosed current snapshot.

### The AI assistant

A manual tool-use loop against the Anthropic Messages API, capped at `MAX_AGENT_STEPS = 8` per turn, with two strictly separated tool families.

**Read tools** are pure, user-scoped database reads: `get_financial_overview`, `list_recurring_payments`, `get_recurring_payment`, `get_upcoming_charges`, `get_commitment_changes`, `find_duplicate_payments`, `list_review_detections`, `get_saving_candidates`, `list_payment_reminders`, plus `research_cheaper_alternatives` and `web_search`. Every response is annotated with scope disclaimers and currency-quality metadata so the model cannot overstate its confidence.

**Action tools** — the ten `propose_*` tools — can only ever create an inert proposal. The model cannot mutate the database. Confirming a proposal is a separate, explicitly authenticated request that re-checks ownership, re-verifies the referenced record has not changed since the proposal was made, and applies the mutation and marks the action complete in one transaction. Proposals expire.

Two details worth noting: IDs reaching the model through page context are treated as untrusted hints, and every tool re-checks ownership server-side before returning anything; and `research_cheaper_alternatives` is cached in `AgentResearchCache` so repeat lookups do not re-hit the model.

### Deployment safety

`/health/ready` compares the applied Alembic revision against the one the running build expects and returns 503 on a definite mismatch, naming both revisions and the fix. A connectivity check alone would report a deploy healthy while every signed-in page 500s on columns that do not exist yet. An unreadable revision on either side is reported as unknown rather than guessed at, so the probe never blocks a release over something it could not determine. `/meta/capabilities` reports which optional integrations are configured.

## Financial semantics and current boundaries

- **Normalized equivalent** spreads a recurring commitment into a budgeting rate. Day cadences use 365 days/year and week cadences use 52 weeks/year. It does not mean the payment is charged monthly.
- **Exact forecast** enumerates anchored calendar occurrences inside a requested date window. It honours lifecycle/end dates and does not use prorated averages.
- **Date-only policy** treats billing and reminder dates as UTC calendar dates. Browser forms serialize them at noon UTC, while comparisons and formatting use the stored UTC date component so a timezone conversion cannot move a bill to the previous day.
- **Recorded history** currently means changes to tracked commitments and Gmail-derived evidence—not a complete bank-transaction ledger. Subtrack must not claim exact historical spending.
- Variable bills use the latest user-approved amount as a clearly labelled estimate.
- A free trial can store its end date and stable post-trial recurring price. Multi-phase introductory pricing (for example A$5/month for three months, then A$15/month) is not yet represented as a price schedule; the assistant is instructed not to flatten it into a false permanent forecast.
- Reminder delivery is currently in-app only. Email and push delivery are not configured.
- Deleting Subtrack app data does not yet delete the external Supabase Auth identity; the account screen and API response disclose this explicitly.

## Local development

Frontend environment (`subtrack-frontend/.env.local`):

```dotenv
NEXT_PUBLIC_SUPABASE_URL=...
NEXT_PUBLIC_SUPABASE_ANON_KEY=...
NEXT_PUBLIC_API_URL=http://127.0.0.1:8000
NEXT_PUBLIC_SUPPORT_EMAIL=... # recommended for the public privacy policy
```

Backend environment (`subtrack-backend/.env`):

```dotenv
DATABASE_URL=...
SUPABASE_JWT_SECRET=...
SUPABASE_URL=...
ANTHROPIC_API_KEY=...
ALLOWED_ORIGINS=http://localhost:3000
FRONTEND_URL=http://localhost:3000
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GOOGLE_REDIRECT_URI=http://127.0.0.1:8000/gmail/callback
TOKEN_ENCRYPTION_KEY=...
```

In production, `ALLOWED_ORIGINS`, `FRONTEND_URL`, `GOOGLE_REDIRECT_URI`, and `NEXT_PUBLIC_API_URL` must all be explicit HTTPS deployment URLs. The API rejects unsafe production defaults. Apply Alembic migrations before shifting traffic; migrations retain and backfill the legacy `cycle` fields for rolling frontend/backend compatibility.

Run the services in separate terminals:

```bash
cd subtrack-backend
venv/bin/python scripts/migrate.py
venv/bin/uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

```bash
cd subtrack-frontend
npm run dev
```

## Release checks

```bash
cd subtrack-backend
venv/bin/python -m pytest -q
venv/bin/ruff check app tests
venv/bin/python -m compileall -q app tests
venv/bin/alembic current
venv/bin/pip check

cd ../subtrack-frontend
npx tsc --noEmit
npm run lint
npm run build
```

Production requires the Vercel environment values above, all `render.yaml` secrets, the Render Blueprint applied to an always-on paid service, and the exact production Google OAuth redirect URI. Gmail's restricted read-only scope must complete Google verification and any required security assessment before a public launch. Live OAuth, revocation, provider-rate, and Gmail scan behaviour must be verified with configured credentials; automated tests use controlled fakes and do not prove external approval.
