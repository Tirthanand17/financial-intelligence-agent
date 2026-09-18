# Production API Schema Surface Hardening

## Purpose

The Render deployment is private operational infrastructure. FastAPI's default Swagger UI, ReDoc UI, and raw OpenAPI JSON are useful during development but unnecessarily disclose the production route inventory when left publicly mounted.

This milestone removes those three documentation/schema routes only when `APP_ENV=production`.

## Behavior

Production:

- `/docs` is not mounted;
- `/redoc` is not mounted;
- `/openapi.json` is not mounted.

Development/test:

- `/docs` remains available;
- `/redoc` remains available;
- `/openapi.json` remains available.

The environment decision reads only the non-secret `APP_ENV` value. It does not load or expose provider credentials at application construction time.

## Unchanged routes

This hardening does not change the behavior of:

- `/health`;
- the read-only dashboard surfaces;
- the authenticated `/api/v1` surfaces;
- authenticated `POST /ingest` and `POST /ask`;
- the scheduler or internal source-processing scripts.

## Safety boundaries

No source, scheduler, ingestion, claim state, trust state, PostgreSQL data, B2 evidence, Qdrant vector, storage policy, or paid infrastructure is changed. Development documentation remains available so testability and local maintainability are not sacrificed for production hardening.
