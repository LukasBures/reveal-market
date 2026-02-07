# Frontend TODO

**MVP - Critical**
- Ensure `NEXT_PUBLIC_API_BASE_URL` and `NEXT_PUBLIC_PRICE_STREAMER_URL` are set in prod.
- Verify event cards load quickly with cache-friendly API queries.

**MVP - High**
- Validate pagination limits and load-more behavior across all event lists.

**MVP - Medium**
- Add Lighthouse checks for SEO and performance regressions.

**MVP - Low**
- Add edge caching for event lists if CDN is available.

**MVP - Nice to have**
- Add prefetch for event detail on hover.

**Production - Critical**
- Ensure CSP and security headers allow only required domains.

**Production - High**
- Add image optimization for event hero images.

**Production - Medium**
- Add analytics sampling to reduce overhead.

**Production - Low**
- Add bundle size budgets.

**Production - Nice to have**
- Add SSR caching for high-traffic pages.
