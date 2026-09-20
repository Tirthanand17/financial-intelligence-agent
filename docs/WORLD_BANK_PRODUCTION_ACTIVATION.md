# World Bank Production Activation

## Current status

Production activation is **not yet enabled** by this milestone.

The bounded live evidence canary on 20 September 2026 succeeded with exact-byte B2/PostgreSQL/Qdrant reconciliation, three evidence chunks, zero structured claims, and clean post-write production readiness. The next gate is a separate operational-monitor canary that proves the same source-specific evidence path can run under the normal monitoring and auto-ingest gates while producing auditable monitor state.

The existing production source set remains RBI, SEBI, NSE and MoSPI until that operational canary passes and a later activation PR explicitly changes the registry and scheduler.

## Proposed initial production contract

The initial World Bank production monitor is intentionally narrow:

- monitor id: `world-bank-india-gdp-api`;
- source: `world_bank`;
- country: India (`IND`);
- indicator: `NY.GDP.MKTP.KD.ZG` — Real GDP Growth;
- API observations requested: 3 recent annual observations;
- monitor interval: 1440 minutes;
- maximum evidence documents handled per due cycle: 1;
- scheduler cadence remains once daily;
- redirects remain rejected;
- JSON response remains capped at 1 MiB;
- exact accepted bytes remain SHA-256 reconciled through B2, PostgreSQL and Qdrant;
- annual observation periods remain observation periods only, never publication/effective dates;
- structured claim count must remain zero under the current temporal model;
- `TRUST_PROMOTION_ENABLED` must remain false.

This design does not route World Bank through the generic discovered-document queue. That queue is designed for first-party document URLs and generic document ingestion, while World Bank uses a separately validated JSON and temporal contract. Production monitoring therefore reuses the source-specific World Bank downloader and persistence path directly.

## Operational-monitor canary

`app/monitoring/world_bank.py` defines the bounded source-specific operational cycle. `scripts/world_bank_operational_canary.py` is the temporary activation probe.

The canary requires:

- explicit network permission;
- explicit write permission;
- exact confirmation `WORLD_BANK_OPERATIONAL_CANARY`;
- `SOURCE_MONITORING_ENABLED=true`;
- `SOURCE_AUTO_INGEST_ENABLED=true`;
- `TRUST_PROMOTION_ENABLED=false`;
- safe measured cloud capacity before the source request;
- safe measured cloud capacity after persistence;
- the 1440-minute cadence guard to say the monitor is due.

A successful new payload records a normal monitor `success` event. Exact already-indexed bytes record `no_change`. Both outcomes update the monitor state to ready and preserve the evidence SHA. Network, source-policy, persistence, reconciliation, or post-write capacity failures record a fail-closed monitor outcome without deleting evidence.

## Temporary execution gate

`.github/workflows/world-bank-operational-canary-once.yml` is a temporary one-shot secret-safe runner. It has no schedule and no manual dispatch surface. It can execute only after it is merged to the default branch and only for the exact repository-owner comment configured in the workflow.

Before the operational canary, the workflow requires the existing four-source production readiness to pass with all normal gates false. It temporarily enables monitoring and auto-ingest only for the bounded World Bank operational cycle, while trust promotion remains false. It then restores the normal false gates and requires production readiness to pass again.

The temporary workflow must be removed in the later activation/cleanup milestone.

## Activation decision after a successful operational canary

Only after the operational canary records a ready monitor state and successful/no-change history may a separate PR:

1. add the fixed World Bank monitor to `app.monitoring.registry.MONITORS` as enabled;
2. add exactly one World Bank source-specific cycle after the existing four sequential source cycles;
3. retain the existing daily scheduler cadence;
4. retain one-document-per-World-Bank-cycle bounds;
5. keep RBI, SEBI, NSE and MoSPI unchanged;
6. update international expansion readiness to reflect validated live reconciliation and successful bounded canaries;
7. remove the temporary one-shot operational canary workflow;
8. run full CI, post-merge CI and deployment verification;
9. verify fail-closed production readiness sees all five enabled monitors as ready before considering activation complete.

If the operational canary fails or post-canary readiness is not clean, World Bank must remain out of the production registry and scheduler.