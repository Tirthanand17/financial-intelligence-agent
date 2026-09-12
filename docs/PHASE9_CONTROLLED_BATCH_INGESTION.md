# Phase 9 — Controlled Bounded Batch Ingestion

Phase 9 is the first multi-item write canary. It does **not** enable scheduled monitoring or automatic ingestion. An operator must explicitly run the script with both network and write consent.

## Safety boundary

The script requires:

- `SOURCE_MONITORING_ENABLED=false`
- `SOURCE_AUTO_INGEST_ENABLED=false`
- `TRUST_PROMOTION_ENABLED=false`
- all configured cloud-capacity checks in the safe state
- an exact requested batch size between 1 and 3

All selected queue items are trusted-preflighted before the first write. If any item fails preflight, the entire batch is blocked with zero writes.

## Exact evidence persistence

Each selected item is downloaded once during preflight. The exact accepted `DownloadedDocument` bytes are then passed to `ingest_downloaded_document` with their approved SHA-256. No second source download is used for persistence, avoiding dynamic-page time-of-check/time-of-use mismatches.

## Exact-record processing

Phase 9 adds `process_specific_pending_discovery`, which processes only a named pending queue record. This prevents a controlled batch from accidentally consuming a different pending item if queue ordering changes. The ordinary `process_pending_discoveries` path keeps its existing one-commit queue-transition semantics.

## Per-item reconciliation

Before each item:

- live cloud capacity is re-measured,
- the selected queue record must still be unchanged and pending,
- its exact preflight bytes must still be the approved evidence.

After each item:

- queue attempt count must increase exactly once,
- successful items must clear the symbolic error code,
- the queue document link must exist and match the preflight SHA-256,
- a newly indexed item must add exactly its preflight byte count to B2 and its chunk count to Qdrant,
- an already-indexed duplicate must add zero B2 bytes and zero Qdrant points,
- trust-event count must not change.

If per-item reconciliation fails, later items are not attempted. Already-preserved evidence is never silently deleted.

## Aggregate reconciliation

After all items, the script verifies:

- discovery-row count unchanged,
- monitor run/state counts unchanged,
- trust-event count unchanged,
- document-count delta equals newly indexed count,
- claim/audit tables never decrease,
- aggregate B2 and Qdrant deltas exactly match the sum of newly indexed preflight evidence,
- cloud capacity is still safe.

## Scope

Passing Phase 9 proves only that a small explicit multi-item write can be processed safely. It does not authorize autonomous trading, scheduled ingestion, recurring source monitoring, or trust promotion.
