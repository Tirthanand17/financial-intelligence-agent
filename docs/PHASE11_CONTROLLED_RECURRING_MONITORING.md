# Phase 11 — Controlled Recurring Monitoring

Phase 11 prepares bounded recurring source monitoring without enabling automatic document ingestion, trust promotion, or any trading action.

## Existing cadence policy

The monitor already has a source-specific interval of at least 60 minutes. `app.monitoring.schedule` enforces:

- a never-checked monitor may run immediately;
- after a successful/no-change run, the next attempt is delayed by the configured interval;
- consecutive failures use exponential backoff;
- failure backoff is capped at 24 hours.

This prevents repeated source requests and keeps source monitoring bounded.

## First Phase 11 checkpoint

`scripts/phase11_schedule_readiness.py` is read-only. It reads the persisted monitor state from PostgreSQL and evaluates whether the RBI monitor is currently due according to the real cadence/backoff policy.

The checkpoint:

- does not fetch RBI or any discovered URL;
- does not create or update monitor records;
- does not create documents or claims;
- does not write Backblaze B2 objects;
- does not write Qdrant points;
- requires automatic ingestion and trust promotion to remain disabled.

A result of `DUE NOW: false` immediately after the Phase 10 canary is expected and demonstrates that the one-hour cadence barrier is working. A later `DUE NOW: true` only means the monitor is eligible for another bounded discovery check; it does not authorize automatic ingestion.

## Scope

This checkpoint validates scheduling state only. A later Phase 11 checkpoint must exercise a due-time recurring discovery runner with the same capacity, source-policy, idempotency, and kill-switch protections before any external scheduler is configured.
