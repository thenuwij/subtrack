# Subtrack

Subtrack is a recurring-payment tracker with a page-aware AI assistant. It finds likely subscriptions and free trials from Gmail, keeps payment totals and reminders in one place, and lets users ask questions or propose changes in natural language.

Live frontend: [subtrack-beryl.vercel.app](https://subtrack-beryl.vercel.app)

## What it does

- Tracks subscriptions, rent, bills, memberships, and other recurring payments.
- Supports flexible cadences such as fortnightly, every four weeks, quarterly, semiannual, multi-year, and custom every N days/weeks/months/years.
- Shows backend-owned normalized monthly/yearly equivalents separately from exact date-window charge forecasts.
- Detects likely recurring payments and trials from the last three months of Gmail receipts.
- Creates dashboard reminders for renewals, cancellation dates, and expiring free trials.
- Provides a persistent, resizable AI workspace with conversation history and page context.
- Answers questions about totals, changes, duplicate records, upcoming charges, and user-labelled opportunities to review costs.
- Proposes add, edit, remove, merge, reminder, and review actions; the user confirms every write before it runs.
- Researches cheaper alternatives with citations and a bounded per-user cache/rate limit.
- Supports AUD, USD, GBP, SGD, EUR, and JPY with a persistent shared exchange-rate cache and explicit stale/unconverted states.
- Distinguishes fixed estimates, variable bills, active/paused/cancelling/cancelled/ended payments, shared bills, and user-controlled essential/optional labels.
- Lets authenticated users export their Subtrack app data or permanently delete all user-owned app records.

Subtrack provides spending information and organisation tools, not investment, tax, credit, or regulated financial advice.

## Stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 16, React 19, TypeScript, Tailwind CSS |
| Backend | FastAPI, SQLAlchemy, Alembic |
| Database | Neon PostgreSQL |
| Authentication | Supabase Auth with Google OAuth |
| AI | Anthropic Claude API |
| Gmail | Google Gmail API with read-only scope |
| Deployment | Vercel frontend, Render API |

## Repository

```text
subtrack/
├── subtrack-frontend/       # Next.js application
├── subtrack-backend/        # FastAPI application, tests, and migrations
├── render.yaml              # Render Blueprint
└── README.md
```

Every user-owned database query is scoped by the verified Supabase user ID. The frontend never connects directly to PostgreSQL. AI write actions are stored as expiring proposals and require explicit confirmation. Gmail OAuth uses user-bound one-time state, PKCE, encrypted refresh tokens, and an authenticated completion step.

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
