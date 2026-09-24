# Subtrack

[![Live demo](https://img.shields.io/badge/Live_demo-Try_it_now-0A84FF?style=for-the-badge&logo=vercel&logoColor=white&labelColor=0060DF)](https://subtrack-beryl.vercel.app/login)

![Next.js](https://img.shields.io/badge/Next.js-20232A?logo=nextdotjs&logoColor=white)
![TypeScript](https://img.shields.io/badge/TypeScript-20232A?logo=typescript&logoColor=3178C6)
![FastAPI](https://img.shields.io/badge/FastAPI-20232A?logo=fastapi&logoColor=009688)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-20232A?logo=postgresql&logoColor=4169E1)
![Claude](https://img.shields.io/badge/Claude_API-20232A?logo=anthropic&logoColor=D97757)

**Know every subscription you're paying for, and catch it when the price changes.**

Subtrack finds your recurring payments in your Gmail receipts, shows what they really cost each month, and flags price rises, expiring free trials and duplicates. An AI agent helps you act on it, and nothing changes until you approve.

**[Try the demo →](https://subtrack-beryl.vercel.app/login)** No sign-up needed: you get a private sandbox with sample data, cleared after 24 hours.

## Why Subtrack

Subscriptions are easy to start and easy to forget. Prices creep up, free trials quietly convert, and the same service ends up billed twice. Subtrack gives you one honest view of everything you've signed up for, without linking your bank or typing anything in.

## What it does

- **Finds your payments for you.** Connect Gmail (read-only) and Subtrack detects subscriptions, bills and trials from your receipts. You approve each one before it's tracked.
- **Shows your real monthly cost.** Rent, utilities, streaming and memberships in one total, whatever the billing cycle or currency.
- **Catches what changed.** Price rises, trials about to convert, duplicate payments and upcoming charges, all on one dashboard.
- **Reminds you in time.** Set reminders before renewals and trial end dates.
- **Helps you cut costs.** Ask the AI agent where your money goes, or have it research cheaper alternatives with sources.

## How it works

1. **Connect Gmail.** Subtrack scans the last three months of receipts with read-only access.
2. **Review what it found.** Every detection waits in your inbox for approval, so nothing wrong sneaks into your totals.
3. **Stay on top of it.** Your dashboard tracks monthly cost, upcoming charges and anything that changed.

New users get a short guided tour and a getting-started checklist to walk them through setup.

## An AI agent you stay in control of

Ask questions in plain English, like *"What changed this month?"* or *"Find me a cheaper alternative to Netflix."* The agent reads your data and prepares updates such as adding, editing or merging payments, or setting reminders. It never changes anything on its own: every action is a proposal until you confirm it.

## Private by design

Gmail access is read-only and can be revoked at any time. You can export everything Subtrack holds about you, or delete it all.

## Repository structure

```text
subtrack/
├── subtrack-frontend/     # Next.js web app (deployed on Vercel)
│   ├── app/               # Pages: dashboard, payments, inbox review, assistant, account
│   ├── components/        # UI, dashboard widgets, onboarding tour and the AI assistant panel
│   └── lib/               # API client, data caching, currency and date helpers
├── subtrack-backend/      # FastAPI service (deployed on Render)
│   ├── app/
│   │   ├── routers/       # REST endpoints, including the demo sandbox
│   │   ├── agent/         # AI agent tools and confirm-before-change actions
│   │   ├── gmail/         # Gmail receipt scanning and payment detection
│   │   └── services/      # Billing cycles, reminders, duplicate detection
│   ├── alembic/           # Database migrations
│   └── tests/
└── render.yaml            # Render deployment config
```

---

*Subtrack provides spending information and organisation tools, not financial advice.*
