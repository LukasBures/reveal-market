# Backend TODO

**MVP - Critical**
- Validate `RM_INTERNAL_API_SECRET` is set for API and caller services.
- Confirm database schema matches expected `backend/shared/models.py`.

**MVP - High**
- Verify cache refresh loop uses distributed locks to avoid multi-worker stampedes.
- Ensure API pricing uses shared HTTP clients and resilient FX cache.

**MVP - Medium**
- Add slow query alerts for API list endpoints.

**MVP - Low**
- Improve cache observability for list endpoints and category caches.

**MVP - Nice to have**
- Add request profiling endpoints behind internal auth.

**Production - Critical**
- Formalize migration plan and schema versioning controls.

**Production - High**
- Add load-shedding strategy for DB outages and Redis failures.

**Production - Medium**
- Add structured alerts for API background task failures.

**Production - Low**
- Add auditing for quote issuance and consumption.

**Production - Nice to have**
- Add read replica support and query routing.
