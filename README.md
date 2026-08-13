# Subtrack

**Find and track every recurring payment you're signed up for — automatically, from your Gmail receipts.**

No bank-feed access. No manual expense logging. Connect Gmail, and Subtrack finds your subscriptions for you.

🔗 **Live app:** [subtrack-beryl.vercel.app](https://subtrack-beryl.vercel.app)

![Next.js](https://img.shields.io/badge/Next.js%2016-black?logo=next.js) ![React](https://img.shields.io/badge/React%2019-61DAFB?logo=react&logoColor=black) ![TypeScript](https://img.shields.io/badge/TypeScript-3178C6?logo=typescript&logoColor=white) ![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white) ![PostgreSQL](https://img.shields.io/badge/PostgreSQL-4169E1?logo=postgresql&logoColor=white) ![Claude](https://img.shields.io/badge/Anthropic%20Claude-D97757)

## Features

- 📧 **Auto-detects subscriptions from Gmail** — scans receipts and invoices, no manual entry
- 💰 **One number across every currency** — AUD, USD, GBP, SGD, EUR, JPY, converted transparently
- 🔁 **Handles real billing cycles** — weekly, fortnightly, quarterly, annual, or custom, not just "monthly"
- 🤖 **AI assistant** that answers questions about your spending and can propose changes you approve
- 🔔 **Reminders** for renewals, free-trial expirations, and price changes
- 🔍 **Duplicate & price-change detection** across your tracked payments
- 🔒 **Privacy-first** — read-only Gmail access, full data export, and one-click account deletion

## Stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 16, React 19, TypeScript, Tailwind CSS |
| Backend | FastAPI, SQLAlchemy, PostgreSQL |
| Auth | Supabase (Google OAuth + email/password) |
| AI | Anthropic Claude API |
| Integrations | Gmail API (read-only), live FX rates |
| Deployment | Vercel + Render |

## Repository

```text
subtrack/
├── subtrack-frontend/       # Next.js application
├── subtrack-backend/        # FastAPI application, tests, and migrations
├── render.yaml              # Render Blueprint
└── README.md
```

Subtrack provides spending information and organisation tools, not investment, tax, credit, or regulated financial advice.
