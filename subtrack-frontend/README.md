# Subtrack frontend

Next.js 16 and React 19 frontend for Subtrack. Product and deployment documentation lives in the repository root [`README.md`](../README.md).

```bash
npm install
npm run dev
```

Required `.env.local` values:

```dotenv
NEXT_PUBLIC_SUPABASE_URL=...
NEXT_PUBLIC_SUPABASE_ANON_KEY=...
NEXT_PUBLIC_API_URL=http://127.0.0.1:8000
```

The production build fails deliberately when `NEXT_PUBLIC_API_URL` is missing so Vercel cannot silently ship a frontend pointed at a visitor's localhost.

Release checks:

```bash
npx tsc --noEmit
npm run lint
npm audit --omit=dev
npm run build
```
