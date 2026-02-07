# Backend

This folder contains the API (`backend/api`) and the worker (`backend/worker`) plus shared models/utilities.

**Key modules**
- `backend/shared/models.py` central SQLAlchemy models used by API/worker.
- `backend/shared/cache_async.py` Redis helpers.
- `backend/shared/repository_async.py` common DB accessors.

**Run**
- `make api`
- `make worker`

**Tests**
- `backend/run_tests.sh`
