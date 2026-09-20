# World Bank Production Activation

## Current status

World Bank production monitoring is enabled by this milestone only after the prior bounded validation gates succeeded.

The 20 September 2026 exact-byte live evidence canary succeeded with B2/PostgreSQL/Qdrant reconciliation, three evidence chunks, zero structured claims, and clean post-write readiness. The subsequent source-specific operational-monitor canary also completed successfully under the normal monitoring and auto-ingest gates with trust promotion disabled and clean pre/post production readiness.

The production source set is therefore extended from RBI, SEBI, NSE and MoSPI to include one narrowly bounded World Bank monitor. IMF remains inactive.

## Production contract

The World Bank production monitor is intentionally narrow:

- monitor id: `world-bank-india-gdp-api`;
- source: `world_bank`;
- country: India (`IND`);
- indicator: `NY.GDP.MKTP.KD.ZG` — Real GDP Growth;
- API observations requested: 3 recent annual observations;
- monitor interval: 1440 minutes;
- maximum evidence documents handled per due cycle: 1;
- scheduler cadence remains once daily at 09:30 Asia/Kolkata;
- World Bank runs only after the existing four source cycles and remains serial;
- redirects remain rejected;
- JSON response remains capped at 1 MiB;
- exact accepted bytes remain SHA-256 reconciled through B2, PostgreSQL and Qdrant;
- annual observation periods remain observation periods only, never publication/effective dates;
- structured claim count must remain zero under the current temporal model;
- `TRUST_PROMOTION_ENABLED` remains false.

World Bank does not route through the generic discovered-document queue. The queue is designed for first-party document URLs and generic document ingestion, while World Bank uses a separately validated JSON and temporal contract. The recurring scheduler therefore calls the source-specific World Bank operational runner after the four existing generic source cycles.

## Runtime gates and failure behavior

The production cycle still requires:

- explicit network permission from the controlled scheduler invocation;
- explicit write permission from the controlled scheduler invocation;
- `SOURCE_MONITORING_ENABLED=true` only inside the bounded source-processing step;
- `SOURCE_AUTO_INGEST_ENABLED=true` only inside that step;
- `TRUST_PROMOTION_ENABLED=false`;
- safe measured cloud capacity before source access;
- safe measured cloud capacity after persistence;
- the 1440-minute cadence guard to say the monitor is due.

A successful new payload records a normal monitor `success` event. Exact already-indexed bytes record `no_change`. A not-due cycle performs no source access or write. Network, source-policy, persistence, reconciliation, or post-write capacity failures remain fail-closed and do not delete retained evidence.

## Scheduler integration

`app.monitoring.registry.MONITORS` contains the fixed enabled World Bank monitor. `.github/workflows/operational-scheduled.yml` retains the existing daily cadence and first processes RBI, SEBI, NSE and MoSPI sequentially with one-item processing bounds. It then runs `scripts/world_bank_operational_cycle.py` once.

Pre-run and post-run production readiness remain mandatory. The existing failure-only deduplicated GitHub operational alert remains unchanged. The temporary one-shot World Bank operational-canary workflow is removed after its successful use.

## Safety invariants retained

Production activation does not:

- widen the World Bank source allow-list;
- enable IMF;
- increase scheduler frequency;
- parallelize evidence writes;
- create publication/effective dates from annual observation years or `lastupdated`;
- enable trust promotion;
- add autonomous financial execution or buy/sell output;
- delete or rewrite historical evidence.

If World Bank readiness, reconciliation or capacity becomes unsafe, the cycle must fail closed and preserve evidence for audit/reconciliation rather than attempting destructive repair.
