# Phase 17 — Production Hardening and Final Validation

Phase 17 is the final hardening checkpoint for the currently defined roadmap. It does not activate unattended monitoring, automatic ingestion, or trust promotion. Instead, it proves that the production data plane and recovery controls are internally consistent while all three global gates remain disabled.

## Safety invariants

The final validation requires:

- `SOURCE_MONITORING_ENABLED=false`
- `SOURCE_AUTO_INGEST_ENABLED=false`
- `TRUST_PROMOTION_ENABLED=false`
- no silent deletion or rewriting of preserved evidence;
- no guessed publication dates;
- no arbitrary source expansion or anti-bot bypass;
- cloud-capacity uncertainty blocks readiness rather than being guessed safe.

## Final production-readiness audit

`scripts/phase17_production_readiness.py` is read-only and fails closed if it finds unsafe cloud capacity, incomplete monitor readiness, queue retry metadata anomalies, broken discovery-to-document links, orphan claims, missing or hash-mismatched B2 evidence, Qdrant/document chunk-count divergence, quality-failed VERIFIED/TRUSTED claims, or unexpected trust events.
The live audit on 2026-09-13 passed with four required monitors ready, zero India Authority-A monitoring gaps, zero queue/link anomalies, zero orphan claims, zero quality-failed high-state claims, zero trust events, 11 preserved documents with valid hashes, and 31 expected Qdrant chunks matching 31 stored points.

Measured cloud usage at the checkpoint was approximately 10.84 MiB in Supabase, 2.33 MiB in Backblaze B2 object versions, and 31 Qdrant points, all inside the configured operator budgets.

## Recovery validation

The existing transactional retry replay was executed for RBI, SEBI, NSE, and MoSPI. For every monitor, a real pending row was staged as a transient failure, exponential backoff deferred it, fresh work was selected instead, the failed row became eligible at the expected retry time, and the transaction was fully rolled back.

This validates starvation resistance and retry recovery without changing the production queue or fetching source evidence.

## Bounded read-only stability soak

`scripts/phase17_read_only_soak.py` repeatedly samples PostgreSQL row counts, B2 usage, Qdrant points, capacity state, and process RSS. It fails if persistence counts drift, capacity becomes unsafe, or memory growth exceeds the configured bound.

The live 10-cycle soak passed with stable counts on every sample: 11 documents, 37 claims, 40 discoveries, 8 monitor runs, 2,448,214 B2 bytes, and 31 Qdrant points. Recorded RSS growth was 131,072 bytes, below the 64 MiB bound.
