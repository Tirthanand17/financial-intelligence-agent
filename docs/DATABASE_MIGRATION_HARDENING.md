# Database Migration Hardening

This post-roadmap hardening milestone introduces Alembic without changing the live production schema automatically.

## Why this exists

The application historically relied on SQLAlchemy `Base.metadata.create_all(...)`. That is useful for creating missing tables, but it is not a controlled migration mechanism for future column/index/constraint changes. Alembic is now configured so later schema changes can be versioned and reviewed.

## Safety model

The deployed database predates Alembic. Therefore revision `0001_existing_schema_baseline` is intentionally **non-destructive and contains no DDL**. It represents the schema already modeled by `app.storage.database.Base`.

Do **not** run an automatic production `upgrade` or `stamp` merely because this code is deployed. First run the read-only guard:

```bash
python scripts/schema_baseline_check.py
```

The command exits `0` only when every modeled table and every modeled column is present. Missing modeled schema exits non-zero and must be treated as a blocker. Unrelated provider/platform tables are reported but do not block because hosted PostgreSQL services may contain their own metadata.

Only after:

1. the schema guard reports `safe: true`;
2. the normal production-readiness/integrity checks pass;
3. a current backup/restore point exists; and
4. an operator explicitly approves the baseline operation,

may the existing database be marked at the baseline with:

```bash
alembic stamp 0001_existing_schema_baseline
```

Stamping records migration state only; it does not execute the baseline revision's upgrade function.

## Future migration rule

Every future schema modification must:

- be represented by a new Alembic revision after `0001_existing_schema_baseline`;
- have upgrade and rollback/recovery reasoning;
- be tested against an isolated database before production;
- avoid deleting evidence/provenance/history as a storage shortcut;
- preserve the project's fail-closed behavior.

## Current production impact

None. This milestone adds migration tooling and read-only validation only. It does not alter Supabase data, evidence in Backblaze B2, Qdrant vectors, scheduler cadence, claim states, trust promotion, or dashboard write capabilities.
