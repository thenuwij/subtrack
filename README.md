# Subtrack

Subtrack is a recurring-payment tracker with a page-aware AI assistant. It finds likely subscriptions and free trials from Gmail, keeps payment totals and reminders in one place, and lets users ask questions or propose changes in natural language.

Live frontend: [subtrack-beryl.vercel.app](https://subtrack-beryl.vercel.app)

## What it does

- Tracks subscriptions, rent, bills, memberships, and other recurring payments.
- Shows monthly and yearly totals with chart, category, and payment views.
- Detects likely recurring payments and trials from the last three months of Gmail receipts.
- Creates dashboard reminders for renewals, cancellation dates, and expiring free trials.
- Provides a persistent, resizable AI workspace with conversation history and page context.
- Answers questions about totals, changes, duplicate payments, upcoming charges, and avoidable spending.
- Proposes add, edit, remove, merge, reminder, and review actions; the user confirms every write before it runs.
- Researches cheaper alternatives with citations and a bounded per-user cache/rate limit.
- Supports AUD, USD, GBP, SGD, EUR, and JPY with stored conversion snapshots.

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

Every user-owned database query is scoped by the verified Supabase user ID. The frontend never connects directly to PostgreSQL. AI write actions are stored as proposals and require explicit confirmation.

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
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GOOGLE_REDIRECT_URI=http://127.0.0.1:8000/gmail/callback
TOKEN_ENCRYPTION_KEY=...
```

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
venv/bin/python -m unittest discover -s tests -p 'test_*.py'
venv/bin/alembic current
venv/bin/pip check

cd ../subtrack-frontend
npx tsc --noEmit
npm run lint
npm run build
```

Production requires the Vercel environment values above, all `render.yaml` secrets, the Render Blueprint applied to an always-on paid service, and the production Google OAuth redirect URI. Gmail's restricted read-only scope must complete Google's verification requirements before a public launch.
