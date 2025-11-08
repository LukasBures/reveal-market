# Reveal Market Frontend

The marketing + investor documentation site is a Next.js 15 app with a fully instrumented SEO/AI surface: JSON-LD schema, CSP/HSTS headers, sitemap/robots metadata, and Vitest coverage for critical components.

## Highlights

- **SEO + AI ready** – Central `lib/seo.ts` emits canonical URLs, rich metadata, and keywords for every page. `app/sitemap.ts`/`app/robots.ts` expose crawl targets automatically.
- **Security headers** – `next.config.mjs` defines CSP, HSTS, COOP/CORP, Referrer-Policy, and Permissions-Policy that mirror the backend. Docs routes also send caching hints.
- **Testing** – Vitest + Testing Library cover hero CTAs, navigation state, and docs layout. Run via `npm run test`.
- **Investor storytelling** – Docs focus on manifesto, roadmap, tokenomics, marketplace, and legal sections aimed at LPs and exchanges.

## Local Development

```bash
cd frontend
npm install
npm run dev    # http://localhost:3000
```

To run the static analyzer + tests:

```bash
npm run lint
npm run test
```

Set `NEXT_PUBLIC_SITE_URL` and `NEXT_PUBLIC_API_BASE_URL` so SEO helpers and CSP include the correct domains.

## Deployment Notes

- Build with `npm run build`; Docker uses the standalone output for slimmer images.
- The dev docker-compose profile mounts `/app/node_modules` as a volume for hot reload; production images run `next start` via the standalone output.
- Security headers are set in Next.js, so ensure the app is served behind HTTPS/CDN to honor HSTS + CSP.
