# Subtrack

A production-grade personal finance dashboard for tracking subscriptions, expenses, and budgets, with an AI financial agent that can query your data and take actions on your behalf.

Live at [subtrack-beryl.vercel.app](https://subtrack-beryl.vercel.app)

## Overview

Subtrack is a full-stack finance management app built with Next.js, FastAPI, and PostgreSQL. It lets users track recurring subscriptions, log one-off expenses, set monthly budgets per category, and monitor overall spending from a single dashboard. An AI agent built on the Anthropic Claude API with 11 custom tools allows users to query their financial data and perform actions through natural conversation rather than navigating forms.

## Features

**Dashboard**
- Monthly spend summary, upcoming bills, and budget status at a glance
- Multi-currency support with live exchange rates via the Frankfurter API
- Currency context cached on the frontend with a one-hour stale check to minimise API calls

**Subscription Tracker**
- Add, view, and delete recurring bills with due date tracking
- Supports multiple currencies per subscription

**Expense Logger**
- Log one-off expenses by category and date
- Multi-currency entries resolved to base currency for dashboard totals

**Budget Manager**
- Set monthly limits per category
- Live spend tracking against each budget

**AI Financial Agent**
- Conversational interface embedded in the dashboard
- 11 custom tools covering read queries (expenses, subscriptions, budgets, income, savings goals) and write actions (log expense, add subscription, create and update savings goals)
- Agent reasons over real user data to answer questions, log transactions, flag non-essential spending, and predict affordability
- Built using Anthropic Claude API tool calling with a multi-turn conversation loop

## Technical Stack

| Layer | Technology |
|---|---|
| Frontend | Next.js, TypeScript, TailwindCSS |
| Backend | FastAPI, Python |
| Database | Neon PostgreSQL |
| Auth | Supabase (Google OAuth, shared JWT) |
| AI Agent | Anthropic Claude API with tool calling |
| Currency | Frankfurter API (live exchange rates) |
| Deployment | Vercel (frontend), Render (backend) |

## Architecture

```
User
 └── Next.js Frontend (Vercel)
       └── FastAPI Backend (Render)
             ├── Neon PostgreSQL
             ├── Supabase Auth (shared JWT with UniVise)
             ├── Anthropic Claude API (AI agent with tool calling)
             └── Frankfurter API (live currency rates)
```

Every database record is scoped by `user_id`. The backend owns all data access — the frontend never queries the database directly. JWT auth is validated on every request.

## AI Agent Architecture

The agent uses Claude's tool calling feature. On each user message, the full conversation history and tool definitions are sent to the Claude API. Claude decides which tools to call and in what order, the backend executes each tool against the database, results are returned to Claude, and a final response is streamed back to the user. The loop continues until Claude has enough information to respond.

Tools are split into read tools (get expenses, subscriptions, budgets, income, savings goals, upcoming bills, spending by category) and write tools (create expense, create subscription, create and update savings goals). Intelligence tools handle cross-data reasoning such as affordability prediction and non-essential expense flagging.

## Project Structure

```
subtrack/
├── frontend/
│   ├── app/                  # Next.js app router pages
│   ├── components/           # Shared UI components
│   └── context/
│       └── CurrencyContext   # Live rate caching, one-hour stale check
├── backend/
│   ├── app/
│   │   ├── routers/          # FastAPI route handlers
│   │   ├── models/           # SQLAlchemy models
│   │   ├── agent/            # Claude tool definitions and conversation loop
│   │   └── main.py
│   └── requirements.txt
└── README.md
```
