# Phase 10 — Source Monitoring Gate Canary

Phase 10 validates the real `SOURCE_MONITORING_ENABLED` runtime gate for one explicit discovery-only run. It does not enable scheduled execution, automatic document ingestion, trust promotion, or any trading action.

## Required runtime state

The canary requires:

- `SOURCE_MONITORING_ENABLED=true` for this process only
- `SOURCE_AUTO_INGEST_ENABLED=false`
- `TRUST_PROMOTION_ENABLED=false`
- all configured cloud-capacity checks in the safe state
- explicit `--allow-network` and `--allow-monitor-write` consent

The intended operator command sets these flags as temporary environment variables. It does not require editing `.env` and does not persist the monitoring gate after the process exits.

## Write boundary

The monitor runner may only:

- fetch the single registered RBI RSS feed,
- discover a bounded number of allow-listed RBI URLs,
- update/re-observe idempotent discovery queue metadata,
- append one monitor-run audit record,
- update the monitor-state row.

It must not:

- fetch discovered item URLs,
- create documents or claims,
- write raw evidence to Backblaze B2,
- create Qdrant points,
- run automatic ingestion,
- create trust events.

The canary stages the database changes first, measures B2 and Qdrant again, validates the complete boundary, and commits only when reconciliation passes. Otherwise it rolls the staged transaction back.

## Scope

Passing Phase 10 proves only that the production source-monitoring gate can safely execute one bounded discovery-only run while the independent ingestion and trust gates remain off. A later phase is required before any recurring schedule is introduced.
