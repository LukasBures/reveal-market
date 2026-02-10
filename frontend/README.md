# Frontend

Next.js 15 + TypeScript + Tailwind app for the marketing site and event browsing.

**Entrypoint**
- `frontend/app/layout.tsx`

**Key pages**
- Home: `frontend/app/(public)/page.tsx`
- Event detail: `frontend/app/(app)/events/[eventId]/page.tsx`

**Data flow**
- Uses `frontend/lib/api.ts` to call the FastAPI backend.
- Uses `frontend/lib/markets.ts` and `frontend/lib/marketMapper.ts` for model shaping.

**SEO**
- Metadata and canonical config live in `frontend/lib/seo.ts`.
- `frontend/app/sitemap.ts` and `frontend/app/robots.ts` are generated from metadata.

**Run**
- `cd frontend && npm run dev`

**Tests**
- `cd frontend && npm run test`

**Performance tooling**
- Lighthouse CI: `cd frontend && npm run lighthouse:ci`
- Bundle budgets: `cd frontend && npm run bundle:check`

**Analytics sampling**
- Set `NEXT_PUBLIC_GA_SAMPLE_RATE` (1-100) to control GA sampling in production.
